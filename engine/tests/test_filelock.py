"""并发写安全：文件锁 + 原子写（AI/脚本并行调用 CLI 的核心保障）。"""
import json
import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assist.filelock import atomic_write_text, locked, update_json


def test_update_json_accumulates(tmp_path):
    p = tmp_path / "x.json"
    for _ in range(10):
        update_json(p, lambda d: d.__setitem__("n", d.get("n", 0) + 1))
    assert json.loads(p.read_text(encoding="utf-8"))["n"] == 10


def test_update_json_recovers_from_corrupt(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{ not json", encoding="utf-8")
    update_json(p, lambda d: d.__setitem__("ok", True), default={})
    assert json.loads(p.read_text(encoding="utf-8")) == {"ok": True}


def test_atomic_write_no_partial(tmp_path):
    p = tmp_path / "a.txt"
    atomic_write_text(p, "hello")
    assert p.read_text(encoding="utf-8") == "hello"
    # 目录里不应残留临时文件
    assert not [f for f in p.parent.iterdir() if f.name.endswith(".tmp")]


def test_locked_exclusive(tmp_path):
    p = tmp_path / "x.json"
    with locked(p):
        pass
    # 锁文件存在但不阻塞再次获取
    with locked(p):
        pass


def _inc_worker(path: str, n: int):
    from assist.filelock import update_json
    for _ in range(n):
        update_json(path, lambda d: d.__setitem__("n", d.get("n", 0) + 1))


def test_parallel_processes_do_not_lose_updates(tmp_path):
    """两个真实进程各自增 30 次，最终必须精确累加（丢更新=测试失败）。"""
    p = tmp_path / "counter.json"
    n = 30
    procs = [mp.Process(target=_inc_worker, args=(str(p), n)) for _ in range(4)]
    for pr in procs:
        pr.start()
    for pr in procs:
        pr.join(timeout=60)
    assert all(pr.exitcode == 0 for pr in procs)
    assert json.loads(p.read_text(encoding="utf-8"))["n"] == n * 4
