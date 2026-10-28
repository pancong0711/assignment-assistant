"""D89-N5：题库 AI 作答（solve.py）+ CLI dry-run + serve 端点参数。"""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from openpyxl import Workbook

from assist.cli import cli
from assist.files import solutions as sol
from assist.grading import solve


def _mk_kb(ws: Path):
    kb = ws / "kb"; kb.mkdir(parents=True, exist_ok=True)
    wb = Workbook(); sh = wb.active; sh.title = "chap04"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["c1", "求质点速度 $v$。", "-", 1, "牛顿力学", "计算", "旧答案", ""])
    sh.append(["c2", "解释熵增。", "-", 1, "热力学", "简答", "", ""])
    wb.save(kb / "problems.xlsx")


def test_list_targets_all_and_filtered(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    all_t = solve.list_targets(ws, "problems")
    # D111：题库 id 全局唯一（章节前缀）；ids 传裸题号也能命中
    assert [t["id"] for t in all_t] == ["chap04-c1", "chap04-c2"]
    one = solve.list_targets(ws, "problems", "chap04", ["c2"])
    assert [t["id"] for t in one] == ["chap04-c2"] and one[0]["related"] == "热力学"


def test_solve_dry_run(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    targets = solve.list_targets(ws, "problems", "chap04", ["c1"])
    res = solve.solve_targets(ws, targets, dry_run=True)
    assert res["dryRun"] is True and res["planned"] == 1
    assert "求质点速度" in res["plans"][0]["prompt"]
    # dry-run 不调 LLM、不写文件
    assert not list((ws / "kb" / "solutions").glob("*.json"))


def test_solve_apply_uses_stub_client(tmp_path, monkeypatch):
    """用桩替换 _client，验证「不覆盖 + 标 ai+model + 追加版本」。"""
    ws = tmp_path / "ws"; _mk_kb(ws)
    # 已有原答案版本（human）
    sol.add_version(ws, "chap04-c1", "原答案", source="human", kb="problems", chap="chap04")

    class _Stub:
        def chat(self, **kw):
            return "AI 作答正文 $E=mc^2$"
    monkeypatch.setattr(solve, "_client", lambda ws_, model="": (_Stub(), model or "stub-model"))

    targets = solve.list_targets(ws, "problems", "chap04", ["c1"])
    res = solve.solve_targets(ws, targets, model="stub-model", apply=True, pin=False, dry_run=False)
    assert res["written"] == 1
    # D110：答案按 (kb, chap, qid) 作用域存/取
    d = sol.read_solutions(ws, "chap04-c1", kb="problems", chap="chap04")
    assert [v["source"] for v in d["versions"]] == ["human", "ai"]
    ai = d["versions"][1]
    assert ai["model"] == "stub-model" and ai["at"] and ai["pinned"] is False
    # 原答案未被覆盖
    assert d["versions"][0]["text"] == "原答案"


def test_solve_apply_pin(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; _mk_kb(ws)
    sol.add_version(ws, "chap04-c1", "原答案", source="human", kb="problems", chap="chap04")
    class _Stub:
        def chat(self, **kw): return "新解"
    monkeypatch.setattr(solve, "_client", lambda ws_, model="": (_Stub(), "m"))
    targets = solve.list_targets(ws, "problems", "chap04", ["c1"])
    solve.solve_targets(ws, targets, model="m", apply=True, pin=True, dry_run=False)
    d = sol.read_solutions(ws, "chap04-c1", kb="problems", chap="chap04")
    assert d["versions"][-1]["pinned"] is True and d["versions"][0]["pinned"] is False
    assert sol.effective_solution(ws, "chap04-c1", kb="problems", chap="chap04")["text"] == "新解"


# ---------------- CLI（dry-run，不调 LLM） ----------------

def test_cli_ai_solve_dry_run(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    r = CliRunner().invoke(cli, ["kb", "ai-solve", "--kb-kind", "problems",
                                 "--chap", "chap04", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output.split("\n{")[0] if "\n{" in r.output else r.output.split("\n（dry-run")[0])
    # 输出首段是 JSON（dry-run 摘要）
    assert d["dryRun"] is True and d["planned"] == 2


def test_cli_ai_solve_no_targets_fails(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    r = CliRunner().invoke(cli, ["kb", "ai-solve", "--chap", "nope", "-w", str(ws)])
    assert r.exit_code != 0
