"""D168-B4：Atopia 一键解析（工步 0 抽取 → 工步 1 AI 结构化）。

教师需求（docs/113-D169 §3.1）：
> 是否需要一键功能……这可以做成一个模板提示词也行，就是让大模型完成一个工作流，
> 但是针对具体文档（甚至可能有新文档扩展），可能太细不易实现。

设计：**两段式**（工步 0 确定性抽取免费 + 工步 1 AI 结构化），**不做工作流编排**。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from assist.atopia import work as W
from assist.files import prompts as P


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def feat(ws):
    W.ensure_feature(ws, "26C1")
    return ws / "atopia" / "work" / "26C1" / "_upload"


# ---------------- 任务模板（第 7 类） ----------------

def test_atopia_task_category_has_three_builtins(ws):
    assert "atopia-task" in P.CATEGORIES
    items = P.list_templates(ws, "atopia-task")
    ids = {t["id"] for t in items}
    assert ids == {"knowledge-outline", "chapter-tag", "example-extract"}


def test_builtin_task_carries_schema_and_kinds(ws):
    items = {t["id"]: t for t in P.list_templates(ws, "atopia-task")}
    ko = items["knowledge-outline"]
    assert ko.get("outputSchema", {}).get("knowledge")
    assert "textbook" in ko.get("inputKinds", [])
    assert ko.get("default") is True


def test_save_task_keeps_schema(ws):
    """改提示词不能把任务契约（outputSchema/inputKinds）弄丢。"""
    t = {x["id"]: x for x in P.list_templates(ws, "atopia-task")}["chapter-tag"]
    r = P.save_template(ws, pid=t["id"], name=t["name"], text=t["text"] + "（教师改）",
                        category="atopia-task")
    assert r["ok"]
    assert "outputSchema" in r["template"]
    assert "inputKinds" in r["template"]


def test_task_template_can_be_deleted_if_custom(ws):
    P.save_template(ws, pid="my-task", name="我的任务", text="做点什么",
                    category="atopia-task")
    assert P.delete_template(ws, "my-task", "atopia-task")["ok"]


def test_builtin_task_cannot_be_deleted(ws):
    r = P.delete_template(ws, "knowledge-outline", "atopia-task")
    assert r["ok"] is False and "内置" in r["error"]


def test_task_prompt_has_bad_example_guard():
    """知识点任务要明确"不要抽课程管理信息"，否则 AI 会把课时当知识点。"""
    texts = {t["id"]: t["text"] for t in P.builtins_for("atopia-task")}
    assert "课程管理" in texts["knowledge-outline"]
    assert "逐字引用" in texts["knowledge-outline"]


# ---------------- 工步 0：抽取（免费） ----------------

def test_extract_markdown(ws, feat):
    (feat / "计划.md").write_text("# 静电场\n库仑定律\n电场强度\n", encoding="utf-8")
    r = W.extract_uploads(ws, "26C1")
    assert r["ok"] and len(r["files"]) == 1
    assert r["files"][0]["kind"] == "text"
    assert r["files"][0]["chars"] > 0


def test_extract_txt(ws, feat):
    (feat / "备注.txt").write_text("高斯定理是重点。", encoding="utf-8")
    r = W.extract_uploads(ws, "26C1")
    assert r["ok"] and r["chars"] > 0


def test_extract_pdf_real(ws, feat):
    """真 PDF（reportlab 生成）→ pdftotext 抽取，无需模型。"""
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    pdf = feat / "讲义.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 720, "Coulomb law F = k q1 q2 / r^2")
    c.save()
    r = W.extract_uploads(ws, "26C1")
    assert r["ok"], r.get("errors")
    f = r["files"][0]
    assert f["kind"] == "pdf" and f["chars"] > 0


def test_extract_reports_per_file_error(ws, feat):
    """单文件失败不影响其它（教师能看到哪份没抽出来）。"""
    (feat / "好的.md").write_text("内容", encoding="utf-8")
    (feat / "坏.pptx").write_bytes(b"not a real pptx")
    r = W.extract_uploads(ws, "26C1")
    assert len(r["files"]) == 1
    assert len(r["errors"]) == 1
    assert "坏.pptx" in r["errors"][0]["file"]


def test_extract_records_manifest(ws, feat):
    (feat / "a.md").write_text("x", encoding="utf-8")
    W.extract_uploads(ws, "26C1")
    man = json.loads((ws / "atopia/work/26C1/manifest.json").read_text(encoding="utf-8"))
    assert man.get("extracted", {}).get("files")


def test_read_extracted_text(ws, feat):
    (feat / "a.md").write_text("库仑定律", encoding="utf-8")
    W.extract_uploads(ws, "26C1")
    src = W.read_extracted_text(ws, "26C1")
    assert "库仑定律" in src["text"]


# ---------------- 工步 1：AI 结构化 ----------------

class _Fake:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat(self, **kw):
        self.calls.append(kw)
        return json.dumps(self.reply, ensure_ascii=False)


def test_parse_with_task_writes_parsed(ws, feat):
    (feat / "计划.md").write_text("库仑定律\n电场强度", encoding="utf-8")
    W.extract_uploads(ws, "26C1")
    fake = _Fake({"knowledge": [{"term": "库仑定律", "evidence": "库仑定律"}]})
    r = W.parse_with_task(fake, ws, "26C1")
    assert r["ok"] and r["taskId"] == "knowledge-outline"
    assert r["primaryKey"] == "knowledge" and r["count"] == 1
    assert (ws / "atopia/work/26C1/_parsed/26C1.json").is_file()


def test_parse_does_not_touch_materials(ws, feat):
    """**安全硬规则**：解析产物只落 atopia/，绝不写 materials/。"""
    (feat / "a.md").write_text("x", encoding="utf-8")
    W.extract_uploads(ws, "26C1")
    W.parse_with_task(_Fake({"knowledge": []}), ws, "26C1")
    assert not (ws / "materials").exists()


def test_parse_uses_selected_task(ws, feat):
    (feat / "a.md").write_text("例题：求场强", encoding="utf-8")
    W.extract_uploads(ws, "26C1")
    r = W.parse_with_task(_Fake({"examples": [{"content": "求场强"}]}), ws, "26C1",
                          task_id="example-extract")
    assert r["ok"] and r["primaryKey"] == "examples" and r["count"] == 1


def test_parse_refuses_without_content(ws):
    W.ensure_feature(ws, "empty")
    r = W.parse_with_task(_Fake({}), ws, "empty")
    assert r["ok"] is False and "没有可解析的内容" in r["error"]


def test_parse_refuses_unknown_task(ws, feat):
    (feat / "a.md").write_text("x", encoding="utf-8")
    W.extract_uploads(ws, "26C1")
    r = W.parse_with_task(_Fake({}), ws, "26C1", task_id="no-such-task")
    assert r["ok"] is False and "找不到任务模板" in r["error"]


def test_parse_prompt_includes_document(ws, feat):
    (feat / "a.md").write_text("独特标记UNIQUE123", encoding="utf-8")
    W.extract_uploads(ws, "26C1")
    fake = _Fake({"knowledge": []})
    W.parse_with_task(fake, ws, "26C1")
    assert "UNIQUE123" in fake.calls[0]["user_text"]


def test_parse_includes_teacher_context(ws, feat):
    (feat / "a.md").write_text("x", encoding="utf-8")
    W.extract_uploads(ws, "26C1")
    fake = _Fake({"knowledge": []})
    W.parse_with_task(fake, ws, "26C1", extra_context="只关注静电场")
    assert "只关注静电场" in fake.calls[0]["user_text"]


def test_parse_handles_model_error_gracefully(ws, feat):
    (feat / "a.md").write_text("x", encoding="utf-8")
    W.extract_uploads(ws, "26C1")

    class Boom:
        def chat(self, **kw):
            raise RuntimeError("模型超时")

    r = W.parse_with_task(Boom(), ws, "26C1")
    assert r["ok"] is False and "模型超时" in r["error"]


# ---------------- 回归：/prompts/templates 必须是 GET ----------------

def test_prompts_templates_route_is_get_not_post():
    """**回归**：D151 曾把这个**只读**接口放进 do_POST，导致前端 GET 全部
    被 302 重定向到 Pages（拿不到数据，且不报错）——模板下拉永远是空的。"""
    from assist import serve as S
    src = __import__("inspect").getsource(S.Handler)
    i_get = src.index("def do_GET(")
    i_route = src.index('"/prompts/templates"')
    # do_POST 定义在 do_GET 之前 → 路由位置必须 > do_GET 起始，才可能在其方法体内
    assert i_route > i_get, ("'/prompts/templates' 必须在 do_GET 中"
                             "（前端用 GET 调用；放进 do_POST 会被 302 到 Pages）")


def test_atopia_task_category_exposed_to_pwa(ws):
    """PWA 的下拉来自 /prompts/templates?category=atopia-task，类别必须被接受。"""
    assert "atopia-task" in P.CATEGORIES
    assert P.list_templates(ws, "atopia-task")
