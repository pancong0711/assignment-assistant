"""跨平台文件锁 + 原子写（无第三方依赖）。

动机（AI/脚本并行调用 CLI 场景）：多处配置/草稿是「读 JSON → 改 → 整文件写回」
（`grade_store` / `solutions` / `packs` / `works` / `work` 发布索引）。两个 CLI 进程
同时做这事会**丢更新**（后写覆盖先写的改动），崩溃时还可能留下半截 JSON。

- `locked(path)`：对 `<path>.lock` 加排他锁（POSIX fcntl / Windows msvcrt）；阻塞等待。
- `atomic_write_text(path, text)`：写临时文件 + `os.replace` 原子替换，避免半截文件。
- `update_json(path, mutator, default=...)`：加锁 + 读 + 改 + 原子写，一步到位。

注意：锁粒度是「同一文件」，不做全局锁；journal 这类**纯追加**的行式文件不在此范围
（单行 `write()` 在 POSIX/Windows 上对 O_APPEND 小写入通常原子，保持原状即可）。
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    try:
        import msvcrt
    except ImportError:  # pragma: no cover
        msvcrt = None


@contextlib.contextmanager
def locked(path: "str | Path", *, timeout_s: float = 30.0):
    """对 `<path>.lock` 加排他锁。拿不到锁会抛 TimeoutError（不无限挂起）。"""
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+")
    try:
        if fcntl is not None:
            _acquire_posix(fh, timeout_s)
        elif msvcrt is not None:  # pragma: no cover - Windows
            _acquire_windows(fh, timeout_s)
        else:  # pragma: no cover - 极端环境：退化为无锁
            pass
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            fh.close()


def _acquire_posix(fh, timeout_s: float) -> None:
    import time
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"获取文件锁超时（{timeout_s}s）：{fh.name}")
            time.sleep(0.05)


def _acquire_windows(fh, timeout_s: float) -> None:  # pragma: no cover - Windows
    import time
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while True:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"获取文件锁超时（{timeout_s}s）：{fh.name}")
            time.sleep(0.05)


def atomic_write_text(path: "str | Path", text: str, *, encoding: str = "utf-8") -> Path:
    """原子写文本：同目录临时文件 + os.replace（崩溃不会留下半截目标文件）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def update_json(path: "str | Path", mutator, *, default=None) -> dict:
    """加锁读-改-写 JSON：`mutator(data)` 原地修改 `data`，返回值被忽略。

    - 文件不存在/损坏 → 用 `default`（缺省 `{}`）；
    - 有锁 + 原子写 → 并发调用不丢更新、崩溃不留半截。
    """
    p = Path(path)
    with locked(p):
        data = default if default is not None else {}
        if p.is_file():
            try:
                loaded = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:  # noqa: BLE001
                data = default if default is not None else {}
        mutator(data)
        atomic_write_text(p, json.dumps(data, ensure_ascii=False, indent=1))
    return data
