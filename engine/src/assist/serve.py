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

CHECK_IDS = ("python_env", "uv", "deps", "playwright", "xelatex", "fonts", "settings", "kb")
INSTALL_ITEMS = ("deps", "playwright", "fonts", "tex_guide", "python_guide", "uv", "kb_init", "katex", "tinytex", "engine_update")

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


def _ws() -> Path:
    from .workspace import find_workspace
    return Path(find_workspace(None)).resolve()


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
    if item == "playwright":
        return [_venv_python(), "-m", "playwright", "install", "chromium"], None
    if item == "fonts":
        if fonts_sh.exists():
            return ["bash", str(fonts_sh)], None
        return None, ["fonts-download.sh 未找到（仓库 tools/）—— CHRIST 自绘示意；Windows 请自备 simsun.ttc/simkai.ttf"]
    if item == "uv":
        return None, [f"未安装 uv：Windows 运行 tools/install.ps1，或 bash：curl -LsSf https://astral.sh/uv/install.sh | sh"]
    if item == "kb_init":
        return None, ["假题库示例：请从 PWA 题库编辑器「载入示例数据」后导出 zip，解压至 workspace/kb/"]
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
    checks.append(_check("uv", "green" if uv_ok else "red", "uv（依赖管理）",
                         "已安装" if uv_ok else "未安装（start 脚本会自动装）",
                         {"type": "guide"}))
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
    ok_kb = (ws / "kb" / "problems.xlsx").exists()
    checks.append(_check("kb", "green" if ok_kb else "yellow", "kb 题库",
                         "kb/problems.xlsx（真实题库不入仓库）", {} if ok_kb else {"type": "guide"}))
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
                                      error=(out[-1] if out else ""))
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
                                           error=(out[-1] if out else ""))
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

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
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
                            "hint": "关闭引擎窗口 → 删除 workspace\_engine → 重新双击 start.bat；见 docs/24 §14"}, 503)
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
                cmd = _xxt_cli_cmd(["xxt", "extract", "--targets", str(spec)])
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
                        "hint": "引擎安装不完整：关闭引擎窗口后删除 workspace\_engine，再双击 start.bat 重装；见 docs/24 §14",
                    }, "avatar": {"ok": False}})
                else:
                    self._json({"ok": False,
                                "error": "学习通模块不可用（引擎安装不完整）",
                                "detail": xxt_err,
                                "hint": "关闭引擎窗口 → 删除 workspace\_engine → 重新双击 start.bat；见 docs/24 §14"}, 503)
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
        elif u.path == "/status":
            self._json({
                "name": "assist-engine",
                "version": __version__,
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
