"""D130-P1b：AI 生成评阅要点 + 知识点标注 + 术语归一 + 受控词表（T5/T6/T7/T8）。

覆盖验收标准（docs/78 §5）：
5. AI 生成要点**不自动置顶**；教师确认后批阅才使用；
6. `related` 为空可被 AI 写入、非空不被覆盖；`pinned_by: human` 后 AI 不触碰；
7. 术语归一必须**教师勾选确认**后执行，且有变更日志（可回滚）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.files.kb_io import read_kb, write_xlsx
from assist.grading import rubric as RB
from assist.grading import termnorm as TN
from assist.grading import vocab as V


def _mk_kb(ws: Path, kind: str = "qa", chap: str = "chap01", rows=None):
    (ws / "kb").mkdir(exist_ok=True)
    rows = rows or [
        {"id": "c1", "content": "什么是惯性？", "solution": "惯性是…", "related": ""},
        {"id": "c2", "content": "动量守恒的条件？", "solution": "合外力为零",
         "related": "动量守恒"},
    ]
    write_xlsx(ws / "kb" / f"{kind}.xlsx", {chap: rows})
    return rows


def _ids(ws: Path, kind: str = "qa", chap: str = "chap01") -> list[str]:
    """D111：题库读入会自动补章节前缀（c1 → chap01-c1）；测试按真实题号跑。"""
    return [str(e.get("id")) for e in read_kb(ws / "kb")[kind][chap]]


class _Client:
    evaluation_model = "fake-eval"

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    def chat(self, *, system_prompt, user_text, model=None, **kw):
        self.prompts.append(user_text)
        return json.dumps(self.payload, ensure_ascii=False)


_RUBRIC = {
    "reference_solution": "惯性是物体保持原有运动状态的性质。",
    "rubric_points": [{"point": "惯性是保持运动状态的性质", "weight": 1},
                      {"point": "质量是惯性大小的量度", "weight": 1}],
    "knowledge": ["惯性", "牛顿第一定律"],
    "diagram": {"required": False, "description": ""},
}


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    _mk_kb(tmp_path)
    return tmp_path


# ---------------- T5：生成要点 ----------------
def test_rubric_prompt_carries_kind_rule_summary(ws: Path):
    """要点生成 prompt 必须带**该题型规则摘要**（docs/78 §3.2 解耦口径）。"""
    p = RB.build_rubric_prompt(ws=ws, kind="qa", content="什么是惯性？")
    assert "评阅范式：qa" in p
    assert "每个未答到的评阅要点扣 5 分" in p
    assert "该答到什么" in p and "不是\"怎么扣分\"" in p.replace("“", "\"")


def test_rubric_prompt_follows_modified_rules(ws: Path):
    from assist.grading import rules as R
    r = R.read_rules(ws)
    r["types"]["qa"]["perMissingPointDeduct"] = 7
    R.write_rules(ws, r)
    assert "扣 7 分" in RB.build_rubric_prompt(ws=ws, kind="qa", content="q")


def test_rubric_to_text_includes_points_and_knowledge():
    txt = RB.rubric_to_text(_RUBRIC)
    assert "【参考解答】" in txt and "【评阅要点】" in txt
    assert "惯性是保持运动状态的性质" in txt
    assert "【知识点】惯性，牛顿第一定律" in txt


def test_save_rubric_version_not_pinned_by_default(ws: Path):
    """验收 5：AI 要点**不自动置顶**，教师确认后才生效。"""
    from assist.files import solutions as sol
    res = RB.save_rubric_version(ws, kb="qa", chap="chap01", qid="c1",
                                 rubric=_RUBRIC, model="fake")
    assert res["ok"] is True
    assert res["added"]["pinned"] is False
    doc = sol.read_solutions(ws, "c1", kb="qa", chap="chap01")
    assert doc["versions"][-1]["source"] == "ai"
    assert doc["versions"][-1]["pinned"] is False


def test_pinned_rubric_becomes_effective_solution(ws: Path):
    """教师置顶后，批阅取到的参考答案就是该要点（反馈进 prompt）。"""
    from assist.files import solutions as sol
    from assist.grading.flow import expand_items
    c1 = _ids(ws)[0]
    res = RB.save_rubric_version(ws, kb="qa", chap="chap01", qid=c1, rubric=_RUBRIC)
    sol.pin_version(ws, c1, res["added"]["id"], kb="qa", chap="chap01")
    items = expand_items(ws, {"items": [{"kb": "qa", "chap": "chap01", "ids": [c1]}]})
    assert "评阅要点" in items[0]["solution"]


def test_generate_rubric_from_fake_client(ws: Path):
    c = _Client(_RUBRIC)
    out = RB.generate_rubric(c, ws=ws, kind="qa", content="什么是惯性？")
    assert out["knowledge"] == ["惯性", "牛顿第一定律"]
    assert "惯性" in c.prompts[0]


# ---------------- T6：知识点标注 ----------------
def test_select_questions_granularity(ws: Path):
    _mk_kb(ws, "problems", "chap02", [{"id": "p1", "content": "求 a"}])
    kb = read_kb(ws / "kb")
    ids = _ids(ws); c1, c2 = ids[0], ids[1]
    assert len(RB.select_questions(kb)) == 3                      # 全部
    assert len(RB.select_questions(kb, kinds=["qa"])) == 2        # 某类型
    assert len(RB.select_questions(kb, kinds=["qa", "problems"])) == 3   # 多类型
    assert [x["qid"] for x in RB.select_questions(kb, ids=[c2])] == [c2]  # 具体题目
    assert len(RB.select_questions(kb, chaps=["chap02"])) == 1    # 章节


def test_plan_tagging_only_empty_by_default(ws: Path):
    """验收 6：默认只标未标注的题，已有内容不覆盖。"""
    kb = read_kb(ws / "kb")
    ids = _ids(ws); c1, c2 = ids[0], ids[1]
    targets = RB.select_questions(kb, kinds=["qa"])
    plan = RB.plan_tagging(ws, targets, only_empty=True)
    assert [t["qid"] for t in plan["todo"]] == [c1]
    assert any("已有知识点" in s["reason"] for s in plan["skipped"])


def test_plan_tagging_force_overrides_existing(ws: Path):
    kb = read_kb(ws / "kb")
    ids = _ids(ws); c1, c2 = ids[0], ids[1]
    plan = RB.plan_tagging(ws, RB.select_questions(kb, kinds=["qa"]), force=True)
    assert {t["qid"] for t in plan["todo"]} == {c1, c2}


def test_plan_tagging_respects_pinned_by_human(ws: Path):
    """验收 6：`pinned_by: human` 后 AI 不再触碰（即便 --force）。"""
    c1 = _ids(ws)[0]
    RB.set_meta(ws, "qa", "chap01", c1, {"pinned_by": "human"})
    kb = read_kb(ws / "kb")
    plan = RB.plan_tagging(ws, RB.select_questions(kb, ids=[c1]), force=True)
    assert plan["todo"] == []
    assert any("教师已锁定" in s["reason"] for s in plan["skipped"])


def test_apply_related_writes_xlsx_and_meta(ws: Path):
    c1 = _ids(ws)[0]
    res = RB.apply_related(ws, [{"kb": "qa", "chap": "chap01", "qid": c1,
                                 "related": "惯性,牛顿第一定律",
                                 "meta": {"source": "ai", "ai_suggested": "惯性,牛顿第一定律"}}])
    assert res["ok"] and res["written"] == 1
    kb = read_kb(ws / "kb")
    row = next(e for e in kb["qa"]["chap01"] if e["id"] == c1)
    assert row["related"] == "惯性,牛顿第一定律"
    assert RB.get_meta(ws, "qa", "chap01", c1)["source"] == "ai"
    # 写盘前快照（可回滚）
    assert res["snapshot"]


def test_apply_related_preserves_other_rows(ws: Path):
    ids = _ids(ws); c1, c2 = ids[0], ids[1]
    RB.apply_related(ws, [{"kb": "qa", "chap": "chap01", "qid": c1, "related": "惯性"}])
    kb = read_kb(ws / "kb")
    row2 = next(e for e in kb["qa"]["chap01"] if e["id"] == c2)
    assert row2["related"] == "动量守恒"      # 未被误改


# ---------------- T7：术语归一 ----------------
def test_normalize_delimiters_before_merge(ws: Path):
    assert TN.normalize_delimiters("动量守恒，弹性碰撞；刚体、转动") == "动量守恒,弹性碰撞,刚体,转动"


def test_propose_groups_defaults_not_all_selected():
    """默认**不全选**：低置信 / 有警示的组默认不勾（验收 7 前置）。"""
    payload = {"groups": [
        {"canonical": "动量守恒", "members": ["动量守恒定律"], "confidence": 0.98,
         "reason": "同义", "warning": ""},
        {"canonical": "动量定理", "members": ["冲量定理"], "confidence": 0.7,
         "reason": "可能同义", "warning": "与动量守恒易混"},
    ]}
    res = TN.propose_groups(_Client(payload), {"动量守恒": {"count": 3}})
    groups = res["groups"]
    assert groups[0]["selected"] is True
    assert groups[1]["selected"] is False          # 低置信 + 警示 → 默认不勾
    assert TN.build_mapping(groups) == {"动量守恒定律": "动量守恒"}


def test_propose_groups_drops_self_only_group():
    payload = {"groups": [{"canonical": "惯性", "members": ["惯性"], "confidence": 0.99}]}
    assert TN.propose_groups(_Client(payload), {"惯性": {"count": 1}})["groups"] == []


def test_impact_and_apply_mapping(ws: Path):
    _mk_kb(ws, "qa", "chap01", [
        {"id": "c1", "content": "q1", "related": "动量守恒定律"},
        {"id": "c2", "content": "q2", "related": "动量守恒，弹性碰撞"},
    ])
    ids = _ids(ws); c1, c2 = ids[0], ids[1]
    mapping = {"动量守恒定律": "动量守恒"}
    imp = TN.impact(ws, mapping)
    assert imp["count"] == 1
    assert imp["items"][0]["after"] == "动量守恒"
    res = TN.apply_mapping(ws, mapping)
    assert res["ok"] and res["changed"] == 1
    kb = read_kb(ws / "kb")
    row = next(e for e in kb["qa"]["chap01"] if e["id"] == c1)
    assert row["related"] == "动量守恒"
    # 变更日志可读
    log = TN.last_log(ws)
    assert log and log["mapping"] == mapping


def test_apply_mapping_dry_run_does_not_write(ws: Path):
    _mk_kb(ws, "qa", "chap01", [{"id": "c1", "content": "q", "related": "动量守恒定律"}])
    c1 = _ids(ws)[0]
    res = TN.apply_mapping(ws, {"动量守恒定律": "动量守恒"}, dry_run=True)
    assert res["dry_run"] is True
    kb = read_kb(ws / "kb")
    assert next(e for e in kb["qa"]["chap01"] if e["id"] == c1)["related"] == "动量守恒定律"


def test_apply_mapping_requires_selection(ws: Path):
    assert TN.apply_mapping(ws, {})["ok"] is False


def test_rollback_restores_previous_terms(ws: Path):
    _mk_kb(ws, "qa", "chap01", [{"id": "c1", "content": "q", "related": "动量守恒定律"}])
    c1 = _ids(ws)[0]
    TN.apply_mapping(ws, {"动量守恒定律": "动量守恒"})
    res = TN.rollback(ws)
    assert res["ok"] and res["rolled_back"] == 1
    kb = read_kb(ws / "kb")
    assert next(e for e in kb["qa"]["chap01"] if e["id"] == c1)["related"] == "动量守恒定律"


# ---------------- T8：受控词表 ----------------
def test_vocab_harvest_from_kb(ws: Path):
    _mk_kb(ws, "qa", "chap01", [
        {"id": "c1", "content": "q1", "related": "惯性，牛顿第一定律"},
        {"id": "c2", "content": "q2", "related": "惯性"},
    ])
    res = V.harvest(ws, write=True)
    terms = {t["term"]: t for t in res["terms"]}
    assert terms["惯性"]["count"] == 2
    assert terms["牛顿第一定律"]["count"] == 1        # 分隔符已标准化
    assert V.load_vocab(ws)["terms"]


def test_vocab_harvest_keeps_human_aliases(ws: Path):
    _mk_kb(ws, "qa", "chap01", [{"id": "c1", "content": "q", "related": "惯性"}])
    V.add_term(ws, "惯性", aliases=["惯性定律"], source="human")
    V.harvest(ws, write=True)
    t = next(t for t in V.load_vocab(ws)["terms"] if t["term"] == "惯性")
    assert t["aliases"] == ["惯性定律"]
    assert t["source"] == "human"


def test_vocab_canonical_maps_alias(ws: Path):
    V.add_term(ws, "动量守恒", aliases=["动量守恒定律"])
    v = V.load_vocab(ws)
    assert V.canonical(v, "动量守恒定律") == "动量守恒"
    assert V.canonical(v, "未知术语") == "未知术语"


def test_vocab_feeds_rubric_prompt(ws: Path):
    """词表进入要点生成 prompt（generate_rubric 自动加载 <ws>/knowledge-terms.json）。"""
    V.add_term(ws, "动量守恒", aliases=["动量守恒定律"])
    c = _Client(_RUBRIC)
    RB.generate_rubric(c, ws=ws, kind="qa", content="q")
    assert "受控词表" in c.prompts[0] and "动量守恒" in c.prompts[0]


def test_vocab_split_join_roundtrip():
    raw = "动量守恒，弹性碰撞; 刚体、转动"
    assert V.join_terms(V.split_terms(raw)) == "动量守恒,弹性碰撞,刚体,转动"


# ---------------- CLI ----------------
def test_cli_vocab_and_tag_knowledge_dry_run(ws: Path):
    from click.testing import CliRunner
    from assist.cli import cli
    r = CliRunner()
    out = r.invoke(cli, ["kb", "vocab", "add", "--term", "惯性", "--alias", "惯性定律",
                         "-w", str(ws)])
    assert out.exit_code == 0, out.output
    out = r.invoke(cli, ["kb", "vocab", "harvest", "-w", str(ws)])
    assert out.exit_code == 0 and '"terms"' in out.output


def test_cli_check_knowledge_mapping_apply(ws: Path):
    from click.testing import CliRunner
    from assist.cli import cli
    _mk_kb(ws, "qa", "chap01", [{"id": "c1", "content": "q", "related": "惯性定律"}])
    c1 = _ids(ws)[0]
    mf = ws / "mapping.json"
    mf.write_text(json.dumps({"groups": [
        {"canonical": "惯性", "members": ["惯性定律"], "confidence": 0.95,
         "selected": True}]}, ensure_ascii=False), encoding="utf-8")
    r = CliRunner()
    out = r.invoke(cli, ["kb", "check-knowledge", "--mapping", str(mf), "--apply",
                         "-w", str(ws)])
    assert out.exit_code == 0, out.output
    kb = read_kb(ws / "kb")
    assert next(e for e in kb["qa"]["chap01"] if e["id"] == c1)["related"] == "惯性"


def test_build_mapping_handwritten_file_selects_all():
    """手写 mapping 无 selected 字段 → 视为全部勾选（不静默产出空映射）。"""
    groups = [{"canonical": "惯性", "members": ["惯性定律"], "confidence": 0.95}]
    assert TN.build_mapping(groups) == {"惯性定律": "惯性"}


def test_build_mapping_all_unselected_stays_empty():
    """明确给了 selected=False 的组不得被"手写兜底"误执行。"""
    groups = [{"canonical": "惯性", "members": ["惯性定律"], "selected": False}]
    assert TN.build_mapping(groups) == {}
