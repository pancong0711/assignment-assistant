"""会话体检 + 扫码登录（D63 T1；port 自 .scratch/xxt_session_check.py 与 xxt_login_capture.py）。

判活三信号（docs/16 §11.1，教训：下游页面 selector 超时 ≠ 会话失效）：
  a) 不被重定向回 passport/login；
  b) 页面无密码输入框；
  c) 教师工作台文案可识别（"老师/workbench"类关键词）。
verdict=alive 时执行 storage_state 回写续期（旧 xuexitong/browser.py 惯例）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlparse

HOME_URL = "https://i.chaoxing.com/base"
LOGIN_URL = ("https://passport2.chaoxing.com/login?fid=&newversion=true"
             "&refer=https%3A%2F%2Fi.chaoxing.com")
SCAN_TIMEOUT = 30 * 60  # 扫码等待上限 30 分钟


# ---------- 纯逻辑（可测，不碰浏览器） ----------

def evaluate_verdict(final_url: str, login_pwd_input: bool) -> tuple[str, list[str]]:
    """三信号 → ("alive"|"dead", reasons)；纯函数，D46 回归口径。"""
    reasons: list[str] = []
    u = urlparse(final_url)
    host, path = (u.netloc or "").lower(), (u.path or "").lower()
    if "passport" in host or "/login" in path:
        reasons.append(f"redirected:{host}{path}")
    if login_pwd_input:
        reasons.append("password_input")
    return ("dead" if reasons else "alive"), reasons


def _launch(pw, headless: bool):
    """D65-P0.1：本机浏览器优先的启动链。

    链序：XXT_CHROME → msedge → chrome → 本机 chromium → Playwright 完整版。
    每档真启动；前档失败才降级。最后一档 channel="chromium" 不会去找
    chromium-headless-shell。
    """
    from .browsers import ARGS, launch_attempts

    last = None
    for kwargs in launch_attempts():
        try:
            return pw.chromium.launch(headless=headless, args=ARGS, **kwargs)
        except Exception as e:  # noqa: BLE001 —— 该档不可用，继续下一档
            last = e
    raise RuntimeError(
        "未找到可用的本机浏览器（Edge/Chrome/Chromium），自带完整版内核也未就绪。"
        "请到设置中心体检 → 修复（只下载完整版内核），或设 XXT_CHROME 指向本机浏览器"
    ) from last


def _is_logged_in(page) -> bool:
    """扫码后轮询判定（port 自 login_capture.is_logged_in）。"""
    u = urlparse(page.url)
    host, path = u.netloc.lower(), u.path.lower()
    if "passport" in host or "login" in path:
        return False
    try:
        names = {c["name"].lower() for c in page.context.cookies()}
        return "_uid" in names or "uid" in names
    except Exception:
        return False


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as e:  # pragma: no cover - 环境差异给明确指引
        raise RuntimeError(
            "playwright 未安装（engine 可选依赖）。安装：pip install 'playwright>=1.40' "
            "并执行 playwright install chromium；或设 XXT_CHROME 指向本机 chromium/chrome") from e


# ---------- 浏览器流程 ----------

def check_session(storage: "Path | str | None" = None,
                  json_out: "Path | str | None" = None,
                  html_out: "Path | str | None" = None) -> dict:
    """体检：goto 教师工作台 → 三信号判定 → alive 则 storage 回写续期。"""
    _require_playwright()
    from playwright.sync_api import sync_playwright
    storage = Path(storage or (Path.home() / "assignment-assistant-workspace"
                               / ".runtime" / "xxt-storage.json"))
    report: dict = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "storage": str(storage),
                    "storage_exists": storage.exists()}
    if not storage.exists():
        report.update({"verdict": "dead", "reasons": ["no_storage"],
                       "hint": "请先运行 assist xxt login 扫码登录"})
        return report
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        markers = page.evaluate(
            "() => ({password: !!document.querySelector('input[type=password]'), "
            "workbench: !!(document.body && /老师|课程|工作台/.test(document.body.innerText))})")
        verdict, reasons = evaluate_verdict(page.url, markers["password"])
        report.update({"final_url": page.url, "markers": markers,
                       "verdict": verdict, "reasons": reasons})
        if verdict == "alive":
            if not markers["workbench"]:
                # 保守口径：工作台文案没对上也算 alive（URL+密码框为主信号），但留痕
                report["reasons"].append("note:workbench_text_missing")
            ctx.storage_state(path=str(storage))
            report["storage_refreshed"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if html_out:
            Path(html_out).write_text(page.content(), encoding="utf-8")
        browser.close()
    if json_out:
        Path(json_out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    return report


def qr_login(storage: "Path | str | None" = None,
             qr_out: "Path | str | None" = None,
             state_out: "Path | str | None" = None,
             html_out: "Path | str | None" = None,
             timeout: int = SCAN_TIMEOUT) -> dict:
    """扫码登录（headless 出二维码图片，教师手机扫码；不自动刷新 QR）→ 保存 storage。"""
    _require_playwright()
    from playwright.sync_api import sync_playwright
    storage = Path(storage or (Path.home() / "assignment-assistant-workspace"
                               / ".runtime" / "xxt-storage.json"))
    qr_out = Path(qr_out or storage.parent / "xxt-qr.png")
    state_out = Path(state_out or storage.parent / "xxt-login-state.json")
    html_out = Path(html_out or storage.parent / "xxt-after-login.html")
    storage.parent.mkdir(parents=True, exist_ok=True)
    state = {"ts": time.strftime("%Y-%m-%d %H:%M:%S")}

    def _write(**kw):
        state.update(kw)
        state_out.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="zh-CN")
        page = ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("#quickCode", timeout=30000)
        page.locator("#quickCode").screenshot(path=str(qr_out))
        _write(stage="waiting_scan", url=page.url, qr=str(qr_out))
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(2)
            if _is_logged_in(page):
                time.sleep(3)
                try:
                    page.goto("https://i.chaoxing.com/", wait_until="domcontentloaded",
                              timeout=60000)
                    page.wait_for_timeout(5000)
                except Exception:
                    pass
                ctx.storage_state(path=str(storage))
                html_out.write_text(page.content(), encoding="utf-8")
                _write(stage="logged_in", url=page.url, title=page.title(),
                       storage=str(storage), html=str(html_out))
                browser.close()
                return {**state, "verdict": "logged_in"}
            if time.time() - state.get("_last_diag", 0) > 15:
                state["_last_diag"] = time.time()
                _write(stage="waiting_scan", url=page.url)
        _write(stage="timeout", url=page.url)
        browser.close()
    return {**state, "verdict": "timeout"}


def fetch_avatar_b64(storage: "Path | str", timeout_ms: int = 25000) -> "dict | None":
    """alive 会话内抓教师工作台头像 → {"ok":True,"dataurl":...}; 无头像 None（PWA 退二维码态）。"""
    _require_playwright()
    import base64
    from playwright.sync_api import sync_playwright
    storage = Path(storage)
    if not storage.exists():
        return None
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        # photo.chaoxing.com 有 Referer 防外链（403）→ 引擎侧以完整浏览器指纹取字节：
        src = page.evaluate("""() => {
            // D63 批次三实测 selector：img.head-img(50x50)/img.icon-head(30x30)
            const el = document.querySelector('img.head-img') || document.querySelector('img.icon-head');
            if (el && el.src && !/error|icon-link/.test(el.src)) return el.src;
            const imgs = [...document.querySelectorAll('img')];
            const hit = imgs.find(i => i.src.indexOf('photo.chaoxing.com/p/') >= 0);
            return hit ? hit.src : null;
        }""")
        if not src:
            return None
        import urllib.request
        from urllib.parse import urlparse as _up
        import base64 as _b64
        ck = "; ".join(f"{c['name']}={c['value']}" for c in ctx.cookies()
                       if 'chaoxing' in c['domain'])
        req = urllib.request.Request(src, headers={
            'Cookie': ck,
            'User-Agent': page.evaluate("() => navigator.userAgent"),
            'Referer': 'https://i.chaoxing.com/',
            'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'})
        data = urllib.request.urlopen(req, timeout=20).read()
        mime = 'image/png' if data[:4] == b'\x89PNG' else 'image/jpeg'
        out = {"ok": True, "dataurl": f"data:{mime};base64," + _b64.b64encode(data).decode()}
        # 会话仍视为只读浏览；顺带回写续期
        ctx.storage_state(path=str(storage))
        browser.close()
        return out
