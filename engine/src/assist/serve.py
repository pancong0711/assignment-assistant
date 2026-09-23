"""assist serve —— Companion 本地引擎 HTTP 服务（阶段4a + R1.3 一键安装，M-D 前移）。

端点：
- GET  /doctor            体检 JSON（A3 id 定版；fix: install=deps/fonts 等）
- GET  /status            引擎版本 / workspace
- POST /install/<item>    发起安装任务（deps/playwright/fonts/tex_guide/python_guide/uv/kb_init）
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
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from loguru import logger

from . import __version__

CHECK_IDS = ("python_env", "uv", "deps", "playwright", "xelatex", "fonts", "settings", "kb")
INSTALL_ITEMS = ("deps", "playwright", "fonts", "tex_guide", "python_guide", "uv", "kb_init")

_JOBS: dict[str, dict] = {}
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
    checks.append(_check("playwright", "green" if pw == "已安装" else "yellow", "Playwright（阶段6）", pw, {}))
    try:
        from .paper.latex import check_xelatex
        x = check_xelatex()
        checks.append(_check("xelatex", "green" if x else "yellow", "TeX (xelatex，样题可选)",
                             x or "未安装；可选依赖", {} if x else {}))
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
    return checks


def _playwright_state() -> str:
    try:
        import importlib.util
        if importlib.util.find_spec("playwright") is None:
            return "未安装（阶段6 需要）"
        for browsers in (Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "") or "~/.cache/ms-playwright").expanduser(),):
            if browsers.exists() and any(browsers.iterdir()):
                return "已安装"
        return "包已装，内核未安装"
    except Exception:
        return "检测失败"


def _static_root() -> "Path | None":
    for cand in (_ENGINE_ROOT.parent / "app" / "dist-lan",
                 _ENGINE_ROOT.parent / "app" / "dist"):
        if (cand / "index.html").exists():
            return cand
    return None


class Handler(BaseHTTPRequestHandler):
    ws: Path = None  # type: ignore
    token: str = ""
    cors: bool = True

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

    def _start_job(self, job_id: str, item: str):
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

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if not self._ok_token(qs):
            self._json({"ok": False, "error": "token required"}, 401)
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
        if u.path == "/doctor":
            checks = _doctor_checks(Path(self.ws).resolve())
            bad = [c["id"] for c in checks if c["status"] == "red"]
            self._json({"ok": True, "engine": {"version": __version__, "workspace": str(self.ws)},
                        "checks": checks, "missing_ids": bad,
                        "sources_used": {"pip_index": os.environ.get('UV_DEFAULT_INDEX') or 'tuna',
                                          "python_dl": os.environ.get('UV_PYTHON_INSTALL_MIRROR') or 'official',
                                          "official": os.environ.get('CN_OFFICIAL') == 'official'}})
        elif u.path == "/status":
            self._json({"name": "assist-engine", "version": __version__,
                        "workspace": True, "ws": str(self.ws)})
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
                            self.wfile.write(b"event: done\ndata: " + str(rc).encode() + b"\\n\\n")
                            self.wfile.flush()
                            break
                        self.wfile.write(b"data: " + line.encode("utf-8") + b"\\n\\n")
                        self.wfile.flush()
                except Exception:
                    pass
                return
            self._json({"ok": True, "item": job["item"], "status": job["status"],
                        "returncode": job["returncode"], "lines": job["lines"][-200:]})
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
            self._json({"ok": False, "hint": "app 构建产物缺失（cd app && npm run build）"}, 404)
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
    httpd = ThreadingHTTPServer((host, port), Handler)
    Handler.token = token
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0

__all__ = ["serve", "_doctor_checks", "CHECK_IDS", "INSTALL_ITEMS"]
