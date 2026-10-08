"""playwright 联网安装（D63 T7.1 → D64 §22.1 重构 2.0：自控下载解压）。

背景：`python -m playwright install chromium` 的 node 下载器在部分网络下
僵死（无 socket/无输出，教师端表现为"卡在安装中"）；而引擎侧 urllib 直链
cdn 端点实测可达且快（2026-10-08: 27MB/s）。故策略改为：

  1) `install chromium --dry-run`（0.2s，node cli 纯输出）解析
     [{安装位置, 官方url}] 任务清单；
  2) 全部已存在 → 就绪返回；
  3) 缺失任务 → urllib 自控下载（含 content-length 进度 emit）+ zip 解压到
     期望位置 + INSTALLATION_COMPLETE 标记（对齐 playwright 布局，
     参考 chromium-1228 现存目录）。

镜像口径（优先国内）：pip 装 = tuna；浏览器二进制 = cdn.npmmirror.com/binaries。
XXT_CHROME env 仍可指向本机现成 chrome/chromium 跳过下载。
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
MIRROR_PLAYWRIGHT = "https://cdn.npmmirror.com/binaries/playwright/"


def _ws_browsers() -> str:
    """内核目录 → workspace/.runtime/browsers（本机 /home ro：不可写 ~/.cache）。"""
    try:
        from ..workspace import find_workspace
        ws = find_workspace(None)
        if (ws / ".runtime").exists():
            return str(Path(ws) / ".runtime" / "browsers")
    except Exception:
        pass
    return ""


def _venv_python() -> str:
    from ..serve import _venv_python
    return str(_venv_python())


def install_playwright(emit) -> int:
    py = _venv_python()
    bp = _ws_browsers()
    if bp:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bp
        emit(f"内核归属 {bp}（/home 只读时免写 ~/.cache）")

    uv = shutil.which("uv")
    idx = os.environ.get("UV_DEFAULT_INDEX") or MIRROR_PYPI
    # ---------- 0) Python 包（①）若不在先装（联网，pip 镜像） ----------
    cp0 = subprocess.run([py, "-m", "playwright", "--version"], capture_output=True, text=True)
    if cp0.returncode != 0:
        pkg = (["uv", "pip", "install", "playwright", "--python", py, "--index-url", idx]
               if uv else [py, "-m", "pip", "install", "playwright", "-i", idx])
        emit(f"$ {' '.join(pkg)}")
        c = subprocess.run(pkg, capture_output=True, text=True, timeout=1200)
        if c.returncode != 0:
            emit("✗ ① playwright Python 包安装失败")
            for l in (c.stderr or c.stdout or "").splitlines()[-5:]:
                emit("  " + l)
            return 1
        emit("✓ ① playwright Python 包 完成")
    else:
        emit(f"✓ ① playwright Python 包已存在（{cp0.stdout.strip().splitlines()[-1][:40]}）")

    # ---------- 1) dry-run 解析内核任务清单 ----------
    emit(f"$ {py} -m playwright install chromium --dry-run")
    cp = subprocess.run([py, "-m", "playwright", "install", "chromium", "--dry-run"],
                        capture_output=True, text=True, timeout=120)
    if cp.returncode != 0:
        emit("✗ 依赖自检失败")
        for l in (cp.stderr or cp.stdout or "").splitlines()[-5:]:
            emit("  " + l)
        return 1
    out = cp.stdout or ""
    jobs = []
    locs = [(m.start(), m.group(1)) for m in re.finditer(r"Install location:\s*(\S+)", out)]
    urlsl = [(m.start(), m.group(1)) for m in re.finditer(r"Download url:\s*(\S+)", out)]
    for (a, loc), (b, url) in zip(locs, urlsl):
        jobs.append((loc, url))
    if not jobs:
        emit("✗ dry-run 未解析到安装任务（格式变更？）")
        emit("  " + out[:200])
        return 1
    emit(f"任务：{len(jobs)} 项；二进制源={MIRROR_PLAYWRIGHT}")

    todo = [(loc, url) for loc, url in jobs if not Path(loc).exists()]
    if not todo:
        emit("✓ playwright 就绪（目录已存在）")
        return 0

    rc, t0 = 0, time.time()
    for loc, url in todo:
        name = Path(loc).name
        builds = url.split("builds/", 1)[-1]
        url_fast = MIRROR_PLAYWRIGHT.rstrip('/') + "/builds/" + builds
        emit(f"下载 {name}：{url_fast}")
        tmp = Path(str(loc) + ".part.zip")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        total = got = 0
        try:
            req = urllib.request.Request(url_fast, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r, tmp.open("wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got, last = 0, t0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    now = time.time()
                    if now - last > 3:
                        emit(f"⏳ {name} {min(got, total) >> 20}/{(total or got) >> 20} MiB @ {int((now - t0) % 3600)}s")
                        last = now
        except Exception as e:
            emit(f"✗ {name} 下载失败：{e}")
            rc = 1
            if tmp.exists():
                tmp.unlink()
            break
        if total and got != total:
            emit(f"✗ {name} 不完整 {got}/{total}")
            tmp.unlink()
            rc = 1
            break
        emit(f"解压 {name} → {loc}")
        try:
            tgt = Path(loc)
            tgt.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(tmp) as z:
                z.extractall(tgt)
            if not tgt.exists():
                raise RuntimeError("解压后目录不存在")
            (tgt / "INSTALLATION_COMPLETE").write_text("")
            (tgt / "DEPENDENCIES_VALIDATED").write_text("")
        except Exception as e:
            emit(f"✗ {name} 解压失败：{e}")
            rc = 1
            if tmp.exists():
                tmp.unlink()
            break
        tmp.unlink(missing_ok=True)
        emit(f"✓ {name} 就绪")

    if rc == 0:
        emit(f"✓ playwright 全部就绪（{int(time.time() - t0)}s）——回设置中心体检应转绿")
    return rc
