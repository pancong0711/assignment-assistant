"""D170：实际使用中的一批缺陷（第 17 轮反馈）。

批次 A（P0）：
  T1 带间隔号的姓名无法批阅（民族姓名「阿丽古丽·玉苏甫」）
  T2 重载题库卡死（前端，见 selfcheck）
  T3 AI 作答写回的知识点必须真的进 xlsx
"""
from __future__ import annotations

from pathlib import Path

import pytest

from assist.grading.items import ItemsError, _clean_id


# ---------------- T1：id 白名单要接受姓名里的间隔号 ----------------

@pytest.mark.parametrize("name", [
    "阿丽古丽·玉苏甫",      # 维吾尔族姓名（回访反馈的真实案例）
    "阿·谢·普希金",         # 俄式姓名
    "张三",                 # 普通中文
    "chap04-c1",            # 题库题号
    "张三（组长）",          # 全角括号
    "A•B",                  # U+2022 项目符号
    "A・B",                 # U+30FB 片假名中点
    "李四.1",               # 点（历史用法）
])
def test_names_with_separators_accepted(name):
    """**回归**：含间隔号的姓名曾导致整份名单批阅失败。"""
    assert _clean_id(name, 0) == name


@pytest.mark.parametrize("bad", ["a/b", "a\\b", "a:b", "a*b", "a?b", "a|b", 'a"b'])
def test_path_separators_still_rejected(bad):
    """真危险字符仍必须拒绝（会破坏文件名）。"""
    with pytest.raises(ItemsError):
        _clean_id(bad, 0)


def test_error_message_is_actionable_for_bad_char():
    """报错必须指出**具体哪个字符**、为什么不行（否则教师不知道改什么）。"""
    with pytest.raises(ItemsError) as ei:
        _clean_id("a/b", 2)
    msg = str(ei.value)
    assert "第 3 条" in msg
    assert "/" in msg
    assert "文件名" in msg


def test_error_message_for_too_long():
    with pytest.raises(ItemsError) as ei:
        _clean_id("x" * 81, 0)
    assert "过长" in str(ei.value)


def test_real_batch_with_minority_name_passes():
    """整份 items 里有民族姓名时，normalize_items 应通过。"""
    from assist.grading.items import normalize_items
    out = normalize_items([
        {"id": "阿丽古丽·玉苏甫", "images": []},
        {"id": "张三", "images": []},
    ])
    assert [x["id"] for x in out] == ["阿丽古丽·玉苏甫", "张三"]


# ---------------- T3：AI 作答写回的知识点必须真的进 xlsx ----------------

def test_tag_knowledge_writes_related_into_xlsx(tmp_path: Path):
    """教师反馈「已勾选同时标注知识点并成功写回，但在编辑器看不到」。

    T2（前端卡死）是主因；这里从**后端**锁定：写回后 xlsx 的 `related` 必须真的变了。
    """
    from assist.files import kb_io
    from assist.grading import rubric as RB

    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    kb_io.write_chapters_preserving(kb_dir / "qa.xlsx", {"chap01": [
        {"id": "c1", "content": "题", "related": "", "solution": ""}]})
    rep = RB.apply_related(tmp_path, [{
        "kb": "qa", "chap": "chap01", "qid": "chap01-c1",
        "related": "库仑定律,电场强度",
        "meta": {"source": "ai", "ai_suggested": "库仑定律,电场强度"},
    }])
    assert rep["ok"] and rep["written"] == 1
    row = kb_io.read_xlsx(kb_dir / "qa.xlsx", kb_dir)["chap01"][0]
    assert "库仑定律" in row["related"], f"related 未写回：{row}"
    # 版本库也应有记录（D166）
    got = RB.get_related(tmp_path, kb="qa", chap="chap01", qid="chap01-c1")
    assert got["versions"], "写回应留下版本记录"


def test_kb_full_returns_related(tmp_path: Path):
    """PWA 重载用的是 /kb/full；它必须带回 related 字段。"""
    from assist.files import kb_io
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    kb_io.write_chapters_preserving(kb_dir / "qa.xlsx", {"chap01": [
        {"id": "c1", "content": "题", "related": "库仑定律", "solution": ""}]})
    data = kb_io.read_kb(kb_dir)
    assert data["qa"]["chap01"][0]["related"] == "库仑定律"


# ---------------- T5：发布重复判定必须按班级过滤 ----------------

def test_published_ids_filters_by_class(monkeypatch):
    """**核心**：平台返回全课程列表时，只保留属于目标班的条目。

    教师实测：目标班从未发布过，但提示"已发布"——因为平台列表页只按 courseid
    过滤，我们此前直接取 workLibraryId 集合，等于把**别的班**的发布也算进来了。
    """
    import assist.xxt.work as W

    fake_items = [
        {"workLibraryId": "lib1", "classId": "999"},   # 别的班
        {"workLibraryId": "lib2", "classId": "101"},   # 目标班
    ]
    monkeypatch.setattr(W, "list_class_works",
                        lambda *a, **kw: {"ok": True, "items": fake_items})
    got = W.published_library_ids("/tmp/x", "course1", "101")
    assert got == {"lib2"}, f"应只保留目标班条目，实际 {got}"


def test_published_ids_keeps_all_when_no_class_field(monkeypatch):
    """平台没给 classId → 无法逐班判定，保持原样（调用方须说明）。"""
    import assist.xxt.work as W
    fake = [{"workLibraryId": "lib1"}, {"workLibraryId": "lib2"}]
    monkeypatch.setattr(W, "list_class_works",
                        lambda *a, **kw: {"ok": True, "items": fake})
    assert W.published_library_ids("/tmp/x", "c1", "101") == {"lib1", "lib2"}


def test_published_ids_strict_false_keeps_all(monkeypatch):
    import assist.xxt.work as W
    fake = [{"workLibraryId": "lib1", "classId": "999"}]
    monkeypatch.setattr(W, "list_class_works",
                        lambda *a, **kw: {"ok": True, "items": fake})
    assert W.published_library_ids("/tmp/x", "c1", "101", strict=False) == {"lib1"}


# ---------------- T6：课堂资料抽取的错误必须能透出 ----------------

def test_extract_error_is_readable_for_missing_sources(tmp_path: Path):
    """没有原件时，错误信息要**具体可操作**（而不是只给 HTTP 400）。"""
    from assist.files import materials as M

    (tmp_path / "materials" / "26C1" / "_source").mkdir(parents=True)
    try:
        rep = M.extract_chap(tmp_path, "26C1")
    except M.MaterialsError as exc:
        assert "26C1" in str(exc) or "原件" in str(exc)
    else:
        # 没有原件时不应崩；应返回可读的 0 结果（不抛）
        assert rep["sources"] == 0


# ---------------- T9b：抄写题字段必须可在规则卡调整 ----------------

def test_copy_rule_fields_are_editable(tmp_path: Path):
    """教师要在界面上调「字数下限」——字段必须在 _NUM_RANGES 里，否则改不了。"""
    from assist.grading import rules as R

    for key in ("minChars", "topicMismatchDeduct"):
        assert key in R._NUM_RANGES, f"{key} 缺范围定义 → 规则卡改不了"

    data = R.read_rules(tmp_path)
    data["types"]["copy"]["minChars"] = 120
    assert R.write_rules(tmp_path, data)["ok"]
    assert R.type_rules(tmp_path, "copy")["minChars"] == 120


def test_copy_rule_rejects_out_of_range(tmp_path: Path):
    from assist.grading import rules as R
    data = R.read_rules(tmp_path)
    data["types"]["copy"]["minChars"] = 99999
    r = R.write_rules(tmp_path, data)
    assert r["ok"] is False and "minChars" in str(r.get("error") or "")


# ---------------- 修订版：必须能进报告（否则"保存后看不到"） ----------------

def test_revision_shows_up_in_report():
    """D170-T10：另存修订版后，**导出报告**应带「人工修订」标注并按行标红。"""
    from assist.grading.report import _mode_report_md

    md, kind = _mode_report_md(
        student="张三",
        ai={"score": 80, "comment": "第一行\n第二行"},
        human={}, human_mode="none",
        revision={"text": "第一行\n第二行（教师补充）"}, revised=True)
    assert kind == "ai-revised", f"报告应标为人工修订版，实际 {kind}"
    assert "人工修订" in md
    assert "教师补充" in md
    assert "[[R]]" in md or "revised" in md, "改动行应有标红标记"


def test_no_revision_reports_plain_ai():
    from assist.grading.report import _mode_report_md
    md, kind = _mode_report_md(student="张三", ai={"score": 80, "comment": "原文"},
                               human={}, human_mode="none", revision={}, revised=False)
    assert kind == "ai"
    assert "人工修订" not in md


def test_revision_survives_grade_store_roundtrip(tmp_path: Path):
    """修订版要真的存进草稿库并能读回（否则关掉页面就丢了）。"""
    from assist.xxt import grade_store as G

    G.save_draft_sets(tmp_path, "c1", "w1", "张三",
                      human_mode="none", revision={"text": "修订后的批语"})
    got = G.read_drafts_normalized(tmp_path, "c1", "w1")
    d = got.get("张三") or {}
    assert (d.get("revision") or {}).get("text") == "修订后的批语"
    assert d.get("revised") is True
