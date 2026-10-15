"""D19 成绩源 family 回归：xuexitong_assignment / xuexitong_stat 解析口径 + _rows_of sheet 关键词。

与 PWA `readScoreSourceXlsx`（app/src/lib/rosterXlsx.ts detectCrostab/buildCrostabSource）同口径：
- assignment：前 8 行扫描含子串"成绩"的行（其上一行为标题行），各"成绩"列全计入取均分；
- stat：按 sheet 关键字（默认"章节测验"）匹配，第 4 行（idx 3）为表头，非 0 才计入取均分。
"""

from pathlib import Path

import pytest
from openpyxl import Workbook

from assist.roster.scores import (_rows_of, read_xuexitong_assignment,
                                  read_xuexitong_stat)


def _wb(path: Path, sheets: dict[str, list[list]]) -> Path:
    wb = Workbook()
    first = True
    for name, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet()
        ws.title = name
        first = False
        for r in rows:
            ws.append(r)
    wb.save(path)
    return path


def test_rows_of_matches_sheet_by_keyword(tmp_path: Path):
    """_rows_of 按名字关键词命中 sheet（此前对命中名 int() 会 ValueError）。"""
    f = _wb(tmp_path / "k.xlsx", {"综合成绩": [["x"]], "作业统计": [["a"], ["b"]],
                                  "章节测验统计": [["c"], ["d"], ["e"], ["f"]]})
    rows = _rows_of(f, "作业统计")
    assert len(rows) == 2
    rows2 = _rows_of(f, "章节测验")
    assert len(rows2) == 4
    # 未命中回落首表；int 直接按索引
    assert len(_rows_of(f, "不存在")) == 1
    assert len(_rows_of(f, 2)) == 4


def test_assignment_substring_marks_and_average(tmp_path: Path, caplog):
    """含"作业N成绩"子串标记行：各成绩列均分（全计入，不跳 0）。"""
    f = _wb(tmp_path / "a.xlsx", {"作业统计": [
        [], [],
        ["", "作业1", "", "作业2"],
        ["", "作业1成绩", "", "作业2成绩"],
        ["学生A", 80, "", 70],
        ["学生B", 100, "", 40],
    ]})
    out = {r["name"]: r["score"] for r in read_xuexitong_assignment(f)}
    assert out == {"学生A": 75.0, "学生B": 70.0}


def test_assignment_empty_string_cells_do_not_crash(tmp_path: Path):
    """openpyxl 空单元格为 ''：float('') 必须被吞掉（否则整表解析崩）。"""
    f = _wb(tmp_path / "b.xlsx", {"作业统计": [
        ["", "作业1", "", "作业2"],
        ["", "成绩", "", "成绩"],
        ["学生A", 90, "", ""],       # 第 4 列全空字符串
        ["学生B", "", "", 60],
    ]})
    out = {r["name"]: r["score"] for r in read_xuexitong_assignment(f)}
    assert out["学生A"] == 90.0
    assert out["学生B"] == 60.0


def test_stat_skips_zero_and_averages(tmp_path: Path):
    """stat：第 4 行表头定位"成绩"列，非 0 才计入均分。"""
    f = _wb(tmp_path / "s.xlsx", {"章节测验统计": [
        ["占位1"], ["占位2"], ["占位3"],
        ["姓名", "第1章成绩", "第2章成绩"],
        ["学生A", 20, 0],
        ["学生B", 10, 30],
    ]})
    out = {r["name"]: r["score"] for r in read_xuexitong_stat(f)}
    assert out == {"学生A": 20.0, "学生B": 20.0}


# ---- 真实 legacy 文件 parity（文件不在检出时 skip-safe） ----

_LEGACY = Path(__file__).resolve().parents[2] / "_legacy" / "2603paperDesign" / "data"


@pytest.mark.skipif(not (_LEGACY / "xxt").exists(), reason="legacy xxt 目录不在检出")
def test_legacy_real_assignment_and_stat_parse():
    import glob
    hits = sorted(glob.glob(str(_LEGACY / "xxt" / "*化工25_统计一键导出-0518.xlsx")))
    if not hits:
        pytest.skip("legacy xxt 真实文件缺失")
    f = Path(hits[0])
    a = read_xuexitong_assignment(f)
    s = read_xuexitong_stat(f)
    assert len(a) > 30 and len(s) > 30
    # 两份解析都应含同一批真实学生；assignment 值来自"作业统计"
    assert "作业统计均值" in a[0]["source"]
