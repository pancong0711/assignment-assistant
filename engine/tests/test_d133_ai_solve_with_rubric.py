"""D133：AI 做参考答案时**同时**产出评阅要点（合并原两条独立路径）。

背景（docs/82 §1）：`kb ai-solve` 原先只产出纯解答文本，
评阅要点要另外跑 `rules generate`，两套口径可能不一致。

本单让 ai-solve 可选 `--with-rubric`：一次调用产出
【参考解答】+【评阅要点】+【知识点】（走 rubric.build_rubric_prompt，**带题型规则摘要**），
写入同一答案版本；**默认不置顶**（未确认的要点不该抢生效答案，D130 验收 5）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.files import solutions as sol
from assist.files.kb_io import write_xlsx
from assist.grading import solve as S

_RUBRIC = {
    "reference_solution": "惯性是物体保持原有运动状态的性质。",
    "rubric_points": [{"point": "惯性是保持运动状态的性质", "weight": 1},
                      {"point": "质量是惯性大小的量度", "weight": 1}],
    "knowledge": ["惯性", "牛顿第一定律"],
    "diagram": {"required": False, "description": ""},
}


class _Client:
    evaluation_model = "fake"
    def __init__(self, payload=None):
        self.payload = payload or _RUBRIC
        self.prompts: list[str] = []

    def chat(self, *, system_prompt, user_text, model=None, **kw):
        self.prompts.append(user_text)
        return json.dumps(self.payload, ensure_ascii=False)


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "kb").mkdir()
    write_xlsx(tmp_path / "kb" / "qa.xlsx",
               {"chap01": [{"id": "c1", "content": "什么是惯性？"}]})
    return tmp_path


@pytest.fixture()
def qid(ws: Path) -> str:
    from assist.files.kb_io import read_kb
    return str(read_kb(ws / "kb")["qa"]["chap01"][0]["id"])


def _run(ws, monkeypatch, *, client=None, pin=False, with_rubric=True, apply=True):
    c = client or _Client()
    monkeypatch.setattr(S, "_client", lambda ws_, model="": (c, "fake-model"))
    targets = S.list_targets(ws, "qa", "chap01")
    rep = S.solve_targets(ws, targets, apply=apply, pin=pin, dry_run=False,
                          with_rubric=with_rubric)
    return c, rep


# ---------------- 核心：解答 + 要点同源产出 ----------------
def test_with_rubric_writes_solution_and_points(ws, qid, monkeypatch):
    _c, rep = _run(ws, monkeypatch)
    assert rep["results"][0]["ok"] is True
    assert rep["results"][0]["withRubric"] is True
    assert rep["results"][0]["rubricPoints"] == 2

    doc = sol.read_solutions(ws, qid, kb="qa", chap="chap01")
    text = doc["versions"][-1]["text"]
    assert "【参考解答】" in text
    assert "【评阅要点】" in text
    assert "惯性是保持运动状态的性质" in text
    assert "【知识点】" in text and "牛顿第一定律" in text


def test_with_rubric_prompt_carries_kind_rules(ws, monkeypatch):
    """要点必须带**该题型规则摘要**（与评阅 prompt 共用同一份口径）。"""
    c, _ = _run(ws, monkeypatch)
    assert "评阅范式：qa" in c.prompts[0]
    assert "评阅要点" in c.prompts[0]


def test_without_rubric_keeps_old_plain_behaviour(ws, qid, monkeypatch):
    """不传 with_rubric 时行为与旧版一致（纯解答，不含要点）。"""
    class Plain:
        evaluation_model = "fake"
        def chat(self, **kw):
            return "惯性是保持运动状态的性质。"
    monkeypatch.setattr(S, "_client", lambda ws_, model="": (Plain(), "fake-model"))
    targets = S.list_targets(ws, "qa", "chap01")
    S.solve_targets(ws, targets, apply=True, pin=True, dry_run=False)
    doc = sol.read_solutions(ws, qid, kb="qa", chap="chap01")
    text = doc["versions"][-1]["text"]
    assert "【评阅要点】" not in text
    assert doc["versions"][-1]["pinned"] is True        # 纯解答仍按 pin


# ---------------- 默认不置顶（D130 验收 5） ----------------
def test_with_rubric_not_pinned_by_default(ws, qid, monkeypatch):
    _run(ws, monkeypatch, pin=False)
    doc = sol.read_solutions(ws, qid, kb="qa", chap="chap01")
    v = doc["versions"][-1]
    assert v["pinned"] is False, "未确认的要点不得抢生效答案"


def test_with_rubric_can_pin_when_explicitly_asked(ws, qid, monkeypatch):
    _run(ws, monkeypatch, pin=True)
    doc = sol.read_solutions(ws, qid, kb="qa", chap="chap01")
    assert doc["versions"][-1]["pinned"] is True


def test_pinned_rubric_feeds_grading_prompt(ws, qid, monkeypatch):
    """置顶后，批阅取到的"参考答案"就是这份带要点的文本（闭环）。"""
    from assist.grading.flow import expand_items
    _run(ws, monkeypatch, pin=True)
    items = expand_items(ws, {"items": [{"kb": "qa", "chap": "chap01"}]})
    assert "【评阅要点】" in items[0]["solution"]


# ---------------- dry-run / 失败 / 口径 ----------------
def test_dry_run_reports_with_rubric_flag(ws, monkeypatch):
    monkeypatch.setattr(S, "_client", lambda ws_, m="": (_Client(), "fake"))
    targets = S.list_targets(ws, "qa", "chap01")
    rep = S.solve_targets(ws, targets, apply=False, dry_run=True, with_rubric=True)
    assert rep["dryRun"] is True and rep["withRubric"] is True


def test_empty_rubric_is_reported_as_failure(ws, monkeypatch):
    empty = {"reference_solution": "", "rubric_points": [], "knowledge": [],
             "diagram": {"required": False, "description": ""}}
    _c, rep = _run(ws, monkeypatch, client=_Client(empty))
    assert rep["results"][0]["ok"] is False
    assert "未给出参考解答" in rep["results"][0]["error"]


# ---------------- CLI ----------------
def test_cli_with_rubric_defaults_to_no_pin(ws, monkeypatch):
    from click.testing import CliRunner
    from assist.cli import cli
    c = _Client()
    monkeypatch.setattr(S, "_client", lambda ws_, model="": (c, "fake-model"))
    out = CliRunner().invoke(cli, ["kb", "ai-solve", "--kb-kind", "qa", "--chap", "chap01",
                                   "--with-rubric", "--apply", "-w", str(ws)])
    assert out.exit_code == 0, out.output
    from assist.files.kb_io import read_kb
    qid = str(read_kb(ws / "kb")["qa"]["chap01"][0]["id"])
    doc = sol.read_solutions(ws, qid, kb="qa", chap="chap01")
    assert doc["versions"][-1]["pinned"] is False
    assert "【评阅要点】" in doc["versions"][-1]["text"]


def test_cli_pin_rubric_opts_in(ws, monkeypatch):
    from click.testing import CliRunner
    from assist.cli import cli
    monkeypatch.setattr(S, "_client", lambda ws_, model="": (_Client(), "fake-model"))
    out = CliRunner().invoke(cli, ["kb", "ai-solve", "--kb-kind", "qa", "--chap", "chap01",
                                   "--with-rubric", "--pin-rubric", "--apply", "-w", str(ws)])
    assert out.exit_code == 0, out.output
    from assist.files.kb_io import read_kb
    qid = str(read_kb(ws / "kb")["qa"]["chap01"][0]["id"])
    assert sol.read_solutions(ws, qid, kb="qa", chap="chap01")["versions"][-1]["pinned"] is True


def test_cli_skips_rubric_for_copy_kind(ws, monkeypatch):
    """copy/summary 按口径不生成 AI 要点 → 只生成解答，并给出提示。"""
    from click.testing import CliRunner
    from assist.cli import cli
    write_xlsx(ws / "kb" / "copy.xlsx", {"chap01": [{"id": "c1", "content": "抄写 xxx"}]})
    class Plain:
        evaluation_model = "fake"
        def chat(self, **kw):
            return "抄写内容"
    monkeypatch.setattr(S, "_client", lambda ws_, model="": (Plain(), "fake-model"))
    out = CliRunner().invoke(cli, ["kb", "ai-solve", "--kb-kind", "copy", "--chap", "chap01",
                                   "--with-rubric", "--apply", "-w", str(ws)])
    assert out.exit_code == 0, out.output
    from assist.files.kb_io import read_kb
    qid = str(read_kb(ws / "kb")["copy"]["chap01"][0]["id"])
    doc = sol.read_solutions(ws, qid, kb="copy", chap="chap01")
    assert "【评阅要点】" not in doc["versions"][-1]["text"]
