"""D65-P4：引擎版本检测与在线更新（PWA 按钮 + CLI 共用）。

设计边界：
- 更新检测只拉取很小的 `engine-version.json`（不含大 zip）；
- 只有远端 commit / engine_version 与本地不同，才允许下载 engine-main.zip；
- D71 起更新只负责下载/解压到 `_engine/staging` 并写 `update.pending`；
  真正安装由外部 launcher 在旧 engine 停止后执行，避免 Windows 下自锁；
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

# D73-12：zip/解压后的完整性红线。现场曾出现 _engine/engine 缺 xxt/session.py，
# serve 能启动但所有 /xxt/* 懒加载失败；这里在写 pending 前就拦住。
REQUIRED_STAGE_FILES = (
    "engine/pyproject.toml",
    "engine/run_engine.bat",
    "engine/src/assist/cli.py",
    "engine/src/assist/serve.py",
    "engine/src/assist/xxt/__init__.py",
    "engine/src/assist/xxt/session.py",
)


def missing_required_files(root: "Path | str") -> list[str]:
    """返回 root 下缺失的关键文件相对路径（可测纯函数）。"""
    root = Path(root)
    return [p for p in REQUIRED_STAGE_FILES if not (root / p).is_file()]


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


def _dep_install_commands(ws: Path, engine_dir: Path) -> list[list[str]]:
    """D69：uv 优先、venv pip 回退；uv 不再显式传已弃用的 --index-url。

    注意：两套命令安装的都是本地 `_engine/engine` editable 包；
    `-i/--index-url` 只用于解析第三方依赖（click/reportlab/...），
    不是从 PyPI 安装 assist-engine 自身。
    """
    py = _venv_python(ws)
    idx = os.environ.get("UV_DEFAULT_INDEX") or PYPI_MIRROR
    cache_dir = Path(ws) / ".runtime" / "cache" / "uv"
    cmds: list[list[str]] = []
    if shutil.which("uv"):
        cmds.append(["uv", "pip", "install", "-e", str(engine_dir),
                     "--python", py, "--cache-dir", str(cache_dir)])
    cmds.append([py, "-m", "pip", "install", "-e", str(engine_dir),
                 "-i", idx, "--disable-pip-version-check", "--no-input"])
    return cmds


def _install_engine_editable(ws: Path, engine_dir: Path, emit) -> int:
    """执行 editable 安装；uv 先试，失败自动回退到 venv pip（与 start.bat 同口径）。

    返回 0=成功，1=全部尝试失败。D69：用户现场 uv rc=2 且输出为空，
    不能让它直接终结更新；pip 回退是 start.bat 已工程验证过的稳定路径。
    """
    idx = os.environ.get("UV_DEFAULT_INDEX") or PYPI_MIRROR
    env = {
        **os.environ,
        "UV_CACHE_DIR": str(Path(ws) / ".runtime" / "cache" / "uv"),
        "UV_PROJECT_ENVIRONMENT": str(Path(ws) / ".runtime" / "venv"),
        # 兼容 uv 不同版本的 index 环境变量名。
        "UV_DEFAULT_INDEX": idx,
        "UV_INDEX_URL": idx,
    }
    last_rc: int | str = "?"
    for i, cmd in enumerate(_dep_install_commands(ws, engine_dir)):
        emit(f"$ {' '.join(cmd)}")
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=1200, env=env)
        except Exception as e:  # noqa: BLE001
            emit(f"✗ 安装命令执行异常：{e}")
            last_rc = str(e)[:200]
            continue
        out = ((cp.stdout or "") + (cp.stderr or "")).splitlines()
        for line in out[-40:]:
            emit("  " + line)
        if cp.returncode == 0:
            if i > 0:
                emit("⚠ uv 安装失败，已用 venv pip 回退成功")
            return 0
        last_rc = cp.returncode
    emit(f"✗ 依赖重装失败（rc={last_rc}）")
    return 1


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
    """D71 两阶段更新：只下载/解压到 staging 并写 pending；不碰运行中的 venv。

    真正的 editable 安装由外部 launcher（start.bat/start.sh）在旧 engine
    退出后执行；这样 Windows 下不会出现 assist.exe 自锁。
    """
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

    engine_root = ws / "_engine"
    stage = engine_root / "staging"
    pending = engine_root / "update.pending"
    try:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        emit(f"✗ 无法创建 staging 目录：{e}")
        return 1

    tmp_zip = stage / "engine-main.part.zip"
    emit(f"下载 engine-main.zip → staging（不覆盖当前 engine）")
    try:
        _download_zip(ZIP_URL, tmp_zip, emit)
    except Exception as e:  # noqa: BLE001
        tmp_zip.unlink(missing_ok=True)
        emit(f"✗ 下载失败：{e}")
        return 1

    try:
        with zipfile.ZipFile(tmp_zip) as z:
            names = set(z.namelist())
            missing_names = [p for p in REQUIRED_STAGE_FILES if p not in names]
            if missing_names:
                raise RuntimeError("zip 内缺少关键文件：" + ", ".join(missing_names[:3]))
            z.extractall(stage)
            missing_disk = missing_required_files(stage)
            if missing_disk:
                raise RuntimeError("解压后缺少关键文件：" + ", ".join(missing_disk[:3]))
        (stage / "engine-version.json").write_text(
            json.dumps(remote, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pending.write_text(
            json.dumps({"commit": rc, "remote": remote}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        emit(f"✗ 解压/写 pending 失败：{e}")
        return 1
    finally:
        tmp_zip.unlink(missing_ok=True)

    emit("✓ 新引擎已暂存到 _engine\\staging；等待 launcher 在旧引擎停止后安装。")
    emit("  PWA 将自动调用 /restart；若未回在线，请关闭终端后双击 start.bat。")
    return 0
