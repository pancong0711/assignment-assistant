"""会话体检 + 扫码登录（D63 T1；port 自 .scratch/xxt_session_check.py 与 xxt_login_capture.py）。

判活三信号（docs/16 §11.1，教训：下游页面 selector 超时 ≠ 会话失效）：
  a) 不被重定向回 passport/login；
  b) 页面无密码输入框；
  c) 教师工作台文案可识别（"老师/workbench"类关键词）。
verdict=alive 时执行 storage_state 回写续期（旧 xuexitong/browser.py 惯例）。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

HOME_URL = "https://i.chaoxing.com/base"
LOGIN_URL = ("https://passport2.chaoxing.com/login?fid=&newversion=true"
             "&refer=https%3A%2F%2Fi.chaoxing.com")
SCAN_TIMEOUT = 30 * 60  # 扫码等待上限 30 分钟

# 旧默认布局标记：这些文件出现在 `<ws>/.runtime/` 下 = 该目录本身就是 xxt 根
_LEGACY_MARKERS = (
    "xxt-storage.json",
    "xxt-qr.png",
    "xxt-login-state.json",
    "xxt-after-login.html",
)


# D119：进程级「当前 workspace」绑定。serve 启动时绑定；CLI 用 -w 时绑定。
# 目的：让 xxt_home() 不再隐式使用 find_workspace(None)（可能与 serve 实际 ws 不同 →
# 跨工作区串数据：在 A 下载、切到 B 批阅仍读 A 的图/草稿）。
_BOUND_WS: "Path | None" = None


def bind_workspace(ws: "Path | str | None") -> None:
    """绑定当前 workspace（D119-L3 口径唯一）。传 None 解除绑定。"""
    global _BOUND_WS
    _BOUND_WS = Path(ws).expanduser().resolve() if ws else None


def bound_workspace() -> "Path | None":
    return _BOUND_WS


def xxt_home() -> Path:
    """统一 xxt 工件根（storage/qr/runs/pages），serve 与 CLI 必须使用同一口径。

    D119 优先级（**已去掉"仓库 .scratch 优先"**，那会让教师的作答图/草稿落到代码仓库里）：
      1. 环境变量 `XXT_HOME`（显式覆盖，保留给高级用法）
      2. **已绑定的 workspace**（serve / CLI -w）→ `<ws>/.runtime/xxt`
      3. 开发便利：`ASSIST_DEV_SCRATCH=1` 且仓库 `.scratch` 有 storage → 用它（**仅显式开启**）
      4. 兜底：`find_workspace(None)/.runtime/xxt`
    兼容旧默认布局：若 `<ws>/.runtime` 下已有旧的 xxt-storage.json/xxt-qr.png，
    则以该目录本身为根，避免升级后突然找不到历史会话或二维码。
    """
    env = os.environ.get("XXT_HOME")
    if env:
        return Path(env).expanduser()
    # 2) 已绑定的 workspace（D119 主路径）
    if _BOUND_WS is not None:
        runtime = _BOUND_WS / ".runtime"
        if any((runtime / name).exists() for name in _LEGACY_MARKERS):
            return runtime
        return runtime / "xxt"
    # 3) 开发便利：必须显式开启，绝不默认生效
    if str(os.environ.get("ASSIST_DEV_SCRATCH") or "") in ("1", "true", "True"):
        repo_root = Path(__file__).resolve().parents[4]
        if (repo_root / ".scratch" / "xxt-storage.json").exists():
            import sys as _sys
            print("[xxt_home] 警告：正在使用仓库 .scratch（ASSIST_DEV_SCRATCH=1）",
                  file=_sys.stderr)
            return repo_root / ".scratch"
    # 4) 兜底
    from ..workspace import find_workspace
    runtime = Path(find_workspace(None)).resolve() / ".runtime"
    legacy_markers = (
        "xxt-storage.json",
        "xxt-qr.png",
        "xxt-login-state.json",
        "xxt-after-login.html",
    )
    if any((runtime / name).exists() for name in legacy_markers):
        return runtime
    return runtime / "xxt"


def resolve_storage_path(storage: "Path | str | None" = None) -> Path:
    """storage 路径口径：显式参数 > XXT_STORAGE > xxt_home()/xxt-storage.json。"""
    if storage:
        return Path(storage).expanduser()
    env = os.environ.get("XXT_STORAGE")
    if env:
        return Path(env).expanduser()
    return xxt_home() / "xxt-storage.json"


def default_qr_path(storage: "Path | str") -> Path:
    """二维码默认与 storage 同目录：<storage.parent>/xxt-qr.png。"""
    return Path(storage).expanduser().parent / "xxt-qr.png"


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


def is_login_redirect_url(url: "str | None") -> bool:
    """D188：URL 是否命中学习通登录页（passport / login）；纯函数，只判布尔。

    只解析主机与路径，忽略 query（避免把票据/token 带进日志或界面）。
    """
    u = urlparse(str(url or ""))
    host = (u.netloc or "").lower()
    path = (u.path or "").lower()
    return "passport" in host or "login" in host or "/login" in path


def steps_have_login_redirect(steps) -> bool:
    """D188：run/targets 的 steps[] 里是否出现登录页跳转（只看 url）。"""
    if not isinstance(steps, list):
        return False
    for step in steps:
        if isinstance(step, dict) and is_login_redirect_url(step.get("url")):
            return True
    return False


def _launch_labeled(pw, headless: bool):
    """D65-P0.1 + D70：返回 (browser, 档位标签)，用于过程诊断。

    链序：XXT_CHROME → msedge → chrome → 本机 chromium → Playwright 完整版。
    每档真启动；前档失败才降级。最后一档 channel="chromium" 不会去找
    chromium-headless-shell。
    """
    from .browsers import ARGS, launch_attempts

    last = None
    for kwargs in launch_attempts():
        label = str(kwargs.get("channel") or kwargs.get("executable_path") or "chromium")
        try:
            browser = pw.chromium.launch(headless=headless, args=ARGS, **kwargs)
            return browser, label
        except Exception as e:  # noqa: BLE001 —— 该档不可用，继续下一档
            last = e
    raise RuntimeError(
        "未找到可用的本机浏览器（Edge/Chrome/Chromium），自带完整版内核也未就绪。"
        "请到设置中心体检 → 修复（只下载完整版内核），或设 XXT_CHROME 指向本机浏览器"
    ) from last


def _launch(pw, headless: bool):
    """保留旧调用口径；需要浏览器档位时用 _launch_labeled。"""
    return _launch_labeled(pw, headless)[0]


def _page_alive(browser, page) -> tuple[bool, str]:
    """D70/D71：判断 browser/page 是否还活着。

    D71 修正：页面导航会销毁 execution context，`Page.evaluate` 会报
    “Execution context was destroyed”；这是正常登录跳转，不是浏览器死亡。
    真死亡只看 browser disconnected / page closed；evaluate 异常仅在明确
    是连接类错误时才判死。
    """
    try:
        if not browser.is_connected():
            return False, "browser disconnected"
        if page.is_closed():
            return False, "page closed"
    except Exception as e:  # noqa: BLE001
        return False, f"browser/page state unavailable: {str(e)[:160]}"
    try:
        page.evaluate("() => 1")
        return True, ""
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        low = msg.lower()
        if "execution context was destroyed" in low or "navigation" in low:
            return True, ""  # 登录成功后的正常跳转
        return False, msg[:200]


def _cookie_names(page) -> list[str]:
    """只取 cookie 名（不取 value），用于脱敏状态诊断。"""
    try:
        names = {str(c.get("name", "")) for c in page.context.cookies() if c.get("name")}
        return sorted(names)[:30]
    except Exception:
        return []


# D189：扫码登录依赖的会话 cookie（大小写不敏感）。
# 只看名字判断会把“以前登录残留的旧 _uid”误当成本次扫码成功。
_SESSION_COOKIE_NAMES = ("_uid", "uid", "fid", "vc3", "uf", "xxtenc")


def cookie_fingerprint(cookies) -> dict:
    """D189：cookie 指纹（只含名字 → 值的短哈希），用于内存比较，不落盘。

    `cookies` 为 Playwright `context.cookies()` 的结果；返回
    `{"_uid": "ab12cd34", ...}`。值永不进入日志/状态文件/界面。
    """
    out: dict = {}
    try:
        for c in cookies or []:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip().lower()
            if not name:
                continue
            raw = str(c.get("value") or "")
            out[name] = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:8]
    except Exception:  # noqa: BLE001 —— 诊断用，失败只返回空指纹
        return {}
    return out


def session_cookie_changed(baseline: "dict | None", current: "dict | None") -> bool:
    """D189：本次扫码是否带来了**新的/变化的**会话 cookie。

    基线为空（第一次扫码）时，只要出现会话 cookie 就视为变化；
    否则至少有一个会话 cookie 新增或值变化。
    """
    cur = current if isinstance(current, dict) else {}
    base = baseline if isinstance(baseline, dict) else {}
    for name in _SESSION_COOKIE_NAMES:
        if not cur.get(name):
            continue
        if not base:
            return True
        if base.get(name) != cur.get(name):
            return True
    return False


def _is_logged_in(page, baseline: "dict | None" = None) -> bool:
    """扫码后轮询判定（D68/D70 口径 + D189 基线校验）。

    原实现只看 `_uid/uid` 是否存在：教师以前登录过时，浏览器里残留旧 cookie，
    新二维码还没扫就被判“已登录”，循环提前退出 → 表现为“扫了没反应/不跳转”。

    D189 口径：
      1) URL 仍是 passport/login → 未登录；
      2) 必须**相对 baseline 出现新的/变化的会话 cookie**；
      3) 页面在 i.chaoxing.com/教学域且不是登录页。
    真伪最终仍由 qr_login 的 HOME_URL 跳转 + CLI check_session 二次确认。
    """
    u = urlparse(page.url)
    host, path = u.netloc.lower(), (u.path or "").lower()
    try:
        current = cookie_fingerprint(page.context.cookies())
    except Exception:  # noqa: BLE001
        return False
    has_session_cookie = any(current.get(n) for n in _SESSION_COOKIE_NAMES)
    if "passport" in host or "login" in path:
        # D70：URL 还在登录页，但**本次扫码**已经写入了新的会话 cookie → 也算成功。
        return bool(has_session_cookie and session_cookie_changed(baseline, current))
    if host != "i.chaoxing.com" and not host.endswith(".chaoxing.com"):
        return False
    # 教学域页面：旧实现无 cookie 也判真（保底行为）；D189 只在 baseline 为空
    # （首次扫码）时保留该保底，避免把“以前登录残留”误判成本次成功。
    if has_session_cookie and session_cookie_changed(baseline, current):
        return True
    return not baseline and not has_session_cookie


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
    storage = resolve_storage_path(storage)
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
    """扫码登录（headless 出二维码图片，教师手机扫码；不自动刷新 QR）→ 保存 storage。

    D66：storage/qr/state/html 统一由 resolve_storage_path 定位；serve 不再依赖
    qr_login 内部的固定默认路径。二维码先写临时文件再原子替换，并清除旧票据。
    """
    _require_playwright()
    from playwright.sync_api import sync_playwright
    storage = resolve_storage_path(storage)
    qr_out = Path(qr_out).expanduser() if qr_out else default_qr_path(storage)
    state_out = (Path(state_out).expanduser() if state_out
                 else storage.parent / "xxt-login-state.json")
    html_out = (Path(html_out).expanduser() if html_out
                else storage.parent / "xxt-after-login.html")
    for path in (storage, qr_out, state_out, html_out):
        path.parent.mkdir(parents=True, exist_ok=True)
    # 清除旧二维码/半成品：旧 QR 仍是有效登录票据，不能让它被页面或手机扫到。
    qr_tmp = qr_out.with_name(f"{qr_out.stem}.tmp{qr_out.suffix}")
    for path in (qr_out, qr_tmp):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    state = {"ts": time.strftime("%Y-%m-%d %H:%M:%S")}

    def _write(**kw):
        state.update(kw)
        payload = json.dumps(state, ensure_ascii=False, indent=1)
        state_out.write_text(payload, encoding="utf-8")
        # D70：同时输出到 CLI stdout，经 serve 子进程转发到 terminal/start.log 与 /jobs。
        print(payload, flush=True)

    _write(stage="starting", storage=str(storage), qr=str(qr_out))
    with sync_playwright() as pw:
        browser, browser_label = _launch_labeled(pw, headless=True)
        try:
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="zh-CN")
            page = ctx.new_page()
            try:
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector("#quickCode", timeout=30000)
                page.locator("#quickCode").screenshot(path=str(qr_tmp))
                os.replace(qr_tmp, qr_out)
                # D189：记录“扫码前”的 cookie 指纹（仅内存），用于判定本次扫码是否真的生效。
                baseline = cookie_fingerprint(ctx.cookies())
            except Exception as e:  # noqa: BLE001 —— 二维码阶段失败要留证并让任务终结
                try:
                    qr_tmp.unlink()
                except FileNotFoundError:
                    pass
                _write(stage="failed", url=getattr(page, "url", ""),
                       browser=browser_label, browser_connected=browser.is_connected(),
                       page_closed=page.is_closed(), error=str(e)[:500])
                raise
            _write(stage="waiting_scan", url=page.url, qr=str(qr_out),
                   browser=browser_label, browser_connected=browser.is_connected(),
                   page_closed=page.is_closed(), cookies=[],
                   session_cookie_names=sorted(baseline))
            deadline = time.time() + timeout
            while time.time() < deadline:
                time.sleep(2)
                # D71：先判登录（cookie-first），再做存活检查；导航中的 evaluate
                # 异常不再提前误杀扫码任务。
                if _is_logged_in(page, baseline):
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
                           storage=str(storage), html=str(html_out),
                           browser=browser_label,
                           browser_connected=browser.is_connected(),
                           page_closed=page.is_closed(),
                           cookies=_cookie_names(page))
                    return {**state, "verdict": "logged_in"}
                alive, alive_err = _page_alive(browser, page)
                if not alive:
                    _write(stage="failed", url=getattr(page, "url", ""),
                           browser=browser_label,
                           browser_connected=browser.is_connected(),
                           page_closed=page.is_closed(),
                           cookies=_cookie_names(page),
                           error=f"browser/page closed before scan: {alive_err}")
                    return {**state, "verdict": "failed"}
                if time.time() - state.get("_last_diag", 0) > 15:
                    state["_last_diag"] = time.time()
                    _write(stage="waiting_scan", url=page.url,
                           browser=browser_label,
                           browser_connected=browser.is_connected(),
                           page_closed=page.is_closed(),
                           cookies=_cookie_names(page))
            _write(stage="timeout", url=page.url,
                   browser=browser_label, browser_connected=browser.is_connected(),
                   page_closed=page.is_closed(), cookies=_cookie_names(page))
        finally:
            try:
                browser.close()
            except Exception:
                pass
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
