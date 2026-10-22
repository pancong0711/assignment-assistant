"""D98：Playground batch --items（每条自带文字+图片，互不共享）。"""
import json

import pytest

from assist.playground import ask as pga


class _FakeClient:
    """记录每次请求收到的 (user_text, images)。"""

    def __init__(self):
        self.calls = []

    def chat(self, system_prompt, user_text, **kw):
        self.calls.append({"text": user_text, "images": []})
        return "A:" + user_text

    def chat_with_images(self, system_prompt, user_text, images, **kw):
        self.calls.append({"text": user_text, "images": list(images)})
        return "A:" + user_text


def _patch(monkeypatch, fake):
    monkeypatch.setattr(pga, "_client", lambda ws, provider="", model="": (fake, "m"))


def test_items_isolated_text_and_images(tmp_path, monkeypatch):
    a = tmp_path / "a.png"; a.write_bytes(b"a")
    b = tmp_path / "b.png"; b.write_bytes(b"b")
    fake = _FakeClient(); _patch(monkeypatch, fake)
    items = [
        {"id": "t1", "question": "甲的问题", "images": [str(a)]},
        {"id": "t2", "question": "乙的问题", "images": [str(b)]},
    ]
    rep = pga.batch_items(tmp_path, items=items, save=False, workers=1)
    assert rep["ok"] and rep["mode"] == "items" and rep["total"] == 2
    # 每条请求只含自己的文本与图片
    by_text = {c["text"].split("（")[0].strip(): c["images"] for c in fake.calls}
    assert by_text["甲的问题"] == [str(a)]
    assert by_text["乙的问题"] == [str(b)]
    for c in fake.calls:
        assert ("甲的问题" in c["text"]) ^ ("乙的问题" in c["text"])


def test_items_single_failure_continues(tmp_path, monkeypatch):
    class Fake:
        def chat(self, system_prompt, user_text, **kw):
            if "坏" in user_text:
                raise RuntimeError("boom")
            return "ok"

        def chat_with_images(self, *a, **kw):
            return "ok"

    monkeypatch.setattr(pga, "_client", lambda ws, provider="", model="": (Fake(), "m"))
    items = [{"id": "good1", "question": "好1"}, {"id": "bad", "question": "坏"},
             {"id": "good2", "question": "好2"}]
    rep = pga.batch_items(tmp_path, items=items, save=False, workers=2)
    assert rep["total"] == 3 and rep["succeeded"] == 2
    by = {r["id"]: r for r in rep["results"]}
    assert by["bad"]["ok"] is False and "boom" in by["bad"]["error"]


def test_items_invalid_input(tmp_path):
    rep = pga.batch_items(tmp_path, items=[{"id": "x"}, {"id": "x"}], save=False)
    assert rep["ok"] is False and "重复" in rep["error"]


def test_cli_items_end_to_end(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from assist.cli import cli
    monkeypatch.setattr("assist.playground.ask._client",
                        lambda ws, provider="", model="": (_FakeClient(), "m"))
    f = tmp_path / "items.json"
    f.write_text(json.dumps([{"id": "t1", "question": "q1"},
                             {"id": "t2", "question": "q2"}]), encoding="utf-8")
    r = CliRunner().invoke(cli, ["playground", "batch", "--items", str(f), "-w", str(tmp_path)])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert d["mode"] == "items" and d["total"] == 2
