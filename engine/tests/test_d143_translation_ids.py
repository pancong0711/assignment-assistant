"""D143：翻译题库题号必须唯一（此前每行都写死 id="translation"）。

症状（教师报错原文）：
    .../translation/translation/translation/...；请用 `assist kb normalize` 检查

根因：`read_translation()` 给**每一行**都写 `id="translation"`，16 道翻译题全部同号。
后果不只是告警——**答案版本库以 qid 为键**，多道翻译题的答案会写进同一个文件互相覆盖。

约定（与其它题库 `<sheet名>-<题号>` 风格一致）：`translation-01`、`translation-02`…
按**行序**生成，行序稳定 → 重读仍对得上。
"""
from __future__ import annotations

import pytest
from openpyxl import Workbook

from assist.files import kb_io as K


def _make_translation(kb, n: int):
    wb = Workbook()
    ws = wb.active
    ws.append(["原文", "作者", "书名", "年份"])
    for i in range(n):
        ws.append([f"Saying {i}", "Author", "Book", "1900"])
    wb.save(kb / "translation.xlsx")


@pytest.fixture()
def kb(tmp_path):
    d = tmp_path / "kb"
    d.mkdir()
    return d


def test_translation_ids_are_unique(kb):
    _make_translation(kb, 16)
    data = K.read_kb(kb)
    entries = data["translation"]["translation"]
    ids = [e["id"] for e in entries]
    assert len(ids) == 16
    assert len(set(ids)) == 16, f"题号仍重复：{ids[:3]}…"


def test_no_duplicate_warning(kb, caplog):
    """不应再出现"存在重复题号"告警。"""
    _make_translation(kb, 3)
    with caplog.at_level("WARNING"):
        K.read_kb(kb)
    assert "重复题号" not in caplog.text


def test_translation_id_format_matches_other_kinds(kb):
    """命名风格与其它题库一致：`<sheet名>-<两位序号>`。"""
    _make_translation(kb, 3)
    ids = [e["id"] for e in K.read_kb(kb)["translation"]["translation"]]
    assert ids == ["translation-01", "translation-02", "translation-03"]


def test_translation_ids_stable_across_reads(kb):
    """行序稳定 → 两次读取题号必须一致（否则答案会对错题）。"""
    _make_translation(kb, 5)
    a = [e["id"] for e in K.read_kb(kb)["translation"]["translation"]]
    b = [e["id"] for e in K.read_kb(kb)["translation"]["translation"]]
    assert a == b


def test_blank_rows_do_not_create_gaps_confusingly(kb):
    """空行跳过，但编号连续（不留空洞，避免教师以为丢题）。"""
    wb = Workbook()
    ws = wb.active
    ws.append(["原文", "作者", "书名", "年份"])
    ws.append(["A", "x", "b", "1900"])
    ws.append([None, None, None, None])      # 空行
    ws.append(["B", "y", "c", "1901"])
    wb.save(kb / "translation.xlsx")
    ids = [e["id"] for e in K.read_kb(kb)["translation"]["translation"]]
    assert ids == ["translation-01", "translation-02"]


def test_translation_answer_files_do_not_collide(kb, tmp_path):
    """答案版本库：不同翻译题的答案必须落到不同文件（此前会互相覆盖）。"""
    from assist.files import solutions as sol
    ws = tmp_path
    (ws / "kb").mkdir(exist_ok=True)
    a = sol.add_version(ws, "translation-01", "答案一", source="ai",
                        kb="translation", chap="translation")
    b = sol.add_version(ws, "translation-02", "答案二", source="ai",
                        kb="translation", chap="translation")
    assert a.get("ok") or b.get("ok")
    pa = sol._path(ws, "translation-01", "translation", "translation")
    pb = sol._path(ws, "translation-02", "translation", "translation")
    assert pa != pb
