"""D47 三段式表头定位（引擎侧补齐）：成绩统计表首行是标题行时仍能解析。

真实现象（docs/12 遗留项）：教务/自建「成绩统计」表首行是大标题
（如 "化工252班成绩统计"），表头在第 2~3 行；旧实现把首行当表头 →
找不到「期末」列、回退也取不到 → 返回空。PWA rosterXlsx.locateHeader 早已是
三段式，本次给引擎 read_exam / read_flex 补齐同口径。
"""

from pathlib import Path

import pytest
from openpyxl import Workbook

from assist.roster.scores import read_exam, read_flex

REPO = Path(__file__).resolve().parents[2]
LEGACY = REPO / "_legacy" / "2603paperDesign" / "data" / "custom"


def _wb_with(rows, tmp_path: Path, name: str = "s.xlsx") -> Path:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    p = tmp_path / name
    wb.save(p)
    return p


def test_read_exam_locates_header_after_title_rows(tmp_path: Path):
    p = _wb_with([
        ["化工252班成绩统计", "", "", ""],   # 标题行
        ["", "", "", ""],                     # 空行
        ["学号", "姓名", "期末", "平时"],
        ["2026001", "学生A", 91, 80],
        ["2026002", "学生B", 77, 70],
    ], tmp_path, "exam-offset.xlsx")
    rows = read_exam(p)
    assert [r["name"] for r in rows] == ["学生A", "学生B"]
    assert [r["score"] for r in rows] == [91.0, 77.0]
    assert rows[0]["number"] == "2026001"


def test_read_exam_prefers_row_containing_target_column(tmp_path: Path):
    # 前面有一行含"姓名"但其实是说明行（无数据校验），真正的表头在后面
    p = _wb_with([
        ["姓名", "说明"],
        ["", ""],
        ["学号", "姓名", "期末成绩"],
        ["2026001", "学生A", 88],
    ], tmp_path, "exam-tricky.xlsx")
    rows = read_exam(p)
    assert rows and rows[0]["name"] == "学生A" and rows[0]["score"] == 88.0


def test_read_flex_locates_header_after_title_rows(tmp_path: Path):
    p = _wb_with([
        ["化工251成绩统计", "", "", ""],
        ["", "", "", ""],
        ["姓名", "语文", "数学", "高数"],
        ["柏佳慧", 110, 108, 51],
    ], tmp_path, "flex-offset.xlsx")
    rows = read_flex(p, cols=["高数"])
    assert rows and rows[0]["name"] == "柏佳慧" and rows[0]["score"] == 51.0


@pytest.mark.skipif(not (LEGACY / "化工251-成绩统计.xlsx").exists(),
                    reason="legacy fixture 不在当前检出（CI 无 _legacy）")
def test_read_flex_real_legacy_title_row_files():
    rows = read_flex(LEGACY / "化工251-成绩统计.xlsx", cols=["高数"])
    assert len(rows) >= 30
    assert rows[0]["name"] == "柏佳慧" and rows[0]["score"] == 51.0
    rows2 = read_flex(LEGACY / "化工252班成绩统计.xlsx", cols=["高数(卷面分)"])
    assert rows2 and rows2[0]["name"] == "杨佳佳" and rows2[0]["score"] == 63.0
