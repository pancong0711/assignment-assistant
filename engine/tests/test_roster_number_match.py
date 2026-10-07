"""B2：成绩源姓名匹配失败时按学号回退。"""

from pathlib import Path

from openpyxl import Workbook

from assist.roster.grouping import merge_scores
from assist.roster.scores import read_exam, read_flex


def test_merge_scores_falls_back_to_number():
    students = [
        {"name": "张三", "number": "2026001"},
        {"name": "李四", "number": "2026002"},
    ]
    score_rows = [
        # 姓名对不上（空格/异体），学号命中 → 回退成功
        {"name": "张 三", "number": "2026001", "score": 88.0, "weight": 1.0, "source": "exam"},
        # 姓名正常，学号也带上
        {"name": "李四", "number": "2026002", "score": 76.0, "weight": 1.0, "source": "exam"},
    ]
    out = merge_scores(students, score_rows, weight_normalize=True)
    assert out["张三"]["mean"] == 88.0
    assert out["李四"]["mean"] == 76.0


def test_read_exam_keeps_number_column(tmp_path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["学号", "姓名", "期末(必填)"])
    ws.append(["2026001", "学生A", 91])
    wb.save(tmp_path / "exam.xlsx")
    rows = read_exam(tmp_path / "exam.xlsx")
    assert rows and rows[0]["name"] == "学生A"
    assert rows[0]["number"] == "2026001"


def test_read_flex_keeps_number_column(tmp_path: Path):
    wb = Workbook()
    ws = wb.active
    ws.append(["学号", "姓名", "平时分"])
    ws.append(["2026001", "学生A", 85])
    wb.save(tmp_path / "custom.xlsx")
    rows = read_flex(tmp_path / "custom.xlsx", cols=["平时分"])
    assert rows and rows[0]["number"] == "2026001"
