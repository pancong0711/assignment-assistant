"""playground batch --combine：一次请求回答多问题、附件只发一遍（省 token）。"""
from pathlib import Path

from assist.playground import ask as pga


class _FakeClient:
    def __init__(self):
        self.calls = 0
        self.last_user = ""

    def chat(self, system_prompt, user_text, **kw):
        self.calls += 1
        self.last_user = user_text
        return "[Q1] 答案一\n[Q2] 答案二\n[Q3] 答案三"

    def chat_with_images(self, system_prompt, user_text, images, **kw):
        self.calls += 1
        self.last_user = user_text
        return "[Q1] 图答一\n[Q2] 图答二"


def _patch(monkeypatch, fake):
    monkeypatch.setattr(pga, "_client", lambda ws, provider="", model="": (fake, "m"))


def test_combine_single_request_and_split(tmp_path, monkeypatch):
    fake = _FakeClient()
    _patch(monkeypatch, fake)
    res = pga.batch(tmp_path, questions=["q1", "q2", "q3"], combine=True, save=False)
    assert res["ok"] is True and res["mode"] == "combine"
    assert fake.calls == 1, "合并模式应只发一次请求"
    assert [r["answer"] for r in res["results"]] == ["答案一", "答案二", "答案三"]
    # 三个问题都在同一请求里
    for q in ("q1", "q2", "q3"):
        assert q in fake.last_user


def test_combine_attachments_sent_once(tmp_path, monkeypatch):
    """附件文本只应出现在这一次请求中（不是每条一次）。"""
    doc = tmp_path / "note.txt"
    doc.write_text("附件正文内容", encoding="utf-8")
    fake = _FakeClient()
    _patch(monkeypatch, fake)
    res = pga.batch(tmp_path, questions=["a", "b"], attachments=[str(doc)],
                    combine=True, save=False)
    assert res["ok"] is True
    assert fake.calls == 1
    assert fake.last_user.count("附件正文内容") == 1


def test_per_item_mode_still_works(tmp_path, monkeypatch):
    fake = _FakeClient()
    _patch(monkeypatch, fake)
    res = pga.batch(tmp_path, questions=["a", "b"], combine=False, save=False)
    assert res["ok"] is True and "mode" not in res or res.get("mode") is None
    assert fake.calls == 2, "逐条模式应每问题一次请求"


def test_split_combined_fallback():
    assert pga._split_combined("无标记", 3) == ["无标记", "", ""]
    assert pga._split_combined("【Q1】甲\n【Q2】乙", 2) == ["甲", "乙"]
