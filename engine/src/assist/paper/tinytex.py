"""TinyTeX optional runtime installer (network-only, no bundle in repo).

D58 背景：TinyTeX 与完整 TeX 都只是可选增强，不入仓库；设置中心/CLI 需要时
直接从 tinytex-releases 官方 Release 下载对应的自解压包，解压到
``<workspace>/.runtime/tex``。安装完成后引擎优先复用该工作区副本，不要求
教师配置系统 PATH；删除 workspace 即可整体卸载。

实现上刻意不调用 yihui 的安装脚本，而是直接拿 release 资产：
- 避免脚本在 Unix 上执行 ``tlmgr path add`` 在用户家目录建软链；
- 避免 Windows 脚本额外清理/写入 ``%APPDATA%``；
- 安装目录固定，AI agent 通过 CLI 也可稳定复现。
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from loguru import logger

Emit = Callable[[str], None]

TINYTEX_VERSION = "daily"
RELEASE_BASE = (
    "https://github.com/rstudio/tinytex-releases/releases/download/"
    f"{TINYTEX_VERSION}"
)
# 国内网络抖动时的只读反代前缀（不改变资源本体，仅做 GitHub 加速）。
MIRROR_PREFIXES = (
    "https://ghfast.top/",
    "https://ghproxy.net/",
)
ASSET_STEM = "TinyTeX-1"


def _is_musl() -> bool:
    try:
        return any(Path("/lib").glob("libc.musl-*.so.1"))
    except OSError:
        return False


def asset_name() -> str | None:
    """当前平台对应的 TinyTeX daily release 资产名；不支持时返回 None。"""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        # tinytex-releases daily 自 2026.03 起为 windows.exe（自解压）
        return f"{ASSET_STEM}-windows.exe"
    if system == "darwin":
        return f"{ASSET_STEM}-darwin.tgz"
    if system == "linux":
        if machine in ("x86_64", "amd64"):
            suffix = "linuxmusl-x86_64" if _is_musl() else "linux-x86_64"
            return f"{ASSET_STEM}-{suffix}.tar.xz"
        if machine in ("aarch64", "arm64"):
            return f"{ASSET_STEM}-linux-arm64.tar.xz"
    return None


def find_xelatex(workspace: Path | str | None = None) -> str | None:
    """返回可用的 xelatex 绝对路径。

    查找顺序：系统 PATH → workspace/.runtime/tex → 兼容旧脚本可能产生的
    .runtime/.TinyTeX / .runtime/TinyTeX。只搜索 TinyTeX 体积很小的目录，
    不遍历 venv/缓存。
    """
    sys_x = shutil.which("xelatex")
    if sys_x:
        return str(Path(sys_x).resolve())
    if workspace is None:
        return None
    rt = Path(workspace).expanduser() / ".runtime"
    for base in (rt / "tex", rt / ".TinyTeX", rt / "TinyTeX"):
        if not base.exists():
            continue
        for p in base.rglob("xelatex*"):
            if p.is_file() and p.name.lower() in ("xelatex", "xelatex.exe"):
                return str(p.resolve())
    return None


def check_xelatex(workspace: Path | str | None = None) -> str | None:
    """兼容旧调用：检查 xelatex（可选依赖）是否存在。"""
    return find_xelatex(workspace)


def _download_with_fallback(url: str, dest: Path, emit: Emit) -> None:
    last_err: Exception | None = None
    for target in (url, *(prefix + url for prefix in MIRROR_PREFIXES)):
        try:
            emit(f"下载 TinyTeX：{target}")
            req = urllib.request.Request(
                target, headers={"User-Agent": "assignment-assistant/0.1"}
            )
            with urllib.request.urlopen(req, timeout=180) as resp, dest.open("wb") as fh:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                next_pct = 10
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = int(done * 100 / total)
                        if pct >= next_pct:
                            emit(f"  已下载 {pct}% ({done // (1024 * 1024)}/{total // (1024 * 1024)} MB)")
                            next_pct = pct + 10
            emit(f"下载完成：{dest.name}（{done} B）")
            return
        except Exception as exc:  # noqa: BLE001 - 逐个源降级
            last_err = exc
            emit(f"下载失败（{target}）：{exc}")
            try:
                dest.unlink()
            except OSError:
                pass
    raise RuntimeError(f"TinyTeX 下载失败：{last_err}")


def _extract_bundle(archive: Path, staging: Path, emit: Emit) -> Path:
    """把 release 资产解压到 staging，返回解压出的 TinyTeX 根目录。"""
    if archive.suffix.lower() == ".exe":
        # 官方 Windows 自解压包：-y 表示静默自解压到当前目录。
        proc = subprocess.run(
            [str(archive), "-y"],
            cwd=str(staging),
            capture_output=True,
            text=True,
            timeout=1200,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"自解压失败（{proc.returncode}）：{(proc.stderr or proc.stdout)[-500:]}"
            )
    elif archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(staging)
    else:
        with tarfile.open(archive, "r:*") as tf:
            tf.extractall(staging)

    children = [p for p in staging.iterdir() if p.is_dir()]
    inner = next((p for p in children if (p / "bin").exists()), None)
    if inner is None and len(children) == 1:
        inner = children[0]
    if inner is None:
        raise RuntimeError(f"未在资产中找到 TinyTeX 根目录：{archive.name}")
    return inner


def _tlmgr_for(tex_dir: Path) -> Path | None:
    for name in ("tlmgr.bat", "tlmgr.cmd", "tlmgr.exe", "tlmgr"):
        for p in sorted(tex_dir.rglob(name)):
            if p.is_file():
                return p
    return None


def _run_xetex_postinstall(tex_dir: Path, emit: Emit) -> None:
    """运行 tlmgr postaction（若失败只告警，不破坏已解压的 TinyTeX）。"""
    tlmgr = _tlmgr_for(tex_dir)
    if tlmgr is None:
        emit("⚠ 未找到 tlmgr，跳过 postaction；xelatex 可能仍可直接使用。")
        return
    cmd = [str(tlmgr), "postaction", "install", "script", "xetex"]
    if tlmgr.suffix.lower() in (".bat", ".cmd"):
        cmd = ["cmd", "/c", *cmd]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(tex_dir),
            capture_output=True,
            text=True,
            timeout=600,
        )
        for line in ((proc.stdout or "") + (proc.stderr or "")).splitlines():
            if line.strip():
                emit(line)
        if proc.returncode != 0:
            emit(f"⚠ tlmgr postaction 返回 {proc.returncode}；仍会保留已解压文件。")
    except Exception as exc:  # noqa: BLE001
        emit(f"⚠ tlmgr postaction 未能执行：{exc}")


def install_tinytex(workspace: Path | str, emit: Emit | None = None) -> int:
    """下载并安装 TinyTeX 到 ``<workspace>/.runtime/tex``；返回 0=成功。"""
    out: Emit = emit or (lambda line: logger.info(line))
    ws = Path(workspace).expanduser().resolve()
    rt = ws / ".runtime"
    rt.mkdir(parents=True, exist_ok=True)
    dest = rt / "tex"

    existing = find_xelatex(ws)
    if existing:
        out(f"已检测到 xelatex：{existing}（无需重复安装）")
        return 0

    asset = asset_name()
    if not asset:
        out(
            f"当前平台不支持自动安装：{platform.system()} {platform.machine()}；"
            "请改用系统 TeX Live，或从 tinytex-releases 手动解压后重试。"
        )
        return 1

    downloads = rt / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / asset
    staging = Path(tempfile.mkdtemp(prefix="tinytex-", dir=str(rt)))
    try:
        _download_with_fallback(f"{RELEASE_BASE}/{asset}", archive, out)
        inner = _extract_bundle(archive, staging, out)
        if dest.exists():
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(str(inner), str(dest))
        out(f"已解压到 {dest}")
        _run_xetex_postinstall(dest, out)
    except Exception as exc:  # noqa: BLE001
        out(f"安装失败：{exc}")
        return 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        try:
            archive.unlink()
        except OSError:
            pass

    x = find_xelatex(ws)
    if x:
        out(f"完成：xelatex = {x}")
        return 0
    out("安装完成但未找到 xelatex；可运行 `assist tex status` 检查，或把完整日志发回。")
    return 1
