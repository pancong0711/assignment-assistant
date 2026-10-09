"""D65-P4：引擎版本检测与在线更新（PWA 按钮 + CLI 共用）。

设计边界：
- 更新检测只拉取很小的 `engine-version.json`（不含大 zip）；
- 只有远端 commit / engine_version 与本地不同，才允许下载 engine-main.zip；
- 更新流程写完文件后必须重启引擎才生效；
- 下载源只使用 Pages `dl/` 同目录资源，避免 GitHub release 可能滞后导致的“版本标记新、内容旧”。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from . import __version__

PAGES_DL = "https://pancong0711.github.io/assignment-assistant/dl"
VERSION_URL = f"{PAGES_DL}/engine-version.json"
ZIP_URL = f"{PAGES_DL}/engine-main.zip"
PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def _fetch_json(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("remote version is not a JSON object")
    return data


def _meta_file(ws: Path) -> Path:
    return Path(ws) / "_engine" / "engine-version.json"


def local_version(ws: Path) -> dict:
    """本地已安装版本；无标记时回退到包 __version__，并显式标记 fallback。"""
    p = _meta_file(ws)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data["_path"] = str(p)
                data.setdefault("_fallback", False)
                return data
        except Exception:
            pass
    return {"engine_version": __version__, "commit": "", "_path": str(p), "_fallback": True}


def remote_version() -> dict:
    return _fetch_json(VERSION_URL, timeout=10)


def _commit(meta: dict) -> str:
    return str(meta.get("commit") or "").strip()


def _engine_version(meta: dict) -> str:
    return str(meta.get("engine_version") or "").strip()


def check_engine_update(ws: Path) -> dict:
    """返回 local/remote/是否有更新；远端不可达时 ok=False 但不抛异常。"""
    ws = Path(ws)
    local = local_version(ws)
    remote: dict | None = None
    error = ""
    try:
        remote = remote_version()
    except Exception as e:  # noqa: BLE001
        error = str(e)[:240]

    update_available: bool | None = None
    if remote is not None:
        lc, rc = _commit(local), _commit(remote)
        if lc and rc:
            update_available = lc != rc
        elif not lc and rc:
            # 尚无本地 commit 标记（pre-P4 安装）：提示一次更新，以写入标记。
            update_available = True
        else:
            lv, rv = _engine_version(local) or __version__, _engine_version(remote)
            update_available = bool(rv and lv != rv)

    return {
        "ok": remote is not None,
        "update_available": update_available,
        "local": local,
        "remote": remote,
        "remote_url": VERSION_URL,
        "error": error,
    }


def _venv_python(ws: Path) -> str:
    for cand in (ws / ".runtime" / "venv" / "bin" / "python",
                 ws / ".runtime" / "venv" / "Scripts" / "python.exe"):
        if cand.exists():
            return str(cand)
    import sys
    return sys.executable


def _download_zip(url: str, dest: Path, emit) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "html" in ctype:
            raise RuntimeError(f"响应不是 zip（Content-Type={ctype}）")
        total = int(r.headers.get("Content-Length") or 0)
        if total <= 0:
            raise RuntimeError("无 Content-Length，拒绝当作完整包")
        got = 0
        with dest.open("wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
        if got != total:
            raise RuntimeError(f"下载不完整 {got}/{total}")
    with dest.open("rb") as f:
        if f.read(4) not in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
            raise RuntimeError("文件头不是 zip")


def update_engine(ws: Path, emit) -> int:
    """执行一次引擎更新；返回 0=成功（仍需重启），1=失败。"""
    ws = Path(ws)
    info = check_engine_update(ws)
    if not info.get("ok"):
        emit(f"无法检测更新：{info.get('error') or '远端版本不可达'}")
        return 1
    if not info.get("update_available"):
        emit("当前已是最新版本，无需更新。")
        return 0

    remote = info.get("remote") or {}
    rc = _commit(remote)
    emit(f"检测到新版本：{_engine_version(remote) or __version__}"
         + (f"（commit {rc[:12]}）" if rc else ""))

    target = ws / "_engine"
    target.mkdir(parents=True, exist_ok=True)
    tmp = target / "engine-main.part.zip"
    emit(f"下载 engine-main.zip ← {ZIP_URL}")
    try:
        _download_zip(ZIP_URL, tmp, emit)
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        emit(f"✗ 下载失败：{e}")
        return 1

    try:
        with zipfile.ZipFile(tmp) as z:
            names = z.namelist()
            if "engine/pyproject.toml" not in names:
                raise RuntimeError("zip 内缺少 engine/pyproject.toml（非预期包结构）")
            z.extractall(target)
        _meta_file(ws).write_text(
            json.dumps(remote, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        emit(f"✗ 解压/写版本标记失败：{e}")
        return 1
    finally:
        tmp.unlink(missing_ok=True)

    py = _venv_python(ws)
    engine_dir = target / "engine"
    idx = os.environ.get("UV_DEFAULT_INDEX") or PYPI_MIRROR
    if shutil.which("uv"):
        cmd = ["uv", "pip", "install", "-e", str(engine_dir),
               "--python", py, "--index-url", idx]
    else:
        cmd = [py, "-m", "pip", "install", "-e", str(engine_dir), "-i", idx]
    env = {
        **os.environ,
        "UV_CACHE_DIR": str(ws / ".runtime" / "cache" / "uv"),
        "UV_PROJECT_ENVIRONMENT": str(ws / ".runtime" / "venv"),
    }
    emit(f"$ {' '.join(cmd)}")
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, env=env)
    except Exception as e:  # noqa: BLE001
        emit(f"✗ 依赖重装失败：{e}")
        return 1
    for line in (cp.stdout or "").splitlines()[-20:]:
        emit("  " + line)
    for line in (cp.stderr or "").splitlines()[-20:]:
        emit("  " + line)
    if cp.returncode != 0:
        emit(f"✗ 依赖重装失败（rc={cp.returncode}）")
        return 1

    emit("✓ 引擎文件已更新；需要重启引擎后生效（PWA 将自动触发 /restart）。")
    return 0
