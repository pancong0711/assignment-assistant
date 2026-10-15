"""D86 §3/§4：批阅任务清单（plan）装配 + 两段式提示词回归。"""

import json
from pathlib import Path

from assist.grading import inputs as I
from assist.grading import prompts as PR


def _mk_class(ws: Path, class_dir: str = "classes/chem25"):
    d = ws / class_dir / "roster"
    d.mkdir(parents=True, exist_ok=True)
    from openpyxl import Workbook
    wb = Workbook(); w = wb.active
    w.append(["姓名", "学号", "班级", "tag"])
    w.append(["学生A", "1", "化工25", "copy"])
    w.append(["学生B", "2", "化工25", "qa"])
    wb.save(d / "roster.xlsx")


def _mk_pad(ws: Path, pad_id: str, tag: str, questions):
    d = ws / "tasks"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{pad_id}.taskpad.json").write_text(json.dumps({
        "id": pad_id, "class_dir": "classes/chem25", "target_tag": tag,
        "items": [{"tag": tag, **q} for q in questions],
    }, ensure_ascii=False), encoding="utf-8")


def test_students_with_tags_and_pads(tmp_path: Path):
    _mk_class(tmp_path)
    st = I.students_with_tags(tmp_path, "classes/chem25")
    assert [(s["name"], s["tag"]) for s in st] == [("学生A", "copy"), ("学生B", "qa")]
    _mk_pad(tmp_path, "p-copy", "copy", [{"no": "1", "content": "抄写公式", "solution": ""}])
    _mk_pad(tmp_path, "p-qa", "qa", [{"no": "1", "content": "求加速度", "solution": "a=2 m/s²"}])
    pads = I.pads_by_tag(tmp_path)
    assert set(pads) == {"copy", "qa"}
    assert pads["qa"]["questions"][0]["solution"] == "a=2 m/s²"
    assert pads["copy"]["padId"] == "p-copy"


def test_build_plan_maps_tag_to_questions_and_images(tmp_path: Path, monkeypatch):
    _mk_class(tmp_path)
    _mk_pad(tmp_path, "p-copy", "copy", [{"no": "1", "content": "抄写", "solution": ""}])
    _mk_pad(tmp_path, "p-qa", "qa", [{"no": "2", "content": "求 a", "solution": "a=2"}])
    review = [{"name": "学生A", "workAnswerId": "wa1", "images": ["/tmp/a1.jpg"]},
              {"name": "学生B", "workAnswerId": "wa2", "images": ["/tmp/b1.jpg", "/tmp/b2.jpg"]}]
    plan = I.build_plan(tmp_path, task_id="t1", class_dir="classes/chem25",
                        class_id="C", work_id="W", review_students=review)
    assert plan["mode"] == "optimized" and plan["tags"] == ["copy", "qa"]
    a = next(s for s in plan["students"] if s["name"] == "学生A")
    b = next(s for s in plan["students"] if s["name"] == "学生B")
    assert a["workAnswerId"] == "wa1" and a["questions"][0]["content"] == "抄写"
    assert b["questions"][0]["solution"] == "a=2" and len(b["images"]) == 2
    # tag 过滤
    only_copy = I.build_plan(tmp_path, task_id="t1", class_dir="classes/chem25",
                             tags=["copy"], review_students=review)
    assert [s["name"] for s in only_copy["students"]] == ["学生A"]


def test_plan_save_load_and_summary(tmp_path: Path):
    _mk_class(tmp_path)
    plan = I.build_plan(tmp_path, task_id="t9", class_dir="classes/chem25",
                        review_students=[{"name": "学生A", "images": []}])
    p = I.save_plan(tmp_path, "classes/chem25", plan)
    assert p.is_file() and p.name == "plan.json"
    back = I.load_plan(tmp_path, "t9", "classes/chem25")
    assert back["taskId"] == "t9"
    summ = I.plan_summary(back)
    assert summ["students"] == 2 and "学生B" in summ["noImages"]


def test_explicit_pads_override_and_review_extra_student(tmp_path: Path):
    _mk_class(tmp_path)
    plan = I.build_plan(tmp_path, task_id="t2", class_dir="classes/chem25",
                        explicit_pads={"qa": {"id": "x", "items": [{"no": 1, "content": "Q"}]}},
                        review_students=[{"name": "学生A", "images": ["/a.jpg"]},
                                         {"name": "临时学生", "images": ["/t.jpg"]}])
    names = [s["name"] for s in plan["students"]]
    assert "临时学生" in names                       # 下载里有、名单里没有 → 补进来
    qa = next(s for s in plan["students"] if s["name"] == "学生B")
    assert qa["questions"][0]["content"] == "Q"      # explicit pads 生效


# ---------------- 提示词 ----------------

def test_tag_instruction_and_evaluate_prompt():
    assert "抄写" in PR.tag_instruction("copyonly")
    assert PR.tag_instruction("copysp") == PR.tag_instruction("copy")
    assert PR.tag_instruction("unknown") == ""
    p = PR.build_evaluate_prompt(questions=[{"no": 1, "content": "求 a", "solution": "a=2"}],
                                 markdown_text="学生：a=3", tag="qa")
    assert "求 a" in p and "a=2" in p and "学生：a=3" in p


def test_bruteforce_prompt_mentions_consistency_and_self_solve():
    p = PR.build_bruteforce_prompt(questions=[], markdown_text="作答", has_sheet_images=True)
    assert "姓名" in p and "题号" in p
    p2 = PR.build_bruteforce_prompt(questions=[], markdown_text="作答")
    assert "自行给出每题的正确解法" in p2


def test_consistency_prompt_shape():
    p = PR.build_consistency_prompt(questions=[{"no": 1, "content": "Q"}], student_name="学生A",
                                    markdown_text="x" * 3000)
    assert "question_match" in p and "name_match" in p
    assert len(p) < 4000                                # 作答片段截断


# ---------------- §5 报告（HTML 版式；PNG 需浏览器，CI 跳过） ----------------

def test_report_html_has_a4_css_kind_label_and_katex():
    from assist.grading.report import report_html, find_katex_dir
    h = report_html("## 小结\n公式 $a^2+b^2=c^2$\n", kind="human",
                    title="学生A 批阅报告", subtitle="classes/chem25")
    assert "210mm" in h or "width: 100%" in h            # A4 版式
    assert "12pt" in h                                   # 小四
    assert "人工批阅报告" in h and "report-tag human" in h
    assert "katex" in h.lower()
    assert find_katex_dir() is not None or "jsdelivr" in h   # 本地优先，CDN 兜底


def test_report_kind_labels_differ_only_by_label():
    from assist.grading.report import report_html
    ai = report_html("x", kind="ai")
    human = report_html("x", kind="human")
    assert "AI 批阅报告" in ai and "人工批阅报告" not in ai
    assert "人工批阅报告" in human and "AI 批阅报告" not in human
