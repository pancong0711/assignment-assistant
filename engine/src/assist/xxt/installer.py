"""D63 T7.1：playwright 联网安装（优先国内镜像；不随仓库分发安装包）。

两步：
① Python 包 playwright —— uv pip install（UV_DEFAULT_INDEX 缺省清华 tuna；无 uv 回落 pip -i 同源）；
② 浏览器内核 chromium —— python -m playwright install chromium
   （PLAYWRIGHT_DOWNLOAD_HOST 缺省 npmmirror 镜像；env 已设则尊重教师覆盖）。

全程在线下载，仓库零内核/零包。XXT_CHROME env 可指向本机现成 chrome/chromium 跳过②。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _venv_python() -> str:
    from ..serve import _venv_python  # 复用 workspace/.runtime/venv 解析
    return str(_venv_python())


MIRROR_PYPI = "https://pypi.tuna.tsinghua.edu.cn/simple"
MIRROR_PLAYWRIGHT = "https://npmmirror.com/mirrors/playwright/"


def install_playwright(emit) -> int:
    """两步联网安装 emit 驱动（对齐 install_katex 的 (line)->unit 接口）；下发失败结果。"""
    py = _venv_python()
    uv = shutil.which("uv")
    idx = os.environ.get("UV_DEFAULT_INDEX") or MIRROR_PYPI
    pw_host = os.environ.get("PLAYWRIGHT_DOWNLOAD_HOST") or MIRROR_PLAYWRIGHT
    emit(f"镜像口径：pypi={idx} ｜ playwright 内核={pw_host}")
    pkg_cmd = (["uv", "pip", "install", "playwright", "--python", py,
                "--cache-dir", str(Path(os.environ.get("UV_CACHE_DIR") or
                                         Path.home() / ".cache" / "uv"))]
               if uv else
               [py, "-m", "pip", "install", "playwright"])
    if uv:
        pkg_cmd = pkg_cmd + ["--index-url", idx]
    else:
        pkg_cmd = pkg_cmd + ["-i", idx]
    kernel_cmd = [py, "-m", "playwright", "install", "chromium"]
    env = {**os.environ, "PLAYWRIGHT_DOWNLOAD_HOST": pw_host}
    rc = 0
    for label, cmd in (("① Python 包 playwright", pkg_cmd),
                       ("② chromium 内核", kernel_cmd)):
        emit(f"$ {' '.join(cmd)}")
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, env=env)
        except subprocess.TimeoutExpired:
            emit(f"✗ {label} 超时（30min）"); return 1
        for line in (cp.stdout or "").splitlines()[-120:]:
            emit(line)
        for line in (cp.stderr or "").splitlines()[-60:]:
            emit(line)
        if cp.returncode != 0:
            emit(f"✗ {label} 失败 rc={cp.returncode}（网络/镜像可自行重试）"); rc = cp.returncode
            break
        emit(f"✓ {label} 完成")
    if rc == 0:
        emit("✓ playwright 就绪：回设置中心体检应转绿；学习通 tab 体检可判会话")
    return rc
