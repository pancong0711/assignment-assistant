"""D130-T12：升级后「批阅学生列表不显示已 AI 批阅的学生」——**列表与弹窗同源**契约。

根因（已复现）：草稿键可能是 `workAnswerId`，也可能是**姓名**
（批阅清单未解析到 id 时 `save_transcripts_to_drafts` 回落姓名）；
而前端列表固定用 `workAnswerId || name` 当键 → 表里显示"未跑"，
点开弹窗却有内容（弹窗另有兜底）。

本测试锁定三件事：
1. 引擎 `resolve_draft_key` 能按"草稿实际写在哪个键"给出正确键；
2. `/xxt/preview/students` 返回 `students[].key`，且与草稿键一致；
3. 前端表格与弹窗使用**同一取数口径**（源码级契约：两边都必须走兜底取数）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.xxt import grade_store


def _ws(tmp_path: Path) -> Path:
    (tmp_path / "classes" / "化工25" / "grading" / "pack1" / "drafts").mkdir(parents=True)
    return tmp_path


def _write_drafts(ws: Path, drafts: dict) -> Path:
    p = ws / "classes" / "化工25" / "grading" / "pack1" / "drafts" / "wid1.json"
    p.write_text(json.dumps(drafts, ensure_ascii=False), encoding="utf-8")
    return p


# ---------------- resolve_draft_key ----------------
def test_resolve_prefers_work_answer_id_when_draft_there():
    drafts = {"998877": {"ai": {"transcript": "x"}}}
    stu = {"name": "张三", "workAnswerId": "998877"}
    assert grade_store.resolve_draft_key(stu, drafts) == "998877"


def test_resolve_falls_back_to_name_when_draft_written_by_name(tmp_path: Path):
    """核心缺陷场景：草稿按**姓名**写，列表却只有 workAnswerId → 必须回落姓名。"""
    drafts = {"张三": {"ai": {"transcript": "x"}}}
    stu = {"name": "张三", "workAnswerId": "998877"}
    assert grade_store.resolve_draft_key(stu, drafts) == "张三"


def test_resolve_defaults_without_drafts():
    """两处都没有草稿时保持原口径（workAnswerId 优先），用于写新草稿。"""
    assert grade_store.resolve_draft_key({"name": "张三", "workAnswerId": "1"}, {}) == "1"
    assert grade_store.resolve_draft_key({"name": "张三"}, {}) == "张三"


def test_resolve_never_returns_empty_for_named_student():
    assert grade_store.resolve_draft_key({"name": "张三", "workAnswerId": ""}, {}) == "张三"


# ---------------- 端到端：写（按姓名）→ 读 → key ----------------
def test_save_transcripts_then_resolve_key(tmp_path: Path):
    """plan 缺 workAnswerId → 草稿落在姓名键；resolve_draft_key 仍能找到。"""
    from assist.grading.drafts import save_transcripts_to_drafts

    ws = _ws(tmp_path)
    tdir = ws / "transcripts"
    tdir.mkdir()
    (tdir / "张三.json").write_text(json.dumps({
        "student": "张三",
        "items": [{"no": "1", "printed_question": "q", "answer": "a", "diagrams": []}],
    }, ensure_ascii=False), encoding="utf-8")
    plan = {"taskId": "pack1", "classDir": "classes/化工25", "classId": "cid1",
            "workId": "wid1",
            "students": [{"name": "张三", "workAnswerId": "", "tag": "q1", "images": []}]}
    n = save_transcripts_to_drafts(ws, class_id="cid1", work_id="wid1", task_id="pack1",
                                  class_dir="classes/化工25", transcripts_dir=tdir,
                                  plan=plan)
    assert n == 1
    drafts = grade_store.read_drafts_normalized(
        str(ws / "xxt"), "cid1", "wid1", ws=ws, class_dir="classes/化工25",
        task_id="pack1")
    assert "张三" in drafts                       # 确实写在姓名键
    # 学生列表页只知道姓名 + workAnswerId（后来才解析到 id）
    stu = {"name": "张三", "workAnswerId": "998877"}
    key = grade_store.resolve_draft_key(stu, drafts)
    assert key == "张三"
    assert drafts[key]["ai"]["transcript"]      # 表格据此能显示「已转写」


def test_save_transcripts_then_resolve_key_with_work_answer_id(tmp_path: Path):
    """plan 有 workAnswerId → 草稿落在 id 键；同口径仍能读到。"""
    from assist.grading.drafts import save_transcripts_to_drafts

    ws = _ws(tmp_path)
    tdir = ws / "transcripts"
    tdir.mkdir()
    (tdir / "张三.json").write_text(json.dumps({
        "student": "张三",
        "items": [{"no": "1", "printed_question": "q", "answer": "a", "diagrams": []}],
    }, ensure_ascii=False), encoding="utf-8")
    plan = {"taskId": "pack1", "classDir": "classes/化工25", "classId": "cid1",
            "workId": "wid1",
            "students": [{"name": "张三", "workAnswerId": "998877", "tag": "q1",
                          "images": []}]}
    save_transcripts_to_drafts(ws, class_id="cid1", work_id="wid1", task_id="pack1",
                              class_dir="classes/化工25", transcripts_dir=tdir, plan=plan)
    drafts = grade_store.read_drafts_normalized(
        str(ws / "xxt"), "cid1", "wid1", ws=ws, class_dir="classes/化工25",
        task_id="pack1")
    assert "998877" in drafts
    assert grade_store.resolve_draft_key(
        {"name": "张三", "workAnswerId": "998877"}, drafts) == "998877"


# ---------------- 前端源码级契约（表与弹窗必须同源） ----------------
APP = Path(__file__).resolve().parents[2] / "app" / "src" / "components"


def test_panel_uses_single_draft_lookup():
    """表格取值必须经 `draftOf()`，不得再直接 `drafts[s.key]`（键可能不对）。"""
    src = (APP / "AiGradingPanel.vue").read_text(encoding="utf-8")
    assert "function draftOf(" in src
    # 表格数据列走 draftOf
    assert "draftOf(s).ai?.score" in src
    # AI 状态/报告模式也走 draftOf（此前直接 drafts[s.key]）
    assert "const d = draftOf(s)" in src
    # 不允许残留 `drafts[s.key]` 取数（那正是表/弹窗不一致的来源）。
    # 只检查**代码**（排除注释块），否则本文件自己的说明文字会误判。
    code_lines = [ln for ln in src.splitlines()
                  if not ln.lstrip().startswith(("*", "//", "/*"))]
    code = "\n".join(code_lines)
    assert "drafts[s.key]" not in code, "表格仍在直接用 s.key 取草稿"


def test_modal_uses_same_fallback_keys():
    """弹窗必须按 key → altKeys → name 兜底，与表格同口径。"""
    src = (APP / "StudentReviewModal.vue").read_text(encoding="utf-8")
    assert "altKeys" in src
    assert "props.drafts[k]" in src
    # 兜底顺序里必须包含姓名（历史按姓名写的草稿）
    assert "s.name" in src


def test_frontend_uses_engine_supplied_key():
    """学生清单必须优先用引擎给的 `key`（引擎知道草稿实际写在哪个键）。"""
    src = (APP / "AiGradingPanel.vue").read_text(encoding="utf-8")
    assert "s.key || s.workAnswerId || s.name" in src
