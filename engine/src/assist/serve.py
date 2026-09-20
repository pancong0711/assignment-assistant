"""assist serve —— Companion 本地引擎 HTTP 服务（阶段 4a，纯 stdlib 无新依赖）。

端点：
- GET /doctor        体检 JSON（cli doctor 的同一份检查逻辑，PWA 体检页真接入）
- GET /status        引擎/版本/workspace 状态
- GET /kb/stats      题库统计（复用 cli）
- 其余路径           静态托管 app 构建产物（dist-lan），PWA 与引擎同源（localhost 即安全上下文）

安全：默认绑 127.0.0.1（不对外）；--lan 开放 0.0.0.0 并要求 ?token=（启动时打印）；
     CORS：允许一切来源（本地/家用局域网模型，无敏感数据返回）。
"""

import json
import secrets
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from loguru import logger

from . import __version__
from .log import setup_logging
from .workspace import find_workspace, load_workspace_settings


def _doctor_checks(ws: Path) -> tuple:
    """与 cli doctor 一致的检查项（提取成函数供 /doctor 复用）。"""
    import importlib
    checks = []
    for mod, label in [("openpyxl", "openpyxl"), ("reportlab", "reportlab"),
                       ("loguru", "loguru"), ("httpx", "httpx"), ("PIL", "pillow")]:
        try:
            importlib.import_module(mod)
            checks.append({"name": label, "status": "green"})
        except ImportError:
            checks.append({"name": label, "status": "red"})
    import shutil
    checks.append({"name": "uv", "status": "green" if shutil_u() else "red"})
    try:
        from .paper.latex import check_xelatex
        checks.append({"name": "xelatex(可选)", "status": "green" if check_xelatex() else "yellow"})
    except ImportError:
        checks.append({"name": "xelatex(可选)", "status": "red"})
    ok_settings = (ws / "settings.local.json").exists()
    checks.append({"name": "settings.local.json", "status": "green" if ok_settings else "yellow"})
    ok_kb = (ws / "kb" / "problems.xlsx").exists()
    checks.append({"name": "kb/problems.xlsx", "status": "green" if ok_kb else "yellow"})
    return checks


def shutil_u():
    import shutil
    return bool(shutil.which("uv"))


def _static_root() -> "Path | None":
    """app 构建产物目录（engine 与 app 同 monorepo）。"""
    for cand in (Path(__file__).resolve().parents[2].parent / "app" / "dist-lan",
                 Path(__file__).resolve().parents[2].parent / "app" / "dist"):
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

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if self.token and qs.get("token", [""])[0] != self.token:
            self._json({"ok": False, "error": "invalid token"}, 401)
            return
        if u.path in ("/doctor",):
            checks = _doctor_checks(self.ws)
            bad = [c["name"] for c in checks if c["status"] == "red"]
            self._json({"ok": True, "engine": {"version": __version__, "workspace": str(self.ws)},
                        "checks": checks, "missing": bad})
        elif u.path in ("/status",):
            self._json({"name": "assist-engine", "version": __version__,
                        "workspace": True, "ws": str(self.ws)})
        elif u.path in ("/", "/index.html"):
            self._static("index.html")
        else:
            self._static(u.path.lstrip("/"))

    def _static(self, rel: str):
        root = _static_root()
        cand = (root / rel).resolve() if root else None
        if not root or not cand.exists() or not str(cand).startswith(str(root)):
            self._json({"ok": False, "hint": "app 构建产物缺失（cd app && npm run build --outDir dist-lan）"}, 404)
            return
        ctype = {"html": "text/html", "js": "text/javascript", "css": "text/css",
                 "json": "application/json", "png": "image/png", "svg": "image/svg+xml",
                 "woff2": "font/woff2"}.get(cand.suffix.lstrip("."))
        body = cand.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype if ctype else "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        if self.cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # 静音默认访问日志（由 loguru 取代）
        logger.debug(f"{self.address_string()} {fmt % args}")


def serve(workspace: str | None, host: str = "127.0.0.1", port: int = 8601,
          lan: bool = False) -> int:
    setup_logging(False)
    ws = find_workspace(workspace).resolve()
    Handler.ws = ws
    token = ""
    if lan:
        host = "0.0.0.0"
        token = secrets.token_urlsafe(9)
        logger.warning(f"LAN 模式开放 {host}:{port}，防蹭网 token：?token={token}")
    else:
        logger.info(f"本机模式 http://127.0.0.1:{port}/ （引擎与 PWA 同源，体验最佳）")
    logger.info(f"workspace={ws}  静态={_static_root()}")
    httpd = ThreadingHTTPServer((host, port), Handler)
    Handler.token = token
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
