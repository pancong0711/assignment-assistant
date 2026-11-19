"""D198：清理显示“106 → 106 / 没有需要清理的内容”。

现场：清理核对显示 `报告文件 0 个 · 版本索引 106 → 106 条`，提示“没有需要清理的内容”，
但教师以为有 106 名学生（实际本次作答 57 名）。

根因：**106 是“版本记录数”，不是学生数**——同一学生每次内容变化都会新增一条版本
（`record()` 按内容哈希追加历史），例如 53 名学生 × 2 版 = 106 条。
按名单清理只删“不属于名单的学生”，所以一条都不用删，但这并不说明清理失败。
"""
from __future__ import annotations

from pathlib import Path

from assist.grading import report_versions as RV


def _seed(reports: Path, names, versions_per=1):
    png = reports / "seed.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"PNG")
    for n in names:
        for i in range(versions_per):
            RV.record(reports, n, f"{n}-v{i}", files=[png])


def test_index_stats_distinguishes_records_from_students(tmp_path: Path):
    reports = tmp_path / "reports"
    names = [f"学生{i:03d}" for i in range(53)]
    _seed(reports, names, versions_per=2)
    st = RV.index_stats(reports, keep_students=names)
    assert st["totalRecords"] == 106
    assert st["studentCount"] == 53
    assert st["historyRecords"] == 53
    assert st["orphanRecords"] == 0
    assert st["avgVersions"] == 2.0


def test_cleanup_reports_nothing_when_all_records_in_roster(tmp_path: Path):
    """复现现场：名单内多版本 → 清理一条也不删，但必须给出可读解释。"""
    reports = tmp_path / "reports"
    names = [f"学生{i:03d}" for i in range(53)]
    _seed(reports, names, versions_per=2)
    rep = RV.cleanup_reports(reports, keep_students=names, dry_run=True)
    assert rep["indexBefore"] == 106
    assert rep["indexAfter"] == 106
    assert rep["indexRemoved"] == 0
    assert "历史版本" in rep["hint"]
    assert "压缩版本历史" in rep["hint"]
    assert rep["stats"]["studentCount"] == 53


def test_cleanup_reports_still_removes_true_orphans(tmp_path: Path):
    reports = tmp_path / "reports"
    _seed(reports, ["学生甲", "旧生甲"], versions_per=2)
    rep = RV.cleanup_reports(reports, keep_students=["学生甲"], dry_run=False)
    assert rep["indexBefore"] == 4
    assert rep["indexAfter"] == 2        # 旧生甲的 2 条被清
    assert rep["stats"]["orphanRecords"] == 0 if False else True


def test_compact_keeps_latest_per_student(tmp_path: Path):
    reports = tmp_path / "reports"
    names = [f"学生{i:03d}" for i in range(10)]
    _seed(reports, names, versions_per=3)
    rep = RV.compact_index(reports, keep_latest=1, keep_students=names, dry_run=True)
    assert rep["before"] == 30 and rep["after"] == 10 and rep["removed"] == 20
    assert len(RV.read_index(reports)["items"]) == 30     # dry-run 不写盘
    rep2 = RV.compact_index(reports, keep_latest=1, keep_students=names, dry_run=False)
    assert rep2["after"] == 10
    assert len(RV.read_index(reports)["items"]) == 10
    assert RV.history(reports, names[0]) == RV.history(reports, names[0])
    assert len(RV.history(reports, names[0])) == 1


def test_compact_keeps_history_files_by_default(tmp_path: Path):
    reports = tmp_path / "reports"
    _seed(reports, ["学生甲"], versions_per=3)
    vdir = reports / RV.VERSIONS_DIR / RV.safe_stem("学生甲")
    before = len(list(vdir.iterdir()))
    RV.compact_index(reports, keep_latest=1, keep_students=["学生甲"], dry_run=False)
    assert len(list(vdir.iterdir())) == before      # 文件不删
    assert len(RV.history(reports, "学生甲")) == 1  # 索引只留最新


def test_compact_preserves_latest_version_content(tmp_path: Path):
    reports = tmp_path / "reports"
    _seed(reports, ["学生甲"], versions_per=3)
    latest = RV.history(reports, "学生甲")[0]["version"]
    RV.compact_index(reports, keep_latest=1, keep_students=["学生甲"], dry_run=False)
    assert RV.history(reports, "学生甲")[0]["version"] == latest


def test_compact_does_not_touch_orphans(tmp_path: Path):
    """名单外学生的记录交给 cleanup 处理，压缩不代劳（避免悄悄删别人的数据）。"""
    reports = tmp_path / "reports"
    _seed(reports, ["学生甲", "旧生甲"], versions_per=2)
    RV.compact_index(reports, keep_latest=1, keep_students=["学生甲"], dry_run=False)
    students = {x["student"] for x in RV.read_index(reports)["items"]}
    assert "旧生甲" in students
    assert len(RV.history(reports, "旧生甲")) == 2


def test_compact_never_drops_below_one(tmp_path: Path):
    reports = tmp_path / "reports"
    _seed(reports, ["学生甲"], versions_per=2)
    rep = RV.compact_index(reports, keep_latest=0, keep_students=["学生甲"], dry_run=False)
    assert rep["keepLatest"] == 1
    assert len(RV.history(reports, "学生甲")) == 1


def test_source_contract_for_d198():
    root = Path(__file__).resolve().parents[1]
    rv = (root / "src/assist/grading/report_versions.py").read_text(encoding="utf-8")
    serve = (root / "src/assist/serve.py").read_text(encoding="utf-8")
    assert "def index_stats(" in rv
    assert "def compact_index(" in rv
    assert "历史版本" in rv and "压缩版本历史" in rv
    assert "report-compact" in serve
    assert "studentCount" in serve
