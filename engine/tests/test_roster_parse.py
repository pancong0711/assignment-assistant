"""D46-1 回归：教务点名册两级回退解析（zjxu 名册形态，PWA readRosterXlsx 同语义哨兵）。"""

from pathlib import Path

from openpyxl import Workbook

from assist.files.roster import read_roster


def _write(path: Path, rows: list[list]) -> Path:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def test_roster_standard_header(tmp_path):
    """① 主路径：标准表头。"""
    fn = _write(tmp_path / "r1.xlsx", [
        ["姓名", "学号", "班级"],
        ["学生A", "2026xxxx01", "classA"],
        ["学生B", "2026xxxx02", "classB"],
    ])
    students = read_roster(fn)
    assert len(students) == 2 and students[0]["name"] == "学生A"


def test_roster_zjxu_preface_rows(tmp_path):
    """② 回退：前 8 行说明文字 + 第 9 行表头（旧 _legacy iloc[8:-3] 场景）。"""
    rows = [["浙江 Xu 大学教学管理系统名册导出"]] + [[""] * 7 for _ in range(7)]
    rows += [["学号", "课程", "姓名", "备注", "班级"],
             ["2026xxxx01", "大学物理", "学生A", "", "classA"],
             ["2026xxxx02", "大学物理", "学生B", "", "classB"]]
    fn = _write(tmp_path / "r2.xlsx", rows)
    students = read_roster(fn)
    assert len(students) == 2
    names = {s["name"] for s in students}
    assert names == {"学生A", "学生B"}
    assert students[0].get("number") == "2026xxxx01"


def test_roster_no_name_column(tmp_path):
    """③ 两级均失败 → 空列表（CLI warning，不抛异常）。"""
    fn = _write(tmp_path / "r3.xlsx", [["aaa", "bbb"], ["1", "2"]])
    assert read_roster(fn) == []
