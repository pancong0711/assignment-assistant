"""D212：批阅图片下载的「更新 + 历史归档 + 孤儿清理」。

设计（与 D193 报告版本同一套哲学：稳定路径 + 内容哈希 + 历史归档）：

- 主目录（`pages/review/<classId>/<workId>/`）**永远只保留最新一份**；
- 内容未变 → 不写盘、不归档（幂等）；
- 内容变化 → 旧文件移入 `.history/<YYYYmmdd-HHMMSS>/`，再原子写入新文件；
- 下载完成后按 manifest 引用集合清理孤儿（移到 `.history/<ts>/_orphans/`）。

纯文件操作，不依赖浏览器，便于单测。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path

HISTORY_DIR = ".history"
MANIFEST_NAME = "students.json"
ORPHAN_DIR = "_orphans"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


def file_sha256(path) -> "str | None":
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:  # noqa: BLE001
        return None


def atomic_write_bytes(path, data: bytes) -> None:
    """临时文件 + os.replace，崩溃不会留下半张图。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def new_history_dir(wdir, ts: "str | None" = None) -> Path:
    """本次下载的历史目录（同名已存在时追加序号，避免并发覆盖）。"""
    base = Path(wdir) / HISTORY_DIR
    stamp = ts or time.strftime("%Y%m%d-%H%M%S")
    d = base / stamp
    n = 1
    while d.exists():
        n += 1
        d = base / f"{stamp}-{n}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_dir(hist_dir):
    """hist_dir 允许是 Path 或“按需创建”的 callable（避免产生空历史目录）。"""
    return Path(hist_dir()) if callable(hist_dir) else Path(hist_dir)


def archive_existing(target, hist_dir, *, subdir: str = "") -> "Path | None":
    """把已存在的文件移到历史目录（保留文件名），返回归档后的路径。"""
    src = Path(target)
    if not src.is_file():
        return None
    base = _resolve_dir(hist_dir)
    dst_dir = base / subdir if subdir else base
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    n = 1
    while dst.exists():
        n += 1
        dst = dst_dir / f"{src.stem}.{n}{src.suffix}"
    try:
        shutil.move(str(src), str(dst))
        return dst
    except Exception:  # noqa: BLE001
        return None


def save_file(wdir, name: str, data: bytes, hist_dir, stats: dict,
              *, archive: bool = True) -> str:
    """保存一个下载文件，返回 'new' | 'updated' | 'unchanged'。

    - 内容相同 → 'unchanged'（不写盘、不归档）
    - 内容不同且旧文件存在 → 归档旧文件后原子写入 → 'updated'
    - 不存在 → 原子写入 → 'new'
    """
    target = Path(wdir) / name
    digest = sha256_bytes(data)
    if target.is_file():
        if file_sha256(target) == digest:
            stats["unchanged"] = int(stats.get("unchanged", 0)) + 1
            return "unchanged"
        if archive and hist_dir is not None:
            if archive_existing(target, hist_dir) is not None:
                stats["archived"] = int(stats.get("archived", 0)) + 1
            else:
                # 归档失败时退化为直接覆盖（保证主目录仍是最新）
                try:
                    target.unlink()
                except OSError:
                    pass
        atomic_write_bytes(target, data)
        stats["updated"] = int(stats.get("updated", 0)) + 1
        return "updated"
    atomic_write_bytes(target, data)
    stats["new"] = int(stats.get("new", 0)) + 1
    return "new"


def manifest_keep_names(students: "list[dict] | None") -> set:
    """D212：manifest 里引用的全部图片文件名（用于孤儿判定）。"""
    keep: set = set()
    for st in students or []:
        if not isinstance(st, dict):
            continue
        keep.update(str(x) for x in (st.get("images") or []) if x)
        keep.update(str(x) for x in (st.get("comment_images") or []) if x)
        for one in (st.get("per_question_comment_images") or []):
            keep.update(str(x) for x in (one or []) if x)
    return keep


def cleanup_orphans(wdir, keep_names, hist_dir, stats: dict) -> list:
    """把不在 keep_names 里的本目录图片移到 `_orphans/`（不直接删）。

    只处理主目录下的**普通文件**，排除 `students.json` 与 `.history/`。
    """
    wdir = Path(wdir)
    keep = {str(x) for x in (keep_names or []) if str(x)}
    moved: list = []
    if not wdir.is_dir():
        return moved
    for p in sorted(wdir.iterdir()):
        try:
            if not p.is_file():
                continue
            if p.name in keep or p.name == MANIFEST_NAME:
                continue
            if p.name.endswith(".tmp"):
                continue
            if hist_dir is not None:
                if archive_existing(p, hist_dir, subdir=ORPHAN_DIR) is not None:
                    moved.append(p.name)
            else:
                p.unlink()
                moved.append(p.name)
        except Exception:  # noqa: BLE001
            continue
    stats["orphans"] = int(stats.get("orphans", 0)) + len(moved)
    return moved


def prune_history(wdir, *, days: int = 30) -> int:
    """清理超过 days 天的历史目录，返回删除的目录数。"""
    root = Path(wdir) / HISTORY_DIR
    if not root.is_dir():
        return 0
    cutoff = time.time() - max(0, int(days)) * 24 * 3600
    removed = 0
    for d in sorted(root.iterdir()):
        try:
            if not d.is_dir():
                continue
            if d.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
        except Exception:  # noqa: BLE001
            continue
    return removed
