"""D212：作业预览重复下载——覆盖 + 历史归档 + 内容哈希去重 + 孤儿清理。

需求：主目录只保留最新一份；旧版进 `.history/`；内容未变不写盘；按 manifest 清孤儿。
"""
from __future__ import annotations

import json
from pathlib import Path

from assist.xxt import review_history as RH


def _write(p: Path, data: bytes):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


# ---------------- 1) 覆盖 + 归档 ----------------

def test_new_then_unchanged_then_updated(tmp_path: Path):
    wdir = tmp_path / "work"
    stats = {"new": 0, "updated": 0, "unchanged": 0, "archived": 0, "orphans": 0}
    hist = RH.new_history_dir(wdir, "20260101-000000")

    assert RH.save_file(wdir, "p01.jpg", b"A", hist, stats) == "new"
    assert stats == {"new": 1, "updated": 0, "unchanged": 0, "archived": 0, "orphans": 0}

    # 同内容 → 不写盘、不归档
    assert RH.save_file(wdir, "p01.jpg", b"A", hist, stats) == "unchanged"
    assert stats["unchanged"] == 1 and stats["archived"] == 0

    # 内容变化 → 旧文件归档，主目录为新内容
    assert RH.save_file(wdir, "p01.jpg", b"B", hist, stats) == "updated"
    assert (wdir / "p01.jpg").read_bytes() == b"B"
    assert stats["updated"] == 1 and stats["archived"] == 1
    archived = list((wdir/".history"/"20260101-000000").glob("p01*.jpg"))
    assert archived and archived[0].read_bytes() == b"A"


def test_atomic_write_leaves_no_tmp(tmp_path: Path):
    target = tmp_path / "a.jpg"
    RH.atomic_write_bytes(target, b"XYZ")
    assert target.read_bytes() == b"XYZ"
    assert not list(tmp_path.glob("*.tmp"))


def test_history_dir_unique_per_run(tmp_path: Path):
    wdir = tmp_path / "w"
    d1 = RH.new_history_dir(wdir, "20260101-000000")
    d2 = RH.new_history_dir(wdir, "20260101-000000")
    assert d1 != d2 and d1.is_dir() and d2.is_dir()


# ---------------- 2) 孤儿清理 ----------------

def test_cleanup_orphans_moves_unreferenced_files(tmp_path: Path):
    wdir = tmp_path / "w"
    _write(wdir/"keep_p01.jpg", b"A")
    _write(wdir/"stale_p03.jpg", b"B")
    (wdir/"students.json").write_text("{}", encoding="utf-8")
    stats = {"new": 0, "updated": 0, "unchanged": 0, "archived": 0, "orphans": 0}
    hist = RH.new_history_dir(wdir, "20260101-000000")
    moved = RH.cleanup_orphans(wdir, {"keep_p01.jpg"}, hist, stats)
    assert moved == ["stale_p03.jpg"]
    assert (wdir/"keep_p01.jpg").is_file()
    assert (wdir/"students.json").is_file()          # manifest 不动
    assert not (wdir/"stale_p03.jpg").exists()
    assert (hist/"_orphans"/"stale_p03.jpg").is_file()
    assert stats["orphans"] == 1


def test_cleanup_orphans_ignores_subdirs(tmp_path: Path):
    wdir = tmp_path / "w"
    (wdir/".history").mkdir(parents=True)
    _write(wdir/"keep.jpg", b"A")
    stats = {"orphans": 0}
    hist = RH.new_history_dir(wdir, "20260101-000000")
    moved = RH.cleanup_orphans(wdir, {"keep.jpg"}, hist, stats)
    assert moved == []
    assert (wdir/".history").is_dir()


# ---------------- 3) 历史清理 ----------------

def test_prune_history_removes_old_dirs(tmp_path: Path):
    import os, time
    wdir = tmp_path / "w"
    old = wdir/".history"/"20200101-000000"
    _write(old/"x.jpg", b"A")
    past = time.time() - 90*24*3600
    os.utime(old, (past, past))
    fresh = RH.new_history_dir(wdir, "20990101-000000")
    assert RH.prune_history(wdir, days=30) == 1
    assert not old.exists() and fresh.exists()


# ---------------- 4) 源码契约 ----------------

def test_review_download_supports_update_mode():
    root = Path(__file__).resolve().parents[1]
    src = (root / "src/assist/xxt/review_download.py").read_text(encoding="utf-8")
    assert '"update"' in src or "'update'" in src
    assert "RH.save_file(" in src
    assert "cleanup_orphans(" in src
    assert '"stats": stats' in src
    assert "orphans" in src
    cli = (root / "src/assist/xxt/cli.py").read_text(encoding="utf-8")
    assert 'default="update"' in cli
    assert '"update", "comments-only"' in cli


def test_missing_mode_still_skips_existing(tmp_path: Path):
    """missing 模式行为不变：已存在则跳过（不归档、不清孤儿）。"""
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/review_download.py").read_text(
        encoding="utf-8")
    assert "if not force and (wdir / fn_probe).is_file():" in src
    assert 'if mode in ("update", "full"):' in src


def test_manifest_keep_names_collects_all_image_kinds():
    students = [
        {"images": ["a_p01.jpg"], "comment_images": ["c_p01.jpg"],
         "per_question_comment_images": [["q1_p01.jpg"], ["q2_p01.jpg"]]},
        {"images": ["b_p01.jpg"]},
        {"images": None},
    ]
    keep = RH.manifest_keep_names(students)
    assert keep == {"a_p01.jpg", "c_p01.jpg", "q1_p01.jpg", "q2_p01.jpg", "b_p01.jpg"}


def test_history_dir_is_lazy_when_nothing_changes(tmp_path: Path):
    """内容全未变时不应创建 .history 目录（避免每次下载留空目录）。"""
    wdir = tmp_path / "w"
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return RH.new_history_dir(wdir, f"20260101-00000{calls['n']}")

    stats = {"new": 0, "updated": 0, "unchanged": 0, "archived": 0, "orphans": 0}
    RH.save_file(wdir, "p01.jpg", b"A", factory, stats)   # 首次：无旧文件，不需历史
    RH.save_file(wdir, "p01.jpg", b"A", factory, stats)   # 第二次：内容相同
    assert calls["n"] == 0
    assert not (wdir/".history").exists()

    RH.save_file(wdir, "p01.jpg", b"B", factory, stats)   # 内容变化 → 才创建
    assert calls["n"] == 1
    assert (wdir/".history").is_dir()
