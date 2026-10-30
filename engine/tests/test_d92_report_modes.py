"""D92-R2：草稿双套 + 五模式报告拼装 + difflib 标红。"""
from pathlib import Path

from assist.grading.report import _mode_report_md, diff_mark, report_html_from_md
from assist.xxt.grade_store import normalize_draft, save_draft_sets, read_drafts


# ---------------- 草稿兼容与双套 ----------------

def test_normalize_old_single_ai(tmp_path):
    d = normalize_draft({"score": 88, "comment": "AI 批语", "images": [], "source": "ai:t1"})
    assert d["ai"]["comment"] == "AI 批语" and d["humanMode"] == "none"
    assert d["human"] == {} and d["revised"] is False


def test_normalize_old_single_human(tmp_path):
    d = normalize_draft({"score": 90, "comment": "人工", "source": "human:t1"})
    assert d["human"]["comment"] == "人工" and d["humanMode"] == "replace"
    assert d["ai"] == {}


def test_save_draft_sets_two_sets_and_revised(tmp_path):
    home = tmp_path / "xxt"
    save_draft_sets(home, "c1", "w1", "s1", ai={"score": 88, "comment": "AI 原文"})
    save_draft_sets(home, "c1", "w1", "s1", human={"score": 90, "comment": "人工批语"},
                    human_mode="revise", revision={"text": "AI 原文（改）"})
    d = read_drafts(home, "c1", "w1")["s1"]
    nd = normalize_draft(d)
    assert nd["ai"]["comment"] == "AI 原文" and nd["human"]["comment"] == "人工批语"
    assert nd["humanMode"] == "revise" and nd["revised"] is True


# ---------------- diff_mark ----------------

def test_diff_mark_marks_changed_lines():
    ai = "第一行\n第二行\n第三行"
    rev = "第一行\n第二行改了\n第三行"
    marked = diff_mark(ai, rev)
    assert "[[R]]第二行改了[[/R]]" in marked
    assert "[[R]]第一行" not in marked   # 未变行不标


def test_diff_mark_formula_atomic():
    ai = "结果为 $E=mc^2$\n结论如上"
    rev = "结果为 $E=mc^2$\n结论更新"
    marked = diff_mark(ai, rev)
    # 公式行未变 → 不标；改动的结论行标
    assert "[[R]]结论更新[[/R]]" in marked
    assert "[[R]]结果为" not in marked


# ---------------- 五模式 ----------------

def _d(ai_comment="AI 内容", human_comment="人工内容", mode="none", rev=""):
    return _mode_report_md(student="张三", ai={"score": 88, "comment": ai_comment},
                           human={"score": 90, "comment": human_comment, "used": True},
                           human_mode=mode, revision={"text": rev},
                           revised=bool(rev) and rev != ai_comment)


def test_mode_1_ai_only():
    md, kind = _d(mode="none")
    assert kind == "ai" and "# AI 批阅报告" in md and "人工批阅报告" not in md


def test_mode_2_ai_revised():
    md, kind = _d(mode="revise", rev="AI 内容（修订）")
    assert kind == "ai-revised" and "AI 批阅报告（人工修订）" in md
    assert "[[R]]AI 内容（修订）[[/R]]" in md


def test_mode_3_append_ai_first_then_human():
    """D127：append = AI 批语在前 + 人工批语在后（此前与 replace 产出相同，属缺陷）。"""
    md, kind = _d(mode="append")
    assert "# AI 批阅报告" in md and "教师补充批语" in md
    assert md.index("AI 内容") < md.index("人工内容"), "AI 批语应在人工批语之前"
    assert "人工批阅报告" not in md, "append 不是纯人工报告"


def test_mode_4_replace_is_human_only():
    """D127：replace = 人工批语**替代** AI → 纯人工报告。"""
    md, kind = _d(mode="replace")
    assert kind == "human"
    assert "# 人工批阅报告" in md and "AI 批阅报告" not in md
    assert "AI 内容" not in md, "替代模式下不应出现 AI 批语"


def test_mode_4b_append_keeps_revision_mark():
    md, kind = _d(mode="append", rev="AI 内容（修订）")
    assert "教师补充批语" in md and "[[R]]" in md


def test_mode_5_human_only():
    md, kind = _d(mode="human")
    assert kind == "human" and "# 人工批阅报告" in md and "AI 批阅报告" not in md


def test_report_html_renders_revised_span():
    md, kind = _d(mode="revise", rev="AI 内容（修订）")
    html = report_html_from_md(md, kind=kind)
    assert '<span class="revised">' in html and "</span>" in html
    assert "[[R]]" not in html   # 标记已转换
    assert "AI 批阅报告（人工修订）" in html
