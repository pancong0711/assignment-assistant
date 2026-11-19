"""D197：清理报告后版本索引仍显示旧记录（106 条 vs 本次 57 名）。

现场：点「🧹 清理多余报告」有弹窗，但「报告版本」仍是 106 条，
而本次作业实际只有 57 名作答学生。

根因：
1. `cleanup_reports()` 只删 reports/ 下的文件和 `.versions/<学生>/` 目录，
   **从不清理 `.versions/index.json`** → 版本列表长期保留历史批次记录；
2. `keep_students` 为空时旧实现静默什么都不删（`if keep and ...`），
   教师以为清理了，其实没动。
"""
from __future__ import annotations

import json
from pathlib import Path

from assist.grading import report_versions as RV


def _seed(reports: Path, students, versions_per=1):
    png = reports / "seed.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"PNG")
    for s in students:
        for i in range(versions_per):
            RV.record(reports, s, f"{s}-v{i}", kind="ai", score=80 + i, files=[png])


def test_cleanup_prunes_index_records_outside_roster(tmp_path: Path):
    """核心回归：清理后索引条数必须等于名单内记录数，而不是一直 106 条。"""
    reports = tmp_path / "reports"
    keep = [f"学生{i:03d}" for i in range(57)]
    old = [f"旧生{i:03d}" for i in range(49)]
    _seed(reports, keep + old)
    assert len(RV.read_index(reports)["items"]) == 106

    rep = RV.cleanup_reports(reports, keep_students=keep, dry_run=False)
    assert rep["ok"] is True
    assert rep["indexBefore"] == 106
    assert rep["indexAfter"] == 57
    assert rep["indexRemoved"] == 49
    assert len(RV.read_index(reports)["items"]) == 57
    # 名单内学生记录保留
    names = {x["student"] for x in RV.read_index(reports)["items"]}
    assert names == set(keep)


def test_dry_run_does_not_touch_index_or_files(tmp_path: Path):
    reports = tmp_path / "reports"
    _seed(reports, ["学生甲", "学生乙"])
    (reports / "旧生甲.md").write_text("x", encoding="utf-8")
    rep = RV.cleanup_reports(reports, keep_students=["学生甲"], dry_run=True)
    assert rep["dryRun"] is True
    assert rep["indexAfter"] == 1          # 预告：只剩名单内 1 条
    assert len(RV.read_index(reports)["items"]) == 2   # 但实际未改
    assert (reports / "旧生甲.md").is_file()


def test_cleanup_refuses_empty_roster(tmp_path: Path):
    """空名单必须拒绝（否则会把全部报告当“多余”删掉）。"""
    reports = tmp_path / "reports"
    _seed(reports, ["学生甲"])
    rep = RV.cleanup_reports(reports, keep_students=[], dry_run=False)
    assert rep["ok"] is False
    assert "keep_students" in rep["error"]
    assert len(RV.read_index(reports)["items"]) == 1


def test_prune_index_drops_missing_files(tmp_path: Path):
    """孤儿条目：历史文件已不存在 → 索引也要清掉。"""
    reports = tmp_path / "reports"
    _seed(reports, ["学生甲", "学生乙"])
    vdir = reports / RV.VERSIONS_DIR / RV.safe_stem("学生乙")
    for f in vdir.iterdir():
        f.unlink()
    rep = RV.prune_index(reports, keep_students=["学生甲", "学生乙"],
                         drop_missing_files=True)
    assert rep["count"] == 1
    assert [x["student"] for x in RV.read_index(reports)["items"]] == ["学生甲"]


def test_prune_index_keeps_roster_records(tmp_path: Path):
    reports = tmp_path / "reports"
    _seed(reports, ["学生甲"], versions_per=3)
    rep = RV.prune_index(reports, keep_students=["学生甲"])
    assert rep["count"] == 0
    assert len(RV.read_index(reports)["items"]) == 3


def test_cleanup_removes_version_dirs_outside_roster(tmp_path: Path):
    reports = tmp_path / "reports"
    _seed(reports, ["学生甲", "旧生甲"])
    root = reports / RV.VERSIONS_DIR
    assert (root / RV.safe_stem("旧生甲")).is_dir()
    RV.cleanup_reports(reports, keep_students=["学生甲"], dry_run=False)
    assert not (root / RV.safe_stem("旧生甲")).exists()
    assert (root / RV.safe_stem("学生甲")).is_dir()


def test_cleanup_missing_dir_is_safe(tmp_path: Path):
    rep = RV.cleanup_reports(tmp_path / "nope", keep_students=["学生甲"], dry_run=False)
    assert rep["ok"] is True and rep["count"] == 0


def test_cleanup_preserves_class_level_reports(tmp_path: Path):
    """班级级汇总产物（_teacher_report / _global_report）不是学生报告，必须保留。"""
    reports = tmp_path / "reports"
    _seed(reports, ["学生甲", "旧生甲"])
    for stu in ("学生甲", "旧生甲"):
        (reports / f"{stu}.md").write_text(f"{stu} 报告", encoding="utf-8")
        (reports / f"{stu}.png").write_bytes(b"PNG")
    (reports / "_teacher_report.md").write_text("教师报告", encoding="utf-8")
    (reports / "_teacher_report.png").write_bytes(b"PNG")
    (reports / "_global_report.md").write_text("全班报告", encoding="utf-8")
    rep = RV.cleanup_reports(reports, keep_students=["学生甲"], dry_run=False)
    names = {x["name"] for x in rep["removed"]}
    assert "旧生甲.md" in names and "旧生甲.png" in names
    assert (reports / "_teacher_report.md").is_file()
    assert (reports / "_teacher_report.png").is_file()
    assert (reports / "_global_report.md").is_file()
    assert (reports / "学生甲.md").is_file()
    assert not (reports / "旧生甲.md").exists()


def test_source_contract_for_d197():
    root = Path(__file__).resolve().parents[1]
    rv = (root / "src/assist/grading/report_versions.py").read_text(encoding="utf-8")
    serve = (root / "src/assist/serve.py").read_text(encoding="utf-8")
    assert "def prune_index(" in rv
    assert "def cleanup_reports(" in rv
    assert "indexRemoved" in rv
    assert "缺少本次名单" in rv
    # 版本查询支持按名单过滤并报告孤儿数
    assert "orphanCount" in serve
    assert "totalInIndex" in serve
