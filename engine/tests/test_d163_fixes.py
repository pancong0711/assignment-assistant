"""D163：课堂资料页可用性 + 翻译题题号不换行。

1. 课堂资料页此前**没有新建入口**——空 workspace 时页面几乎空白，
   只能手工建 `materials/<名>/_source/` 目录；
2. translation 题的 content 以 `\\n` 开头 → 渲染成「2.」后另起一行，
   与其它题型（题号与题目同行）不一致。
"""
from __future__ import annotations

import pytest
from openpyxl import Workbook

from assist.files import materials as M
from assist.files import kb_io as K


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


# ---------------- 课堂资料：新建特征名 ----------------
def test_empty_workspace_has_no_chaps(ws):
    """空 workspace 没有任何资料目录（所以页面是空的）。"""
    assert M.list_chaps(ws) == []


def test_ensure_chap_creates_and_lists(ws):
    """新建特征名后能被列出（页面才有内容可选）。"""
    M.ensure_chap(ws, "26C1")
    assert "26C1" in M.list_chaps(ws)


def test_manual_dir_without_source_not_listed(ws):
    """手建目录但没 `_source/` 不会被列出——这是"看不到"的一个原因。"""
    (ws / "materials" / "26C1").mkdir(parents=True)
    assert M.list_chaps(ws) == []
    M.ensure_chap(ws, "26C1")
    assert M.list_chaps(ws) == ["26C1"]


def test_illegal_feature_name_rejected(ws):
    with pytest.raises(M.MaterialsError):
        M.ensure_chap(ws, "../evil")


# ---------------- 翻译题：题号与正文同行 ----------------
def test_translation_content_does_not_start_with_newline(ws):
    wb = Workbook(); sh = wb.active
    sh.append(["原文", "作者", "书名", "年份"])
    sh.append(["To be or not to be", "Shakespeare", "Hamlet", "1600"])
    wb.save(ws / "kb" / "translation.xlsx")
    e = K.read_kb(ws / "kb")["translation"]["translation"][0]
    assert not e["content"].startswith("\n"), "content 不应以换行开头"
    first = e["content"].split("\n")[0]
    assert first.startswith("请翻译以下内容："), first
    # 与其它题型一致：题号 + 题目在同一行
    assert "To be or not to be" in first


def test_translation_content_still_has_second_line(ws):
    """「并回答」部分仍在第二行（保留原有结构）。"""
    wb = Workbook(); sh = wb.active
    sh.append(["原文", "作者", "书名", "年份"])
    sh.append(["X", "A", "B", "1900"])
    wb.save(ws / "kb" / "translation.xlsx")
    e = K.read_kb(ws / "kb")["translation"]["translation"][0]
    assert "并回答" in e["content"]
    assert len(e["content"].split("\n")) >= 2
