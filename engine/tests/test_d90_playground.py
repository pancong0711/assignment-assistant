"""D90-P1/P2：LLM Playground 引擎（extract/store/ask/batch）。"""
import base64
import json
import zipfile
from pathlib import Path

from PIL import Image

from assist.playground import ask as pask
from assist.playground import extract, store


# ---------------- extract ----------------

def test_kind_and_whitelist():
    assert extract.kind_of("a.PNG") == "image"
    assert extract.kind_of("b.pdf") == "pdf"
    assert extract.kind_of("c.docx") == "docx"
    assert extract.kind_of("d.doc") == "doc"
    assert extract.kind_of("e.txt") == "text"
    assert extract.kind_of("evil.exe") == ""
    assert extract.is_allowed("x.pdf") and not extract.is_allowed("x.exe")


def test_save_upload_and_traversal(tmp_path):
    ws = tmp_path / "ws"
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 16).decode()
    r = extract.save_upload(ws, "../../etc/a.png", "data:image/png;base64," + png)
    assert r["ok"] is True
    assert Path(r["path"]).parent.name == "uploads"
    assert r["path"].endswith("a.png")  # basename 清洗
    assert ".runtime" in r["path"]
    assert extract.save_upload(ws, "x.exe", png)["ok"] is False
    assert extract.save_upload(ws, "x.png", "!!!")["ok"] is False


def test_extract_text_txt_pdf_docx(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir(parents=True)
    t = ws / "a.txt"; t.write_text("纯文本内容", encoding="utf-8")
    assert "纯文本内容" in extract.extract_text(t)

    # docx：手工构造最小 zip（word/document.xml）
    docx = ws / "b.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml",
                   "<w:document><w:body><w:p><w:r><w:t>你好</w:t></w:r>"
                   "<w:r><w:t>世界</w:t></w:r></w:p><w:p><w:r><w:t>第二段</w:t></w:r></w:p></w:body></w:document>")
    got = extract.extract_text(docx)
    assert "你好世界" in got and "第二段" in got

    # .doc 不支持
    doc = ws / "c.doc"; doc.write_bytes(b"\xd0\xcf\x11\xe0")
    assert "不支持" in extract.extract_text(doc)


def test_build_attachment_block(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir(parents=True)
    Image.new("RGB", (10, 10), (1, 2, 3)).save(ws / "p.png")
    (ws / "d.txt").write_text("文档内容", encoding="utf-8")
    (ws / "old.doc").write_bytes(b"\xd0\xcf")
    images, texts, notes = extract.build_attachment_block([ws / "p.png", ws / "d.txt", ws / "old.doc"])
    assert len(images) == 1
    assert any("文档内容" in t for t in texts)
    assert any("旧版 .doc" in n for n in notes)


# ---------------- store ----------------

def test_folder_crud(tmp_path):
    ws = tmp_path / "ws"
    assert store.list_folders(ws) == [store.DEFAULT_FOLDER]
    assert store.add_folder(ws, "实验")["ok"] is True
    assert "实验" in store.list_folders(ws)
    assert store.add_folder(ws, "实验")["ok"] is True  # 幂等
    assert store.delete_folder(ws, store.DEFAULT_FOLDER)["ok"] is False
    assert store.delete_folder(ws, "实验")["ok"] is True


def test_record_save_list_move_delete(tmp_path):
    ws = tmp_path / "ws"
    r1 = store.save_record(ws, {"id": "r1", "question": "q1", "answer": "a1", "folder": "默认"})
    assert r1["ok"]
    store.add_folder(ws, "化学")
    store.save_record(ws, {"id": "r2", "question": "q2", "answer": "a2", "folder": "化学"})
    recs = store.list_records(ws)
    assert {r["id"] for r in recs} == {"r1", "r2"}
    # 移动 r1 → 化学
    assert store.move_records(ws, ["r1"], "化学")["moved"] == 1
    assert store.read_record(ws, "r1")["folder"] == "化学"
    # 删文件夹 → 记录回默认
    store.delete_folder(ws, "化学")
    assert store.read_record(ws, "r1")["folder"] == store.DEFAULT_FOLDER
    assert store.delete_record(ws, "r2")["ok"] is True
    assert store.delete_record(ws, "nope")["ok"] is False


def test_illegal_record_id(tmp_path):
    ws = tmp_path / "ws"
    assert store.read_record(ws, "../evil") is None


# ---------------- ask / batch（桩 client） ----------------

class _StubClient:
    def __init__(self): self.calls = []
    def chat(self, system_prompt, user_text, **kw):
        self.calls.append(("chat", user_text))
        return f"回答：{user_text[:20]}"
    def chat_with_images(self, system_prompt, user_text, image_paths, **kw):
        self.calls.append(("img", user_text, len(image_paths)))
        return "多模态回答"


def test_ask_single_saves_record(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir(parents=True)
    stub = _StubClient()
    monkeypatch.setattr(pask, "_client", lambda ws_, provider="", model="": (stub, model or "stub-model"))
    r = pask.ask(ws, question="什么是熵？", model="stub-model")
    assert r["ok"] is True and r["answer"].startswith("回答：")
    rec = store.read_record(ws, r["recordId"])
    assert rec["question"] == "什么是熵？" and rec["model"] == "stub-model" and rec["answer"]


def test_ask_with_image_uses_multimodal(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir(parents=True)
    Image.new("RGB", (8, 8), (9, 9, 9)).save(ws / "p.png")
    stub = _StubClient()
    monkeypatch.setattr(pask, "_client", lambda ws_, provider="", model="": (stub, "m"))
    r = pask.ask(ws, question="看图", attachments=[str(ws / "p.png")])
    assert r["ok"] and r["answer"] == "多模态回答"
    assert stub.calls[0][0] == "img"


def test_ask_empty_question_rejected(tmp_path):
    ws = tmp_path / "ws"
    assert pask.ask(ws, question="  ")["ok"] is False


def test_batch_saves_each(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir(parents=True)
    stub = _StubClient()
    monkeypatch.setattr(pask, "_client", lambda ws_, provider="", model="": (stub, "m"))
    r = pask.batch(ws, questions=["q1", "q2", "q3"])
    assert r["ok"] and r["total"] == 3 and r["succeeded"] == 3
    recs = store.list_records(ws)
    assert len(recs) == 3 and all(x["mode"] == "batch" for x in recs)
    assert all(x["batchGroup"] == r["groupId"] for x in recs)


def test_ask_error_saves_record(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir(parents=True)
    class _Boom:
        def chat(self, *a, **k): raise RuntimeError("限流(429)")
    monkeypatch.setattr(pask, "_client", lambda ws_, provider="", model="": (_Boom(), "m"))
    r = pask.ask(ws, question="q")
    assert r["ok"] is False and "429" in r["error"]
    assert any(rec.get("error") for rec in store.list_records(ws))
