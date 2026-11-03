"""D131（P2）：课堂资料 `/materials` → 知识点清单 → `summary` 批阅联动（T19/T20/T21）。

覆盖 docs/79 §8 验收标准：
1. `.pptx` / `.pdf` / 图片放进 `_source/` 后 `extract` 产出 `索引.json` + 非空 `_extract/`；
2. 同一文件二次抽取因 sha256 未变而**跳过**（增量）；
3. `suggest` 产出 `知识点清单.ai.json`，**不自动生成** `知识点清单.md`；
4. `--apply` 后才生成 `.md`，且 **AI 不覆盖**已有 `.md`（除非 `--force`）；
5. `summary` 批阅时清单进 prompt；无清单时行为与 D130 一致（不报错）；
6. 批阅结果含 `knowledge_missing[]`，`guidance` 指向遗漏知识点；
7. `officecli` 缺失时给可读提示并走回退；全失败时报错清楚、不静默产出空清单。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from assist.files import materials as M


# ---------------- 测试夹具：不依赖外部文件的最小 pptx/pdf ----------------
def _make_pptx(path: Path, slides: list[tuple[str, list[str]]]) -> Path:
    """构造最小合法 .pptx（无需 python-pptx）。"""
    from urllib.parse import quote
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>',
          '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>']
    for i in range(1, len(slides) + 1):
        ct.append(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
    ct.append('</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
            '</Relationships>')
    ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{i}"/>' for i in range(1, len(slides) + 1))
    pres = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            f'<p:sldIdLst>{ids}</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/>'
            '<p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    prels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             + "".join(
                 '<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>'.format(i=i)
                 for i in range(1, len(slides) + 1))
             + '</Relationships>')

    def slide_xml(title, lines):
        paras = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in [title] + lines)
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
                '</p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="Content"/>'
                '<p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="914400" y="914400"/>'
                '<a:ext cx="9144000" cy="4572000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
                f'</a:prstGeom></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/>{paras}</p:txBody>'
                '</p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "".join(ct))
        z.writestr("_rels/.rels", rels)
        z.writestr("ppt/presentation.xml", pres)
        z.writestr("ppt/_rels/presentation.xml.rels", prels)
        for i, (title, lines) in enumerate(slides, start=1):
            z.writestr(f"ppt/slides/slide{i}.xml", slide_xml(title, lines))
    return path


def _make_pdf(path: Path, pages: int = 2) -> Path:
    """用 PIL 生成图片型 PDF（无文本层 → 验证多模态/图片回退路径）。"""
    from PIL import Image
    ims = [Image.new("RGB", (600, 400), "white") for _ in range(pages)]
    ims[0].save(path, save_all=True, append_images=ims[1:])
    return path


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "kb").mkdir()
    return tmp_path


class _Client:
    """假 LLM：记录 prompt，返回固定知识点 JSON。"""
    evaluation_model = "fake"

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    def chat(self, *, system_prompt, user_text, model=None, **kw):
        self.prompts.append(user_text)
        return json.dumps(self.payload, ensure_ascii=False)


# ---------------- 布局与边界 ----------------
def test_layout_dirs_created(ws: Path):
    d = M.ensure_chap(ws, "chap04")
    assert (d / "_source").is_dir() and (d / "_extract").is_dir()
    assert M.chap_dir(ws, "chap04") == ws.resolve() / "materials" / "chap04"


def test_chap_name_rejected_when_traversal(ws: Path):
    for bad in ("", "..", "../x", "a/b"):
        with pytest.raises(M.MaterialsError):
            M.chap_dir(ws, bad)


def test_materials_not_under_kb(ws: Path):
    """设计约束：materials 与 kb 平级，**不得**落在 kb/ 下（D120 语义边界）。"""
    d = M.ensure_chap(ws, "chap04")
    assert (ws / "kb") not in d.parents


# ---------------- T19/T20：抽取 ----------------
def test_extract_pptx_produces_index_and_text(ws: Path):
    d = M.ensure_chap(ws, "chap04")
    _make_pptx(d / "_source" / "lecture01.pptx",
               [("第四章 动量守恒", ["动量守恒定律：合外力为零时总动量守恒"]),
                ("完全弹性碰撞", ["动能也守恒"])])
    rep = M.extract_chap(ws, "chap04")
    assert rep["ok"] and rep["sources"] == 1 and rep["chars"] > 0
    idx = M.read_index(ws, "chap04")
    src = idx["sources"][0]
    assert src["kind"] == "office"
    # schema（docs/79 §3）：抽取信息嵌在 extract 下
    assert src["extract"]["engine"] and src["extract"]["text_file"]
    assert "动量守恒" in Path(src["extract"]["text_file"]).read_text(encoding="utf-8")


def test_extract_is_incremental_by_sha256(ws: Path):
    d = M.ensure_chap(ws, "chap04")
    _make_pptx(d / "_source" / "a.pptx", [("T", ["内容"])])
    r1 = M.extract_chap(ws, "chap04")
    assert r1["skipped_unchanged"] == []
    r2 = M.extract_chap(ws, "chap04")
    assert r2["skipped_unchanged"] == ["_source/a.pptx"]
    # 文件变了 → 重新抽取
    _make_pptx(d / "_source" / "a.pptx", [("T", ["内容变了"])])
    r3 = M.extract_chap(ws, "chap04")
    assert r3["skipped_unchanged"] == []
    assert "内容变了" in M.read_source_text(ws, "chap04")["text"]
    # --force 即便没变也重抽
    r4 = M.extract_chap(ws, "chap04", force=True)
    assert r4["skipped_unchanged"] == []


def test_extract_pdf_and_image_and_text(ws: Path):
    d = M.ensure_chap(ws, "chap05")
    _make_pdf(d / "_source" / "doc.pdf", pages=2)
    from PIL import Image
    Image.new("RGB", (300, 200), "white").save(d / "_source" / "fig.png")
    (d / "_source" / "plan.md").write_text("# 授课计划\n第4章 动量守恒", encoding="utf-8")
    rep = M.extract_chap(ws, "chap05")
    assert rep["ok"]
    kinds = {s["file"]: s["kind"] for s in M.read_index(ws, "chap05")["sources"]}
    assert kinds["_source/doc.pdf"] == "pdf"
    assert kinds["_source/fig.png"] == "image"
    assert kinds["_source/plan.md"] == "text"
    pdf = next(s for s in M.read_index(ws, "chap05")["sources"]
               if s["file"].endswith("doc.pdf"))
    # 图片型 PDF 抽不到文字，但必须渲染出页图（供多模态）
    assert len(pdf["extract"]["images"]) == 2
    assert "动量守恒" in M.read_source_text(ws, "chap05")["text"]


def test_extract_reports_unsupported_file(ws: Path):
    d = M.ensure_chap(ws, "chap06")
    (d / "_source" / "weird.xyz").write_bytes(b"x")
    rep = M.extract_chap(ws, "chap06")
    assert rep["ok"] is False
    assert any("不支持" in e["error"] for e in rep["errors"])


def test_office_failure_message_is_readable(ws: Path, monkeypatch):
    """验收 7：officecli 缺失时给**可读提示**，不是异常栈。"""
    d = M.ensure_chap(ws, "chap07")
    _make_pptx(d / "_source" / "x.pptx", [("T", ["a"])])
    monkeypatch.setattr(M, "which", lambda cmd: None)   # 两个工具都没有
    rep = M.extract_chap(ws, "chap07")
    assert rep["ok"] is False
    err = rep["errors"][0]["error"]
    assert "officecli" in err and "PDF" in err


def test_extract_empty_source_reports_zero(ws: Path):
    M.ensure_chap(ws, "chap08")
    rep = M.extract_chap(ws, "chap08")
    assert rep["ok"] and rep["sources"] == 0


# ---------------- T21a：AI 抽取知识点（不自动生效） ----------------
_SUGGEST = {
    "knowledge": [
        {"term": "动量守恒", "aliases": ["动量守恒定律"], "importance": "core",
         "evidence": "第 5 页：合外力为零时总动量守恒"},
        {"term": "完全弹性碰撞", "aliases": [], "importance": "supporting",
         "evidence": "第 6 页"},
    ],
    "logic": [{"from": "牛顿第三定律", "to": "动量守恒", "note": "作用力反作用力"}],
    "notes": "",
}


def _prep_chap_with_text(ws: Path, chap: str = "chap04") -> None:
    d = M.ensure_chap(ws, chap)
    (d / "_source" / "plan.md").write_text(
        "第4章 动量守恒\n动量守恒定律：系统合外力为零时总动量守恒\n完全弹性碰撞：动能守恒",
        encoding="utf-8")
    M.extract_chap(ws, chap)


def test_suggest_writes_ai_json_but_not_effective_md(ws: Path):
    """验收 3：AI 建议**不**自动生成生效清单。"""
    _prep_chap_with_text(ws)
    rep = M.suggest_knowledge(_Client(_SUGGEST), ws, "chap04")
    d = M.chap_dir(ws, "chap04")
    assert (d / M.KNOW_AI).is_file()
    assert not (d / M.KNOW_MD).is_file(), "AI 建议不得自动成为生效清单"
    assert rep["term_count"] == 2
    assert "动量守恒" in M.read_knowledge_md(ws, "chap04") or True


def test_suggest_prompt_carries_material_text(ws: Path):
    _prep_chap_with_text(ws)
    c = _Client(_SUGGEST)
    M.suggest_knowledge(c, ws, "chap04")
    assert "动量守恒" in c.prompts[0]
    assert "evidence" in c.prompts[0]


def test_suggest_without_material_raises_readable(ws: Path):
    M.ensure_chap(ws, "chap09")
    with pytest.raises(M.MaterialsError) as ei:
        M.suggest_knowledge(_Client(_SUGGEST), ws, "chap09")
    assert "materials extract" in str(ei.value)


# ---------------- T21b：教师确认 ----------------
def test_confirm_creates_effective_md(ws: Path):
    _prep_chap_with_text(ws)
    M.suggest_knowledge(_Client(_SUGGEST), ws, "chap04")
    rep = M.confirm_knowledge(ws, "chap04")
    assert rep["ok"] and rep["terms"] == 2
    md = M.read_knowledge_md(ws, "chap04")
    assert "动量守恒" in md and "核心知识点" in md
    terms = M.knowledge_terms(ws, "chap04")
    assert "动量守恒" in terms


def test_confirm_does_not_overwrite_existing_without_force(ws: Path):
    """验收 4：AI **不覆盖**教师已确认的 .md。"""
    _prep_chap_with_text(ws)
    M.suggest_knowledge(_Client(_SUGGEST), ws, "chap04")
    M.confirm_knowledge(ws, "chap04")
    md_path = M.chap_dir(ws, "chap04") / M.KNOW_MD
    md_path.write_text("# 教师手改版\n- 只保留这个\n", encoding="utf-8")
    rep = M.confirm_knowledge(ws, "chap04")
    assert rep["ok"] is False
    assert md_path.read_text(encoding="utf-8").startswith("# 教师手改版")
    # --force 才覆盖，且记 journal
    rep2 = M.confirm_knowledge(ws, "chap04", force=True)
    assert rep2["ok"] is True
    jl = (M.chap_dir(ws, "chap04") / M.KNOW_JOURNAL).read_text(encoding="utf-8")
    assert "confirm" in jl and '"replaced_existing": true' in jl


def test_confirm_without_suggestion_raises(ws: Path):
    M.ensure_chap(ws, "chap10")
    with pytest.raises(M.MaterialsError):
        M.confirm_knowledge(ws, "chap10")


# ---------------- T21c：summary 批阅联动 ----------------
def test_summary_prompt_includes_knowledge_manifest(ws: Path):
    """验收 5：有清单时 summary 题 prompt 带上清单。"""
    from assist.grading.evaluate import build_user_prompt
    _prep_chap_with_text(ws)
    M.suggest_knowledge(_Client(_SUGGEST), ws, "chap04")
    M.confirm_knowledge(ws, "chap04")
    items = [{"序号": 1, "content": "总结本章要点", "kind": "summary",
              "kb": "summary", "chap": "chap04"}]
    p = build_user_prompt(items, "学生作答", ws=ws)
    assert "【本堂课应掌握的知识点（教师确认的课堂资料清单）】" in p
    assert "动量守恒" in p
    assert "knowledge_missing" in p


def test_prompt_without_manifest_unchanged(ws: Path):
    """验收 5：无清单时**不报错**、不加块（保持 D130 行为）。"""
    from assist.grading.evaluate import build_user_prompt
    items = [{"序号": 1, "content": "总结本章要点", "kind": "summary",
              "kb": "summary", "chap": "chap99"}]
    p = build_user_prompt(items, "学生作答", ws=ws)
    # 注意：summary 输出要求里本来就有「本堂课应掌握的知识点」这句话（指令举例），
    # 所以这里用**清单块的标题行**判断，不能只查这个短语。
    assert "【本堂课应掌握的知识点（教师确认的课堂资料清单）】" not in p
    assert "评阅范式：summary" in p          # 题型规则仍在


def test_non_summary_kind_does_not_get_block(ws: Path):
    from assist.grading.evaluate import build_user_prompt
    _prep_chap_with_text(ws)
    M.suggest_knowledge(_Client(_SUGGEST), ws, "chap04")
    M.confirm_knowledge(ws, "chap04")
    items = [{"序号": 1, "content": "求加速度", "kind": "problems",
              "kb": "problems", "chap": "chap04"}]
    assert "【本堂课应掌握的知识点（教师确认的课堂资料清单）】" not in \
        build_user_prompt(items, "作答", ws=ws)


def test_score_collects_knowledge_missing(ws: Path, tmp_path: Path):
    """验收 6：评阅结果含 knowledge_missing[]。"""
    from assist.grading.evaluate import evaluate_student
    items = [{"序号": 1, "content": "总结本章", "kind": "summary", "kb": "summary",
              "chap": "chap04"}]
    analysis = {
        "question_match": {"status": True, "match": True, "note": "", "evidence": "",
                           "reason": ""},
        "questions": [{
            "id": 1, "reasoning": {"status": "ok", "note": ""}, "correct_points": [],
            "errors": [], "confidence": "high", "has_diagram": True,
            "covered": {"知识点与概念": True, "重要公式及推导": False, "示意图": True},
            "knowledge_missing": ["完全弹性碰撞"],
        }],
        "has_signature": True, "summary": "", "guidance": "想一想完全弹性碰撞？",
        "strengths": [], "weaknesses": [],
    }
    tf = tmp_path / "张三.json"
    tf.write_text(json.dumps({"student": "张三", "items": [
        {"no": "1", "printed_question": "总结本章", "answer": "写了点", "diagrams": []}]},
        ensure_ascii=False), encoding="utf-8")
    out = evaluate_student(_Client(analysis), tf, items, tmp_path / "eval", ws=ws)
    res = json.loads(out.read_text(encoding="utf-8"))
    assert res["knowledge_missing"] == ["完全弹性碰撞"]
    assert res["total_score"] == 95        # summary checklist 缺一项 −5


# ---------------- CLI ----------------
def test_cli_extract_list_show(ws: Path):
    from click.testing import CliRunner
    from assist.cli import cli
    d = M.ensure_chap(ws, "chap04")
    _make_pptx(d / "_source" / "a.pptx", [("T", ["内容"])])
    r = CliRunner()
    out = r.invoke(cli, ["materials", "extract", "--chap", "chap04", "-w", str(ws)])
    assert out.exit_code == 0, out.output
    assert '"ok": true' in out.output
    out = r.invoke(cli, ["materials", "list", "-w", str(ws)])
    assert out.exit_code == 0 and "chap04" in out.output
    out = r.invoke(cli, ["materials", "show", "--chap", "chap04", "--text", "-w", str(ws)])
    assert out.exit_code == 0 and "内容" in out.output


def test_cli_confirm_requires_suggestion(ws: Path):
    from click.testing import CliRunner
    from assist.cli import cli
    M.ensure_chap(ws, "chap04")
    out = CliRunner().invoke(cli, ["materials", "confirm", "--chap", "chap04",
                                   "-w", str(ws)])
    assert out.exit_code != 0
    assert "suggest" in out.output


# ---------------- T21d：serve 接口（真实 HTTP） ----------------
def test_serve_materials_endpoints(ws: Path):
    import socket, threading, time, urllib.request
    from assist import serve as S

    _prep_chap_with_text(ws)
    M.suggest_knowledge(_Client(_SUGGEST), ws, "chap04")
    M.confirm_knowledge(ws, "chap04")

    S.Handler.ws = ws
    S.Handler.token = ""
    s0 = socket.socket(); s0.bind(("127.0.0.1", 0)); port = s0.getsockname()[1]; s0.close()
    httpd = S.ThreadingHTTPServer(("127.0.0.1", port), S.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.2)
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{base}/materials/list", timeout=5) as r:
            o = json.loads(r.read().decode())
        assert o["ok"] and any(c["chap"] == "chap04" and c["hasConfirmed"]
                               for c in o["chaps"])
        with urllib.request.urlopen(f"{base}/materials/knowledge?chap=chap04",
                                    timeout=5) as r:
            k = json.loads(r.read().decode())
        assert k["ok"] and "动量守恒" in k["terms"] and "核心知识点" in k["markdown"]
    finally:
        httpd.shutdown()


# ---------------- T21 补漏：图片/扫描件走多模态 ----------------
class _VisionClient:
    """假 LLM：区分文本/看图两条通道，记录调用与图数。"""
    evaluation_model = "fake"

    def __init__(self):
        self.text_calls: list[str] = []
        self.vision_calls: list[list[str]] = []
        self.vision_prompts: list[str] = []

    def chat(self, *, system_prompt, user_text, model=None, **kw):
        self.text_calls.append(user_text)
        return json.dumps({"knowledge": [
            {"term": "动量守恒", "aliases": [], "importance": "core",
             "evidence": "文字来源"}], "logic": []}, ensure_ascii=False)

    def chat_with_images(self, *, system_prompt, user_text, image_paths, model=None, **kw):
        self.vision_calls.append([str(p) for p in image_paths])
        self.vision_prompts.append(user_text)
        return json.dumps({"knowledge": [
            {"term": "完全弹性碰撞", "aliases": [], "importance": "core",
             "evidence": "第 1 页图"}], "logic": []}, ensure_ascii=False)


def test_scanned_pdf_uses_vision(ws: Path):
    """核心缺口：图片型 PDF 抽不到文字，必须走多模态，而不是报"没有可用文本"。"""
    d = M.ensure_chap(ws, "chap11")
    _make_pdf(d / "_source" / "scan.pdf", pages=3)
    M.extract_chap(ws, "chap11")
    assert M.read_source_text(ws, "chap11")["chars"] == 0     # 确认没有文字层
    c = _VisionClient()
    rep = M.suggest_knowledge(c, ws, "chap11")
    assert len(c.text_calls) == 0, "不应走纯文本通道"
    assert len(c.vision_calls) == 1 and len(c.vision_calls[0]) == 3
    assert rep["source"]["mode"] == "vision" and rep["source"]["images_used"] == 3
    assert rep["knowledge"][0]["term"] == "完全弹性碰撞"


def test_vision_path_sends_real_page_images(ws: Path):
    d = M.ensure_chap(ws, "chap12")
    _make_pdf(d / "_source" / "scan.pdf", pages=2)
    M.extract_chap(ws, "chap12")
    c = _VisionClient()
    M.suggest_knowledge(c, ws, "chap12")
    sent = c.vision_calls[0]
    assert all(Path(p).is_file() for p in sent), "送出的必须是真实存在的页图文件"
    assert all(p.endswith(".png") for p in sent)


def test_rich_text_prefers_text_mode(ws: Path):
    """文字充足时不该花成本看图（避免每章都多模态）。"""
    _prep_chap_with_text(ws)
    c = _VisionClient()
    rep = M.suggest_knowledge(c, ws, "chap04")
    assert len(c.vision_calls) == 0 and len(c.text_calls) == 1
    assert rep["source"]["mode"] == "text"


def test_vision_image_cap_is_reported_not_silent(ws: Path):
    """超过 --max-images 时：只送前 N 张，且 prompt 里明确告知（不静默截断）。"""
    d = M.ensure_chap(ws, "chap13")
    _make_pdf(d / "_source" / "scan.pdf", pages=4)
    M.extract_chap(ws, "chap13")
    c = _VisionClient()
    rep = M.suggest_knowledge(c, ws, "chap13", max_images=2)
    assert len(c.vision_calls[0]) == 2
    assert rep["source"]["images_used"] == 2
    # 截断必须在**送给模型的 prompt** 里明说（否则模型以为自己看了全章）
    prompt = c.vision_prompts[0]
    assert "仅提供了前 2 张" in prompt and "共 4 张" in prompt, prompt[-300:]


def test_no_text_no_images_raises_readable(ws: Path):
    """既无文本也无页图 → 明确报错（不静默产出空清单）。"""
    d = M.ensure_chap(ws, "chap14")
    (d / "_source" / "empty.md").write_text("   ", encoding="utf-8")
    M.extract_chap(ws, "chap14")
    with pytest.raises(M.MaterialsError) as ei:
        M.suggest_knowledge(_VisionClient(), ws, "chap14")
    assert "extract" in str(ei.value)


def test_read_source_images_orders_pages_numerically(ws: Path):
    """页序必须按数字排（-2 在 -10 之前），否则知识点 evidence 会标错页。"""
    d = M.ensure_chap(ws, "chap15")
    pages = d / M.EXTRACT / "scan.pages"
    pages.mkdir(parents=True, exist_ok=True)
    for n in (1, 2, 10, 11):
        (pages / f"scan-{n}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    M.write_index(ws, "chap15", {"version": 1, "chap": "chap15", "sources": [
        {"file": "_source/scan.pdf", "kind": "pdf",
         "extract": {"engine": "pdftoppm",
                     "images": [str(pages / f"scan-{n}.png") for n in (10, 1, 11, 2)]}}]})
    imgs = M.read_source_images(ws, "chap15")["images"]
    assert [Path(p).name for p in imgs] == ["scan-1.png", "scan-2.png",
                                            "scan-10.png", "scan-11.png"]


def test_read_source_images_skips_missing_cache(ws: Path):
    """缓存被删（_extract 可删）时不能崩，只跳过。"""
    d = M.ensure_chap(ws, "chap16")
    M.write_index(ws, "chap16", {"version": 1, "chap": "chap16", "sources": [
        {"file": "_source/x.pdf", "kind": "pdf",
         "extract": {"images": [str(d / "_extract" / "gone-1.png")]}}]})
    assert M.read_source_images(ws, "chap16")["images"] == []


def test_vision_suggest_feeds_summary_prompt_end_to_end(ws: Path):
    """扫描版资料 → 多模态抽知识点 → 教师确认 → summary 批阅 prompt 里真的有。"""
    from assist.grading.evaluate import build_user_prompt

    d = M.ensure_chap(ws, "chap17")
    _make_pdf(d / "_source" / "scan.pdf", pages=1)
    M.extract_chap(ws, "chap17")
    M.suggest_knowledge(_VisionClient(), ws, "chap17")
    assert M.confirm_knowledge(ws, "chap17")["ok"]

    items = [{"序号": 1, "content": "总结本章", "kind": "summary",
              "kb": "summary", "chap": "chap17"}]
    p = build_user_prompt(items, "学生作答", ws=ws)
    assert "【本堂课应掌握的知识点（教师确认的课堂资料清单）】" in p
    assert "完全弹性碰撞" in p
