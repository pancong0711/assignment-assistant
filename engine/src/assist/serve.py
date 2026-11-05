"""assist serve —— Companion 本地引擎 HTTP 服务（阶段4a + R1.3 一键安装，M-D 前移）。

端点：
- GET  /doctor            体检 JSON（A3 id 定版；fix: install=deps/fonts 等）
- GET  /status            引擎版本 / workspace
- GET  /engine/version    本地/远端 engine 版本对比（D65-P4）
- POST /kb/write          B4：openpyxl 样式保留写回（PWA 在线保存）
- POST /install/<item>    发起安装任务（deps/playwright/fonts/katex/tinytex/tex_guide/python_guide/uv/kb_init）
                          返回 {ok, job_id}；item 不支持的安装给 guide 文本作业输出
- GET  /jobs/<id>          任务状态 + 最近输出
- GET  /jobs/<id>/stream   SSE 逐行输出（text/event-stream；__DONE__<rc> 结束）
- GET  /                  静态托管 app/dist-lan（PWA 与引擎同源）

安全：默认 127.0.0.1；--lan 0.0.0.0 + 强制 ?token=；CORS 允许 Pages 来源。
"""

import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from loguru import logger

from . import __version__
from .xxt import layout as xxt_layout

CHECK_IDS = ("python_env", "uv", "deps", "viz", "playwright", "xelatex", "fonts", "settings",
              "kb", "grading_layout", "workspace_layout", "roster_persist", "class_dir_names")
INSTALL_ITEMS = ("deps", "viz", "playwright", "fonts", "tex_guide", "python_guide", "uv",
                 "kb_init", "katex", "tinytex", "engine_update")

KATEX_VERSION = "0.16.4"


def install_katex(ws: Path, emit) -> int:
    """D55/H1：把 KaTeX 选择集写入 <workspace>/sheets/katex/**（零解压直装）。
    优先从引擎同源静态目录（app/dist/katex，构建期 npm 注入）复制；缺失时回退 jsdelivr 下载。
    emit(line) 逐行汇报。返回 0=成功。"""
    dest = ws / "sheets" / "katex"
    src = _static_root()
    kat = (src / "katex") if src else None
    if kat and (kat / "katex.min.js").exists():
        count = 0
        for f in sorted(kat.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(kat)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            count += 1
            emit(f"写入 sheets/katex/{rel.as_posix()}（{target.stat().st_size} B）")
        emit(f"完成：{count} 个文件（来源=引擎同源 dist，版本 {KATEX_VERSION}）")
        return 0
    # 回退：CDN 下载（无本地 dist 的裸引擎场景）
    import urllib.request
    base = f"https://cdn.jsdelivr.net/npm/katex@{KATEX_VERSION}/dist"
    try:
        css = urllib.request.urlopen(f"{base}/katex.min.css", timeout=30).read().decode("utf-8")
    except Exception as e:  # noqa: BLE001
        emit(f"失败：无法获取 katex.min.css（{e}）；请先在 PWA 侧构建 dist 或联网重试")
        return 1
    files = ["katex.min.css", "katex.min.js", "contrib/auto-render.min.js"]
    files += [f"fonts/{n}.woff2" for n in sorted(set(re.findall(r"url\(fonts/([^)'\"\s]+)\.woff2\)", css)))]
    for rel in files:
        try:
            data = urllib.request.urlopen(f"{base}/{rel}", timeout=60).read()
        except Exception as e:  # noqa: BLE001
            emit(f"失败：{rel}（{e}）")
            return 1
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        emit(f"下载写入 sheets/katex/{rel}（{len(data)} B）")
    emit(f"完成：{len(files)} 个文件（来源=jsdelivr，版本 {KATEX_VERSION}）")
    return 0

_JOBS: dict[str, dict] = {}
_RESTART_ARGS: tuple = (  # ('serve', --workspace …)：python -c 入口的 click argv
    'serve',
)  # serve() 收到的启动参数（/restart 用 os.execv 原样再生进程）
_JOBS_LOCK: threading.Lock = threading.Lock()
_ENGINE_ROOT = Path(__file__).resolve().parents[2]

# serve 实际使用的 workspace（serve() 启动时写入）。_ws() 优先返回它，
# 避免「serve --workspace X 但 ASSIST_WORKSPACE 未设」时 find_workspace(None) 解析到别处，
# 导致白名单由 X 写入、却由 CLI 子进程从另一目录读取 → 已勾选班级被误拒（D83-5.0）。
_SERVE_WS: Path | None = None


def _set_serve_ws(ws: Path) -> None:
    global _SERVE_WS
    _SERVE_WS = Path(ws).resolve()
    # D119-L3：xxt_home() 必须跟随 serve 的 workspace（下载/草稿/作答原件口径唯一）
    try:
        from .xxt.session import bind_workspace
        bind_workspace(_SERVE_WS)
    except Exception:  # noqa: BLE001
        pass


_ATOPIA_MIGRATED = False


def _ws() -> Path:
    global _ATOPIA_MIGRATED
    if _SERVE_WS is not None:
        ws = _SERVE_WS
    else:
        from .workspace import find_workspace
        ws = Path(find_workspace(None)).resolve()
    if not _ATOPIA_MIGRATED:
        _ATOPIA_MIGRATED = True
        # D134：旧 <ws>/assistopia/ 与 <ws>/extensions/ 幂等迁到 <ws>/atopia/
        try:
            from .atopia import paths as _ap
            _ap.ensure_migrated(ws)
        except Exception:  # noqa: BLE001 —— 迁移不阻断服务
            pass
    return ws


def _venv_python() -> Path:
    ws = _ws()
    for cand in (ws / ".runtime" / "venv" / "bin" / "python",
                 ws / ".runtime" / "venv" / "Scripts" / "python.exe"):
        if Path(cand).exists():
            return Path(cand)
    return Path(sys.executable)


def _xxt_python() -> str:
    """D73：优先使用正在运行 engine 的解释器（它一定可 import assist.cli）。"""
    try:
        exe = str(sys.executable or "")
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass
    return str(_venv_python())


def _xxt_env(home: "Path | str") -> dict:
    """D73：CLI 子进程统一环境：workspace + XXT_HOME/STORAGE + engine src PYTHONPATH。"""
    home = Path(home)
    env = {
        **os.environ,
        "XXT_HOME": str(home),
        "XXT_STORAGE": str(home / "xxt-storage.json"),
        "ASSIST_WORKSPACE": str(_ws()),
        # D74-9：serve 已记录 job 级 journal；子进程 CLI 不再重复记录
        "ASSIST_NO_JOURNAL": "1",
    }
    src = _ENGINE_ROOT / "src"
    if src.is_dir():
        old = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(src) + (os.pathsep + old if old else "")
    return env


def _xxt_cli_cmd(args: list[str]) -> list[str]:
    return [_xxt_python(), "-m", "assist.cli", *args]

def _xxt_preflight(cwd: str, env: dict) -> tuple[bool, str]:
    """D73：执行前先验证解释器能 import assist.cli，失败返回可读原因。"""
    try:
        cp = subprocess.run(
            [_xxt_python(), "-c", "import assist.cli; print('assist.cli ok')"],
            capture_output=True, text=True, timeout=20, env=env, cwd=cwd)
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]
    if cp.returncode == 0:
        return True, ""
    detail = (cp.stderr or cp.stdout or f"rc={cp.returncode}").strip()
    return False, detail[:300]


def _xxt_login_cmd(home: Path) -> list[str]:
    """D68/D73：PWA 扫码登录走 CLI 套壳，而非直接绕过 click 调 qr_login()。"""
    home = Path(home)
    return _xxt_cli_cmd([
        "xxt", "login",
        "--storage", str(home / "xxt-storage.json"),
        "--qr", str(home / "xxt-qr.png"),
        "--timeout", "1800",
    ])


def installer_for(item: str) -> tuple[list[str] | None, str | None]:
    """item → (cmd, guide)；guide 非 None 表示逐行文本引导（无法静默装的系统级依赖）。"""
    py = str(_venv_python() or sys.executable)
    engine_root = str(_ENGINE_ROOT)
    fonts_sh = (_ENGINE_ROOT.parent / "tools" / "fonts-download.sh")
    if item == "deps":
        base = ["uv", "pip", "install", "-e", engine_root,
                "--python", py,
                "--cache-dir", str(_ws() / ".runtime" / "cache" / "uv")] if shutil.which("uv") \
               else None
        if base is None:
            return [py, "-m", "pip", "install", "-e", engine_root], None
        return base, None
    if item == "viz":
        return [_venv_python(), "-m", "pip", "install", "matplotlib", "networkx"], None
    if item == "playwright":
        return [_venv_python(), "-m", "playwright", "install", "chromium"], None
    if item == "fonts":
        if fonts_sh.exists():
            return ["bash", str(fonts_sh)], None
        return None, ["fonts-download.sh 未找到（仓库 tools/）—— CHRIST 自绘示意；Windows 请自备 simsun.ttc/simkai.ttf"]
    if item == "uv":
        return [py, "-m", "pip", "install", "--user", "uv"], None
    if item == "kb_init":
        return [py, "-m", "assist.cli", "bootstrap", "--no-sync", "-w", str(_ws())], None
    if item == "tinytex":
        return None, ["TinyTeX 请使用设置中心专用栏或 CLI `assist tex install`（/install/tinytex 为服务端直装通道）"]
    raise ValueError(f"unknown install item {item}")


def _check(id: str, status: str, name: str, detail: str = "", fix: dict | None = None) -> dict:
    return {"id": id, "name": name, "status": status, "detail": detail, "fix": fix or {}}


def _doctor_checks(ws: Path) -> list[dict]:
    """体检检查项集（A3/D25：id 定版供 PWA 【修复】按钮定位）。"""
    import importlib
    checks: list[dict] = []
    checks.append(_check("python_env", "green" if sys.version_info >= (3, 11) else "red",
                         "Python (≥3.11)", f"Python {sys.version.split()[0]}",
                         {"type": "guide"}))
    uv_ok = bool(shutil.which("uv"))
    checks.append(_check("uv", "green" if uv_ok else "yellow", "uv（可选·依赖安装加速）",
                         "已安装" if uv_ok else "未安装；可用 pip 快速修复，或让 start 脚本自动安装",
                         {} if uv_ok else {"type": "install", "install": "uv"}))
    missing: list[str] = []
    for mod in ("openpyxl", "reportlab", "loguru", "httpx", "PIL"):
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    checks.append(_check("deps", "red" if missing else "green", "引擎依赖",
                         ("缺: " + ", ".join(missing)) if missing else "openpyxl/reportlab/loguru/httpx/pillow",
                         {"type": "install", "install": "deps"} if missing else {}))
    pw = _playwright_state()
    # D168-B3：可视化依赖（matplotlib/networkx）——缺失时给**可读提示**，
    # 不是 import 异常堆栈（docs/113-D169 §4.4）。
    try:
        from .grading import viz as _vz
        _vz_ready = _vz.available()
    except Exception as exc:  # noqa: BLE001
        _vz_ready = {"ok": False, "missing": [], "hint": f"探测失败：{exc}"}
    checks.append(_check(
        "viz", "green" if _vz_ready.get("ok") else "yellow",
        "知识点分析图表（matplotlib/networkx）",
        "已安装" if _vz_ready.get("ok") else (_vz_ready.get("hint") or "未安装"),
        {} if _vz_ready.get("ok") else {"type": "install", "install": "viz"}))
    checks.append(_check("playwright", "green" if pw == "已安装" else "yellow", "Playwright（阶段6）", pw,
                         {"type": "install", "install": "playwright"}))
    try:
        from .paper.latex import check_xelatex
        x = check_xelatex(ws)
        checks.append(_check("xelatex", "green" if x else "yellow", "TeX (xelatex，样题可选)",
                             x or "未安装；可选依赖（设置中心/assist tex install 可装 TinyTeX）",
                             {} if x else {"type": "install", "install": "tinytex"}))
    except ImportError:
        checks.append(_check("xelatex", "red", "TeX (xelatex, 样题可选)", "", {}))
    assets_fonts = _ENGINE_ROOT / "assets" / "fonts"
    def _font_hit(prim: str, fb: str) -> bool:
        f = (ws / prim).exists() or (assets_fonts / fb).exists()
        if not f:
            for p in (Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"), shutil.which("fc-list")):
                if p and Path(p).exists():
                    f = True
                    break
        return bool(f)
    checks.append(_check("fonts", "green" if all(_font_hit(a, b) for a, b in
                 (("simsun.ttc", "wqy-microhei.ttc"), ("simkai.ttf", "LXGWWenKai-Regular.ttf")))
                 else "yellow", "中文字体",
                 "simsun/simkai(自备) → wqy/LXGW(开源) → 系统字体",
                 {"type": "install", "install": "fonts"}))
    ok_settings = (ws / "settings.local.json").exists()
    checks.append(_check("settings", "green" if ok_settings else "yellow",
                         "settings.local.json",
                         str(ws / "settings.local.json") if ok_settings else "未生成（assist bootstrap 可生成）", {}))
    kb_dir = ws / "kb"
    kb_xlsx = sorted(p.name for p in kb_dir.glob("*.xlsx")) if kb_dir.is_dir() else []
    ok_kb = len(kb_xlsx) > 0
    checks.append(_check("kb", "green" if ok_kb else "yellow", "kb 题库",
                         f"{kb_dir}；xlsx={len(kb_xlsx)}" + (f"（{', '.join(kb_xlsx[:5])}）" if kb_xlsx else "（缺失，可创建默认题库）"),
                         {} if ok_kb else {"type": "install", "install": "kb_init"}))
    # D124（兼容期）：班级目录名是否等于班级真名（RosterClass.name）
    try:
        from . import class_dir_audit as _cda
        aud = _cda.audit(ws)
        n_fix, n_conf = aud["summary"]["fixable"], aud["summary"]["conflict"]
        n_unk = aud["summary"]["unknown"]
        if n_fix or n_conf:
            parts = []
            if n_fix:
                names = "、".join(f"{x['dir']}→{x['className']}" for x in aud["fixable"][:3])
                parts.append(f"{n_fix} 个班级目录名与班级名不一致（{names}）")
            if n_conf:
                parts.append(f"{n_conf} 个目标目录已存在，需人工确认")
            checks.append(_check(
                "class_dir_names", "yellow", "班级目录命名",
                "；".join(parts),
                {"type": "api", "endpoint": "/workspace/fix-class-dirs",
                 "label": "🔧 按班级名修正目录"}))
        elif n_unk:
            checks.append(_check(
                "class_dir_names", "yellow", "班级目录命名",
                f"{n_unk} 个班级缺 className 元信息（旧数据）：到「班级与标签」保存一次班级即可写入",
                {"type": "guide"}))
        else:
            checks.append(_check("class_dir_names", "green", "班级目录命名",
                                 "各班级目录名与班级名一致", {}))
    except Exception:  # noqa: BLE001
        pass
    # D120：workspace 目录布局（kb/ 下不得出现 classes/ roster/ grading/ 等）
    try:
        from . import workspace_layout as _wl
        inv = _wl.inspect(ws)
        n_files = (inv.get("summary") or {}).get("files", 0)
        if n_files:
            names = "、".join(f"kb/{v['name']}" for v in inv.get("violations") or [])
            checks.append(_check(
                "workspace_layout", "yellow", "workspace 目录布局",
                f"检测到 {names}（共 {n_files} 个文件错位，如名单被写到题库目录下）",
                {"type": "api", "endpoint": "/workspace/fix-layout", "label": "🔧 一键迁移到正确位置"}))
        else:
            checks.append(_check("workspace_layout", "green", "workspace 目录布局",
                                 "kb/ 下无错位目录", {}))
    except Exception:  # noqa: BLE001
        checks.append(_check("workspace_layout", "yellow", "workspace 目录布局",
                             "检查失败（不影响使用）", {}))
    # D120：名单是否已落盘（localStorage 有、磁盘没有 → 提醒写盘）
    try:
        from .files import roster_io as _rio
        # D121-G3：只认**真正的班级目录**（含 roster/，且不是 grading/ 等保留名）。
        # 旧实现把 classes/ 下所有子目录都当班级 → `classes/grading` 被误报"缺 roster"。
        from .xxt import classmap as _cmap
        classes_dir = ws / "classes"
        missing: list[str] = []
        if classes_dir.is_dir():
            for c in sorted(p for p in classes_dir.iterdir() if p.is_dir()):
                if c.name in _cmap.RESERVED_CLASS_DIR_NAMES:
                    continue
                if not (c / "roster" / "roster.xlsx").is_file():
                    missing.append(c.name)
        if missing:
            checks.append(_check(
                "roster_persist", "yellow", "名单落盘",
                f"{len(missing)} 个班级缺 roster.xlsx（{'、'.join(missing[:5])}）："
                f"到「班级与标签」点一次保存即会自动写盘（D120：保存即落盘）",
                {"type": "guide", "hint": "打开「班级与标签」→ 保存" }))
        else:
            checks.append(_check("roster_persist", "green", "名单落盘", "各班级均有 roster.xlsx", {}))
    except Exception:  # noqa: BLE001
        pass
    # D119：批阅产物布局体检（作答原件/草稿是否在正确 workspace；是否有旧目录残留）
    try:
        from .xxt import migrate_layout as _ml
        inv = _ml.inventory(ws)
        issues: list[str] = []
        if inv.get("usesRepoScratch"):
            issues.append(f"xxt 根落在代码仓库（{inv.get('xxtHome')}）—— 换 workspace 不换数据，请运行 "
                          f"`assist xxt migrate-layout --apply`")
        if not inv.get("sameHome") and (inv.get("summary") or {}).get("reviewDirs"):
            issues.append(f"作答原件仍分布在旧目录（{inv.get('xxtHome')}）")
        if (inv.get("summary") or {}).get("legacyDrafts"):
            issues.append(f"有 {inv['summary']['legacyDrafts']} 份旧草稿未迁移（grade-drafts/）")
        if (inv.get("summary") or {}).get("staleImagesDirs"):
            issues.append(f"有 {inv['summary']['staleImagesDirs']} 个已废弃的 "
                          f"grading/<task>/images/ 目录，可用 `assist grading clean --stale-images --apply` 清理")
        checks.append(_check("grading_layout", "yellow" if issues else "green",
                             "批阅产物布局（D119）",
                             "；".join(issues) if issues else "作答原件与批阅成果位置正确",
                             {"type": "guide"} if issues else {}))
    except Exception:  # noqa: BLE001 —— 体检失败不阻断
        checks.append(_check("grading_layout", "yellow", "批阅产物布局（D119）",
                             "检查失败（不影响使用）", {"type": "guide"}))
    # D74-7：云同步/网盘占用（只提示，不阻塞）
    try:
        from .xxt.sync import detect as _detect_sync
        sy = _detect_sync(ws)
        if sy.get("detected"):
            detail = "；".join(sy.get("reasons") or []) + "。更新引擎前请暂停同步并退出客户端"
            checks.append(_check("sync_root", "yellow", "云同步/网盘占用", detail, {"type": "guide"}))
        else:
            checks.append(_check("sync_root", "green", "云同步/网盘占用", "未检测到同步目录/客户端", {}))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("sync_root", "green", "云同步/网盘占用", f"检测跳过：{exc}", {}))
    return checks


def _playwright_state() -> str:
    """D65-P0.1/P0.2：本机浏览器优先，且用 probe 验证可启动；否则查完整版内核。

    旧检测只看包/目录存在，既会把 Playwright 的 headless_shell 误当完整内核，
    也会把“本机有 Edge 文件但实际不可启动”误报为绿。本版：
    - 先让 inventory(probe=True) 真正启动本机浏览器档位；
    - 无本机浏览器时，用 installer 的 `--no-shell` dry-run 清单检查完整版；
    - 不把 chromium-headless-shell 计入必需项。
    """
    try:
        py = str(_venv_python() or sys.executable)
        cp0 = subprocess.run([py, "-m", "playwright", "--version"],
                            capture_output=True, text=True, timeout=30)
        if cp0.returncode != 0:
            return "未安装（阶段6 需要）"

        from .xxt.browsers import inventory
        inv = inventory(probe=True)
        if inv.get("pick"):
            return f"将使用：{inv['pick']['name']}（已验证可启动，零下载）"

        from .xxt.installer import pkg_manifest
        man = pkg_manifest()
        if not man.get("ok"):
            return f"包已装但自检失败：{man.get('reason') or '未知'}"
        items = [it for it in man.get("items", []) if it.get("needed")]
        if not items:
            return "包已装，内核未安装（dry-run 无输出）"
        missing = [it for it in items if not it.get("installed")]
        if missing:
            return f"无本机 Edge/Chrome；自带完整版内核未下载（需：{missing[0]['name']}）→ 一键修复"
        return "自带完整版内核就绪（不依赖 headless_shell）"
    except Exception as e:  # noqa: BLE001
        return f"检测失败：{e}"



def _job_error_summary(lines: list[str]) -> str:
    """从 CLI 输出尾部提取错误摘要（D83 修复：别把 indent JSON 的结尾 '}' 当错误）。

    引擎 CLI 失败时会先 echo 一份 indent JSON（含 "error" 字段），末行是 '}'；
    旧实现取末行 → journal 记成 "}"。这里优先取 JSON error 字段，回退最后一个非空行。
    """
    text = "\n".join(lines)
    m = None
    for cand in re.finditer(r'"error"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
        m = cand  # 取最后一个：CLI 末尾的结果 JSON 才是本 job 的结论
    if m:
        try:
            return str(json.loads(f'"{m.group(1)}"'))[:400]
        except Exception:  # noqa: BLE001
            return m.group(1)[:400]
    for ln in reversed(lines):
        if ln.strip():
            return ln.strip()[:400]
    return ""


def _xxt_home() -> Path:
    """xxt 工件根（storage/runs/pages）：与 xxt.session.xxt_home 共用同一口径。"""
    from .xxt.session import xxt_home
    return xxt_home()


def _xxt_import_error() -> str:
    """D73-12：xxt.session 不可导入时返回可读错误；空串表示正常。

    现场案例：更新后 _engine/engine 安装树缺少 src/assist/xxt/session.py，
    serve 仍能启动（layout 已导入），但所有 /xxt/* 懒加载 session 时 500。
    这里提前探测并给 PWA 可读提示，避免刷屏 traceback。
    """
    try:
        from .xxt.session import xxt_home  # noqa: F401
        return ""
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"[:300]


def _xxt_storage_newer_than(ts: float) -> bool:
    """D68：登录 CLI 刚写完 storage 时，不能被 60s 的旧 dead 缓存挡住。"""
    try:
        storage = _xxt_home() / "xxt-storage.json"
        return storage.exists() and storage.stat().st_mtime > ts
    except Exception:
        return False


def _xxt_session_check_cached(max_age=60):
    """体检结果进程内缓存（TTL；fallback：playwright 未装时给明确 unknown）。

    D68：storage 文件 mtime 比缓存时间新（例如 QR 登录刚成功、CLI 刚回写续期）
    时立即失效缓存并重跑体检，避免 PWA 扫码后最长 60s 像“没反应”。
    """
    import time as _t
    global _XXT_CHECK
    now = _t.time()
    if _XXT_CHECK and now - _XXT_CHECK[0] < max_age:
        if not _xxt_storage_newer_than(_XXT_CHECK[0]):
            return _XXT_CHECK[1]
    from .xxt.session import check_session
    try:
        rep = check_session(_xxt_home() / "xxt-storage.json")
    except Exception as e:  # playwright missing 等
        rep = {"verdict": "unknown", "reasons": [str(e)[:200]]}
    # 缓存时间取“体检结束时间”和 storage mtime 的较大者；否则 check_session
    # 自己回写 storage 会被下一次请求误判为“登录态刚更新”，导致反复起浏览器。
    cache_ts = _t.time()
    if _xxt_storage_newer_than(cache_ts):
        try:
            cache_ts = max(cache_ts, (_xxt_home() / "xxt-storage.json").stat().st_mtime)
        except Exception:
            pass
    _XXT_CHECK = (cache_ts, rep)
    return rep


def _xxt_avatar_cached(max_age=600):
    """头像 data-URL（engine 同会话中转，base64；TTL 缓存）。

    D68：storage 在扫码后刚被 CLI 回写时，旧的头像 None 缓存也要失效。
    """
    import time as _t
    global _XXT_AVATAR
    now = _t.time()
    if _XXT_AVATAR and now - _XXT_AVATAR[0] < max_age:
        if not _xxt_storage_newer_than(_XXT_AVATAR[0]):
            return _XXT_AVATAR[1]
    data = None
    if _xxt_session_check_cached().get("verdict") == "alive":
        try:
            from .xxt.session import fetch_avatar_b64
            data = fetch_avatar_b64(_xxt_home() / "xxt-storage.json")
        except Exception:
            data = None
    cache_ts = _t.time()
    try:
        cache_ts = max(cache_ts, (_xxt_home() / "xxt-storage.json").stat().st_mtime)
    except Exception:
        pass
    _XXT_AVATAR = (cache_ts, data)
    return data


def _static_root() -> "Path | None":
    for cand in (_ENGINE_ROOT.parent / "app" / "dist-lan",
                 _ENGINE_ROOT.parent / "app" / "dist"):
        if (cand / "index.html").exists():
            return cand
    return None

_XXT_CHECK = None  # (ts, report)
_XXT_AVATAR = None  # (ts, dataurl|None)

# D67：进程实例身份与重启监督协议
_INSTANCE_ID = ""      # 每次 serve() 启动生成；/status 用于判断是否换了新进程
_STARTED_AT = ""       # 人类可读启动时间
_SERVER_PORT = 0       # 当前监听端口（/status 回显，便于验收固定端口）


_WM_UPLOAD_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _wm_serve_assets(ws: Path, explicit=None) -> tuple[Path, str]:
    """serve 水印端点素材目录：explicit > <ws>/assets（写入型默认，即使目录尚不存在）。

    与 CLI/引擎出 PDF 的 resolve_assets_dir 不同：后者在 ws 尚无 assets/ 时回落 engine；
    但 PWA 上传/管理样式必须写进 workspace，故这里默认即 <ws>/assets。
    """
    if explicit:
        from .paper.assets import resolve_assets_dir
        return resolve_assets_dir(ws=ws, explicit=explicit)
    from .paper.assets import workspace_assets
    return workspace_assets(ws), "workspace"


def make_atopia_confirm(*, confirmed: bool, confirmed_tool: str = "",
                        confirmed_args: "dict | None" = None,
                        confirmed_by: str = "teacher:pwa") -> "callable":
    """D147：构造 Atopia 的 L2 确认回调（**精确到工具 + 参数**）。

    背景：PWA 是异步的，不能在请求线程里等教师点确认，所以采用
    "拒绝 → 返回 pendingConfirm → 教师弹窗确认 → 带 confirmedTool/confirmedArgs 重发"。

    **安全要求**：只放行"教师确认的那一次调用"。
    此前只看 `confirmed is True` → 教师为 A 确认后，同一次请求里模型改请求
    另一个 L2 工具（如 kb.write）也会被自动执行（实测可复现），
    违背 D132「L2 必须教师**逐次**确认」。

    规则：
    - `confirmed=False` → 一律拒绝（返回空串）；
    - 带 confirmed 但**没说是哪个工具** → 拒绝（不允许"盲确认"）；
    - 工具名不一致 → 拒绝；
    - 传了 `confirmed_args` 但参数不一致 → 拒绝；
    - 全部一致 → 返回确认来源（记入 journal 的 `confirmed_by`）。
    """
    conf_tool = str(confirmed_tool or "").strip()

    def _same_args(a: dict, b: "dict | None") -> bool:
        if b is None:
            return True              # 老客户端没传参数 → 只按工具名匹配
        try:
            return json.dumps(a or {}, sort_keys=True, ensure_ascii=False) == \
                json.dumps(b, sort_keys=True, ensure_ascii=False)
        except Exception:            # noqa: BLE001
            return False

    def _confirm(tool_name: str, args: dict) -> str:
        if not confirmed:
            return ""
        if not conf_tool:
            logger.warning("[atopia] 拒绝确认：请求带 confirmed 却没指明 confirmedTool")
            return ""
        if conf_tool != str(tool_name):
            logger.warning(f"[atopia] 拒绝确认错配：教师确认 {conf_tool}，"
                           f"模型请求 {tool_name}")
            return ""
        if not _same_args(args, confirmed_args):
            logger.warning(f"[atopia] 拒绝确认参数不符：{tool_name}")
            return ""
        return str(confirmed_by or "teacher:pwa")

    return _confirm


def _rewrite_legacy_atopia(path: str) -> "tuple[str, bool]":
    """D134：旧路由 `/assistopia/*` → `/atopia/*`（旧名永久兼容）。

    返回 (新路径, 是否发生了改写)。改写只认**前缀**，不做全局替换，
    避免误伤路径里恰好含 `assistopia` 的正常资源。
    """
    if path == "/assistopia" or path.startswith("/assistopia/"):
        return "/atopia" + path[len("/assistopia"):], True
    return path, False


def _save_watermark_upload(assets_dir: Path, payload: dict) -> dict:
    """水印图片 base64 → <assets_dir>/watermark/<文件名>（D87 §4 POST /watermark/upload）。

    安全：只接受白名单图片扩展名；文件名走 basename 清洗，杜绝路径穿越；
    返回相对 assets_dir 的引用（`watermark/<文件名>`，与样式 items[].image 口径一致）。
    """
    import base64
    import re as _re
    name = Path(str(payload.get("name") or "watermark.png")).name
    name = _re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", name) or "watermark.png"
    ext = Path(name).suffix.lower()
    if ext not in _WM_UPLOAD_EXTS:
        return {"ok": False, "error": f"不支持的图片类型：{ext or '(无扩展名)'}（限 png/jpg/webp/gif/bmp）"}
    raw = payload.get("data")
    if isinstance(raw, str) and raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    if not raw or not isinstance(raw, str):
        return {"ok": False, "error": "缺少 data（base64 图片内容）"}
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"base64 解码失败：{exc}"}
    if not blob:
        return {"ok": False, "error": "图片内容为空"}
    d = Path(assets_dir) / "watermark"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(blob)
    return {"ok": True, "name": name, "path": f"watermark/{name}",
            "bytes": len(blob), "file": str(p)}


def restart_plan(platform_name: str, supervised: bool) -> str:
    """D67：返回重启执行模式。

    - POSIX 保持 execv（原地替换，行为已由 D64 验证）；
    - Windows + start.bat 托管：exit75（start.bat supervisor loop 接管重启）；
    - Windows 非托管：manual（返回 409，前端提示手动重启，绝不误报成功）。
    """
    if supervised:
        # D71：只要有 start.bat/start.sh supervisor，就统一走 exit75，
        # 让 launcher 在 engine 停止后执行 pending 安装，再启动新 engine。
        return "exit75"
    if platform_name == "nt":
        return "manual"
    return "execv"


def _llm_error_kind(msg: str) -> str:
    """D127-FIX：把 LLM 测试失败分成三类，避免教师把"请求参数问题"误判成"配置错误"。

    - ``config``：鉴权失败 / 模型不存在 / 地址不可达 —— **真配置问题**；
    - ``request``：400 且提示参数不合法（图片尺寸、格式、token 上限等）—— 探针/请求本身的问题，
      说明 base_url/key/model **已经通了**（请求已到达供应商）；
    - ``unknown``：其它。
    """
    m = str(msg or "")
    low = m.lower()
    if any(k in low for k in ("401", "403", "unauthorized", "invalid api key",
                              "invalid_api_key", "model is unavailable",
                              "model not found", "model_not_found")):
        return "config"
    if ("status=400" in low or "invalid_parameter" in low
            or "must be larger than" in low or "invalid_request" in low):
        return "request"
    if any(k in low for k in ("connection", "timeout", "network", "resolve",
                              "name or service", "unreachable")):
        return "config"
    return "unknown"


def _llm_test_summary(results: "list[dict]") -> str:
    """D127：把逐段测试失败原因压成一行摘要（供前端直接展示，绝不含 key）。"""
    bad = [r for r in (results or []) if not r.get("ok")]
    if not bad:
        return ""
    parts = []
    for r in bad:
        stage = "转录" if r.get("stage") == "transcription" else "评阅"
        parts.append(f"{stage}段失败（{r.get('provider') or '-'} / {r.get('model') or '-'}"
                     f" @ {r.get('base_url') or '-'}）：{str(r.get('error') or '未知错误')[:200]}")
    return "；".join(parts)


class Handler(BaseHTTPRequestHandler):
    ws: Path = None  # type: ignore
    token: str = ""
    cors: bool = True

    def _raw(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        body = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if self.cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _ok_token(self, qs: dict) -> bool:
        return (not Handler.token) or qs.get("token", [""])[0] == Handler.token

    def _start_stream_job(self, job_id: str, cmd: list[str], env: dict,
                          item: str, prefix: str, cwd: "str | None" = None,
                          journal_kind: "str | None" = None,
                          journal_params: "dict | None" = None):
        """D72：通用 CLI job 流式转发（terminal/start.log + /jobs + SSE）。"""
        q_, out = queue.Queue(), []
        with _JOBS_LOCK:
            _JOBS[job_id] = {"item": item, "queue": q_, "lines": out,
                             "status": "running", "returncode": None}

        def worker():
            t0 = time.time()
            # D70/D72：Popen 逐行读取，避免长任务等待期间 terminal 空白。
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, env=env,
                    cwd=cwd or str(_ENGINE_ROOT.parent))

                def reader():
                    try:
                        for raw in proc.stdout:
                            line = raw.rstrip("\r\n")
                            q_.put(line); out.append(line)
                            try:
                                print(f"[{prefix}] {line}", flush=True)
                            except Exception:
                                pass
                    except Exception as exc:  # noqa: BLE001
                        q_.put(str(exc)); out.append(str(exc))

                rt = threading.Thread(target=reader, daemon=True)
                rt.start()
                try:
                    proc.wait(timeout=2300)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=10)
                    except Exception:
                        pass
                    msg = "任务超时（超过 2300s），已强制终止"
                    q_.put(msg); out.append(msg)
                rt.join(timeout=5)
                rc = proc.returncode if proc.returncode is not None else -1
                _JOBS[job_id]["returncode"] = rc
                _JOBS[job_id]["status"] = "done" if rc == 0 else "failed"
                q_.put(f"__DONE__{rc}__")
                # D74-9：全局操作记录（成功/失败都记）
                try:
                    from .xxt import journal
                    journal.log_event(journal_kind or item, home=_xxt_home(),
                                      source="pwa", params=journal_params or {},
                                      result="ok" if rc == 0 else "fail",
                                      duration_ms=int((time.time() - t0) * 1000),
                                      error=(_job_error_summary(out) if rc != 0 else ""))
                except Exception:  # noqa: BLE001
                    pass
            except Exception as exc:  # noqa: BLE001
                q_.put(str(exc)); out.append(str(exc))
                _JOBS[job_id]["status"] = "failed"; _JOBS[job_id]["returncode"] = -1
                q_.put("__DONE__-1__")

        threading.Thread(target=worker, daemon=True).start()

    def _start_job(self, job_id: str, item: str):
        if item in ("deps", "katex", "tinytex", "playwright", "engine_update"):
            # D55/H1/D58 + D63/T7.1：特殊安装项（服务端写盘 / 联网下载解压；playwright=两步国内镜像联网）
            q: "queue.Queue[str]" = queue.Queue()
            out: list[str] = []
            with _JOBS_LOCK:
                _JOBS[job_id] = {"item": item, "queue": q, "lines": out, "status": "running", "returncode": None}

            def special_worker():
                try:
                    emit = lambda line: (q.put(line), out.append(line))
                    if item == "deps":
                        # D69：一键修复与 PWA 引擎更新共用同一套 uv→venv pip 回退安装。
                        from .engine_update import _install_engine_editable
                        rc = _install_engine_editable(_ws(), _ENGINE_ROOT, emit)
                    elif item == "katex":
                        rc = install_katex(_ws(), emit)
                    elif item == "playwright":
                        from .xxt.installer import install_playwright
                        rc = install_playwright(emit)
                    elif item == "engine_update":
                        from .engine_update import update_engine
                        rc = update_engine(_ws(), emit)
                    else:
                        from .paper.tinytex import install_tinytex
                        rc = install_tinytex(_ws(), emit)
                    _JOBS[job_id]["status"] = "ok" if rc == 0 else "fail"
                    _JOBS[job_id]["returncode"] = rc
                    q.put(f"__DONE__{rc}__")
                    try:
                        from .xxt import journal as _journal
                        _journal.log_event(f"install_{item}", home=_xxt_home(), source="pwa",
                                           result="ok" if rc == 0 else "fail",
                                           error=(_job_error_summary(out) if rc != 0 else ""))
                    except Exception:  # noqa: BLE001
                        pass
                except Exception as e:  # noqa: BLE001
                    q.put(f"异常：{e}"); out.append(str(e))
                    _JOBS[job_id]["status"] = "fail"; _JOBS[job_id]["returncode"] = 1
                    q.put("__DONE__1__")
                    try:
                        from .xxt import journal as _journal
                        _journal.log_event(f"install_{item}", home=_xxt_home(), source="pwa",
                                           result="fail", error=str(e))
                    except Exception:  # noqa: BLE001
                        pass

            threading.Thread(target=special_worker, daemon=True).start()
            return
        cmd, guide = installer_for(item) if item != "kb_init" else (None, None)
        if item in ("kb_init",):
            _, guide = installer_for("kb_init")
        q: "queue.Queue[str]" = queue.Queue()
        out: list[str] = []
        with _JOBS_LOCK:
            _JOBS[job_id] = {"item": item, "queue": q, "lines": out, "status": "running", "returncode": None}
        def worker():
            try:
                if cmd is None:
                    for line in (guide or ["无指引"]):
                        q.put(str(line)); out.append(str(line))
                    _JOBS[job_id]["status"] = "ok"; _JOBS[job_id]["returncode"] = 0
                    q.put("__DONE__0__")
                    return
                env = {
                    **os.environ,
                    "UV_CACHE_DIR": str(_ws() / ".runtime" / "cache" / "uv"),
                    "UV_PROJECT_ENVIRONMENT": str(_ws() / ".runtime" / "venv"),
                    "PLAYWRIGHT_BROWSERS_PATH": str(_ws() / ".runtime" / "browsers"),
                    "UV_DEFAULT_INDEX": os.environ.get(
                        "UV_DEFAULT_INDEX", "https://pypi.tuna.tsinghua.edu.cn/simple"),
                }
                cp = subprocess.run(cmd, capture_output=True, text=True, timeout=1200,
                                    cwd=str(_ENGINE_ROOT.parent), env=env)
                for line in (cp.stdout or "").splitlines():
                    q.put(line)
                for line in (cp.stderr or "").splitlines():
                    q.put(line)
                _JOBS[job_id]["returncode"] = cp.returncode
                _JOBS[job_id]["status"] = "done" if cp.returncode == 0 else "failed"
                q.put(f"__DONE__{cp.returncode}__")
            except Exception as exc:
                q.put(str(exc))
                _JOBS[job_id]["status"] = "failed"
                _JOBS[job_id]["returncode"] = -1
                q.put("__DONE__-1__")
        threading.Thread(target=worker, daemon=True).start()


    def do_OPTIONS(self):
        """CORS 预检：PWA 跨源 POST JSON（如 /kb/write）需要。
        D64 §22.1：Pages(公网https) → 本机引擎(http://127.0.0.1) 属 Chrome
        Private Network Access，预检必须回 Allow-Private-Network，否则体检/安装全线哑火。"""
        self.send_response(204)
        if self.cors:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def _auto_bind_classes(self, works: "list[dict]") -> "tuple[list[dict], list[dict]]":
        """D121-G2：为作业列表里的学习通班级自动建立 classmap（仅唯一精确命中）。

        返回 `(auto_bound, need_confirm)`：
        - auto_bound:  `[{classId, className, classDir}]`
        - need_confirm:`[{classId, className, candidates: [...]}]`
        """
        auto_bound: list[dict] = []
        need_confirm: list[dict] = []
        seen: set = set()
        try:
            from .xxt import classmap
            ws = Path(self.ws).resolve()
            for w in works or []:
                kid = str(w.get("classId") or "")
                cid = str(w.get("courseId") or "")
                if not kid or (cid, kid) in seen:
                    continue
                seen.add((cid, kid))
                if cid and classmap.class_dir_for(ws, cid, kid):
                    continue                      # 已绑定
                name = str(w.get("className") or "")
                try:
                    rep = classmap.resolve_or_raise(ws, cid, kid, name)
                    if rep.get("source") == "auto":
                        auto_bound.append({"classId": kid, "className": name,
                                           "classDir": rep["classDir"]})
                except classmap.ClassDirResolutionError:
                    cands = classmap.suggest_class_dir(ws, name)
                    need_confirm.append({"classId": kid, "className": name,
                                         "candidates": cands[:5]})
        except Exception:  # noqa: BLE001 —— 自动绑定失败不影响作业列表
            logger.debug("auto bind classes 跳过（异常）", exc_info=True)
        return auto_bound, need_confirm

    def _grade_preflight(self, cid: str, kid: str, work: str, task_id: str,
                         pad_path: Path, pads_dir: str = "",
                         ) -> "tuple[dict, int] | None":
        """D118：AI 批阅启动前的输入体检。

        只检查"有没有学生作答图"这一条**最常见且不可自动修复**的前提：
        学习通下载的作答图落在 `<ws>/grading/<class>/<work>/images/`（或 review 目录），
        若一张都没有，转录步必然无从下手。此前会一路跑到 `group_images()` 才抛
        `FileNotFoundError: [WinError 3] ...\\images`，教师只看到堆栈。
        """
        try:
            import json as _json
            from .grading import inputs as _inputs
            from .xxt import classmap
            ws = Path(self.ws).resolve()
            task = _json.loads(pad_path.read_text(encoding="utf-8"))
            resolved = classmap.resolve_class_dir(ws, cid, kid, str(task.get("class") or ""))
            class_dir = resolved.get("classDir") or str(task.get("class_dir") or "classes")
            tasks_dir = Path(pads_dir).expanduser().resolve() if pads_dir else None
            plan = _inputs.build_plan(ws, task_id=task_id, class_dir=class_dir,
                                      class_id=kid, work_id=work,
                                      mode="optimized", tags=[], tasks_dir=tasks_dir)
            summ = _inputs.plan_summary(plan)
            if summ.get("students") and not summ.get("withImages"):
                return ({"ok": False,
                         "error": ("没有任何学生有作答图，AI 批阅无法开始。"
                                   "请先到「作业预览-学习通」对该作业点「⬇ 下载作答/批语」，"
                                   "再回到本页重试。"),
                         "detail": {"students": summ.get("students"),
                                    "withImages": 0,
                                    "hint": "下载后作答图落在 <workspace>/grading/<班级>/<作业>/images/"},
                         "hint": "下载作答图"}, 400)
            return None
        except Exception:  # noqa: BLE001 —— 体检失败不阻断（交给正式流程报错）
            logger.warning("grade preflight 跳过（异常，不影响正式流程）", exc_info=True)
            return None

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        _np, _legacy = _rewrite_legacy_atopia(u.path)
        if _legacy:
            # D134：旧名 `/assistopia/*` 永久转发到 `/atopia/*`
            u = u._replace(path=_np)
            self.path = urllib.parse.urlunparse(u)
        qs = urllib.parse.parse_qs(u.query)
        if not self._ok_token(qs):
            self._json({"ok": False, "error": "token required"}, 401)
            return
        if u.path.startswith("/xxt/"):
            xxt_err = _xxt_import_error()
            if xxt_err:
                self._json({"ok": False,
                            "error": "学习通模块不可用（引擎安装不完整）",
                            "detail": xxt_err,
                            "hint": "关闭引擎窗口 → 删除 workspace/_engine → 重新双击 start.bat；见 docs/24 §14"}, 503)
                return
        if u.path == "/materials/upload":
            # D134-T3a：PWA 上传附件 → materials/<chap>/_source/（同名不覆盖）
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8")) \
                    if length else {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .files import materials as _mup
            chap = str(payload.get("chap") or "").strip()
            if not chap:
                self._json({"ok": False, "error": "缺少 chap（章节名）"}, 400)
                return
            try:
                rep = _mup.save_uploads(Path(self.ws).resolve(), chap,
                                        payload.get("items") or [],
                                        kind=str(payload.get("kind") or ""))
            except _mup.MaterialsError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            rep["files"] = _mup.files_of(Path(self.ws).resolve(), chap)
            self._json(rep)
            return
        if u.path == "/roster/tags-snapshot":
            # D168：「重算并打 tag」关联作业包 → 立即冻结该包的 学生→tag 快照
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .grading import snapshots as _sn
            try:
                rep = _sn.write_tags_snapshot(
                    Path(self.ws).resolve(),
                    str(payload.get("classDir") or ""),
                    str(payload.get("packId") or ""),
                    payload.get("students") or [],
                    source=str(payload.get("source") or _sn.SOURCE_RECOMPUTE),
                    force=bool(payload.get("force")))
            except _sn.SnapshotError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/roster/write":
            # D120：名单落盘（路径由引擎权威决定：<ws>/<class_dir>/roster/roster.xlsx）
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .files import roster_io
            rep = roster_io.write_roster(Path(self.ws).resolve(),
                                         str(payload.get("classDir") or ""),
                                         payload.get("students") or [],
                                         class_name=str(payload.get("className") or ""),
                                         class_id=str(payload.get("classId") or ""))
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/taskpad/save":
            payload = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .files import taskpads
            rep = taskpads.save_taskpad(Path(self.ws).resolve(), payload.get("taskpad") or {})
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/workspace/backup":
            payload = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception:  # noqa: BLE001
                payload = {}
            from . import backup as B
            rep = B.create_backup(Path(self.ws).resolve(),
                                  browser_data=payload.get("browser") or None)
            if rep.get("ok"):
                chk = B.verify_no_secrets(rep["path"])
                rep["secretCheck"] = chk
                if not chk.get("ok"):
                    rep["ok"] = False
                    rep["error"] = "备份包自检失败：疑似含未脱敏密钥"
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/workspace/clean-junk":
            payload = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception:  # noqa: BLE001
                payload = {}
            from . import workspace_junk as WJ
            rep = WJ.clean_junk(Path(self.ws).resolve(), apply=bool(payload.get("apply")))
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/workspace/fix-layout":
            payload = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception:  # noqa: BLE001
                payload = {}
            from . import workspace_layout as WL
            rep = WL.fix_layout(Path(self.ws).resolve(),
                               apply=bool(payload.get("apply")),
                               move=bool(payload.get("move")))
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/workspace/fix-class-dirs":
            payload = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception:  # noqa: BLE001
                payload = {}
            from . import class_dir_audit as CDA
            rep = CDA.fix(Path(self.ws).resolve(), apply=bool(payload.get("apply")))
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/workspace/auto-bind-classes":
            # D124：把 PWA 的班级表（id/name）交给引擎，按名称自动绑定 class_map
            payload = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception:  # noqa: BLE001
                payload = {}
            from .xxt import classmap
            ws_ = Path(self.ws).resolve()
            bound, skipped = [], []
            for c in payload.get("classes") or []:
                if not isinstance(c, dict):
                    continue
                name = str(c.get("name") or "").strip()
                cid = str(c.get("id") or "").strip()
                if not (name and cid):
                    continue
                if (ws_ / "classes" / name).is_dir():
                    try:
                        classmap.set_class_dir(ws_, "", cid, f"classes/{name}")
                        bound.append({"classId": cid, "classDir": f"classes/{name}"})
                    except Exception:  # noqa: BLE001
                        skipped.append({"classId": cid})
                else:
                    skipped.append({"classId": cid, "reason": f"目录不存在：classes/{name}"})
            self._json({"ok": True, "bound": bound, "skipped": skipped})
            return
        if u.path == "/workspace/clean-migrated":
            payload = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception:  # noqa: BLE001
                payload = {}
            from . import workspace_layout as WL
            rep = WL.clean_migrated(Path(self.ws).resolve(), apply=bool(payload.get("apply")))
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/kb/write":
            # B4：PWA 把内存 KbBook（kind + chapters）交给引擎，openpyxl 原位改值保留样式。
            from .files import snapshot, write_chapters_preserving
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            kind = str((payload or {}).get("kind") or "")
            chapters = (payload or {}).get("chapters")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", kind) or not isinstance(chapters, dict):
                self._json({"ok": False, "error": "kind/chapters required"}, 400)
                return
            try:
                kb_dir = Path(self.ws).resolve() / "kb"
                kb_dir.mkdir(parents=True, exist_ok=True)
                snapshot(kb_dir, [kind])
                out = write_chapters_preserving(kb_dir / f"{kind}.xlsx", chapters)
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)}, 500)
                return
            self._json({"ok": True, "path": str(out), "kind": kind})
            return
        if u.path == "/xxt/login/start":
            job_id = secrets.token_urlsafe(6)
            home = _xxt_home()
            # D66：同步清掉旧二维码，避免后台任务刚启动时又让前端拿到过去的登录票据。
            try:
                (home / "xxt-qr.png").unlink()
            except FileNotFoundError:
                pass
            # 顺序很重要：本引擎解析出的 xxt 根必须覆盖外部环境里的旧 XXT_STORAGE/XXT_HOME；
            # 这样 qr_login 写出的 QR 与 GET /xxt/qr 读取的路径才是同一处。
            # D68：与 docs/16 §20.3 “CLI 套壳”决议对齐——PWA 不直接调 qr_login()，
            # 而是走 `assist xxt login`：内部同样写 storage JSON，并在登录后跑
            # check_session() 做二次确认 + storage_state 回写续期。
            env = _xxt_env(home)
            cwd = str(_ws())
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False,
                            "error": "engine 无法 import assist.cli",
                            "detail": detail}, 500)
                return
            cmd = _xxt_login_cmd(home)
            self._start_stream_job(job_id, cmd, env, "xxt_login", "xxt-login", cwd,
                                    journal_kind="xxt_login")
            self._json({"ok": True, "job_id": job_id, "qr_url": "/xxt/qr"})
            return
        if u.path == "/xxt/extract":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            mode = str(payload.get("mode") or "all")
            home = _xxt_home()
            target_count = 0
            if mode == "all":
                cmd = _xxt_cli_cmd(["xxt", "extract", "--all"])
            elif mode == "targets":
                from .xxt.targets import sanitize_targets
                targets, err = sanitize_targets(payload.get("targets"))
                if err:
                    self._json({"ok": False, "error": err}, 400)
                    return
                # D74-6：spec 写到 targets/ 子目录，避免被 run 扫描当成 run；
                # 顺手清掉旧位置遗留文件，防止历史列表再出现 xxt-extract-targets。
                spec = xxt_layout.targets_spec_json(home)
                try:
                    spec.parent.mkdir(parents=True, exist_ok=True)
                    spec.write_text(json.dumps({"courses": targets}, ensure_ascii=False),
                                    encoding="utf-8")
                    legacy = home / "xxt-extract-targets.json"
                    if legacy.is_file():
                        legacy.unlink()
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": f"write targets failed: {exc}"}, 500)
                    return
                target_count = sum(len(c["classes"]) for c in targets)
                append_run = str(payload.get("append_run_id") or "").strip()
                cmd = _xxt_cli_cmd(["xxt", "extract", "--targets", str(spec)])
                if append_run:
                    cmd += ["--append", append_run[:120]]
            else:
                self._json({"ok": False, "error": "unsupported mode",
                            "hint": "支持 mode=all 或 mode=targets"}, 400)
                return
            env = _xxt_env(home)
            cwd = str(_ws())
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False,
                            "error": "engine 无法 import assist.cli",
                            "detail": detail}, 500)
                return
            if bool(payload.get("skip_notices", False)):
                cmd.append("--skip-notices")
            job_id = secrets.token_urlsafe(6)
            self._start_stream_job(job_id, cmd, env, "xxt_extract", "xxt-extract", cwd,
                                    journal_kind="xxt_extract",
                                    journal_params={"mode": mode, "classes": target_count,
                                                    "append_run_id": str(payload.get("append_run_id") or ""),
                                                    "skip_notices": bool(payload.get("skip_notices", False))})
            self._json({"ok": True, "job_id": job_id, "mode": mode,
                        "targets": target_count,
                        "skip_notices": bool(payload.get("skip_notices", False))})
            return
        if u.path == "/xxt/discover":
            home = _xxt_home()
            env = _xxt_env(home)
            cwd = str(_ws())
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False,
                            "error": "engine 无法 import assist.cli",
                            "detail": detail}, 500)
                return
            out_path = xxt_layout.targets_json(home)
            cmd = _xxt_cli_cmd(["xxt", "discover", "--out", str(out_path)])
            job_id = secrets.token_urlsafe(6)
            self._start_stream_job(job_id, cmd, env, "xxt_discover", "xxt-discover", cwd,
                                    journal_kind="xxt_discover")
            self._json({"ok": True, "job_id": job_id})
            return
        if u.path == "/xxt/works":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .xxt.targets import sanitize_targets
            targets, err = sanitize_targets(payload.get("targets"))
            if err:
                self._json({"ok": False, "error": err}, 400)
                return
            home = _xxt_home()
            spec = xxt_layout.works_spec_json(home)
            spec.parent.mkdir(parents=True, exist_ok=True)
            spec.write_text(json.dumps({"courses": targets}, ensure_ascii=False),
                            encoding="utf-8")
            env = _xxt_env(home)
            cwd = str(_ws())
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False, "error": "engine 无法 import assist.cli",
                            "detail": detail}, 500)
                return
            cmd = _xxt_cli_cmd(["xxt", "discover-works", "--targets", str(spec),
                                "--out", str(xxt_layout.works_json(home))])
            job_id = secrets.token_urlsafe(6)
            self._start_stream_job(job_id, cmd, env, "xxt_works", "xxt-works", cwd,
                                   journal_kind="xxt_discover_works",
                                   journal_params={"classes": sum(len(c["classes"]) for c in targets)})
            self._json({"ok": True, "job_id": job_id})
            return
        if u.path in ("/xxt/review/download", "/xxt/review/probe"):
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            ids = {k: str(payload.get(k) or "").strip() for k in ("courseId", "classId", "workId")}
            bad = next((k for k, v in ids.items() if not re.fullmatch(r"[0-9A-Za-z]{1,32}", v)), None)
            if bad:
                self._json({"ok": False, "error": f"{bad} 非法"}, 400)
                return
            home = _xxt_home()
            env = _xxt_env(home)
            cwd = str(_ws())
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False, "error": "engine 无法 import assist.cli",
                            "detail": detail}, 500)
                return
            is_probe = u.path.endswith("/probe")
            args = ["xxt", "review-probe" if is_probe else "review-download",
                    "--course", ids["courseId"], "--class", ids["classId"], "--work", ids["workId"]]
            if not is_probe:
                for key, flag in (("courseName", "--course-name"), ("className", "--class-name"),
                                  ("workName", "--work-name")):
                    if payload.get(key):
                        args += [flag, str(payload[key])[:80]]
                if payload.get("limit"):
                    args += ["--limit", str(int(payload["limit"]))]
                if payload.get("mode"):
                    args += ["--mode", str(payload["mode"])[:20]]
            else:
                args += ["--sample", str(int(payload.get("sample") or 1))]
            for pat in (payload.get("allowPost") or [])[:20]:
                args += ["--allow-post", str(pat)[:200]]
            if payload.get("fallback"):
                args.append("--fallback")
            job_id = secrets.token_urlsafe(6)
            self._start_stream_job(job_id, _xxt_cli_cmd(args), env,
                                   "xxt_review_probe" if is_probe else "xxt_review_download",
                                   "xxt-review", cwd,
                                   journal_kind="xxt_review_probe" if is_probe else "xxt_review_download",
                                   journal_params={"classId": ids["classId"], "workId": ids["workId"],
                                                   "mode": str(payload.get("mode") or "missing")})
            self._json({"ok": True, "job_id": job_id})
            return
        if u.path == "/xxt/write-allowlist":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .xxt.allowlist import write_allowlist
            items = write_allowlist(Path(self.ws).resolve(), payload.get("items") or [])
            self._json({"ok": True, "items": items})
            return
        if u.path in ("/xxt/work/folder-create", "/xxt/work/copy"):
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            cid = str(payload.get("courseId") or "")
            kid = str(payload.get("classId") or "")
            cpi = str(payload.get("cpi") or "0")
            directory = str(payload.get("directoryId") or "0")
            title = str(payload.get("title") or "")[:50]
            from .xxt.work import copy_work, create_folder, validate_work_target
            err = validate_work_target(cid, kid, Path(self.ws).resolve())
            if err:
                self._json({"ok": False, "error": err}, 400)
                return
            if u.path.endswith("/folder-create"):
                rep = create_folder(_xxt_home() / "xxt-storage.json", cid, kid, cpi, directory, title)
            else:
                rep = copy_work(_xxt_home() / "xxt-storage.json", cid, kid, cpi, directory,
                                str(payload.get("workLibraryId") or ""), title)
            self._json(rep)
            return
        if u.path == "/xxt/work/create":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            cid = str(payload.get("courseId") or "")
            kid = str(payload.get("classId") or "")
            cpi = str(payload.get("cpi") or "0")
            title = str(payload.get("title") or "")[:100]
            stem = str(payload.get("stemHtml") or "")
            directory = str(payload.get("directoryId") or "0")
            from .xxt.work import validate_work_target
            err = validate_work_target(cid, kid, Path(self.ws).resolve())
            if err:
                self._json({"ok": False, "error": err}, 400)
                return
            args = ["xxt", "work-create", "--course", cid, "--class", kid, "--cpi", cpi,
                    "--title", title, "--stem", stem, "--directory-id", directory]
            # D83-7：附件（base64 items）→ 落 workspace 临时目录 → 作为 --attach 传给 CLI；
            #        扩展名白名单复用通知那套（settings.local.json → xxt.notice_attachment_exts）。
            att_items = payload.get("attachments") or []
            if att_items:
                from .xxt.allowlist import read_notice_attachment_exts
                from .xxt.notice import save_notice_uploads
                saved = save_notice_uploads(Path(self.ws).resolve(), att_items,
                                            allowed_exts=read_notice_attachment_exts(Path(self.ws).resolve()))
                for it in saved:
                    args += ["--attach", str(it.get("path"))]
            home = _xxt_home(); env = _xxt_env(home); cwd = str(_ws())
            # D106：图片压缩模式与 SVG 重绘开关（PWA 设置 → 环境变量）
            if str(payload.get("imageMode") or "") == "original":
                env["ASSIST_IMAGE_MODE"] = "original"
            if payload.get("svgRedraw") is True:
                env["ASSIST_SVG_REDRAW"] = "1"
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False, "error": "engine 无法 import assist.cli", "detail": detail}, 500)
                return
            job_id = secrets.token_urlsafe(6)
            self._start_stream_job(job_id, _xxt_cli_cmd(args), env, "xxt_work_create", "xxt-work", cwd,
                                   journal_kind="xxt_work_create",
                                   journal_params={"courseId": cid, "classId": kid, "directoryId": directory})
            self._json({"ok": True, "job_id": job_id})
            return
        if u.path == "/xxt/class-map":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .xxt import classmap
            ws = Path(self.ws).resolve()
            cid, kid = str(payload.get("courseId") or ""), str(payload.get("classId") or "")
            if payload.get("auto"):
                rep = classmap.resolve_class_dir(ws, cid, kid, str(payload.get("name") or ""),
                                                 auto_write=bool(payload.get("write")))
            else:
                # D123：保存映射时规范化 + 校验目录存在（不存在 → 400 + 可选项）
                try:
                    rep = {"ok": True, "map": classmap.set_class_dir(ws, cid, kid,
                                                                    str(payload.get("classDir") or ""))}
                except classmap.ClassDirResolutionError as exc:
                    self._json({"ok": False, "error": str(exc),
                                "candidates": [c["classDir"] for c in
                                               classmap.list_class_candidates(ws)][:8]}, 400)
                    return
            self._json(rep, 200 if rep.get("ok", True) else 400)
            return
        if u.path == "/llm/test":
            # D125：按段测试 LLM 配置（转录=多模态 / 评阅=纯文本）
            payload = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception:  # noqa: BLE001
                payload = {}
            stage = str(payload.get("stage") or "both").lower()
            stages = (["transcription", "evaluation"] if stage == "both" else [stage])
            from .grading.llm import LLMAPIError, LLMClient
            ws_ = Path(self.ws).resolve()
            results = []
            for st in stages:
                item: dict = {"stage": st, "ok": False}
                try:
                    client = LLMClient(ws=ws_)
                    ep = client._step_endpoint(st)
                    item.update({"provider": ep.get("provider") or "",
                                 "type": ep.get("type") or "api",
                                 "base_url": ep.get("base_url") or "",
                                 "model": ep.get("model") or "",
                                 "hasKey": bool(ep.get("api_key"))})
                    t0 = time.time()
                    if st == "transcription":
                        import tempfile as _tf

                        from PIL import Image as _Im
                        fd, png = _tf.mkstemp(suffix=".png")
                        try:
                            # D127-FIX：探针图 **128×128 彩色块**。
                            # 之前用 8×8 纯白，阿里云 MAAS 直接 400
                            # "height:8 or width:8 must be larger than 10" →
                            # 看起来像"配置错误"，其实配置是通的，只是测试图太小。
                            # 真实作答图都是 1000px 级别，探针也必须接近真实量级。
                            _probe = _Im.new("RGB", (128, 128), (220, 40, 40))
                            for _x in range(64, 128):
                                for _y in range(128):
                                    _probe.putpixel((_x, _y), (40, 60, 200))
                            _probe.save(png)
                            txt = client.chat_with_images(
                                "你是一个测试助手。", "这张图片主要是什么颜色？只回答颜色。",
                                [png], max_tokens=256, step="transcription")
                        finally:
                            try:
                                Path(png).unlink()
                            except OSError:
                                pass
                    else:
                        txt = client.chat("你是一个测试助手。", "只回复两个字：收到。",
                                          max_tokens=256, step="evaluation")
                    item.update({"ok": True, "ms": int((time.time() - t0) * 1000),
                                 "reply": str(txt or "")[:60]})
                except LLMAPIError as exc:
                    item["error"] = str(exc)[:400]
                    item["errorKind"] = _llm_error_kind(str(exc))
                except Exception as exc:  # noqa: BLE001
                    item["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                    item["errorKind"] = "unknown"
                results.append(item)
            ok = all(r["ok"] for r in results)
            # D127：**始终返回 200**。此前用 HTTP 400 表达"测试没通过"，
            # 前端 `if (!res.ok && !o?.error) throw new Error("HTTP 400")` 只能显示
            # 一句 "HTTP 400"，把真正的 provider/base_url/model/error 全吞掉了。
            self._json({"ok": ok, "results": results,
                        "error": "" if ok else _llm_test_summary(results)}, 200)
            return
        if u.path == "/llm/provider":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .grading import providers
            ws = Path(self.ws).resolve()
            action = str(payload.get("action") or "set")
            if action == "delete":
                rep = providers.delete_provider(ws, str(payload.get("name") or ""))
            elif action == "stage":
                rep = providers.set_stage(ws, str(payload.get("stage") or ""),
                                          provider=str(payload.get("provider") or ""),
                                          model=str(payload.get("model") or ""),
                                          batch=payload.get("batch"))
            else:
                key = payload.get("api_key")
                # D137：PWA 可编辑自定义请求头 / user-agent（白名单由 providers 强校验）
                hdrs = payload.get("headers")
                rep = providers.save_provider(
                    ws, str(payload.get("name") or ""),
                    base_url=str(payload.get("base_url") or ""),
                    api_key=(None if key is None else str(key)),
                    batch_support=payload.get("batch_support"),
                    model=str(payload.get("model") or ""),
                    forget_model=str(payload.get("forget_model") or ""),
                    headers=(dict(hdrs) if isinstance(hdrs, dict) else None),
                    user_agent=(str(payload["user_agent"])
                                if "user_agent" in payload else None))
            rep["config"] = providers.public_config(ws)
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/materials/copy-from-atopia":
            # D164：把 Atopia 解析产物**复制**进课堂资料（会成为 summary 批阅依据）。
            # 安全口径与 materials.confirm 一致：必须教师显式 confirm + 全文预览在前端完成。
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            confirm = str(payload.get("confirm") or "").strip()
            if not confirm:
                self._json({"ok": False, "denied": True,
                            "error": "复制到课堂资料必须由教师显式确认（缺少 confirm）"}, 403)
                return
            from .atopia import work as _aw
            from .files import materials as _mat
            feat = str(payload.get("feature") or "").strip()
            fname = str(payload.get("file") or "").strip()
            ws_ = Path(self.ws).resolve()
            try:
                data = _aw.read_parsed(ws_, feat, fname)
            except _aw.WorkError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            try:
                d = _mat.ensure_chap(ws_, feat)
                # 写 json（机器读，权威）+ md（人可读）
                jp = d / "知识点清单.json"
                jp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                              encoding="utf-8")
                md = _mat.render_knowledge_md({**data, "chap": feat})
                (d / _mat.KNOW_MD).write_text(md, encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"写入失败：{str(exc)[:200]}"}, 500)
                return
            self._json({"ok": True, "feature": feat, "json": str(jp),
                        "md": str(d / _mat.KNOW_MD), "confirmed_by": confirm,
                        "terms": len([k for k in (data.get("knowledge") or [])
                                      if isinstance(k, dict)])})
            return
        if u.path == "/atopia/work/upload":
            # D164：上传到 atopia/work/<特征名>/_upload/（与 materials 物理隔离）
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .atopia import work as _aw
            feat = str(payload.get("feature") or "").strip()
            try:
                rep = _aw.save_uploads(Path(self.ws).resolve(), feat,
                                       payload.get("items") or [])
                rep["files"] = _aw.files_of(Path(self.ws).resolve(), feat)
            except _aw.WorkError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            self._json(rep)
            return
        if u.path == "/atopia/work/extract":
            # D168-B4 工步 0：抽取（确定性、**免费**、不调模型）
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .atopia import work as _aw
            feat = str(payload.get("feature") or "").strip()
            try:
                rep = _aw.extract_uploads(Path(self.ws).resolve(), feat,
                                          force=bool(payload.get("force")))
            except _aw.WorkError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/atopia/work/parse":
            # D168-B4 工步 1：用 atopia-task 模板做 AI 结构化（**会花模型钱**）
            # 产物只落 _parsed/；进 materials 仍需教师显式确认（D164 已有）。
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .atopia import work as _aw
            from .grading.llm import LLMConfigError, LLMClient
            feat = str(payload.get("feature") or "").strip()
            if not feat:
                self._json({"ok": False, "error": "缺少 feature（特征名）"}, 400)
                return
            try:
                client = LLMClient(ws=Path(self.ws).resolve())
                rep = _aw.parse_with_task(
                    client, Path(self.ws).resolve(), feat,
                    task_id=str(payload.get("taskId") or ""),
                    model=str(payload.get("model") or "") or None,
                    extra_context=str(payload.get("extraContext") or ""))
            except LLMConfigError as exc:
                self._json({"ok": False, "error": f"LLM 未配置：{exc}"}, 400)
                return
            except _aw.WorkError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)[:300]}, 500)
                return
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/kb/examples/import":
            # D168-B5：把 Atopia `example-extract` 的产物导入 `kb/example.xlsx`
            # 例题库**只做分析**（标准共现图），不布置、不批阅。
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            confirm = str(payload.get("confirm") or "").strip()
            if not confirm:
                self._json({"ok": False, "denied": True,
                            "error": "导入例题库必须由教师显式确认（缺少 confirm）"}, 403)
                return
            from .atopia import work as _aw
            from .grading import kb_examples as _ke
            ws_ = Path(self.ws).resolve()
            data = payload.get("data")
            if not isinstance(data, dict):
                # 没直接给数据 → 从 atopia 解析产物读
                feat = str(payload.get("feature") or "").strip()
                fname = str(payload.get("file") or "").strip()
                if not (feat and fname):
                    self._json({"ok": False, "error": "需要 data，或 feature+file"}, 400)
                    return
                try:
                    data = _aw.read_parsed(ws_, feat, fname)
                except _aw.WorkError as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
                    return
            try:
                rep = _ke.import_examples(
                    ws_, data,
                    chap=str(payload.get("chap") or "examples"),
                    replace=bool(payload.get("replace")))
            except _ke.ExampleError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            rep["confirmed_by"] = confirm
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/materials/create":
            # D163：新建一个「特征名」资料目录（26C1 等）——PWA 里没有它就只能手工建目录
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .files import materials as _mc
            chap = str(payload.get("chap") or "").strip()
            if not chap:
                self._json({"ok": False, "error": "请填写特征名（如 26C1）"}, 400)
                return
            try:
                d = _mc.ensure_chap(Path(self.ws).resolve(), chap)
            except _mc.MaterialsError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            self._json({"ok": True, "chap": chap, "path": str(d)})
            return
        if u.path == "/materials/extract":
            # D137：抽取某章资料（无 LLM 成本）
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .files import materials as _mx
            chap = str(payload.get("chap") or "").strip()
            if not chap:
                self._json({"ok": False, "error": "缺少 chap"}, 400)
                return
            try:
                rep = _mx.extract_chap(Path(self.ws).resolve(), chap,
                                       force=bool(payload.get("force")))
            except _mx.MaterialsError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            rep["chap"] = chap
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/materials/suggest":
            # D137：AI 抽取知识点建议（**会花模型钱**，只写 .ai.json，不生效）
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .files import materials as _ms
            from .grading.llm import LLMConfigError, LLMClient
            chap = str(payload.get("chap") or "").strip()
            if not chap:
                self._json({"ok": False, "error": "缺少 chap"}, 400)
                return
            ws_ = Path(self.ws).resolve()
            try:
                client = LLMClient(ws=ws_)
                rep = _ms.suggest_knowledge(client, ws_, chap,
                                            model=str(payload.get("model") or "") or None)
            except _ms.MaterialsError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            except LLMConfigError as exc:
                self._json({"ok": False, "error": f"LLM 未配置：{exc}"}, 400)
                return
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)[:400]}, 500)
                return
            rep["chap"] = chap
            self._json(rep)
            return
        if u.path == "/materials/confirm":
            # D137：把 AI 建议固化为**生效**清单。
            # 安全口径（D131 原意不放松）：教师显式点击 + 弹窗先看全文 +
            # 默认不覆盖已有 .md（需显式 force）。
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            confirm = str(payload.get("confirm") or "").strip()
            if not confirm:
                self._json({"ok": False, "denied": True,
                            "error": "确认生效必须由教师显式确认（缺少 confirm）"}, 403)
                return
            from .files import materials as _mc
            chap = str(payload.get("chap") or "").strip()
            if not chap:
                self._json({"ok": False, "error": "缺少 chap"}, 400)
                return
            try:
                rep = _mc.confirm_knowledge(Path(self.ws).resolve(), chap,
                                            force=bool(payload.get("force")))
            except _mc.MaterialsError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            rep["chap"] = chap
            rep["confirmed_by"] = confirm
            self._json(rep)
            return
        # ---------------- D151：提示词模板（多类别 system prompt） ----------------
        # ---------------- D148：知识点（标注 / 词表 / 要点生成） ----------------
        if u.path == "/knowledge/tag":
            # AI 为题目打知识点标签（默认只标未标注；dryRun 只预览）
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            dry = payload.get("dryRun") is True
            args = ["kb", "tag-knowledge"]
            for k in (payload.get("kb") or []):
                args += ["--kb", str(k)]
            for c in (payload.get("chap") or []):
                args += ["--chap", str(c)]
            if payload.get("ids"):
                ids = payload.get("ids")
                args += ["--ids", ",".join(ids) if isinstance(ids, list) else str(ids)]
            if payload.get("force") is True:
                args += ["--force"]
            if dry:
                args += ["--dry-run"]
            if payload.get("model"):
                args += ["--model", str(payload.get("model"))]
            cmd = [sys.executable, "-m", "assist.cli", *args, "--workspace", str(self.ws)]
            try:
                proc = subprocess.run(cmd, cwd=str(self.ws), capture_output=True,
                                      text=True, timeout=1800, check=False)
            except subprocess.TimeoutExpired:
                self._json({"ok": False, "error": "知识点标注超时（>30 分钟）"}, 504)
                return
            if proc.returncode != 0:
                self._json({"ok": False, "error": (proc.stderr or "")[-600:]}, 400)
                return
            try:
                self._json(json.loads(proc.stdout))
            except json.JSONDecodeError:
                self._json({"ok": True, "raw": proc.stdout[-2000:]})
            return
        if u.path == "/knowledge/vocab":
            from .grading import vocab as V
            ws_ = Path(self.ws).resolve()
            self._json({"ok": True, **V.load_vocab(ws_)})
            return
        if u.path == "/knowledge/rubric-batch":
            # 批量生成 AI 评阅要点（dryRun 只预览；apply 写版本库，默认不置顶）
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            args = ["rules", "generate", "--kind", str(payload.get("kind") or "problems")]
            if payload.get("chap"):
                args += ["--chap", str(payload.get("chap"))]
            if payload.get("ids"):
                ids = payload.get("ids")
                args += ["--ids", ",".join(ids) if isinstance(ids, list) else str(ids)]
            if payload.get("force") is True:
                args += ["--force"]
            if payload.get("apply") is True:
                args += ["--apply"]
            cmd = [sys.executable, "-m", "assist.cli", *args, "--workspace", str(self.ws)]
            try:
                proc = subprocess.run(cmd, cwd=str(self.ws), capture_output=True,
                                      text=True, timeout=1800, check=False)
            except subprocess.TimeoutExpired:
                self._json({"ok": False, "error": "生成要点超时（>30 分钟）"}, 504)
                return
            if proc.returncode != 0:
                self._json({"ok": False, "error": (proc.stderr or "")[-600:]}, 400)
                return
            try:
                self._json(json.loads(proc.stdout))
            except json.JSONDecodeError:
                self._json({"ok": True, "raw": proc.stdout[-2000:]})
            return
        if u.path == "/prompts/save":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .files import prompts as _pp
            ws_ = Path(self.ws).resolve()
            cat = str(payload.get("category") or "ai-solve")
            action = str(payload.get("action") or "save")
            if action == "delete":
                rep = _pp.delete_template(ws_, str(payload.get("id") or ""), cat)
            elif action == "default":
                rep = _pp.set_default(ws_, str(payload.get("id") or ""), cat)
            else:
                rep = _pp.save_template(ws_, pid=str(payload.get("id") or ""),
                                        name=str(payload.get("name") or ""),
                                        text=str(payload.get("text") or ""),
                                        make_default=payload.get("makeDefault") is True,
                                        category=cat)
            rep["items"] = _pp.list_templates(ws_, cat)
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/atopia/ask":
            # D140：Atopia 对话（多轮 + 工具调用，全部经同一 Gate）
            # 安全：L3 拒绝、L2 必须教师确认（confirmed=true 才放行）、护栏照旧。
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            task = str(payload.get("task") or "").strip()
            if not task:
                self._json({"ok": False, "error": "请输入要 AI 做的事（task）"}, 400)
                return
            from .atopia import agent as _ag
            from .atopia import limits as _al3
            from .atopia.registry import ToolDenied as _TD3
            from .grading.llm import LLMClient, LLMConfigError
            ws_ = Path(self.ws).resolve()
            sess = _al3.Session(session_id=str(payload.get("session") or "pwa-chat"),
                                limits=_al3.read_limits(ws_))
            confirmed = payload.get("confirmed") is True
            conf_note = str(payload.get("confirmedBy") or "teacher:pwa")
            # D147 安全修复：确认必须**精确到"哪个工具 + 哪些参数"**。
            # 此前只看 `confirmed=true` → 教师为 A 确认后，同一次请求里 AI 改请求
            # 另一个 L2 工具（如 kb.write）也会被自动放行（实测可复现），
            # 违背 D132「L2 必须**逐次**确认」。
            conf_args = payload.get("confirmedArgs")
            # D147：确认精确到"哪个工具 + 哪些参数"（实现见 make_atopia_confirm）
            _confirm = make_atopia_confirm(
                confirmed=confirmed,
                confirmed_tool=str(payload.get("confirmedTool") or ""),
                confirmed_args=(conf_args if isinstance(conf_args, dict) else None),
                confirmed_by=conf_note)

            # D146：Atopia 可选 provider/模型（与 Playground 共用 build_client_for）
            try:
                from .grading.llm import build_client_for
                client, _used_model = build_client_for(
                    ws_, str(payload.get("provider") or ""),
                    str(payload.get("model") or ""), session_prefix="atopia")
            except LLMConfigError as exc:
                self._json({"ok": False, "error": f"LLM 未配置：{exc}"}, 400)
                return
            # D136：一次对话 = 一个 session id（前端传则复用，保证 prompt 缓存命中）
            if payload.get("sessionId"):
                client.set_session_id(str(payload.get("sessionId")))
            try:
                # D168-B6：按场景分组暴露工具（payload.groups=["kb","materials"]）；
                # 不传 = 全部（旧行为）。
                _groups = payload.get("groups")
                _groups = ([str(g) for g in _groups]
                           if isinstance(_groups, list) and _groups else None)
                rep = _ag.run_session_auto(
                    client, ws_, task, model=str(payload.get("model") or "") or None,
                    session=sess, confirm=_confirm,
                    max_turns=int(payload.get("maxTurns") or 6),
                    prefer=str(payload.get("protocol") or "native"),
                    groups=_groups)
            except _TD3 as exc:
                self._json({"ok": False, "denied": True, "error": str(exc)}, 403)
                return
            except _al3.LimitExceeded as exc:
                self._json({"ok": False, "limited": True, "error": str(exc)}, 429)
                return
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)[:400]}, 500)
                return
            # 若被拒是因为 L2 未确认 → 让前端弹窗（带上工具名与参数）
            steps = rep.get("steps") or []
            pend = None
            for st in steps:
                if st.get("denied") and "教师确认" in str(st.get("reason") or ""):
                    pend = {"tool": st.get("tool"), "args": st.get("args") or {},
                            "reason": st.get("reason")}
            if pend:
                rep["pendingConfirm"] = pend
            rep["sessionId"] = client.session_id
            # D140-B4：会话历史落 <ws>/atopia/sessions/（可整体删除）
            try:
                import time as _t
                sd = ws_ / "atopia" / "sessions"
                sd.mkdir(parents=True, exist_ok=True)
                with (sd / f"{client.session_id or 'default'}.jsonl").open(
                        "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": _t.strftime("%Y-%m-%d %H:%M:%S"),
                                        "task": task, "ok": bool(rep.get("ok")),
                                        "answer": str(rep.get("answer") or "")[:1000],
                                        "steps": steps}, ensure_ascii=False) + "\n")
            except OSError as exc:
                logger.warning(f"[atopia] 会话历史写入失败：{exc}")
            self._json(rep)
            return
        if u.path == "/atopia/sessions":
            # D140-B4：列出/回看会话历史
            from .atopia import agent as _ag2  # noqa: F401 —— 保持导入一致
            ws_ = Path(self.ws).resolve()
            sd = ws_ / "atopia" / "sessions"
            q = urllib.parse.parse_qs(u.query)
            sid = str((q.get("id") or [""])[0]).strip()
            if sid:
                f = sd / f"{sid}.jsonl"
                if not f.is_file():
                    self._json({"ok": False, "error": f"会话不存在：{sid}"}, 404)
                    return
                recs = []
                for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        recs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                self._json({"ok": True, "id": sid, "records": recs})
                return
            items = []
            if sd.is_dir():
                for f in sorted(sd.glob("*.jsonl"), key=lambda x: x.stat().st_mtime,
                                reverse=True):
                    try:
                        n = sum(1 for _ in f.open(encoding="utf-8", errors="replace"))
                    except OSError:
                        n = 0
                    items.append({"id": f.stem, "turns": n,
                                  "mtime": time.strftime(
                                      "%Y-%m-%d %H:%M:%S",
                                      time.localtime(f.stat().st_mtime))})
            self._json({"ok": True, "sessions": items[:50]})
            return
        if u.path == "/atopia/limits":
            # D137：教师调整护栏（受 HARD_CAPS 硬顶约束；超限直接拒绝并说明原因）
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .atopia import limits as _alm
            ws_ = Path(self.ws).resolve()
            patch = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
            rep = _alm.write_limits(ws_, patch)
            rep["limits"] = _alm.read_limits(ws_)
            rep["hardCaps"] = _alm.HARD_CAPS
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/llm/migrate":
            from .grading import providers
            ws = Path(self.ws).resolve()
            rep = providers.migrate_legacy(ws)
            rep["config"] = providers.public_config(ws)
            self._json(rep)
            return
        if u.path == "/playground/upload":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    if length > 30 * 1024 * 1024:
                        self._json({"ok": False, "error": "payload too large"}, 413)
                        return
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .playground import extract as pgeo
            ws = Path(self.ws).resolve()
            rep = pgeo.save_upload(ws, str(payload.get("name") or ""),
                                   str(payload.get("data") or ""),
                                   subdir=str(payload.get("group") or ""))
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/playground/record":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .playground import store as pgs
            ws = Path(self.ws).resolve()
            action = str(payload.get("action") or "save")
            if action == "delete":
                rep = pgs.delete_record(ws, str(payload.get("id") or ""))
            elif action == "move":
                rep = pgs.move_records(ws, payload.get("ids") or [], str(payload.get("folder") or ""))
            else:
                rep = pgs.save_record(ws, payload.get("record") or {})
            rep["records"] = pgs.list_records(ws)
            self._json(rep, 200 if rep.get("ok", True) else 400)
            return
        if u.path == "/playground/folder":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .playground import store as pgs
            ws = Path(self.ws).resolve()
            action = str(payload.get("action") or "new")
            if action == "delete":
                rep = pgs.delete_folder(ws, str(payload.get("name") or ""))
            elif action == "rename":
                rep = pgs.rename_folder(ws, str(payload.get("name") or ""),
                                        str(payload.get("new_name") or ""))
            else:
                rep = pgs.add_folder(ws, str(payload.get("name") or ""))
            rep["folders"] = pgs.list_folders(ws)
            self._json(rep, 200 if rep.get("ok", True) else 400)
            return
        if u.path == "/playground/ask":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .playground import ask as pga
            ws = Path(self.ws).resolve()
            rep = pga.ask(ws, question=str(payload.get("question") or ""),
                          provider=str(payload.get("provider") or ""),
                          model=str(payload.get("model") or ""),
                          system=str(payload.get("system") or ""),
                          attachments=payload.get("attachments") or [],
                          temperature=payload.get("temperature"),
                          max_tokens=int(payload.get("max_tokens") or 8192),
                          folder=str(payload.get("folder") or ""),
                          save=bool(payload.get("save", True)))
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/playground/batch":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .playground import ask as pga
            ws = Path(self.ws).resolve()
            if payload.get("items"):
                # D98：每条自带 question+images（各条互不共享）
                rep = pga.batch_items(ws, items=payload.get("items") or [],
                                      provider=str(payload.get("provider") or ""),
                                      model=str(payload.get("model") or ""),
                                      system=str(payload.get("system") or ""),
                                      temperature=payload.get("temperature"),
                                      max_tokens=int(payload.get("max_tokens") or 8192),
                                      folder=str(payload.get("folder") or ""),
                                      workers=int(payload.get("workers") or 3),
                                      save=bool(payload.get("save", True)))
                self._json(rep, 200 if rep.get("ok") else 400)
                return
            rep = pga.batch(ws, questions=payload.get("questions") or [],
                            provider=str(payload.get("provider") or ""),
                            model=str(payload.get("model") or ""),
                            system=str(payload.get("system") or ""),
                            attachments=payload.get("attachments") or [],
                            temperature=payload.get("temperature"),
                            max_tokens=int(payload.get("max_tokens") or 8192),
                            folder=str(payload.get("folder") or ""),
                            workers=int(payload.get("workers") or 3),
                            save=bool(payload.get("save", True)),
                            combine=bool(payload.get("combine", False)))
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/kb/related/apply":
            # D166：写入知识点（追加版本，可追溯）。改前自动快照。
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .grading import rubric as _rb
            kb = str(payload.get("kb") or "").strip()
            chap = str(payload.get("chap") or "").strip()
            qid = str(payload.get("qid") or "").strip()
            terms = payload.get("terms")
            if not (kb and chap and qid):
                self._json({"ok": False, "error": "缺少 kb/chap/qid"}, 400)
                return
            if not isinstance(terms, list):
                self._json({"ok": False, "error": "terms 必须是字符串数组"}, 400)
                return
            rep = _rb.apply_related(Path(self.ws).resolve(), [{
                "kb": kb, "chap": chap, "qid": qid,
                "related": "，".join(str(t).strip() for t in terms if str(t).strip()),
                "meta": {"source": str(payload.get("source") or "human"),
                         "note": str(payload.get("note") or "PWA 写入")}}])
            self._json(rep, 200 if rep.get("ok") else 400)
        if u.path == "/kb/related/tidy":
            # D166：AI 再整理知识点 —— **只产出建议**（diff），不落盘；
            # 教师逐题勾选后再调 /kb/related/tidy/apply 写回。
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .grading import related_tidy as _rt
            from .grading.llm import LLMConfigError, LLMClient
            ids = payload.get("ids")
            ids = [str(i) for i in ids] if isinstance(ids, list) else None
            ws_ = Path(self.ws).resolve()
            try:
                client = LLMClient(ws=ws_)
                rep = _rt.tidy_related(
                    client, ws_,
                    kind=str(payload.get("kb") or ""),
                    chap=str(payload.get("chap") or ""),
                    ids=ids, force=bool(payload.get("force")),
                    model=str(payload.get("model") or "") or None)
            except LLMConfigError as exc:
                self._json({"ok": False, "error": f"LLM 未配置：{exc}"}, 400)
                return
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)[:300]}, 500)
                return
            self._json(rep, 200 if rep.get("ok") else 400)
        if u.path == "/kb/related/tidy/apply":
            # D166：把教师**勾选后**的整理结果写回（追加版本 + 自动快照）
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            items = payload.get("items")
            if not isinstance(items, list) or not items:
                self._json({"ok": False, "error": "缺少 items（教师勾选的条目）"}, 400)
                return
            from .grading import related_tidy as _rt
            rep = _rt.apply_tidy(Path(self.ws).resolve(), items)
            self._json(rep, 200 if rep.get("ok") else 400)
        if u.path == "/kb/ai-solve":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            # 默认 dry-run；apply=true 才真跑并写回 kb/solutions/
            apply = bool(payload.get("apply"))
            ids = payload.get("ids")
            ids = [str(i) for i in ids] if isinstance(ids, list) else []
            chap_ = str(payload.get("chap") or "").strip()
            # D110：没有任何范围的请求不再默默升级为"整库作答"。
            if not ids and not chap_ and payload.get("all") is not True:
                self._json({"ok": False,
                            "error": "未指定范围（章节/题号）。请选择章节或题号；"
                                     "整库作答需显式 all=true"}, 400)
                return
            args = ["kb", "ai-solve", "--kb-kind", str(payload.get("kb") or "problems")]
            if chap_:
                args += ["--chap", chap_]
            if ids:
                args += ["--ids", ",".join(ids)]
            elif payload.get("all") is True:
                args += ["--all"]
            if payload.get("model"):
                args += ["--model", str(payload.get("model"))]
            # D104：教师额外作答要求（如"画示意图""输出 HTML"）→ CLI --requirement
            if str(payload.get("requirement") or "").strip():
                args += ["--requirement", str(payload.get("requirement"))]
            # D108：提示词模板（优先于 requirement）
            if str(payload.get("requirementTemplate") or "").strip():
                args += ["--requirement-template", str(payload.get("requirementTemplate"))]
            # D133：可选同时生成评阅要点（带题型规则摘要）
            if payload.get("withRubric") is True:
                args += ["--with-rubric"]
                if payload.get("pinRubric") is True:
                    args += ["--pin-rubric"]
            # D152：同时把知识点写回题库（CLI 侧 --tag-knowledge）
            if payload.get("tagKnowledge") is True:
                args += ["--tag-knowledge"]
            # D100-T3：AI 作答默认置顶（生效答案）；显式 pin=false 才保持"不抢原答案"。
            if payload.get("pin", True) is False:
                args += ["--no-pin"]
            if apply:
                args += ["--apply"]
            home = _xxt_home(); env = _xxt_env(home); cwd = str(_ws())
            # D106：图片压缩模式与 SVG 重绘开关（PWA 设置 → 环境变量）
            if str(payload.get("imageMode") or "") == "original":
                env["ASSIST_IMAGE_MODE"] = "original"
            if payload.get("svgRedraw") is True:
                env["ASSIST_SVG_REDRAW"] = "1"
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False, "error": "engine 无法 import assist.cli", "detail": detail}, 500)
                return
            job_id = secrets.token_urlsafe(6)
            self._start_stream_job(job_id, _xxt_cli_cmd(args), env, "kb_ai_solve", "kb-ai-solve", cwd,
                                   journal_kind="kb_ai_solve",
                                   journal_params={"kb": payload.get("kb") or "problems",
                                                   "chap": payload.get("chap") or "",
                                                   "apply": apply})
            self._json({"ok": True, "job_id": job_id})
            return
        if u.path == "/prompts/ai-solve":
            # D108：save / delete / set_default
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .files import prompts as P
            ws_ = Path(self.ws).resolve()
            action = str(payload.get("action") or "save")
            if action == "delete":
                rep = P.delete_template(ws_, str(payload.get("id") or ""))
            elif action == "set_default":
                rep = P.set_default(ws_, str(payload.get("id") or ""))
            else:
                rep = P.save_template(ws_, pid=str(payload.get("id") or ""),
                                      name=str(payload.get("name") or ""),
                                      text=str(payload.get("text") or ""),
                                      make_default=bool(payload.get("default")))
            rep["items"] = P.list_templates(ws_)
            rep["default"] = (P.default_template(ws_) or {}).get("id", "")
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/kb/solution":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .files import solutions as sol
            ws = Path(self.ws).resolve()
            action = str(payload.get("action") or "add")
            qid = str(payload.get("qid") or "")
            kb = str(payload.get("kb") or "")
            chap = str(payload.get("chap") or "")
            if action == "pin":
                rep = sol.pin_version(ws, qid, str(payload.get("version") or ""),
                                      kb=kb, chap=chap)
            elif action == "rm":
                rep = sol.remove_version(ws, qid, str(payload.get("version") or ""),
                                         kb=kb, chap=chap)
            else:
                rep = sol.add_version(ws, qid, str(payload.get("text") or ""),
                                      source=str(payload.get("source") or "ai"),
                                      model=str(payload.get("model") or ""),
                                      kb=kb, chap=chap,
                                      pin=bool(payload.get("pin")))
            if rep.get("ok") and qid:
                rep["solutions"] = sol.read_solutions(ws, qid, kb=kb, chap=chap)
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/pack":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from . import packs
            ws = Path(self.ws).resolve()
            action = str(payload.get("action") or "save")
            if action == "delete":
                rep = packs.delete_pack(ws, str(payload.get("id") or ""))
            elif action == "rename":
                rep = packs.rename_pack(ws, str(payload.get("id") or ""),
                                        str(payload.get("new_id") or ""))
            else:
                rep = packs.save_pack(ws, str(payload.get("id") or ""), payload.get("pack") or {})
            rep["packs"] = packs.list_packs(ws)
            self._json(rep, 200 if rep.get("ok", True) else 400)
            return
        if u.path == "/watermark/style":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .paper import watermark_styles as wsx
            ws = Path(self.ws).resolve()
            ad, _src = _wm_serve_assets(ws, payload.get("assets_dir"))
            action = str(payload.get("action") or "save")
            if action == "delete":
                rep = wsx.delete_style(ad, str(payload.get("name") or ""))
            elif action == "rename":
                rep = wsx.rename_style(ad, str(payload.get("name") or ""),
                                       str(payload.get("new_name") or ""))
            elif action == "set_default":
                rep = wsx.set_default(ad, str(payload.get("name") or ""))
            else:
                rep = wsx.save_style(ad, str(payload.get("name") or ""),
                                     payload.get("style") or {},
                                     make_default=bool(payload.get("default")))
            rep["assets_dir"] = str(ad)
            rep["styles"] = wsx.list_styles(ad)
            self._json(rep, 200 if rep.get("ok", True) else 400)
            return
        if u.path == "/watermark/upload":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    if length > 30 * 1024 * 1024:
                        self._json({"ok": False, "error": "payload too large"}, 413)
                        return
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            ws = Path(self.ws).resolve()
            ad, _src = _wm_serve_assets(ws, payload.get("assets_dir"))
            rep = _save_watermark_upload(ad, payload)
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/xxt/grade/ai-run":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            cid = str(payload.get("courseId") or "")
            kid = str(payload.get("classId") or "")
            cpi = str(payload.get("cpi") or "0")
            work = str(payload.get("workId") or "")
            pad = payload.get("taskpad")
            pads = payload.get("pads")  # D89：作业包内多张作业纸（按 tag 匹配不同学生）
            if isinstance(pads, list) and pads:
                pad = pads[0] if not isinstance(pad, dict) else pad
            if not (cid and kid and work and isinstance(pad, dict)):
                self._json({"ok": False, "error": "courseId/classId/workId/taskpad(s) 必填"}, 400)
                return
            from .xxt.work import validate_work_target
            err = validate_work_target(cid, kid, Path(self.ws).resolve())
            if err:
                self._json({"ok": False, "error": err}, 400)
                return
            # 作业包落 workspace 临时目录（PWA 的 pad 存在 localStorage，需显式传入）
            # D127-FIX：批阅**作用域键**必须前后端一致。
            #   作业包模式 → packId（该包内所有 tag 的作业纸共用同一批阅目录）
            #   单张作业纸 → 作业纸 id
            # 此前引擎固定用 pad.id、前端读用 packId → 写了草稿但逐生审核读不到。
            pack_id = str(payload.get("packId") or "").strip()
            task_id = pack_id or (str(pad.get("id") or "").strip() or "ai-grade-task")
            pad_dir = Path(self.ws).resolve() / "tmp" / "ai-grade"
            pad_dir.mkdir(parents=True, exist_ok=True)
            pad_path = pad_dir / f"{task_id}.taskpad.json"
            pad_path.write_text(json.dumps(pad, ensure_ascii=False, indent=1), encoding="utf-8")
            args = ["grade", "--task", str(pad_path), "--xxt-class", f"{cid}:{kid}",
                    "--work", work, "--scope-id", task_id]
            # D89：作业包多作业纸 → 落同一临时目录，--pads-dir 让 build_plan 按 tag 全量匹配
            if isinstance(pads, list) and len(pads) > 1:
                pool = pad_dir / f"{task_id}-pads"
                pool.mkdir(parents=True, exist_ok=True)
                for p_ in pads:
                    if not isinstance(p_, dict):
                        continue
                    pid = str(p_.get("id") or "pad").strip() or "pad"
                    (pool / f"{pid}.taskpad.json").write_text(
                        json.dumps(p_, ensure_ascii=False, indent=1), encoding="utf-8")
                args += ["--pads-dir", str(pool)]
            if payload.get("mode"):
                args += ["--mode", str(payload.get("mode"))]
            if payload.get("tags"):
                tags = payload.get("tags")
                args += ["--tags", ",".join(tags) if isinstance(tags, list) else str(tags)]
            if payload.get("limit"):
                args += ["--limit", str(int(payload.get("limit")))]
            # D148：逐生补批（只处理指定学生，避免整批重跑）
            stu_ = payload.get("students")
            if isinstance(stu_, list) and stu_:
                args += ["--students", ",".join(str(x) for x in stu_)]
            elif isinstance(stu_, str) and stu_.strip():
                args += ["--students", stu_]
            # D157：强制重跑（逐生补批必须能覆盖已有结果）
            if payload.get("force") is True:
                args += ["--force-rerun"]
            # D125：分步批阅（仅转录 / 仅评阅 / 转录+评阅）与"允许部分失败"
            steps_ = payload.get("steps")
            if isinstance(steps_, list) and steps_:
                args += ["--steps", ",".join(str(x) for x in steps_)]
            if payload.get("allowPartial") is True:
                args += ["--allow-partial"]
            # D118：启动前先装配 plan 做**前置体检**——没有任何学生作答图时直接给可读错误，
            # 而不是等引擎跑到转录步才抛 FileNotFoundError（Windows 上表现为 WinError 3）。
            pads_dir_arg = ""
            if "--pads-dir" in args:
                pads_dir_arg = args[args.index("--pads-dir") + 1]
            pre = self._grade_preflight(cid, kid, work, task_id, pad_path, pads_dir_arg)
            if pre is not None:
                self._json(pre[0], pre[1])
                return
            home = _xxt_home(); env = _xxt_env(home); cwd = str(_ws())
            # D106：图片压缩模式与 SVG 重绘开关（PWA 设置 → 环境变量）
            if str(payload.get("imageMode") or "") == "original":
                env["ASSIST_IMAGE_MODE"] = "original"
            if payload.get("svgRedraw") is True:
                env["ASSIST_SVG_REDRAW"] = "1"
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False, "error": "engine 无法 import assist.cli", "detail": detail}, 500)
                return
            job_id = secrets.token_urlsafe(6)
            self._start_stream_job(job_id, _xxt_cli_cmd(args), env, "xxt_grade_ai", "xxt-grade-ai", cwd,
                                   journal_kind="xxt_grade_ai",
                                   journal_params={"courseId": cid, "classId": kid, "workId": work,
                                                   "mode": payload.get("mode") or "optimized",
                                                   "taskpad": task_id})
            self._json({"ok": True, "job_id": job_id, "taskpadPath": str(pad_path)})
            return
        if u.path == "/xxt/grade/render-drafts":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            cid = str(payload.get("courseId") or "")
            kid = str(payload.get("classId") or "")
            work = str(payload.get("workId") or "")
            task_id = str(payload.get("taskId") or "")
            kind = str(payload.get("kind") or "human")
            if not (cid and kid and work and task_id):
                self._json({"ok": False, "error": "courseId/classId/workId/taskId 必填"}, 400)
                return
            from .xxt.work import validate_work_target
            err = validate_work_target(cid, kid, Path(self.ws).resolve())
            if err:
                self._json({"ok": False, "error": err}, 400)
                return
            pad_path = Path(self.ws).resolve() / "tmp" / "ai-grade" / f"{task_id}.taskpad.json"
            if not pad_path.is_file():
                self._json({"ok": False, "error": f"未找到作业包：{pad_path}（先跑一次 AI 批阅）"}, 400)
                return
            args = ["grade-drafts", "--task", str(pad_path), "--class", kid, "--work", work,
                    "--kind", kind]
            home = _xxt_home(); env = _xxt_env(home); cwd = str(_ws())
            # D106：图片压缩模式与 SVG 重绘开关（PWA 设置 → 环境变量）
            if str(payload.get("imageMode") or "") == "original":
                env["ASSIST_IMAGE_MODE"] = "original"
            if payload.get("svgRedraw") is True:
                env["ASSIST_SVG_REDRAW"] = "1"
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False, "error": "engine 无法 import assist.cli", "detail": detail}, 500)
                return
            job_id = secrets.token_urlsafe(6)
            self._start_stream_job(job_id, _xxt_cli_cmd(args), env, "xxt_grade_render", "xxt-grade-render",
                                   cwd, journal_kind="xxt_grade_render",
                                   journal_params={"courseId": cid, "classId": kid, "workId": work,
                                                   "taskId": task_id, "kind": kind})
            self._json({"ok": True, "job_id": job_id})
            return
        if u.path == "/atopia/run":
            # D132：执行一个工具。**L2 必须带 confirm**（教师在前端点了确认），
            # L3 一律拒绝（由 runner 保证）；每次调用写 journal。
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .atopia import limits as _al2
            from .atopia import runner as _arn2
            from .atopia.registry import ToolDenied as _TD
            ws_ = Path(self.ws).resolve()
            tool = str(payload.get("tool") or "")
            args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
            confirm = str(payload.get("confirm") or "")
            sess = _al2.Session(session_id=str(payload.get("session") or "pwa"),
                                limits=_al2.read_limits(ws_))
            try:
                rep = _arn2.run_tool(ws_, tool, args, session=sess,
                                     confirmed_by=confirm)
            except _TD as exc:
                self._json({"ok": False, "error": str(exc), "denied": True}, 403)
                return
            except _al2.LimitExceeded as exc:
                self._json({"ok": False, "error": str(exc), "limited": True}, 429)
                return
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/rules/save":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .grading import rules as _rules
            rules = payload.get("rules")
            if not isinstance(rules, dict):
                self._json({"ok": False, "error": "rules 必须是对象"}, 400)
                return
            rep = _rules.write_rules(Path(self.ws).resolve(), rules)
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/rules/reset":
            from .grading import rules as _rules
            rep = _rules.reset_rules(Path(self.ws).resolve())
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/xxt/grade/draft":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .xxt import grade_store
            key = str(payload.get("key") or payload.get("workAnswerId")
                      or payload.get("name") or "")
            cid_, wid_ = str(payload.get("classId") or ""), str(payload.get("workId") or "")
            # D119：草稿按 (ws, class_dir, taskId) 归属 → 不同作业批次互不覆盖
            scope = {"ws": Path(self.ws).resolve(),
                     "class_dir": str(payload.get("classDir") or ""),
                     "task_id": str(payload.get("taskId") or "")}
            # D92：支持双套结构（ai/human/human_mode/revision）；旧字段（score/comment/images）走兼容
            if any(k in payload for k in ("ai", "human", "human_mode", "revision")):
                rep = grade_store.save_draft_sets(
                    _xxt_home(), cid_, wid_, key,
                    ai=payload.get("ai"), human=payload.get("human"),
                    human_mode=payload.get("human_mode"),
                    revision=payload.get("revision"),
                    student=str(payload.get("student") or ""), tag=str(payload.get("tag") or ""),
                    **scope)
            else:
                rep = grade_store.save_draft(
                    _xxt_home(), cid_, wid_, key,
                    score=payload.get("score"), comment=str(payload.get("comment") or ""),
                    comment_text=str(payload.get("commentText") or ""),
                    images=payload.get("images"), **scope)
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/xxt/grade/render-from-drafts":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .grading.drafts import render_reports_from_drafts
            ws = Path(self.ws).resolve()
            rep = render_reports_from_drafts(
                ws, class_id=str(payload.get("classId") or ""),
                work_id=str(payload.get("workId") or ""),
                task_id=str(payload.get("taskId") or ""),
                class_dir=str(payload.get("classDir") or ""),
                with_report_png=bool(payload.get("withReportPng", True)))
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/xxt/grade/delete-draft":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .xxt import grade_store
            rep = grade_store.delete_draft(_xxt_home(), str(payload.get("classId") or ""),
                                           str(payload.get("workId") or ""),
                                           str(payload.get("key") or ""))
            self._json(rep, 200 if rep.get("ok") else 400)
            return
        if u.path == "/xxt/grade/upload":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            cid = str(payload.get("courseId") or "")
            kid = str(payload.get("classId") or "")
            cpi = str(payload.get("cpi") or "0")
            work = str(payload.get("workId") or "")
            student = str(payload.get("student") or "")
            send = bool(payload.get("send"))
            force = bool(payload.get("force"))
            if not (cid and kid and work):
                self._json({"ok": False, "error": "courseId/classId/workId 必填"}, 400)
                return
            from .xxt.work import validate_work_target
            err = validate_work_target(cid, kid, Path(self.ws).resolve())
            if err:
                self._json({"ok": False, "error": err}, 400)
                return
            args = ["xxt", "grade-upload", "--course", cid, "--class", kid, "--cpi", cpi,
                    "--work", work, "--from-drafts"]
            if student:
                args += ["--student", student]
            if send:
                args += ["--confirm-send"]
            if force:
                args += ["--force"]
            home = _xxt_home(); env = _xxt_env(home); cwd = str(_ws())
            # D106：图片压缩模式与 SVG 重绘开关（PWA 设置 → 环境变量）
            if str(payload.get("imageMode") or "") == "original":
                env["ASSIST_IMAGE_MODE"] = "original"
            if payload.get("svgRedraw") is True:
                env["ASSIST_SVG_REDRAW"] = "1"
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False, "error": "engine 无法 import assist.cli", "detail": detail}, 500)
                return
            job_id = secrets.token_urlsafe(6)
            self._start_stream_job(job_id, _xxt_cli_cmd(args), env, "xxt_grade_upload", "xxt-grade", cwd,
                                   journal_kind="xxt_grade_upload",
                                   journal_params={"courseId": cid, "classId": kid,
                                                   "workId": work, "send": send, "student": student})
            self._json({"ok": True, "job_id": job_id})
            return
        if u.path == "/xxt/work/publish":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            ids = {k: str(payload.get(k) or "").strip() for k in ("courseId", "classId", "workLibraryId", "cpi")}
            # D95：多班（classIds 优先；单 classId 兼容）
            class_ids = [str(x).strip() for x in (payload.get("classIds") or []) if str(x).strip()]
            if not class_ids and ids["classId"]:
                class_ids = [ids["classId"]]
            if not (ids["courseId"] and class_ids and ids["workLibraryId"] and ids["cpi"]):
                self._json({"ok": False, "error": "courseId/classIds/workLibraryId/cpi 必填"}, 400)
                return
            from .xxt.work import validate_work_target
            errs = [e for e in (validate_work_target(ids["courseId"], c, Path(self.ws).resolve())
                                for c in class_ids) if e]
            if errs:
                self._json({"ok": False, "error": "；".join(errs)}, 400)
                return
            args = ["xxt", "work-publish", "--course", ids["courseId"]]
            for c in class_ids:
                args += ["--class", c]
            args += ["--work-library-id", ids["workLibraryId"], "--cpi", ids["cpi"]]
            if payload.get("startTime"):
                args += ["--start", str(payload["startTime"])[:30]]
            if payload.get("endTime"):
                args += ["--end", str(payload["endTime"])[:30]]
            if payload.get("allowLate"):
                args += ["--allow-late"]
            if payload.get("lateDeadline"):
                args += ["--late-deadline", str(payload["lateDeadline"])[:30]]
            if payload.get("redoTimes"):
                args += ["--redo-times", str(int(payload["redoTimes"]))]
            if payload.get("send"):
                args += ["--send"]
            home = _xxt_home()
            env = _xxt_env(home)
            cwd = str(_ws())
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False, "error": "engine 无法 import assist.cli", "detail": detail}, 500)
                return
            job_id = secrets.token_urlsafe(6)
            self._start_stream_job(job_id, _xxt_cli_cmd(args), env, "xxt_work_publish", "xxt-work", cwd,
                                   journal_kind="xxt_work_publish",
                                   journal_params={**ids, "classIds": class_ids})
            self._json({"ok": True, "job_id": job_id, "mode": "send" if payload.get("send") else "dry-run"})
            return
        if u.path == "/workspace/bootstrap":
            from .xxt.workspace_ops import create_default_kb
            self._json(create_default_kb(Path(self.ws).resolve()))
            return
        if u.path == "/kb/migrate":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .xxt.workspace_ops import migrate_kb
            self._json(migrate_kb(Path(self.ws).resolve(), str(payload.get("srcDir") or "")))
            return
        if u.path == "/xxt/notice/attachment-whitelist":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .xxt.allowlist import write_notice_attachment_exts
            items = write_notice_attachment_exts(Path(self.ws).resolve(), payload.get("items") or [])
            self._json({"ok": True, "items": items})
            return
        if u.path == "/xxt/notice/upload":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    if length > 30 * 1024 * 1024:
                        self._json({"ok": False, "error": "payload too large"}, 413)
                        return
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .xxt.allowlist import read_notice_attachment_exts
            from .xxt.notice import save_notice_uploads
            ws = Path(self.ws).resolve()
            items = save_notice_uploads(ws, payload.get("items") or [],
                                        allowed_exts=read_notice_attachment_exts(ws))
            self._json({"ok": True, "items": items})
            return
        if u.path == "/xxt/notice/send":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    if length > 5 * 1024 * 1024:
                        self._json({"ok": False, "error": "payload too large"}, 413)
                        return
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .xxt.notice import normalize_targets, validate_targets
            targets = normalize_targets(payload.get("targets"))
            err = validate_targets(targets)
            if err:
                self._json({"ok": False, "error": err}, 400)
                return
            spec = {
                "targets": targets,
                "title": str(payload.get("title") or "")[:128],
                "bodyHtml": str(payload.get("bodyHtml") or payload.get("body") or ""),
                "attachments": [str(x) for x in (payload.get("attachments") or [])[:20]],
            }
            home = _xxt_home()
            env = _xxt_env(home)
            cwd = str(_ws())
            ok, detail = _xxt_preflight(cwd, env)
            if not ok:
                self._json({"ok": False, "error": "engine 无法 import assist.cli",
                            "detail": detail}, 500)
                return
            spec_path = xxt_layout.notice_spec_json(home)
            try:
                spec_path.parent.mkdir(parents=True, exist_ok=True)
                spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"write notice spec failed: {exc}"}, 500)
                return
            args = ["xxt", "notice-send", "--spec", str(spec_path)]
            if bool(payload.get("send")):
                args.append("--send")
            job_id = secrets.token_urlsafe(6)
            self._start_stream_job(job_id, _xxt_cli_cmd(args), env, "xxt_notice_send",
                                   "xxt-notice", cwd, journal_kind="xxt_notice_send",
                                   journal_params={"mode": "send" if bool(payload.get("send")) else "dry-run",
                                                   "courses": len(targets),
                                                   "classes": sum(len(c.get("classes") or []) for c in targets)})
            self._json({"ok": True, "job_id": job_id, "mode": "send" if bool(payload.get("send")) else "dry-run"})
            return
        if u.path == "/xxt/run/import":
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    if length > 20 * 1024 * 1024:
                        self._json({"ok": False, "error": "payload too large"}, 413)
                        return
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) or {}
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad json: {exc}"}, 400)
                return
            from .xxt import legacy
            home = _xxt_home()
            try:
                if isinstance(payload.get("data"), dict):
                    summary = legacy.import_run_data(
                        payload["data"], fallback_id=payload.get("filename"), home=home)
                elif payload.get("path"):
                    summary = legacy.import_run_file(payload["path"], home=home)
                else:
                    self._json({"ok": False, "error": "需要 data 对象或 path"}, 400)
                    return
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)[:200]}, 400)
                return
            try:
                from .xxt import journal as _journal
                _journal.log_event("xxt_run_import", home=home, source="pwa",
                                   params={"filename": str(payload.get("filename") or ""),
                                           "run_id": summary.get("run_id"),
                                           "classes": summary.get("classes"),
                                           "works": summary.get("works")})
            except Exception:  # noqa: BLE001
                pass
            self._json({"ok": True, "imported": summary})
            return
        if (m_rwp := re.fullmatch(r"/xxt/review/work/([0-9A-Za-z\-_]{1,40})/([0-9A-Za-z\-_]{1,40})/purge", u.path)):
            from .xxt import review as _review
            res = _review.purge_review_work(_xxt_home(), m_rwp.group(1), m_rwp.group(2))
            try:
                from .xxt import journal as _journal
                _journal.log_event("xxt_review_purge", home=_xxt_home(), source="pwa",
                                   params={"classId": m_rwp.group(1), "workId": m_rwp.group(2)},
                                   result="ok" if res.get("ok") else "fail",
                                   error=str(res.get("error") or ""))
            except Exception:  # noqa: BLE001
                pass
            self._json(res if res.get("ok") else {**res, "ok": False}, 200 if res.get("ok") else 404)
            return
        if (m_rwd := re.fullmatch(r"/xxt/review/work/([0-9A-Za-z\-_]{1,40})/([0-9A-Za-z\-_]{1,40})/delete", u.path)):
            from .xxt import review as _review
            res = _review.delete_work_images(_xxt_home(), m_rwd.group(1), m_rwd.group(2))
            try:
                from .xxt import journal as _journal
                _journal.log_event("xxt_review_delete_images", home=_xxt_home(), source="pwa",
                                   params={"classId": m_rwd.group(1), "workId": m_rwd.group(2),
                                           "answer": res.get("deleted_answer"),
                                           "comment": res.get("deleted_comment")},
                                   result="ok" if res.get("ok") else "fail",
                                   error=str(res.get("error") or ""))
            except Exception:  # noqa: BLE001
                pass
            self._json(res if res.get("ok") else {**res, "ok": False}, 200 if res.get("ok") else 404)
            return
        if u.path == "/xxt/review/prune":
            from .xxt import review as _review
            res = _review.prune_review(_xxt_home(), months=6)
            try:
                from .xxt import journal as _journal
                _journal.log_event("xxt_review_prune", home=_xxt_home(), source="pwa",
                                   params={"removed": res.get("removed_count"), "months": 6})
            except Exception:  # noqa: BLE001
                pass
            self._json({"ok": True, **res})
            return
        if u.path == "/xxt/runs/prune":
            res = xxt_layout.prune_runs(_xxt_home())
            try:
                from .xxt import journal as _journal
                _journal.log_event("xxt_runs_prune", home=_xxt_home(), source="pwa",
                                   params={"removed": res.get("removed_count")})
            except Exception:  # noqa: BLE001
                pass
            self._json({"ok": True, **res})
            return
        if u.path == "/xxt/targets/history/clear":
            from .xxt.targets import clear_history
            removed = clear_history(_xxt_home())
            try:
                from .xxt import journal as _journal
                _journal.log_event("targets_history_clear", home=_xxt_home(), source="pwa",
                                   params={"removed": len(removed)})
            except Exception:  # noqa: BLE001
                pass
            self._json({"ok": True, "removed": removed})
            return
        if u.path == "/journal/clear":
            from .xxt import journal as _journal
            removed = _journal.clear(_xxt_home())
            self._json({"ok": True, "removed": removed})
            return
        if u.path == "/xxt/runs/clear":
            res = xxt_layout.clear_runs(_xxt_home())
            try:
                from .xxt import journal as _journal
                _journal.log_event("xxt_runs_clear", home=_xxt_home(), source="pwa",
                                   params={"runs": len(res.get("runs") or []),
                                           "removed": len(res.get("removed") or [])})
            except Exception:  # noqa: BLE001
                pass
            self._json({"ok": True, **res})
            return
        if (m_del := re.fullmatch(r"/xxt/run/([A-Za-z0-9\-]+)/delete", u.path)):
            run_id = m_del.group(1)
            if not re.fullmatch(r"xxt-[0-9A-Za-z\-]+", run_id):
                self._json({"ok": False, "error": "bad run"}, 404)
                return
            removed = xxt_layout.delete_run_artifacts(run_id, _xxt_home())
            if not removed:
                self._json({"ok": False, "error": "no such run"}, 404)
                return
            try:
                from .xxt import journal as _journal
                _journal.log_event("xxt_run_delete", home=_xxt_home(), source="pwa",
                                   params={"run_id": run_id, "removed": len(removed)})
            except Exception:  # noqa: BLE001
                pass
            self._json({"ok": True, "run_id": run_id, "removed": removed})
            return
        if u.path == "/restart":
            # D64 §22.1 + D67：引擎自愈式重启（安装了新代码/改了 env 后 PWA 一键生效）。
            # 安全哨兵：非 lan 模式只接受回环来源；lan 模式已过 token 校验（do_POST 顶部）。
            peer = self.client_address[0]
            if not Handler.token and peer not in ("127.0.0.1", "::1"):
                self._json({"ok": False, "error": "loopback only"}, 403)
                return
            if not _RESTART_ARGS:
                self._json({"ok": False, "error": "restart args unknown (进程非 assist serve 启动？)"}, 409)
                return
            supervised = os.environ.get("ASSIST_SUPERVISED") == "1"
            mode = restart_plan(os.name, supervised)
            if mode == "manual":
                self._json({
                    "ok": False,
                    "error": "engine is not supervised by start.bat",
                    "hint": "Windows 下请关闭当前引擎终端，再双击 start.bat；不要依赖 execv 原地重启",
                }, 409)
                return
            try:
                from .xxt import journal as _journal
                _journal.log_event("engine_restart", home=_xxt_home(), source="pwa",
                                   params={"mode": mode})
            except Exception:  # noqa: BLE001
                pass
            self._json({"ok": True, "restarting": True, "mode": mode})
            try:
                self.wfile.flush()  # 确保 PWA 先收到受理响应；随后进程会退出
            except Exception:
                pass
            import time as _t2, threading as _th
            def _reborn():
                _t2.sleep(0.5)  # 让响应字节先落到 socket
                if mode == "exit75":
                    # start.bat 的 :ENGINE_LOOP 收到 75 后自动同端口重启，不进入 pause。
                    os._exit(75)
                os.execv(sys.executable,
                         [sys.executable, "-c",
                          "from assist.cli import main; main()", *_RESTART_ARGS])
            _th.Thread(target=_reborn, daemon=True).start()
            return
        m = re.fullmatch(r"/install/([a-z_]+)", u.path)
        if not m:
            self._json({"ok": False, "error": "not found"}, 404)
            return
        item = m.group(1)
        if item not in INSTALL_ITEMS:
            self._json({"ok": False, "error": f"unknown install item {item}"}, 404)
            return
        job_id = secrets.token_urlsafe(6)
        self._start_job(job_id, item)
        self._json({"ok": True, "job_id": job_id})

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        _np, _legacy = _rewrite_legacy_atopia(u.path)
        if _legacy:
            # D134：旧名 `/assistopia/*` 永久转发到 `/atopia/*`
            u = u._replace(path=_np)
            self.path = urllib.parse.urlunparse(u)
        raw_qs = urllib.parse.parse_qs(u.query)
        if not self._ok_token(raw_qs):
            self._json({"ok": False, "error": "token required"}, 401)
            return
        if u.path.startswith("/xxt/"):
            xxt_err = _xxt_import_error()
            if xxt_err:
                if u.path == "/xxt/status":
                    self._json({"ok": True, "xxt": {
                        "verdict": "unknown",
                        "reasons": [f"学习通模块不可用：{xxt_err}"],
                        "hint": "引擎安装不完整：关闭引擎窗口后删除 workspace/_engine，再双击 start.bat 重装；见 docs/24 §14",
                    }, "avatar": {"ok": False}})
                else:
                    self._json({"ok": False,
                                "error": "学习通模块不可用（引擎安装不完整）",
                                "detail": xxt_err,
                                "hint": "关闭引擎窗口 → 删除 workspace/_engine → 重新双击 start.bat；见 docs/24 §14"}, 503)
                return
        if u.path == "/xxt/status":
            self._json({"ok": True, "xxt": _xxt_session_check_cached(),
                        "avatar": _xxt_avatar_cached()})
            return
        elif u.path == "/xxt/qr":
            qr = _xxt_home() / "xxt-qr.png"
            if not qr.exists():
                body = json.dumps({"ok": False, "error": "no qr yet"},
                                  ensure_ascii=False).encode("utf-8")
                self.send_response(404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = qr.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        elif u.path == "/xxt/review/probe/latest":
            from .xxt import review as _review
            data = _review.latest_probe(_xxt_home())
            if data is None:
                self._json({"ok": False, "error": "no probe yet",
                            "hint": "先点击「🧪 只读探针」"}, 404)
                return
            self._json({"ok": True, **data})
            return
        elif (m_rw := re.fullmatch(r"/xxt/review/work/([0-9A-Za-z\-_]{1,40})/([0-9A-Za-z\-_]{1,40})", u.path)):
            from .xxt import review as _review
            data = _review.read_manifest(_xxt_home(), m_rw.group(1), m_rw.group(2))
            if data is None:
                self._json({"ok": False, "error": "no manifest"}, 404)
                return
            self._json({"ok": True, **data})
            return
        elif u.path == "/xxt/review/index":
            from .xxt import review as _review
            works = _review.list_review_works(_xxt_home())
            # D121-G2：顺手做「学习通班级 → 本地班级目录」的自动绑定。
            # 提取/下载流程过去完全不碰 classmap，导致教师从未建立映射 →
            # 批阅时 class_dir 解析不到 → 拼出 <ws>/classes/grading 假目录。
            # 这里只对「唯一精确命中」自动写入；其余收集成待确认列表返回给 PWA。
            auto_bound, need_confirm = self._auto_bind_classes(works)
            self._json({"ok": True, "works": works,
                        "stats": _review.review_stats(_xxt_home()),
                        "autoBound": auto_bound, "needConfirm": need_confirm})
            return
        elif (m_rev := re.fullmatch(r"/xxt/review/file/([0-9A-Za-z\-_]{1,40})/([0-9A-Za-z\-_]{1,40})/([^/]{1,160})", u.path)):
            from .xxt import review as _review
            fname = urllib.parse.unquote(m_rev.group(3))
            fpath = _review.safe_image_path(_xxt_home(), m_rev.group(1), m_rev.group(2), fname)
            if fpath is None:
                self._json({"ok": False, "error": "no such image"}, 404)
                return
            ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                     "gif": "image/gif", "webp": "image/webp"}.get(
                fpath.suffix.lstrip(".").lower(), "application/octet-stream")
            body = fpath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        elif u.path == "/xxt/write-allowlist":
            from .xxt.allowlist import read_allowlist
            self._json({"ok": True, "items": read_allowlist(Path(self.ws).resolve())})
            return
        elif u.path == "/xxt/work/class-works":
            from .xxt.work import list_class_works
            q = urllib.parse.parse_qs(u.query)
            cid = (q.get("courseId") or [""])[0]
            kid = (q.get("classId") or [""])[0]
            cpi = (q.get("cpi") or ["0"])[0]
            if not cid or not kid:
                self._json({"ok": False, "error": "courseId/classId 必填"}, 400)
                return
            self._json(list_class_works(_xxt_home() / "xxt-storage.json", cid, kid, cpi))
            return
        elif u.path == "/xxt/work/folders":
            from .xxt.work import list_folders
            q = urllib.parse.parse_qs(u.query)
            cid = (q.get("courseId") or [""])[0]
            kid = (q.get("classId") or [""])[0]
            cpi = (q.get("cpi") or ["0"])[0]
            if not cid or not kid:
                self._json({"ok": False, "error": "courseId/classId 必填"}, 400)
                return
            self._json(list_folders(_xxt_home() / "xxt-storage.json", cid, kid, cpi))
            return
        elif u.path == "/xxt/work/detail":
            from .xxt.work import work_detail
            q = urllib.parse.parse_qs(u.query)
            cid = (q.get("courseId") or [""])[0]
            kid = (q.get("classId") or [""])[0]
            cpi = (q.get("cpi") or ["0"])[0]
            wid = (q.get("workLibraryId") or [""])[0]
            if not all((cid, kid, wid)):
                self._json({"ok": False, "error": "参数不全"}, 400)
                return
            self._json(work_detail(_xxt_home() / "xxt-storage.json", cid, kid, cpi, wid))
            return
        elif u.path == "/xxt/class-map":
            # D86 §1：映射 + 本地候选
            from .xxt import classmap
            ws = Path(self.ws).resolve()
            self._json({"ok": True, "map": classmap.read_class_map(ws),
                        "candidates": classmap.list_class_candidates(ws)})
        elif u.path == "/llm/config":
            # D86 §2：provider（掩码）+ 两段式
            from .grading import providers
            self._json({"ok": True, **providers.public_config(Path(self.ws).resolve())})
        elif u.path == "/playground/records":
            from .playground import store as pgs
            ws = Path(self.ws).resolve()
            self._json({"ok": True, "records": pgs.list_records(ws), "folders": pgs.list_folders(ws)})
        elif u.path == "/playground/folders":
            from .playground import store as pgs
            self._json({"ok": True, "folders": pgs.list_folders(Path(self.ws).resolve())})
        elif u.path.startswith("/playground/record/"):
            from .playground import store as pgs
            rid = urllib.parse.unquote(u.path[len("/playground/record/"):])
            d = pgs.read_record(Path(self.ws).resolve(), rid)
            self._json(d or {"ok": False, "error": f"记录不存在：{rid}"}, 200 if d else 404)
        elif (u.path.startswith("/kb/related/") and not u.path.startswith("/kb/related/apply")
              and not u.path.startswith("/kb/related/tidy")):
            # D166：知识点完整视图（供 PWA 预览弹窗：版本/来源/词表命中）
            from .grading import rubric as _rb
            qid = urllib.parse.unquote(u.path[len("/kb/related/"):])
            q = urllib.parse.parse_qs(u.query)
            kb = (q.get("kb") or [""])[0]
            chap = (q.get("chap") or [""])[0]
            fb = (q.get("fallback") or [""])[0]
            self._json(_rb.get_related(Path(self.ws).resolve(), kb=kb, chap=chap,
                                       qid=qid, fallback=fb))
        elif u.path.startswith("/kb/solutions/"):
            from .files import solutions as sol
            qid = urllib.parse.unquote(u.path[len("/kb/solutions/"):])
            q = urllib.parse.parse_qs(u.query)
            kb = (q.get("kb") or [""])[0]
            chap = (q.get("chap") or [""])[0]
            d = sol.read_solutions(Path(self.ws).resolve(), qid, kb=kb, chap=chap)
            self._json(d or {"ok": False, "error": f"无版本库：{qid}"}, 200 if d else 404)
        elif u.path == "/kb/solutions":
            # D100-T2：批量生效答案索引 {qid: {text, source, version, from, ...}}，
            # 供 PWA 一次性取全库（题库表格摘要 + 作业纸预览题帧），语义 = effective_solution。
            from .files import solutions as sol
            ws_ = Path(self.ws).resolve()
            q = urllib.parse.parse_qs(u.query)
            if q.get("raw", ["0"])[0] == "1":
                self._json({"ok": True, "items": sol.list_solutions(ws_)})
            else:
                # D110：effective（按 qid，兼容旧前端）+ effectiveByKey（按 kb__chap__qid，精确）
                self._json({"ok": True, "effective": sol.effective_map(ws_),
                            "effectiveByKey": sol.effective_by_key(ws_),
                            "digest": sol.solutions_digest(ws_)})
        elif u.path == "/prompts/templates":
            # GET /prompts/templates?category=evaluate
            from .files import prompts as _pp
            q = urllib.parse.parse_qs(u.query)
            cat = str((q.get("category") or ["ai-solve"])[0])
            ws_ = Path(self.ws).resolve()
            if cat not in _pp.CATEGORIES:
                self._json({"ok": False, "error": f"未知类别：{cat}"}, 400)
                return
            self._json({"ok": True, "category": cat,
                        "categories": list(_pp.CATEGORIES),
                        "items": _pp.list_templates(ws_, cat),
                        "default": (_pp.default_template(ws_, cat) or {}).get("id", "")})
            return
        elif u.path == "/prompts/ai-solve":
            # D108：提示词模板库（PWA 下拉/默认/删除）
            from .files import prompts as P
            ws_ = Path(self.ws).resolve()
            self._json({"ok": True, "items": P.list_templates(ws_),
                        "default": (P.default_template(ws_) or {}).get("id", "")})
        elif u.path == "/roster/tags-snapshot":
            # D168：快照列表（无 packId）/ 单包明细 + 与当前 roster 的差异（有 packId）
            from .grading import snapshots as _sn
            q = urllib.parse.parse_qs(u.query)
            class_dir = str((q.get("classDir") or [""])[0])
            pack_id = str((q.get("packId") or [""])[0]).strip()
            ws_ = Path(self.ws).resolve()
            try:
                if not pack_id:
                    self._json({"ok": True, "items": _sn.list_tags_snapshots(ws_, class_dir)})
                    return
                snap = _sn.read_tags_snapshot(ws_, class_dir, pack_id)
                if not snap.get("ok"):
                    self._json(snap, 404)
                    return
                self._json({**snap,
                            "diff": _sn.diff_against_roster(ws_, class_dir, pack_id),
                            "tagCounts": _sn.tag_counts(ws_, class_dir, pack_id)})
            except _sn.SnapshotError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
            return
        elif u.path == "/analysis/errors":
            # D168：知识点加权失误率（tag 加权 + 跨班两层 + 跨包按总题数）
            from .grading import error_stats as _es
            from .grading import snapshots as _sn
            from .grading import teacher_report as _tr
            from .grading import vocab as _vb
            q = urllib.parse.parse_qs(u.query)
            classes = [x for x in str((q.get("classes") or [""])[0]).split(",") if x.strip()]
            packs = [x for x in str((q.get("packs") or [""])[0]).split(",") if x.strip()]
            tags = [x for x in str((q.get("tags") or [""])[0]).split(",") if x.strip()]
            only_known = str((q.get("onlyKnown") or ["1"])[0]) != "0"
            ws_ = Path(self.ws).resolve()
            if not classes or not packs:
                self._json({"ok": False, "error": "需要 classes 与 packs 参数"}, 400)
                return
            records, sources = _tr.collect_multi(ws_, classes, packs, tags or None)
            if not records:
                self._json({"ok": False, "error": "没有找到评阅结果",
                            "sources": sources}, 404)
                return
            # 每个包各自的提交人数（来自 D168 快照；缺失则用记录数兜底）
            submitted_by_tag: dict[str, int] = {}
            per_pack = []
            for cd in classes:
                for pid in packs:
                    try:
                        st = _sn.submit_stats(ws_, cd, pid)
                    except Exception:  # noqa: BLE001
                        st = {"ok": False}
                    if st.get("ok"):
                        for tag, v in (st.get("byTag") or {}).items():
                            submitted_by_tag[tag] = (submitted_by_tag.get(tag, 0)
                                                     + int(v.get("submitted") or 0))
                    got = [r for r in records
                           if str(r.get("_sourcePack")) == f"{cd}/{pid}"]
                    stats_p = _es.collect_errors(got)
                    per_pack.append({
                        "packId": pid, "classDir": cd,
                        "byTerm": {k: v["count"] for k, v in stats_p["byTerm"].items()},
                        "totalQuestions": stats_p["totals"]["questions"],
                        "submitted": len(got),
                    })
            if not submitted_by_tag:
                # 无快照：用"有评阅记录的人数"兜底，并在响应里明确标出
                for r in records:
                    t = str(r.get("tag") or "").strip()
                    submitted_by_tag[t] = submitted_by_tag.get(t, 0) + 1
            vocab = _vb.load_vocab(ws_)
            rep = _es.build_report(records, submitted_by_tag=submitted_by_tag,
                                   vocab=vocab, only_known=only_known)
            rep["crossPack"] = _es.cross_pack_rate(per_pack)
            rep["perPack"] = per_pack
            rep["sources"] = sources
            rep["tagSource"] = next(
                (str(r.get("_tagSource")) for r in records if r.get("_tagSource")), "none")
            rep["submittedByTag"] = submitted_by_tag
            self._json(rep)
            return
        elif u.path == "/analysis/chart":
            # D168-B3：知识点分析出图（PNG）。引擎算数 + 出图，前端只 <img> 显示。
            from .grading import teacher_report as _tr
            from .grading import viz as _vz
            from .grading import error_stats as _es
            from .grading import snapshots as _sn
            from .grading import vocab as _vb
            q = urllib.parse.parse_qs(u.query)
            classes = [x for x in str((q.get("classes") or [""])[0]).split(",") if x.strip()]
            packs = [x for x in str((q.get("packs") or [""])[0]).split(",") if x.strip()]
            tags = [x for x in str((q.get("tags") or [""])[0]).split(",") if x.strip()]
            kind = str((q.get("kind") or ["bar"])[0])
            n = int((q.get("n") or ["2"])[0] or 2)
            ws_ = Path(self.ws).resolve()
            ready = _vz.available()
            if not ready["ok"]:
                self._json({"ok": False, "needViz": True,
                            "error": ready.get("hint") or "可视化依赖未安装"}, 501)
                return
            if not classes or not packs:
                self._json({"ok": False, "error": "需要 classes 与 packs 参数"}, 400)
                return
            records, sources = _tr.collect_multi(ws_, classes, packs, tags or None)
            if not records:
                self._json({"ok": False, "error": "没有找到评阅结果"}, 404)
                return
            vocab = _vb.load_vocab(ws_)
            out_dir = ws_ / "reports" / "charts"
            stamp = time.strftime("%Y%m%d-%H%M%S")
            try:
                if kind == "bar":
                    sub_by_tag: dict[str, int] = {}
                    for cd in classes:
                        for pid in packs:
                            try:
                                st = _sn.submit_stats(ws_, cd, pid)
                            except Exception:  # noqa: BLE001
                                st = {"ok": False}
                            if st.get("ok"):
                                for tag, v in (st.get("byTag") or {}).items():
                                    sub_by_tag[tag] = (sub_by_tag.get(tag, 0)
                                                       + int(v.get("submitted") or 0))
                    if not sub_by_tag:
                        for r in records:
                            t = str(r.get("tag") or "").strip()
                            sub_by_tag[t] = sub_by_tag.get(t, 0) + 1
                    rep = _es.build_report(records, submitted_by_tag=sub_by_tag,
                                           vocab=vocab, only_known=True)
                    path = _vz.bar_error_rates(
                        rep.get("items") or [],
                        out_dir / f"error-rate-{stamp}.png",
                        title="知识点加权失误率（次/人）")
                else:
                    sub_by_tag = {}
                    try:
                        rep0 = None
                        for cd in classes:
                            for pid in packs:
                                st = _sn.submit_stats(ws_, cd, pid)
                                if st.get("ok"):
                                    for tag, v in (st.get("byTag") or {}).items():
                                        sub_by_tag[tag] = (sub_by_tag.get(tag, 0)
                                                           + int(v.get("submitted") or 0))
                        if not sub_by_tag:
                            for r in records:
                                t = str(r.get("tag") or "").strip()
                                sub_by_tag[t] = sub_by_tag.get(t, 0) + 1
                        rep0 = _es.build_report(records, submitted_by_tag=sub_by_tag,
                                                vocab=vocab, only_known=True)
                    except Exception:  # noqa: BLE001
                        rep0 = {"items": []}
                    rates = {i["term"]: float(i.get("rate") or 0)
                             for i in (rep0.get("items") or [])}
                    path = _vz.cooccurrence_network(
                        records, out_dir / f"cooccurrence-{stamp}.png", n=n,
                        vocab=vocab, rates=rates,
                        title=f"知识点共现网络（{n} 元）")
            except _vz.VizUnavailable as exc:
                self._json({"ok": False, "needViz": True, "error": str(exc)}, 501)
                return
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"出图失败：{str(exc)[:200]}"}, 500)
                return
            rel = str(path.relative_to(ws_)).replace("\\", "/")
            self._json({"ok": True, "kind": kind, "file": rel, "path": str(path),
                        "bytes": path.stat().st_size, "sources": sources,
                        "url": f"/analysis/chart/file?name={urllib.parse.quote(path.name)}"})
            return
        elif u.path == "/analysis/chart/file":
            # D168-B3：读取已生成的图（直接给 <img src>）
            q = urllib.parse.parse_qs(u.query)
            name = Path(str((q.get("name") or [""])[0])).name
            f = Path(self.ws).resolve() / "reports" / "charts" / name
            if not name or not f.is_file():
                self._json({"ok": False, "error": "图表不存在"}, 404)
                return
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        elif u.path == "/atopia/tool-groups":
            # D168-B6：工具分组概览（前端"按场景"选择器用）
            from .atopia import registry as _rg
            rep = _rg.group_summary(Path(self.ws).resolve())
            self._json({"ok": True, **rep})
            return
        elif u.path == "/analysis/standard-cooccurrence":
            # D168-B5：**标准共现图**（数据源 = 例题库，反映授课结构）
            # 与 /analysis/cooccurrence（作答共现图）并列，两者语义不同：
            #   标准图 = 老师怎么教；作答图 = 学生怎么错。
            from .grading import cooccurrence as _co
            from .grading import kb_examples as _ke
            from .grading import vocab as _vb
            q = urllib.parse.parse_qs(u.query)
            n = int((q.get("n") or ["2"])[0] or 2)
            ws_ = Path(self.ws).resolve()
            sumry = _ke.summary(ws_)
            if not sumry.get("ready"):
                self._json({"ok": False, "needExamples": True,
                            "error": ("例题库为空或太少（需要 ≥2 条带知识点的例题）。"
                                      "请先在 Atopia 用「example-extract」任务解析教材/课件，"
                                      "再点「导入例题库」。"),
                            "summary": sumry}, 404)
                return
            records = _ke.examples_as_records(ws_)
            vocab = _vb.load_vocab(ws_)
            self._json({"ok": True, "n": n, "summary": sumry,
                        "graphs": _co.by_tag(records, n=n, vocab=vocab),
                        "clusters": _co.natural_clusters(records, n=n, vocab=vocab)})
            return
        elif u.path == "/kb/examples":
            # D168-B5：例题库概览（数据源就绪与否）
            from .grading import kb_examples as _ke
            self._json(_ke.summary(Path(self.ws).resolve()))
            return
        elif u.path == "/analysis/cooccurrence":
            # D168：共现（可按 tag 拆开）+ 自然聚类
            from .grading import cooccurrence as _co
            from .grading import teacher_report as _tr
            from .grading import vocab as _vb
            q = urllib.parse.parse_qs(u.query)
            classes = [x for x in str((q.get("classes") or [""])[0]).split(",") if x.strip()]
            packs = [x for x in str((q.get("packs") or [""])[0]).split(",") if x.strip()]
            tags = [x for x in str((q.get("tags") or [""])[0]).split(",") if x.strip()]
            n = int((q.get("n") or ["2"])[0] or 2)
            ws_ = Path(self.ws).resolve()
            if not classes or not packs:
                self._json({"ok": False, "error": "需要 classes 与 packs 参数"}, 400)
                return
            records, sources = _tr.collect_multi(ws_, classes, packs, tags or None)
            vocab = _vb.load_vocab(ws_)
            self._json({"ok": True, "n": n,
                        "graphs": _co.by_tag(records, n=n, vocab=vocab),
                        "clusters": _co.natural_clusters(records, n=n, vocab=vocab),
                        "sources": sources})
            return
        elif u.path == "/grade/submissions":
            # D168：作答名单 + 提交率（分母 = roster-tags 快照）
            from .grading import snapshots as _sn
            q = urllib.parse.parse_qs(u.query)
            ws_ = Path(self.ws).resolve()
            class_dir = str((q.get("classDir") or [""])[0])
            pack_id = str((q.get("packId") or [""])[0]).strip()
            try:
                sub = _sn.read_submissions(ws_, class_dir, pack_id)
                stats = _sn.submit_stats(ws_, class_dir, pack_id)
                self._json({"ok": True, "submissions": sub, "stats": stats})
            except _sn.SnapshotError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
            return
        elif u.path == "/roster/read":
            from .files import roster_io
            q = urllib.parse.parse_qs(u.query)
            rep = roster_io.read_roster_file(Path(self.ws).resolve(),
                                             (q.get("classDir") or [""])[0])
            self._json(rep, 200 if rep.get("ok") else 404)
        elif u.path == "/taskpads":
            from .files import taskpads
            self._json({"ok": True, "items": taskpads.list_taskpads(Path(self.ws).resolve())})
        elif u.path.startswith("/workspace/backup/file"):
            from . import backup as B
            q = urllib.parse.parse_qs(u.query)
            ws_ = Path(self.ws).resolve()
            name = (q.get("name") or [""])[0]
            safe = Path(name).name
            p = (ws_ / "backups" / safe).resolve()
            if not str(p).startswith(str(ws_ / "backups")) or not p.is_file():
                self._json({"ok": False, "error": "备份文件不存在"}, 404)
                return
            self._raw(p.read_bytes(), "application/zip")
        elif u.path == "/workspace/layout":
            from . import workspace_layout as WL
            from . import workspace_junk as WJ
            ws_ = Path(self.ws).resolve()
            from . import class_dir_audit as _cda
            self._json({**WL.inspect(ws_), "junk": WJ.find_junk(ws_),
                        "classDirAudit": _cda.audit(ws_)})
        elif u.path == "/kb/catalog":
            from .files.kb_io import catalog as _catalog
            q = urllib.parse.parse_qs(u.query)
            with_content = (q.get("content", ["1"])[0] != "0")
            self._json({"ok": True, **_catalog(Path(self.ws).resolve() / "kb",
                                               with_content=with_content)})
        elif u.path == "/packs":
            from . import packs
            self._json({"ok": True, "packs": packs.list_packs(Path(self.ws).resolve())})
        elif u.path.startswith("/pack/"):
            from . import packs
            pid = urllib.parse.unquote(u.path[len("/pack/"):])
            d = packs.read_pack(Path(self.ws).resolve(), pid)
            self._json(d or {"ok": False, "error": f"作业包不存在：{pid}"},
                       200 if d else 404)
        elif u.path == "/watermark/styles":
            # D87 §4：命名样式列表（含 default 标记）+ 素材文件清单
            from .paper.watermark_styles import list_styles
            q = urllib.parse.parse_qs(u.query)
            explicit = (q.get("assets_dir") or [None])[0]
            ad, src = _wm_serve_assets(Path(self.ws).resolve(), explicit)
            wm_dir = ad / "watermark"
            files = sorted(p.name for p in wm_dir.glob("*") if p.is_file()) if wm_dir.is_dir() else []
            self._json({"ok": True, "assets_dir": str(ad), "source": src,
                        "styles": list_styles(ad), "files": files})
        elif u.path.startswith("/xxt/grade/drafts/"):
            # D119：读本地批阅草稿（新布局 grading/<taskId>/drafts/ 优先，旧 grade-drafts/ 回落）
            m = re.fullmatch(r"/xxt/grade/drafts/([0-9A-Za-z\-_]{1,40})/([0-9A-Za-z\-_]{1,40})", u.path)
            if not m:
                self._json({"ok": False, "error": "bad path"}, 400)
                return
            from .xxt import grade_store
            qd = urllib.parse.parse_qs(u.query)
            # D126-FIX：统一归一为双套结构，前端按 ai.transcript / ai.comment 取值
            # D127-FIX：支持 altTaskId 兼容回落（历史上目录键在 padId / packId 间漂移过）
            # D130-FIX2：允许逗号分隔的多个兼容键（前端一次带多个反查结果）
            _alt = [x.strip() for a in (qd.get("altTaskId") or [])
                    for x in str(a).split(",") if x.strip()]
            _task_id = (qd.get("taskId") or [""])[0]
            _cdir = (qd.get("classDir") or [""])[0]
            # D130-FIX2：前端没传 taskId（刷新后 packId/padId 为空）时，
            # 由引擎**从磁盘反查**该作业的批阅目录，避免"表里全空、弹窗有内容"。
            _discovered: list[str] = []
            if not str(_task_id).strip() and _cdir:
                _discovered = grade_store.discover_draft_scopes(
                    Path(self.ws).resolve(), _cdir, m.group(2))
                if _discovered:
                    _task_id = _discovered[0]
                    _alt = _alt + _discovered[1:]
            drafts = grade_store.read_drafts_normalized(
                _xxt_home(), m.group(1), m.group(2),
                ws=Path(self.ws).resolve(),
                class_dir=_cdir,
                task_id=_task_id,
                alt_task_ids=_alt)
            self._json({"ok": True, "classId": m.group(1), "workId": m.group(2),
                        "count": len(drafts), "drafts": drafts,
                        "resolvedTaskId": _task_id,
                        "draftScopes": _discovered})
        elif u.path == "/xxt/work/list":
            from .xxt.work import list_works
            q = urllib.parse.parse_qs(u.query)
            course = (q.get("courseId") or [""])[0]
            clazz = (q.get("classId") or [""])[0]
            cpi = (q.get("cpi") or ["0"])[0]
            directory = (q.get("directoryId") or ["0"])[0]
            class_ids = [x for x in (q.get("classIds") or [""])[0].split(",") if x.strip()]
            if not course or not clazz:
                self._json({"ok": False, "error": "courseId/classId 必填"}, 400)
                return
            self._json(list_works(_xxt_home() / "xxt-storage.json", course, clazz, cpi, directory,
                                  class_ids=class_ids or None))
            return
        elif u.path == "/xxt/notice/attachment-whitelist":
            from .xxt.allowlist import read_notice_attachment_exts
            self._json({"ok": True, "items": read_notice_attachment_exts(Path(self.ws).resolve())})
            return
        elif u.path == "/xxt/notice/attachments":
            from .xxt.notice import list_notice_attachments
            q = urllib.parse.parse_qs(u.query)
            limit = int((q.get("limit") or ["200"])[0] or 200)
            self._json({"ok": True, "items": list_notice_attachments(Path(self.ws).resolve(), limit=max(1, min(limit, 500)))})
            return
        elif u.path == "/xxt/preview/archives":
            from .xxt import preview as _preview
            self._json({"ok": True, "items": _preview.list_review_archives(_xxt_home())})
            return
        elif (m_prev := re.fullmatch(
                r"/xxt/preview/students/([0-9A-Za-z\-_]{1,40})/([0-9A-Za-z\-_]{1,40})", u.path)):
            from .xxt import preview as _preview
            q = urllib.parse.parse_qs(u.query)
            run_id = (q.get("run_id") or [None])[0]
            rep = _preview.preview_students(
                _xxt_home(), m_prev.group(1), m_prev.group(2), run_id=run_id)
            # D126：把「作答原件文件名」合并进学生清单（逐生审核要显示原图）。
            # preview_students 只解析列表页 HTML，没有图片名；这里用已下载的
            # students.json 补齐（read_review_students 返回绝对路径，转成文件名）。
            try:
                from .grading import inputs as _gi
                _d, rev = _gi.read_review_students(m_prev.group(1), m_prev.group(2))
                by_name = {str(x.get("name") or ""): x for x in rev}
                for stu in rep.get("students") or []:
                    hit = by_name.get(str(stu.get("name") or ""))
                    if hit:
                        stu["images"] = [Path(p_).name for p_ in (hit.get("images") or [])]
                        if hit.get("workAnswerId"):
                            stu.setdefault("workAnswerId", hit["workAnswerId"])
            except Exception:  # noqa: BLE001 —— 补齐失败不影响列表
                logger.debug("补充作答图文件名失败", exc_info=True)
            # D130-FIX2：**补 tag**。学习通列表页只有姓名/分数，没有分层 tag；
            # tag 是本校名单里的概念（roster），必须由引擎按姓名 join 回去，
            # 否则前端「tag」列永远空白（此前 preview_students 根本不返回 tag 字段）。
            try:
                from .grading import inputs as _gi2
                _q_tag = urllib.parse.parse_qs(u.query)
                _cdir_tag = (_q_tag.get("classDir") or [""])[0]
                if _cdir_tag:
                    _tags = {str(x.get("name")): str(x.get("tag") or "")
                             for x in _gi2.students_with_tags(
                                 Path(self.ws).resolve(), _cdir_tag)}
                    for stu in rep.get("students") or []:
                        stu["tag"] = _tags.get(str(stu.get("name") or ""), "")
            except Exception:  # noqa: BLE001 —— 无名单/读取失败时留空即可
                logger.debug("补充 tag 失败", exc_info=True)
            # D130-FIX2：**服务端自己找批阅目录**（刷新后前端 packId/padId 为空）。
            # 否则 taskId='' → 读不到草稿 → 「AI 状态」全空，而弹窗又有内容。
            try:
                from .xxt import grade_store as _gs2
                _q3 = urllib.parse.parse_qs(u.query)
                rep["draftScopes"] = _gs2.discover_draft_scopes(
                    Path(self.ws).resolve(),
                    (_q3.get("classDir") or [""])[0], m_prev.group(2))
            except Exception:  # noqa: BLE001
                rep["draftScopes"] = []
                logger.debug("反查批阅目录失败", exc_info=True)
            # D130-T12：**服务端**给出统一的草稿键 `key`（前端不得再自行拼接）。
            # 草稿历史上可能按 workAnswerId 写、也可能按姓名写（批阅清单未解析到 id 时），
            # 前端若固定用 "workAnswerId || name" 取，就会"表里显示未跑、点开却有内容"。
            try:
                from .xxt import grade_store as _gs
                from .xxt import layout as _xxt_layout2
                _q2 = urllib.parse.parse_qs(u.query)
                # 用与前端同口径的参数定位草稿：taskId / altTaskId / classDir
                _task_id = (_q2.get("taskId") or [""])[0]
                _alt = [x.strip() for a in (_q2.get("altTaskId") or [])
                        for x in str(a).split(",") if x.strip()]
                _cdir = (_q2.get("classDir") or [""])[0]
                _drafts: dict = {}
                if _task_id:
                    _drafts = _gs.read_drafts_normalized(
                        _xxt_home(), m_prev.group(1), m_prev.group(2),
                        ws=Path(self.ws).resolve(), class_dir=_cdir,
                        task_id=_task_id, alt_task_ids=_alt)
                for stu in rep.get("students") or []:
                    stu["key"] = _gs.resolve_draft_key(stu, _drafts)
            except Exception:  # noqa: BLE001 —— 键解析失败不阻断列表
                logger.debug("解析草稿键失败", exc_info=True)
                for stu in rep.get("students") or []:
                    stu.setdefault("key", str(stu.get("workAnswerId")
                                              or stu.get("name") or ""))
            self._json(rep)
            return
        elif u.path == "/atopia/tools":
            # D132：工具白名单 + 分级（含扩展覆盖后的生效级别）
            from .atopia import limits as _al
            from .atopia import registry as _ar
            ws_ = Path(self.ws).resolve()
            self._json({"ok": True,
                        "levels": _ar.LEVEL_LABEL,
                        "limits": _al.read_limits(ws_),
                        "hardCaps": _al.HARD_CAPS,
                        "extensions": str(_ar.extensions_dir(ws_)),
                        "tools": [t.to_dict() for t in _ar.effective_tools(ws_)]})
            return
        elif u.path == "/atopia/journal":
            from .atopia import runner as _arn
            q = urllib.parse.parse_qs(u.query)
            limit = int((q.get("limit") or ["100"])[0] or 100)
            self._json({"ok": True, "records": _arn.read_journal(
                Path(self.ws).resolve(), limit=max(1, min(limit, 500)))})
            return
        elif u.path == "/materials/suggest-preview":
            # D137：待确认的 AI 建议**全文预览**（确认弹窗必须让教师看清将生效什么）
            from .files import materials as _mp
            q = urllib.parse.parse_qs(u.query)
            chap = str((q.get("chap") or [""])[0]).strip()
            if not chap:
                self._json({"ok": False, "error": "缺少 chap"}, 400)
                return
            ws_ = Path(self.ws).resolve()
            try:
                d = _mp.chap_dir(ws_, chap)
            except _mp.MaterialsError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            ai = d / _mp.KNOW_AI
            md = d / _mp.KNOW_MD
            out: dict = {"ok": True, "chap": chap,
                         "hasAiSuggest": ai.is_file(),
                         "hasConfirmed": md.is_file()}
            if ai.is_file():
                try:
                    data = json.loads(ai.read_text(encoding="utf-8"))
                    out["data"] = data
                    out["preview"] = _mp.render_knowledge_md(data)
                    out["terms"] = [str(k.get("term")) for k in (data.get("knowledge") or [])
                                    if isinstance(k, dict) and k.get("term")]
                except Exception as exc:  # noqa: BLE001
                    out["ok"] = False
                    out["error"] = f"AI 建议文件损坏：{exc}"
            self._json(out)
            return
        elif u.path == "/atopia/work":
            # D164：Atopia 工作区（特征名列表 / 文件清单 / 解析产物预览）
            from .atopia import work as _aw
            q = urllib.parse.parse_qs(u.query)
            ws_ = Path(self.ws).resolve()
            feat = str((q.get("feature") or [""])[0]).strip()
            if not feat:
                self._json({"ok": True, "features": _aw.list_features(ws_),
                            "root": str(_aw.work_root(ws_))})
                return
            parsed = str((q.get("parsed") or [""])[0]).strip()
            try:
                if parsed:
                    data = _aw.read_parsed(ws_, feat, parsed)
                    self._json({"ok": True, "feature": feat, "parsed": data,
                                "file": parsed})
                    return
                self._json({"ok": True, "feature": feat,
                            "files": _aw.files_of(ws_, feat),
                            "text": _aw.read_upload_text(ws_, feat)})
            except _aw.WorkError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
            return
        elif u.path == "/workspace/classes":
            # D153：列出 workspace 下的班级目录（供报告多选）
            ws_ = Path(self.ws).resolve()
            root = ws_ / "classes"
            out = []
            if root.is_dir():
                for d in sorted(p for p in root.iterdir() if p.is_dir()):
                    if d.name.startswith("."):
                        continue
                    grading = d / "grading"
                    packs = []
                    if grading.is_dir():
                        packs = sorted(x.name for x in grading.iterdir()
                                       if x.is_dir() and not x.name.startswith("_")
                                       and (x / "evaluations").is_dir())
                    out.append({"classDir": f"classes/{d.name}", "name": d.name,
                                "packs": packs})
            self._json({"ok": True, "classes": out})
            return
        elif u.path == "/roster/grading-packs":
            # D149：列出该班级有评阅结果的作业包（每次作业 = 一列成绩）
            from .roster import grading_scores as _gs
            q = urllib.parse.parse_qs(u.query)
            class_dir = str((q.get("classDir") or [""])[0]).strip().strip("/")
            try:
                packs = _gs.list_grading_packs(Path(self.ws).resolve(), class_dir)
            except _gs.GradingScoreError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            self._json({"ok": True, "classDir": class_dir, "packs": packs})
            return
        elif u.path == "/roster/grading-scores":
            # D149：某作业包的批阅成绩（未批阅/未提交记 0 分）
            from .roster import grading_scores as _gs
            q = urllib.parse.parse_qs(u.query)
            class_dir = str((q.get("classDir") or [""])[0]).strip().strip("/")
            pack_id = str((q.get("packId") or [""])[0]).strip()
            names = [x for x in str((q.get("students") or [""])[0]).split(",") if x.strip()]
            try:
                rep = _gs.grading_scores(Path(self.ws).resolve(), class_dir, pack_id,
                                         students=names or None)
            except _gs.GradingScoreError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            rep["classDir"] = class_dir
            self._json(rep)
            return
        elif u.path == "/materials/files":
            # D134-T3b：某章 _source/ 原件清单（只读）
            from .files import materials as _mfl
            q = urllib.parse.parse_qs(u.query)
            chap = str((q.get("chap") or [""])[0]).strip()
            if not chap:
                self._json({"ok": False, "error": "缺少 chap"}, 400)
                return
            try:
                rows = _mfl.files_of(Path(self.ws).resolve(), chap,
                                     include_trash=bool(q.get("trash")))
            except _mfl.MaterialsError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            self._json({"ok": True, "chap": chap, "count": len(rows), "files": rows})
            return
        elif u.path == "/materials/list":
            # D131-T21d：课堂资料章节清单（PWA 只读展示；抽取/确认仍走 CLI 以保教师把关）
            from .files import materials as _mat
            ws_ = Path(self.ws).resolve()
            chaps = []
            for c in _mat.list_chaps(ws_):
                d = _mat.chap_dir(ws_, c)
                idx = _mat.read_index(ws_, c)
                chaps.append({
                    "chap": c,
                    "sources": len(_mat.list_sources(ws_, c)),
                    "extracted": len(idx.get("sources") or []),
                    "chars": (idx.get("summary") or {}).get("chars", 0),
                    "hasAiSuggest": (d / _mat.KNOW_AI).is_file(),
                    "hasConfirmed": (d / _mat.KNOW_MD).is_file(),
                })
            self._json({"ok": True, "root": str(_mat.materials_root(ws_)),
                        "chaps": chaps})
            return
        elif u.path == "/materials/knowledge":
            # D131-T21d：某章节生效知识点清单（summary 批阅依据）
            from .files import materials as _mat
            q = urllib.parse.parse_qs(u.query)
            chap = str((q.get("chap") or [""])[0])
            try:
                ws_k = Path(self.ws).resolve()
                md = _mat.read_knowledge_md(ws_k, chap)
                terms = _mat.knowledge_terms(ws_k, chap)
                # D138：两层分类（章 → 主题 → 术语）供 PWA 分组展示
                topics = _mat.knowledge_topics(ws_k, chap)
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)[:200]}, 400)
                return
            self._json({"ok": bool(md), "chap": chap, "terms": terms,
                        "topics": topics, "markdown": md})
            return
        elif u.path == "/rules":
            # D130-T9：评阅规则卡读取（默认值 + 当前值 + 校验范围 + 可读摘要）
            from .grading import rules as _rules
            ws_ = Path(self.ws).resolve()
            cur = _rules.read_rules(ws_)
            summaries = {k: _rules.rule_summary(ws_, k) for k in _rules.SUPPORTED_KINDS}
            self._json({"ok": True, "rules": cur, "defaults": _rules.DEFAULT_RULES,
                        "kinds": list(_rules.SUPPORTED_KINDS),
                        "summaries": summaries,
                        "numericRanges": {k: list(v) for k, v in _rules._NUM_RANGES.items()},
                        "file": str(_rules.rules_path(ws_))})
            return
        elif u.path == "/grade/teacher-report-multi":
            # D153：多选（班级 × 作业包 × tag）的教师报告，供「题库AI+」使用
            # 路径：/grade/teacher-report-multi?classDirs=a,b&packIds=p1,p2&tags=x,y
            from .grading import teacher_report as _trm
            q = urllib.parse.parse_qs(u.query)
            cds = [x for x in str((q.get("classDirs") or [""])[0]).split(",") if x.strip()]
            pids = [x for x in str((q.get("packIds") or [""])[0]).split(",") if x.strip()]
            tgs = [x for x in str((q.get("tags") or [""])[0]).split(",") if x.strip()]
            if not cds or not pids:
                self._json({"ok": False, "error": "classDirs 与 packIds 必填"}, 400)
                return
            ws_ = Path(self.ws).resolve()
            try:
                recs, srcs = _trm.collect_multi(ws_, cds, pids, tags=tgs or None)
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)[:300]}, 500)
                return
            if not recs:
                self._json({"ok": False, "error": "所选范围内没有评阅结果",
                            "hint": "换一个作业包或班级试试", "sources": srcs}, 404)
                return
            try:
                topics = _trm.load_topic_map(ws_)
                stat = _trm.analyze(recs, topics=topics)
                md = _trm.render_md(stat, title="／".join(srcs[:3])
                                    + ("…" if len(srcs) > 3 else ""))
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"生成失败：{str(exc)[:200]}"}, 500)
                return
            self._json({"ok": True, "stat": stat, "markdown": md,
                        "sources": srcs, "records": len(recs),
                        "classDirs": cds, "packIds": pids, "tags": tgs})
            return
        elif u.path == "/grade/trend":
            # D135：跨多次作业的知识点趋势（只给教师）
            # 路径：/grade/trend?classDir=classes/化工25[&rebuild=1][&minRecur=2]
            from .grading import trend as _td
            q = urllib.parse.parse_qs(u.query)
            class_dir = str((q.get("classDir") or [""])[0]).strip().strip("/")
            if not class_dir:
                self._json({"ok": False, "error": "classDir 必填"}, 400)
                return
            ws_ = Path(self.ws).resolve()
            try:
                (ws_ / class_dir).resolve().relative_to((ws_ / "classes").resolve())
            except Exception:  # noqa: BLE001
                self._json({"ok": False, "error": "路径越界"}, 400)
                return
            try:
                min_recur = max(1, int((q.get("minRecur") or ["2"])[0] or 2))
            except ValueError:
                min_recur = 2
            out = ws_ / class_dir / "grading" / "_trend"
            try:
                rep = _td.generate(ws_, class_dir, out, min_recur=min_recur,
                                   title=f"知识点趋势 · {class_dir}")
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)[:300]}, 500)
                return
            self._json({"ok": True, "stat": rep["stat"], "markdown": rep["markdown"],
                        "written": rep["written"]})
            return
        elif u.path == "/grade/teacher-report":
            # D126-B：教师总结报告（统计 JSON + Markdown 正文，供 PWA 画共现矩阵/得分率）
            # 路径：/grade/teacher-report?classDir=classes/化工25&taskId=pack1&rebuild=1
            from .grading import teacher_report as _tr
            q = urllib.parse.parse_qs(u.query)
            class_dir = str((q.get("classDir") or [""])[0]).strip().strip("/")
            task_id = str((q.get("taskId") or [""])[0]).strip()
            rebuild = str((q.get("rebuild") or [""])[0]) in ("1", "true", "yes")
            # D135：导出格式（png/pdf）；空 = 不导图（默认，保持既有行为）
            export_format = str((q.get("export") or [""])[0]).strip().lower()
            if not (class_dir and task_id):
                self._json({"ok": False, "error": "classDir/taskId 必填"}, 400)
                return
            ws_ = Path(self.ws).resolve()
            safe_task = re.sub(r"[\\/:*?\"<>|]", "_", task_id).strip(" .") or "task"
            base = ws_ / class_dir / "grading" / safe_task
            try:
                base.resolve().relative_to((ws_ / "classes").resolve())
            except Exception:  # noqa: BLE001
                self._json({"ok": False, "error": "路径越界"}, 400)
                return
            ev = base / "evaluations"
            stats_p = base / "reports" / "_teacher_report.stats.json"
            md_p = base / "reports" / "_teacher_report.md"
            png_p = base / "reports" / "_teacher_report.png"
            pdf_p = base / "reports" / "_teacher_report.pdf"
            # 导图请求：即使统计已存在也要**重新导出**（格式可能是本次才要的）
            need_build = (rebuild or not stats_p.is_file()
                          or (export_format in ("png", "pdf") and not png_p.is_file())
                          or (export_format == "pdf" and not pdf_p.is_file()))
            if need_build:
                if not any(ev.glob("[!_]*.json")):
                    self._json({"ok": False, "error": "没有评阅结果",
                                "hint": "先跑批阅（转写+评阅）再生成教师报告",
                                "dir": str(ev)}, 404)
                    return
                try:
                    # D138：按主题分组（从各章生效清单取映射；读不到则退回扁平）
                    _topics = _tr.load_topic_map(ws_)
                    built = _tr.generate(
                        ev, base / "reports", title=task_id, subtitle=class_dir,
                        render_png=export_format in ("png", "pdf"),
                        render_pdf=(export_format == "pdf"), topics=_topics)
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": f"生成失败：{str(exc)[:200]}"}, 500)
                    return
                if export_format in ("png", "pdf") and not built.get("png"):
                    self._json({"ok": False,
                                "error": "PNG 导出失败（浏览器不可用）",
                                "hint": "报告本身已生成，可先用 Markdown；"
                                        "装好 Chromium 后重试", "mdFile": str(md_p)}, 500)
                    return
            try:
                stat = json.loads(stats_p.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"读取统计失败：{str(exc)[:160]}"}, 500)
                return
            md = md_p.read_text(encoding="utf-8", errors="replace") if md_p.is_file() else ""
            self._json({"ok": True, "stat": stat, "markdown": md,
                        "statsFile": str(stats_p), "mdFile": str(md_p),
                        "png": str(png_p) if png_p.is_file() else "",
                        "pdf": str(pdf_p) if pdf_p.is_file() else ""})
            return
        elif u.path.startswith("/grade/report/"):
            # D130-T10：逐生审核「报告」页——返回已生成的报告 HTML 供 iframe 预览。
            # 路径：/grade/report/<classDir>?taskId=&student=
            # 注意：**不**放在 /xxt/ 分支下——报告预览是纯本地产物，
            # 不应因学习通模块不可用而被 503 拦掉。
            from .grading import report as _report_mod
            q = urllib.parse.parse_qs(u.query)
            task_id = str((q.get("taskId") or [""])[0]).strip()
            student = str((q.get("student") or [""])[0]).strip()
            class_dir = urllib.parse.unquote(u.path[len("/grade/report/"):]).strip("/")
            ws_ = Path(self.ws).resolve()
            if not (task_id and student and class_dir):
                self._json({"ok": False, "error": "classDir/taskId/student 必填"}, 400)
                return
            # 安全：只允许在 <ws>/classes/**/grading/<taskId>/reports/ 下取
            safe_task = re.sub(r"[\\/:*?\"<>|]", "_", task_id).strip(" .") or "task"
            safe_stu = re.sub(r"[\\/:*?\"<>|]", "_", student).strip(" .")
            base = (ws_ / class_dir / "grading" / safe_task / "reports")
            try:
                base.resolve().relative_to((ws_ / "classes").resolve())
            except Exception:  # noqa: BLE001
                self._json({"ok": False, "error": "路径越界"}, 400)
                return
            cand = [base / f"{safe_stu}.html", base / f"{safe_stu}.md"]
            hit = next((p for p in cand if p.is_file()), None)
            if hit is None:
                self._json({"ok": False, "error": "尚未生成报告",
                            "hint": "先点「📄 一键生成批阅报告」",
                            "candidates": [str(p) for p in cand]}, 404)
                return
            html = hit.read_text(encoding="utf-8", errors="replace")
            if hit.suffix == ".md":
                html = _report_mod.report_html_from_md(html, kind="ai",
                                                       title=f"{student} 批阅报告")
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        elif u.path == "/xxt/works":
            wp = xxt_layout.works_json(_xxt_home())
            if not wp.is_file():
                self._json({"ok": False, "error": "no works yet",
                            "hint": "先 POST /xxt/works 或 assist xxt discover-works"}, 404)
                return
            try:
                self._json(json.loads(wp.read_text(encoding="utf-8")))
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"bad works json: {exc}"}, 500)
            return
        elif u.path == "/xxt/targets":
            from .xxt.targets import targets_view
            view = targets_view(_xxt_home())
            if not view.get("ok"):
                self._json({"ok": False, "error": "no targets yet",
                            "hint": "先运行 POST /xxt/discover 或 assist xxt discover"}, 404)
                return
            self._json(view)
            return
        elif u.path == "/xxt/runs":
            home = _xxt_home()
            runs = []
            for f2 in xxt_layout.run_json_files(home):
                try:
                    d = json.loads(f2.read_text(encoding="utf-8"))
                    runs.append({"run_id": d.get("run_id") or f2.stem, "ts_start": d.get("ts_start"),
                                 "ts_end": d.get("ts_end"),
                                 "failures": len(d.get("failures") or []),
                                 "classes": sum(len(c.get("classes", [])) for c in d.get("courses", [])),
                                 "works": sum(len(c2.get("works", [])) for c in d.get("courses", [])
                                              for c2 in c.get("classes", []))})
                except Exception:
                    continue
            self._json({"ok": True, "runs": runs[:20]})
            return
        elif u.path.startswith("/xxt/shot/"):
            m3 = re.fullmatch(r"/xxt/shot/([A-Za-z0-9\-]+)/([A-Za-z0-9\-_.]+)", u.path)
            if not m3:
                self._json({"ok": False, "error": "bad path"}, 404)
                return
            run_id, fname = m3.group(1), m3.group(2)
            if not re.fullmatch(r"xxt-[0-9A-Za-z\-]+", run_id):
                self._json({"ok": False, "error": "bad run"}, 404)
                return
            candidates = xxt_layout.shot_candidates(run_id, fname, _xxt_home())
            if not candidates:
                self._json({"ok": False, "error": "no shot"}, 404)
                return
            f3 = candidates[0]
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(f3.read_bytes())
            return
        elif (m2 := re.fullmatch(r"/xxt/run/([A-Za-z0-9\-]+)", u.path)):
            run_id = m2.group(1)
            fr = xxt_layout.find_run_json(run_id, _xxt_home())
            if fr is None or not re.fullmatch(r"xxt-[0-9A-Za-z\-]+", run_id):
                self._json({"ok": False, "error": "no such run"}, 404)
                return
            self._json(json.loads(fr.read_text(encoding="utf-8")))
            return
        if u.path == "/xxt/storage":
            self._json({"ok": True, **xxt_layout.run_artifacts_stats(_xxt_home())})
            return
        if u.path == "/xxt/freshness":
            from .xxt.targets import freshness
            self._json(freshness(_xxt_home()))
            return
        if u.path == "/journal":
            from .xxt import journal as _journal
            q = raw_qs
            ev = _journal.events(_xxt_home(),
                                 start=(q.get("start", [""])[0] or None),
                                 end=(q.get("end", [""])[0] or None),
                                 kind=(q.get("kind", [""])[0] or None),
                                 limit=int(q.get("limit", ["500"])[0] or 500))
            self._json({"ok": True, "events": ev, "stats": _journal.stats(_xxt_home())})
            return
        if u.path == "/engine/version":
            from .engine_update import check_engine_update
            self._json(check_engine_update(Path(self.ws).resolve()))
            return
        if u.path == "/doctor":
            checks = _doctor_checks(Path(self.ws).resolve())
            bad = [c["id"] for c in checks if c["status"] == "red"]
            self._json({"ok": True, "engine": {"version": __version__, "workspace": str(self.ws)},
                        "checks": checks, "missing_ids": bad,
                        "sources_used": {"pip_index": os.environ.get('UV_DEFAULT_INDEX') or 'tuna',
                                          "python_dl": os.environ.get('UV_PYTHON_INSTALL_MIRROR') or 'official',
                                          "official": os.environ.get('CN_OFFICIAL') == 'official'}})
        elif u.path == "/workspace/info":
            from .xxt.workspace_ops import workspace_info
            self._json(workspace_info(Path(self.ws).resolve()))
            return
        elif u.path == "/status":
            from . import get_commit
            self._json({
                "name": "assist-engine",
                "version": __version__,
                "commit": get_commit(),
                "workspace": True,
                "ws": str(self.ws),
                # D67：重启前后实例身份；PWA 必须等 instance_id 变化才算重启成功。
                "pid": os.getpid(),
                "instance_id": _INSTANCE_ID,
                "started_at": _STARTED_AT,
                "supervised": os.environ.get("ASSIST_SUPERVISED") == "1",
                "port": _SERVER_PORT,
            })
        elif (m := re.fullmatch(r"/jobs/([A-Za-z0-9_\\-]+)(/stream)?", u.path)):
            job = _JOBS.get(m.group(1))
            if job is None:
                self._json({"ok": False, "error": "no such job"}, 404)
                return
            if m.group(2):  # SSE 流
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                try:
                    while True:
                        try:
                            line = job["queue"].get(timeout=60)
                        except queue.Empty:
                            continue
                        if line.startswith("__DONE__"):
                            rc = line.replace("__DONE__", "").strip("_")
                            self.wfile.write(b"event: done\ndata: " + str(rc).encode() + b"\n\n")
                            self.wfile.flush()
                            break
                        self.wfile.write(b"data: " + line.encode("utf-8") + b"\n\n")
                        self.wfile.flush()
                except Exception:
                    pass
                return
            self._json({"ok": True, "item": job["item"], "status": job["status"],
                        "returncode": job["returncode"], "lines": job["lines"][-200:]})
        elif u.path == "/pw/pkgs":
            # D65-P2：浏览器直下清单——实测镜像链接 + 收包路径 + 已装/在包状态
            from .xxt.installer import pkg_manifest
            self._json(pkg_manifest())
        elif u.path == "/kb/full":
            # D162：把**引擎侧的题库**（含 AI 标注后的 related）整体返回给 PWA。
            # 背景：题库编辑器用的是**浏览器内存副本**，引擎写回 xlsx 后前端看不到
            # （教师反馈"勾了标注知识点，题库编辑器里看不到"）。
            from .files import kb_io as _kbio
            kb = _kbio.read_kb(Path(self.ws).resolve() / "kb")
            self._json({"ok": True, "kb": kb})
            return
        elif u.path == "/kb/stats":
            from .files import read_kb
            kb = read_kb(Path(self.ws) / "kb")
            counts = {k: sum(len(c) for c in chaps.values()) for k, chaps in kb.items()}
            self._json({"ok": True, "by_kind": counts})
        else:
            self._static(u.path.lstrip("/") if u.path != "/" else "index.html")

    def _static(self, rel: str):
        root = _static_root()
        cand = (root / rel).resolve() if root else None
        if not root or not cand.exists() or not str(cand).startswith(str(root)):
            # D41-B: redirect to Pages when no local PWA is present
            self.send_response(302)
            self.send_header("Location", PAGES_URL)
            self.end_headers()
            return
        ctype = {"html": "text/html; charset=utf-8", "js": "text/javascript",
                 "css": "text/css", "json": "application/json", "png": "image/png",
                 "svg": "image/svg+xml", "woff2": "font/woff2"}.get(cand.suffix.lstrip("."))
        body = cand.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype if ctype else "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        if self.cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logger.debug(f"{self.address_string()} {fmt % args}")


PAGES_URL = "https://pancong0711.github.io/assignment-assistant/"

def serve(workspace: str | None, host: str = "127.0.0.1", port: int = 8601,
          lan: bool = False) -> int:
    from .log import setup_logging
    setup_logging(False)
    ws = Path(workspace).expanduser().resolve() if workspace else _ws()
    _set_serve_ws(ws)
    Handler.ws = ws
    token = ""
    if lan:
        host = "0.0.0.0"
        token = secrets.token_urlsafe(9)
        logger.warning(f"LAN 模式开放 http://{host}:{port}/?token={token}（含 /install）")
    else:
        logger.info(f"本机模式 http://127.0.0.1:{port}/（引擎与 PWA 同源）")
    logger.info(f"workspace={ws}")
    global _RESTART_ARGS, _INSTANCE_ID, _STARTED_AT, _SERVER_PORT
    _RESTART_ARGS = ("serve", "--workspace", str(ws), "--port", str(port)) + (("--lan",) if lan else ())
    _INSTANCE_ID = secrets.token_urlsafe(6)
    _STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S")
    _SERVER_PORT = port
    httpd = ThreadingHTTPServer((host, port), Handler)
    Handler.token = token
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0

__all__ = ["serve", "_doctor_checks", "CHECK_IDS", "INSTALL_ITEMS"]
