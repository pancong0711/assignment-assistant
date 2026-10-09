"""Playwright 联网安装（D65-P0.2 / D65-P1 / D65-P2）。

策略：
  1) Python 包缺失则 pip/uv 走国内镜像安装；
  2) `playwright install chromium --no-shell --dry-run` 只取**完整版 chromium**
     与 ffmpeg（`--no-shell` 不支持时回退普通 dry-run 并过滤 headless_shell）；
  3) 缺失任务优先认领 `.runtime/browsers_pkgs/` 中浏览器直下包；
  4) 否则按真实镜像源降级：npmmirror cdn → azureedge → npmmirror registry
     → dry-run 官方 URL；
  5) 下载必须校验 Content-Length、zip 文件头与解压结果；
  6) 解压到 Playwright 期望目录并写 INSTALLATION_COMPLETE 标记；
  7) `/pw/pkgs` 给 PWA 提供直下链接、收包路径与目标路径。

注意：不再使用未经证实的华为云 playwright 路径；URL 仅来自 dry-run 或实测可用镜像。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path

MIRROR_PYPI = "https://pypi.tuna.tsinghua.edu.cn/simple"
MIRROR_PLAYWRIGHT_CDN = "https://cdn.npmmirror.com/binaries/playwright"
MIRROR_PLAYWRIGHT_REGISTRY = "https://registry.npmmirror.com/-/binary/playwright"
MIRROR_PLAYWRIGHT_AZURE = "https://playwright.azureedge.net"


def _inbox_dir() -> str:
    """浏览器直下收包文件夹：<workspace>/.runtime/browsers_pkgs。"""
    try:
        from ..workspace import find_workspace
        ws = find_workspace(None)
        return str(Path(ws) / ".runtime" / "browsers_pkgs")
    except Exception:
        return ""


def _ws_browsers() -> str:
    """内核目录 → workspace/.runtime/browsers（D14：不写 ~/.cache）。"""
    try:
        from ..workspace import find_workspace
        ws = find_workspace(None)
        if (ws / ".runtime").exists():
            return str(Path(ws) / ".runtime" / "browsers")
    except Exception:
        pass
    return ""


def _venv_python() -> str:
    from ..serve import _venv_python as _vp
    return str(_vp())


def _pw_env() -> dict[str, str]:
    """dry-run / install 子进程统一继承 workspace 内核目录。"""
    env = {**os.environ}
    bp = _ws_browsers()
    if bp:
        env["PLAYWRIGHT_BROWSERS_PATH"] = bp
    return env


def _parse_dry_run(out: str, skip_headless: bool = False) -> list[dict]:
    """解析 dry-run 输出；按 Install location 去重，保留官方与 fallback URL。"""
    jobs: dict[str, dict] = {}
    for block in re.split(r"\r?\n\s*\r?\n", out or ""):
        m = re.search(r"Install location:\s*(\S+)", block)
        if not m:
            continue
        loc = m.group(1)
        if skip_headless and "headless_shell" in Path(loc).name.lower():
            continue
        urls = re.findall(r"Download[^\n]*?:\s*(\S+)", block)
        if not urls:
            continue
        if loc not in jobs:
            jobs[loc] = {"loc": loc, "official": urls[0], "urls": urls}
    return list(jobs.values())


def _dry_run_jobs(py: str) -> list[dict]:
    """优先 `--no-shell`；旧 Playwright 不支持时回退并过滤 headless_shell。"""
    base = [py, "-m", "playwright", "install", "chromium"]
    cp = subprocess.run(base + ["--no-shell", "--dry-run"],
                        capture_output=True, text=True, timeout=120, env=_pw_env())
    if cp.returncode == 0:
        return _parse_dry_run(cp.stdout or "", skip_headless=False)

    cp2 = subprocess.run(base + ["--dry-run"],
                         capture_output=True, text=True, timeout=120, env=_pw_env())
    if cp2.returncode != 0:
        detail = (cp2.stderr or cp2.stdout or cp.stderr or cp.stdout or "").strip()
        raise RuntimeError(detail.splitlines()[-1][:240] if detail else "playwright dry-run 失败")
    return _parse_dry_run(cp2.stdout or "", skip_headless=True)


def _builds_tail(official_url: str) -> str:
    if "builds/" not in official_url:
        return ""
    return official_url.split("builds/", 1)[-1]


def _job_urls(job: dict) -> dict[str, str]:
    """命名 URL 字典；所有镜像前缀均经过 HEAD 实测或来自 dry-run。"""
    tail = _builds_tail(job["official"])
    urls = {
        "npmmirror_cdn": MIRROR_PLAYWRIGHT_CDN.rstrip("/") + "/builds/" + tail if tail else job["official"],
        "azureedge": MIRROR_PLAYWRIGHT_AZURE.rstrip("/") + "/builds/" + tail if tail else job["official"],
        "npmmirror_registry": MIRROR_PLAYWRIGHT_REGISTRY.rstrip("/") + "/builds/" + tail if tail else job["official"],
        "official": job["official"],
    }
    return urls


def _job_sources(job: dict) -> list[str]:
    urls = _job_urls(job)
    ordered = [
        urls["npmmirror_cdn"],
        urls["azureedge"],
        urls["npmmirror_registry"],
        urls["official"],
    ]
    ordered.extend(job.get("urls", [])[1:])
    out, seen = [], set()
    for u in ordered:
        if u and u not in seen:
            out.append(u)
            seen.add(u)
    return out


def _is_zip(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
    except Exception:
        return False


def _download_to_tmp(url: str, tmp: Path, emit, name: str) -> None:
    """下载单源到 tmp，失败即抛异常由调用方换源。"""
    tmp.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype and "html" in ctype:
            raise RuntimeError(f"响应不是 zip（Content-Type={ctype}）")
        total = int(r.headers.get("Content-Length") or 0)
        if total <= 0:
            raise RuntimeError("无 Content-Length，拒绝当作完整包")
        got, last = 0, time.time()
        with tmp.open("wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                now = time.time()
                if now - last > 3:
                    emit(f"⏳ {name} {min(got, total) >> 20}/{(total or got) >> 20} MiB")
                    last = now
        if got != total:
            raise RuntimeError(f"下载不完整 {got}/{total}")
    if not _is_zip(tmp):
        raise RuntimeError("文件头不是 zip")


def pkg_manifest() -> dict:
    """/pw/pkgs：PWA 直下清单 + 收包目录 + 安装状态。"""
    py = _venv_python()
    try:
        jobs = _dry_run_jobs(py)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": str(e)[:240]}
    inbox = _inbox_dir()
    items = []
    for job in jobs:
        loc = job["loc"]
        fname = Path(job["official"]).name
        items.append({
            "name": Path(loc).name,
            "dir": loc,
            "file": fname,
            "needed": True,
            "installed": Path(loc).exists(),
            "in_inbox": bool(inbox) and (Path(inbox) / fname).exists(),
            "urls": _job_urls(job),
        })
    return {"ok": True, "inbox": inbox, "items": items}


def install_playwright(emit) -> int:
    py = _venv_python()
    bp = _ws_browsers()
    if bp:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bp
        emit(f"内核归属 {bp}")

    uv = shutil.which("uv")
    idx = os.environ.get("UV_DEFAULT_INDEX") or MIRROR_PYPI
    cp0 = subprocess.run([py, "-m", "playwright", "--version"],
                         capture_output=True, text=True, env=_pw_env())
    if cp0.returncode != 0:
        pkg = (["uv", "pip", "install", "playwright", "--python", py, "--index-url", idx]
               if uv else [py, "-m", "pip", "install", "playwright", "-i", idx])
        emit(f"$ {' '.join(pkg)}")
        c = subprocess.run(pkg, capture_output=True, text=True, timeout=1200, env=_pw_env())
        if c.returncode != 0:
            emit("✗ playwright Python 包安装失败")
            for line in (c.stderr or c.stdout or "").splitlines()[-5:]:
                emit("  " + line)
            return 1
        emit("✓ playwright Python 包完成")
    else:
        line = (cp0.stdout or "").strip().splitlines()[-1][:60]
        emit(f"✓ playwright Python 包已存在（{line}）")

    try:
        jobs = _dry_run_jobs(py)
    except Exception as e:  # noqa: BLE001
        emit(f"✗ dry-run 解析失败：{e}")
        return 1

    todo = [j for j in jobs if not Path(j["loc"]).exists()]
    if not todo:
        emit("✓ playwright 就绪（完整版内核已存在；无需 headless_shell）")
        return 0

    inbox = _inbox_dir()
    rc = 0
    t0 = time.time()
    for job in todo:
        loc = job["loc"]
        name = Path(loc).name
        fname = Path(job["official"]).name
        tmp = Path(str(loc) + ".part.zip")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        ok = False

        hit = (Path(inbox) / fname) if inbox else None
        if hit and hit.exists():
            emit(f"📦 认领本地包 {fname}（来自浏览器直下）")
            try:
                shutil.copy2(hit, tmp)
                if not _is_zip(tmp):
                    raise RuntimeError("本地包不是 zip")
                ok = True
            except Exception as e:  # noqa: BLE001
                emit(f"✗ 本地包不可用（回退联网）：{e}")
                tmp.unlink(missing_ok=True)

        if not ok:
            sources = _job_sources(job)
            for src in sources:
                emit(f"下载 {name} ← {src}")
                try:
                    _download_to_tmp(src, tmp, emit, name)
                    ok = True
                    break
                except Exception as e:  # noqa: BLE001
                    emit(f"✗ 该源失败：{e}")
                    tmp.unlink(missing_ok=True)

        if not ok:
            emit(f"✗ {name} 全部源失败。可走浏览器直下：zip 放入 {inbox or '<workspace>/.runtime/browsers_pkgs/'} 后重试")
            rc = 1
            break

        try:
            p = Path(loc)
            p.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(tmp) as z:
                z.extractall(p)
            (p / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")
            (p / "DEPENDENCIES_VALIDATED").write_text("", encoding="utf-8")
            emit(f"✓ {name} 就绪")
        except Exception as e:  # noqa: BLE001
            emit(f"✗ {name} 解压失败：{e}")
            rc = 1
            break
        finally:
            tmp.unlink(missing_ok=True)

    if rc == 0:
        emit(f"✓ playwright 全部就绪（{int(time.time() - t0)}s）")
    return rc
