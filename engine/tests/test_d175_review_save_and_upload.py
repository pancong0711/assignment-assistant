"""D175：逐生审核"改批语+改分数"保存后没变化 / 上传分数恒为空 等缺陷。

教师反馈（第 20 轮）：
  1. 逐生「批阅」点了没变化，审核看不到批语与打分；
  2. 修改 AI 批语另存后，再改分数点保存没有变化；
  3. 想要"改 AI 批语另存 → 再改分数 → 一起作为作业批语"的**一个**功能键。

根因（本文件逐条锁死）：
  A. **报告**只打印 AI 分，教师在 human 套改的分不体现 → "改了分数报告没变化"；
  B. **上传**（`--from-drafts`）读原始草稿 + 只看顶层 `score/comment`（双套结构里没有）
     → 上传的分数/批语恒为空；
  C. 报告图回写草稿时**漏传 scope**，落到旧布局 → 报告预览永远"未生成"；
  D. 预览与保存是两套拼法 → 教师无法在保存前确认"最终发给学生的是什么"。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assist.grading import report as R
from assist.xxt import grade_store as GS
from assist.xxt.grade_upload import drafts_to_payloads, resolve_draft_effective

CID, WID, KEY, CDIR, TID = "c1", "w1", "wa1", "classes/A", "pack1"


@pytest.fixture()
def store(tmp_path: Path):
    home = tmp_path / "home"; ws = tmp_path / "ws"
    (ws / CDIR / "grading" / TID).mkdir(parents=True)
    home.mkdir()

    def save(**kw):
        return GS.save_draft_sets(home, CID, WID, KEY, student="张三",
                                  ws=ws, class_dir=CDIR, task_id=TID, **kw)
    return {"home": home, "ws": ws, "save": save}


def _draft(store) -> dict:
    raw = GS.read_drafts_normalized(store["home"], CID, WID, ws=store["ws"],
                                    class_dir=CDIR, task_id=TID)
    return raw[KEY]


# ---------------- A. 报告必须体现人工改分 ----------------

def test_report_shows_human_score_without_replace(store):
    """只改分数、不勾"替代 AI"（humanMode=none + human.used）→ 报告显示人工分。"""
    store["save"](ai={"score": 85, "comment": "AI 原文"},
                  human={"score": 76.0, "comment": "", "used": True}, human_mode="none")
    md, kind = R._mode_report_md(student="张三", **_drafts_args(_draft(store)))
    assert "76" in md and "AI 原分 85" in md
    assert kind == "ai"


def test_report_keeps_ai_score_when_no_human_score(store):
    store["save"](ai={"score": 85, "comment": "AI 原文"})
    md, _ = R._mode_report_md(student="张三", **_drafts_args(_draft(store)))
    assert "**AI 评分：** 85" in md


def _drafts_args(d: dict) -> dict:
    return {"ai": d.get("ai") or {}, "human": d.get("human") or {},
            "human_mode": d.get("humanMode") or "none",
            "revision": d.get("revision") or {}, "revised": bool(d.get("revised"))}


# ---------------- 报告与上传必须"同一口径" ----------------

@pytest.mark.parametrize("mode,revision,expected_score", [
    ("none", "", 76.0),
    ("none", "教师改过的批语", 76.0),
    ("replace", "", 76.0),
    ("append", "", 76.0),
    ("revise", "教师改过的批语", 76.0),
])
def test_report_and_upload_agree(store, mode, revision, expected_score):
    store["save"](ai={"score": 85, "comment": "AI 原文"},
                  human={"score": 76.0, "comment": "人工批语", "used": True},
                  human_mode=mode,
                  **({"revision": {"text": revision}} if revision else {}))
    d = _draft(store)
    md, _ = R._mode_report_md(student="张三", **_drafts_args(d))
    eff = resolve_draft_effective(d)
    assert eff["score"] == expected_score
    assert str(int(expected_score)) in md, "报告分数与上传分数必须一致"


# ---------------- B. 上传路径：双套草稿不再传空 ----------------

def test_upload_payload_reads_dual_set_draft(store):
    store["save"](ai={"score": 85, "comment": "AI 原文"},
                  human={"score": 76.0, "comment": "", "used": True}, human_mode="none",
                  revision={"text": "教师修订批语"})
    raw = GS.read_drafts_normalized(store["home"], CID, WID, ws=store["ws"],
                                    class_dir=CDIR, task_id=TID)
    pl = drafts_to_payloads(raw)[0]
    assert pl["score"] == 76.0, "教师改的分数必须上传（此前读顶层 score → 恒为空）"
    assert "教师修订批语" in pl["comment"]
    assert pl["student"] == "张三"


def test_upload_payload_legacy_single_set_still_works():
    """D92 之前的单套草稿 {score, comment} 仍按原样上传。"""
    pl = drafts_to_payloads({"k1": {"score": 90, "comment": "旧批语"}})[0]
    assert pl["score"] == 90 and pl["comment"] == "旧批语"


def test_effective_comment_by_mode():
    ai = {"score": 80, "comment": "AI"}
    human = {"score": 70, "comment": "人工", "used": True}
    assert resolve_draft_effective({"ai": ai, "human": human, "humanMode": "replace"})["comment"] == "人工"
    append = resolve_draft_effective({"ai": ai, "human": human, "humanMode": "append"})["comment"]
    assert "AI" in append and "人工" in append and "教师补充" in append
    rev = resolve_draft_effective({"ai": ai, "human": human, "humanMode": "revise",
                                   "revision": {"text": "修订"}})["comment"]
    assert rev == "修订"


# ---------------- C. 报告图回写必须在**同一份**草稿 ----------------

def test_render_reports_from_drafts_writes_same_scope(store, monkeypatch):
    """此前回写漏传 ws/class_dir/task_id → 落到旧布局，报告预览看不到。"""
    from assist.grading import drafts as D
    from assist.grading import report as _R
    store["save"](ai={"score": 90, "comment": "AI"})
    monkeypatch.setattr(_R, "html_to_png", lambda html, out: None)  # 不真渲染
    rep = D.render_reports_from_drafts(store["ws"], class_id=CID, work_id=WID,
                                       task_id=TID, class_dir=CDIR,
                                       home=store["home"], with_report_png=True)
    assert rep.get("ok") is True
    scoped = store["ws"] / CDIR / "grading" / TID / "drafts" / f"{WID}.json"
    legacy = store["home"] / "grade-drafts" / CID / f"{WID}.json"
    assert scoped.is_file(), "报告应写回 scoped 草稿"
    assert not legacy.is_file(), "不得再写旧布局（逐生审核读不到）"


# ---------------- D. 预览 == 保存后的报告 ----------------

def test_preview_matches_saved_report(store):
    """预览（未保存的编辑值）与保存后批量生成的报告必须逐字一致。"""
    from assist.grading.drafts import build_draft_report
    store["save"](ai={"score": 85, "comment": "AI 原文"})
    edited = GS.normalize_draft(_draft(store))
    edited["human"] = {"score": 72.0, "comment": "", "used": True}
    edited["revision"] = {"text": "教师改过的批语"}
    edited["humanMode"] = "none"
    edited["revised"] = GS._is_revised(edited)
    md_preview, kind_preview = build_draft_report(edited)
    # 真保存
    store["save"](human={"score": 72.0, "comment": "", "used": True},
                  human_mode="none", revision={"text": "教师改过的批语"})
    md_saved, kind_saved = build_draft_report(_draft(store))
    assert (md_preview, kind_preview) == (md_saved, kind_saved)
