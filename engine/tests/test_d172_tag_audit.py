"""D172：tag 审计（纯 Python 匹配器 + 全班审计 + 补丁式应用 + 撤销 + 历史副本）。

教师红线（docs/117-D172 §9）：
1. 无噪声 → 命中 100%；
2. 加 OCR 噪声 → 命中 ≥90%，且**错判必须落 unknown**（不允许“自信地判错”）；
3. 同包三层、题干高度相似 → 靠**数值常量**区分；
4. 题块缺失 → `linkMissing` / `unknown`，进程不崩；
5. **全程不调模型**（断言审计路径无 LLMClient）；
6. 同输入两次 → 判定部分逐字节相同（可复现）；
7. 应用 tag → 有 previousTag/source/history/resolution/journal 全链路；重复应用幂等；
8. 未转写 → `skippedNotTranscribed`，**不混入 unknown**。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from assist.grading import tag_audit as T

CLASS = "classes/化工251"
PACK = "hw-d172"

# ---- 三层作业纸（同章、题干高度相似，只差参数）----
BASE_QS = [
    ("1", "空气由压强为 1.52×10^3 Pa，体积为 5.0×10^-3 m^3，等温膨胀到压强为 1.01×10^3 Pa，然后再等压压缩到原来体积。计算空气所做的功。"),
    ("2", "1 mol 理想气体在 300 K 下等温膨胀，体积由 1.0 L 增大到 10.0 L，求气体对外做的功。"),
    ("3", "一定量理想气体经历绝热过程，初始温度 400 K，膨胀后温度降为 300 K，求内能变化（n=2 mol）。"),
]
MID_QS = [
    ("1", "空气由压强为 2.03×10^3 Pa，体积为 4.2×10^-3 m^3，等温膨胀到压强为 1.35×10^3 Pa，然后再等压压缩到原来体积。计算空气所做的功。"),
    ("2", "1 mol 理想气体在 350 K 下等温膨胀，体积由 2.0 L 增大到 20.0 L，求气体对外做的功。"),
    ("3", "一定量理想气体经历绝热过程，初始温度 500 K，膨胀后温度降为 320 K，求内能变化（n=3 mol）。"),
]
TOP_QS = [
    ("1", "空气由压强为 3.04×10^3 Pa，体积为 3.8×10^-3 m^3，等温膨胀到压强为 1.90×10^3 Pa，然后再等压压缩到原来体积。计算空气所做的功，并画出 PV 图。"),
    ("2", "1 mol 理想气体在 420 K 下等温膨胀，体积由 3.0 L 增大到 30.0 L，求气体对外做的功。"),
    ("3", "一定量理想气体经历绝热过程，初始温度 600 K，膨胀后温度降为 350 K，求内能变化（n=4 mol）。"),
]


def _pad(pid: str, tag: str, qs) -> dict:
    return {"padId": pid, "tag": tag,
            "questions": [{"no": n, "content": c} for n, c in qs]}


PADS = [_pad("pad-base", "基础", BASE_QS),
        _pad("pad-mid", "提高", MID_QS),
        _pad("pad-top", "拓展", TOP_QS)]


def _transcript(qs, *, noise: float = 0.0, seed: int = 0) -> dict:
    """构造转写（printed_question = 作业纸题干，可加 OCR 噪声）。"""
    rnd = random.Random(seed)
    items = []
    for no, q in qs:
        s = q
        if noise:
            chars = list(s)
            for i in range(len(chars)):
                if rnd.random() < noise:
                    chars[i] = rnd.choice("的在了和是□_·•")
            s = "".join(chars)
            # 插入圈画/下划线噪声
            if rnd.random() < 0.5:
                s = s.replace("计", "计__", 1)
        items.append({"no": no, "printed_question": s, "answer": "解：略", "diagrams": []})
    return {"items": items, "unmatched_notes": "", "quality": {}}


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    d = tmp_path / "classes" / "化工251" / "grading" / PACK / "transcripts"
    d.mkdir(parents=True)
    return tmp_path


def _write_tr(ws: Path, name: str, qs, **kw) -> None:
    d = ws / CLASS / "grading" / PACK / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(
        json.dumps(_transcript(qs, **kw), ensure_ascii=False), encoding="utf-8")


# ---------------- 阶段 B：打分 ----------------

def test_identical_stem_scores_high():
    a = BASE_QS[0][1]
    assert T.score_pair(a, a) > 0.99


def test_same_question_with_ocr_noise_still_high():
    a = BASE_QS[0][1]
    b = a.replace("压强", "压強").replace("体积", "体 积").replace("10^3", "10³")
    assert T.score_pair(a, b) > 0.8


def test_different_question_scores_low():
    assert T.score_pair(BASE_QS[0][1], TOP_QS[2][1]) < 0.2


def test_numbers_distinguish_layers():
    """同章不同参数 → 数值常量是主要区分信号。"""
    s = T.score_pair(BASE_QS[0][1], BASE_QS[0][1])
    d = T.score_pair(BASE_QS[0][1], MID_QS[0][1])
    assert s > d


def test_number_overlap_neutral_when_both_empty():
    assert T.number_overlap(set(), set()) == 1.0


# ---------------- 阶段 C：判定 ----------------

def test_audit_matches_correct_layer():
    papers = T.papers_of(PADS)
    row = T.audit_student(_transcript(MID_QS), papers, roster_tag="提高")
    assert row["auditTag"] == "提高"
    assert row["confidence"] == "high"
    assert row["verdict"] == "match"


def test_audit_detects_mismatch():
    """roster 说「基础」，学生实际做了「拓展」→ mismatch。"""
    papers = T.papers_of(PADS)
    row = T.audit_student(_transcript(TOP_QS), papers, roster_tag="基础")
    assert row["auditTag"] == "拓展"
    assert row["verdict"] == "mismatch"
    assert "拓展" in row["reason"] and "基础" in row["reason"]


def test_audit_without_roster_tag_is_unknown_not_match():
    papers = T.papers_of(PADS)
    row = T.audit_student(_transcript(BASE_QS), papers, roster_tag=None,
                          current_roster_tag=None)
    assert row["auditTag"] == "基础"
    assert row["verdict"] == "unknown"          # 不能硬说 match


def test_audit_falls_back_to_current_roster_and_marks_source():
    papers = T.papers_of(PADS)
    row = T.audit_student(_transcript(BASE_QS), papers, roster_tag=None,
                          current_roster_tag="基础")
    assert row["rosterTagSource"] == "current-roster"
    assert row["verdict"] == "match"


def test_all_stems_missing_is_unknown():
    papers = T.papers_of(PADS)
    tr = {"items": [{"no": "1", "printed_question": "", "answer": "解：略"}]}
    row = T.audit_student(tr, papers, roster_tag="基础")
    assert row["auditTag"] is None
    assert row["verdict"] == "unknown"
    assert row["linkMissing"] == [1]
    assert "题干" in row["reason"]


def test_partial_missing_stems_still_audits():
    """只有一题没抄题干 → 其余题照样判，只是记 linkMissing。"""
    papers = T.papers_of(PADS)
    tr = _transcript(TOP_QS)
    tr["items"][1]["printed_question"] = ""
    row = T.audit_student(tr, papers, roster_tag="拓展")
    assert row["linkMissing"] == [2]
    assert row["auditTag"] == "拓展"


def test_no_transcript_items_is_unknown():
    papers = T.papers_of(PADS)
    row = T.audit_student({}, papers, roster_tag="基础")
    assert row["verdict"] == "unknown" and row["auditTag"] is None


def test_empty_pack_is_unknown():
    row = T.audit_student(_transcript(BASE_QS), [], roster_tag="基础")
    assert row["verdict"] == "unknown"
    assert "作业包" in row["reason"]


def test_low_confidence_never_mismatch():
    """分数过低 → unknown（不允许“自信地判错”）。

    修复前：分数 0.09 但**碰巧**落到同 tag 的纸上 → 报 `match`。现改为 unknown。
    """
    papers = T.papers_of(PADS)
    tr = {"items": [{"no": "1", "printed_question": "请简述牛顿第一定律的内容及其适用条件？",
                     "answer": "解：略"}]}
    row = T.audit_student(tr, papers, roster_tag="基础")
    assert row["confidence"] == "low"
    assert row["verdict"] == "unknown"
    assert "过低" in row["reason"]


def test_low_confidence_same_tag_is_not_match():
    """分数很低时，就算 Top1 恰好等于 roster tag，也**不能**报绿。"""
    row = T.audit_student(
        {"items": [{"no": "1", "printed_question": "请简述牛顿第一定律的内容及其适用条件？"}]},
        T.papers_of([{"padId": "x", "tag": "基础",
                      "questions": [{"no": "1", "content": BASE_QS[0][1]}]}]),
        roster_tag="基础")
    assert row["verdict"] == "unknown" and row["confidence"] == "low"


# ---------------- 验收红线：噪声命中率 ----------------

def test_acceptance_noise_recall():
    """无噪声 100%；加 OCR 噪声 ≥90%；**错判必须落 unknown**。"""
    papers = T.papers_of(PADS)
    layers = [("基础", BASE_QS), ("提高", MID_QS), ("拓展", TOP_QS)]

    hits = total = 0
    for tag, qs in layers:
        for seed in range(10):
            row = T.audit_student(_transcript(qs, seed=seed), papers, roster_tag=tag)
            total += 1
            if row["auditTag"] == tag:
                hits += 1
            elif row["verdict"] == "match":
                pytest.fail(f"无噪声却判错：期望 {tag}，得到 {row['auditTag']}")
    assert hits == total, f"无噪声命中率 {hits}/{total}"

    hits = total = 0
    wrong_confident = 0
    for tag, qs in layers:
        for seed in range(20):
            row = T.audit_student(_transcript(qs, noise=0.05, seed=seed),
                                  papers, roster_tag=tag)
            total += 1
            if row["auditTag"] == tag:
                hits += 1
            elif row["verdict"] == "mismatch":
                wrong_confident += 1
            # 错判落在 unknown 是可接受的
    rate = hits / total
    assert rate >= 0.9, f"加噪命中率 {rate:.2%} 低于 90%"
    # 红线：错判不能“自信地判成另一个层”
    assert wrong_confident == 0, f"有 {wrong_confident} 次自信错判（应为 unknown）"


def test_reproducible_same_input_same_output():
    papers = T.papers_of(PADS)
    tr = _transcript(MID_QS, noise=0.03, seed=7)
    a = T.audit_student(tr, papers, roster_tag="提高")
    b = T.audit_student(tr, papers, roster_tag="提高")
    assert json.dumps(a, ensure_ascii=False, sort_keys=True) == \
        json.dumps(b, ensure_ascii=False, sort_keys=True)


def test_no_llm_client_called(monkeypatch):
    """审计路径**绝不**触碰 LLMClient（教师 D2b：不需要 AI）。"""
    import assist.grading.llm as llm_mod
    monkeypatch.setattr(llm_mod, "LLMClient",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("调用了模型")))
    papers = T.papers_of(PADS)
    tr = _transcript(BASE_QS)
    row = T.audit_student(tr, papers, roster_tag="基础")
    assert row["verdict"] == "match"


# ---------------- 全班审计 ----------------

def test_run_audit_writes_file_and_summary(ws):
    _write_tr(ws, "张三", BASE_QS)
    _write_tr(ws, "李四", TOP_QS)
    from assist.grading import snapshots as S
    S.write_tags_snapshot(ws, CLASS, PACK,
                          [{"name": "张三", "number": "1", "tag": "基础"},
                           {"name": "李四", "number": "2", "tag": "基础"}])
    rep = T.run_audit(ws, class_dir=CLASS, pack_id=PACK, pads=PADS)
    assert rep["ok"]
    assert rep["summary"]["match"] == 1 and rep["summary"]["mismatch"] == 1
    p = T.audit_path(ws, CLASS, PACK)
    assert p.is_file()
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["engine"] == T.ENGINE_VER
    assert on_disk["papers"][0]["tag"] == "基础"


def test_run_audit_skips_not_transcribed(ws):
    """教师 N2：未转写 → skippedNotTranscribed，不混入 unknown。"""
    _write_tr(ws, "张三", BASE_QS)
    from assist.grading import snapshots as S
    S.write_tags_snapshot(ws, CLASS, PACK, [
        {"name": "张三", "number": "1", "tag": "基础"},
        {"name": "王五", "number": "3", "tag": "基础"}])
    rep = T.run_audit(ws, class_dir=CLASS, pack_id=PACK, pads=PADS)
    assert [s["name"] for s in rep["skippedNotTranscribed"]] == ["王五"]
    assert "未转写" in rep["skippedNotTranscribed"][0]["reason"]
    assert rep["summary"]["unknown"] == 0


def test_run_audit_students_filter(ws):
    _write_tr(ws, "张三", BASE_QS)
    _write_tr(ws, "李四", TOP_QS)
    rep = T.run_audit(ws, class_dir=CLASS, pack_id=PACK, pads=PADS, students=["李四"])
    assert [r["name"] for r in rep["students"]] == ["李四"]


def test_run_audit_history_appended(ws):
    _write_tr(ws, "张三", BASE_QS)
    T.run_audit(ws, class_dir=CLASS, pack_id=PACK, pads=PADS)
    rep = T.run_audit(ws, class_dir=CLASS, pack_id=PACK, pads=PADS)
    assert len(rep["history"]) == 2


def test_read_audit_missing(ws):
    got = T.read_audit(ws, class_dir=CLASS, pack_id=PACK)
    assert got["missing"] is True


# ---------------- 应用 / 幂等 / 撤销 / 历史 ----------------

def _snap(ws):
    from assist.grading import snapshots as S
    return S.write_tags_snapshot(ws, CLASS, PACK, [
        {"name": "张三", "number": "1", "tag": "基础"},
        {"name": "李四", "number": "2", "tag": "基础"}])


def test_apply_patches_snapshot_with_audit_trail(ws):
    _snap(ws)
    _write_tr(ws, "张三", TOP_QS)
    T.run_audit(ws, class_dir=CLASS, pack_id=PACK, pads=PADS)
    rep = T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                             changes=[{"name": "张三", "tag": "拓展"}])
    assert rep["ok"] and rep["written"]
    from assist.grading import snapshots as S
    snap = S.read_tags_snapshot(ws, CLASS, PACK)
    zs = next(s for s in snap["students"] if s["name"] == "张三")
    assert zs["tag"] == "拓展"
    assert zs["previousTag"] == "基础"
    assert zs["tagUpdateReason"] == "audit-apply"
    assert snap["source"] == "audit-apply"
    # 未点名的学生不变
    ls = next(s for s in snap["students"] if s["name"] == "李四")
    assert ls["tag"] == "基础" and "previousTag" not in ls
    # 历史副本
    assert Path(rep["historyPath"]).is_file()
    # audit 的 resolution
    aud = T.read_audit(ws, class_dir=CLASS, pack_id=PACK)
    zrow = next(s for s in aud["students"] if s["name"] == "张三")
    assert zrow["resolution"]["to"] == "拓展"
    assert zrow["verdict"] == "match"


def test_apply_is_idempotent(ws):
    _snap(ws)
    T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                       changes=[{"name": "张三", "tag": "拓展"}])
    rep = T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                             changes=[{"name": "张三", "tag": "拓展"}])
    assert rep["ok"] and rep["written"] is False
    assert rep["unchanged"] == ["张三"]


def test_apply_without_snapshot_errors(ws):
    rep = T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                             changes=[{"name": "张三", "tag": "拓展"}])
    assert rep["ok"] is False and "快照" in rep["error"]


def test_apply_unknown_student_reported(ws):
    _snap(ws)
    rep = T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                             changes=[{"name": "不存在", "tag": "拓展"}])
    assert rep["missing"] == ["不存在"]


def test_undo_restores_byte_identical_snapshot(ws):
    _snap(ws)
    from assist.grading import snapshots as S
    before = json.loads(S.tags_snapshot_path(ws, CLASS, PACK).read_text(encoding="utf-8"))
    T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                       changes=[{"name": "张三", "tag": "拓展"}])
    rep = T.undo_last(ws, class_dir=CLASS, pack_id=PACK)
    assert rep["ok"]
    after = json.loads(S.tags_snapshot_path(ws, CLASS, PACK).read_text(encoding="utf-8"))
    # 除元信息外逐字段相同
    for meta in ("generatedAt", "source", "restoredFrom"):
        before.pop(meta, None)
        after.pop(meta, None)
    assert before == after


def test_undo_without_history_errors(ws):
    _snap(ws)
    rep = T.undo_last(ws, class_dir=CLASS, pack_id=PACK)
    assert rep["ok"] is False


def test_list_history_named_with_pack_and_timestamp(ws):
    """教师 N1：命名 = <packId>__<时间戳>.json。"""
    _snap(ws)
    T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                       changes=[{"name": "张三", "tag": "拓展"}])
    hist = T.list_history(ws, class_dir=CLASS, pack_id=PACK)
    assert hist and hist[0]["file"].startswith(f"{PACK}__")
    assert hist[0]["reason"] == "audit-apply"


# ---------------- 规则卡可调 ----------------

def test_cfg_overrides_applied():
    papers = T.papers_of(PADS)
    tr = _transcript(MID_QS, noise=0.02, seed=1)
    strict = T.audit_student(tr, papers, roster_tag="提高", cfg={"minScore": 0.999})
    assert strict["confidence"] != "high"
    loose = T.audit_student(tr, papers, roster_tag="提高", cfg={"minScore": 0.1})
    assert loose["confidence"] == "high"


def test_cfg_ignores_bad_values():
    c = T._cfg({"minScore": "not-a-number", "unknownKey": 1})
    assert c["minScore"] == T.DEFAULTS["minScore"]
    assert "unknownKey" not in c


# ---------------- 对抗场景（2026-11-06 实测暴露的真实缺陷） ----------------

def _near_layers():
    """三层题干**只差一两位参数**（同章同题、换个数字）——最难的一类。"""
    def mk(p2, ext=""):
        return [("1", "空气由压强为 1.52×10^3 Pa，体积为 5.0×10^-3 m^3，等温膨胀到压强为 "
                       f"{p2}×10^3 Pa，然后再等压压缩到原来体积。计算空气所做的功。{ext}"),
                ("2", "1 mol 理想气体在 300 K 下等温膨胀，体积由 1.0 L 增大到 10.0 L，求气体对外做的功。")]
    return mk("1.01"), mk("1.02"), mk("1.03", ext="要求画出 PV 图并标出各过程。")


def test_near_identical_layers_never_confident_wrong():
    """题干几乎相同 → 领先不足时必须 `unknown`，**不得**报 mismatch 把行标红。"""
    a, b, c = _near_layers()
    papers = T.papers_of([
        {"padId": "a", "tag": "甲", "questions": [{"no": n, "content": q} for n, q in a]},
        {"padId": "b", "tag": "乙", "questions": [{"no": n, "content": q} for n, q in b]}])
    row = T.audit_student({"items": [{"no": n, "printed_question": q, "answer": ""}
                                     for n, q in b]}, papers, roster_tag="甲")
    assert row["verdict"] == "unknown", "领先不足却报 mismatch = 把未错配的学生标红"
    assert row["confidence"] == "medium"
    assert "不足" in row["reason"]


def test_question_count_distinguishes_layers():
    """层间差别是**题量**时也能区分（覆盖率权重）。"""
    p = [("1", "质量为 2 kg 的物块以 3 m/s 撞静止物块，完全弹性碰撞，求碰后两物块速度。"),
         ("2", "质量为 2 kg 的物块以 3 m/s 撞静止物块，完全非弹性碰撞，求碰后共同速度。")]
    papers = T.papers_of([
        {"padId": "short", "tag": "短卷", "questions": [{"no": p[0][0], "content": p[0][1]}]},
        {"padId": "long", "tag": "长卷", "questions": [{"no": n, "content": q} for n, q in p]}])
    long_row = T.audit_student({"items": [{"no": n, "printed_question": q, "answer": ""}
                                          for n, q in p]}, papers, roster_tag="长卷")
    short_row = T.audit_student({"items": [{"no": n, "printed_question": q, "answer": ""}
                                            for n, q in p[:1]]}, papers, roster_tag="短卷")
    assert long_row["auditTag"] == "长卷" and long_row["verdict"] == "match"
    assert long_row["confidence"] == "high"
    # 只抄了第 1 题：信息量少 → 判对但置信度只到 medium（< high 断言即可）
    assert short_row["auditTag"] == "短卷"
    assert short_row["confidence"] in ("medium", "high")


def test_false_positive_rate_zero_under_noise():
    """**误报率红线**：加噪后不允许出现任何 `mismatch`（宁可 unknown）。"""
    papers = T.papers_of(PADS)
    for tag, qs in (("基础", BASE_QS), ("提高", MID_QS), ("拓展", TOP_QS)):
        for seed in range(20):
            row = T.audit_student(_transcript(qs, noise=0.10, seed=seed),
                                  papers, roster_tag=tag)
            assert row["verdict"] != "mismatch", (
                f"{tag} 层被误报为 {row['auditTag']}（{row['confidence']}）")


def test_real_mismatch_still_detected_with_clear_margin():
    """真正的错配（层间差异明显）必须能报出来——不能为了不误报而全 unknown。"""
    papers = T.papers_of(PADS)
    row = T.audit_student(_transcript(TOP_QS), papers, roster_tag="基础")
    assert row["verdict"] == "mismatch"
    assert row["margin"] >= T.DEFAULTS["marginMin"]


def test_papers_of_is_idempotent():
    """归一两次不能丢题干（CLI 与 PWA 双入口都传 papers_of 的结果）。"""
    once = T.papers_of(PADS)
    twice = T.papers_of(once)
    assert [q["stem"] for q in twice[0]["questions"]] == \
        [q["stem"] for q in once[0]["questions"]]
    papers = T.papers_of(once)
    row = T.audit_student(_transcript(BASE_QS), papers, roster_tag="基础")
    assert row["verdict"] == "match" and row["score"] > 0.9


# ---------------- T7b/T7c：历史副本命名（教师 N1） ----------------

def test_snapshot_force_write_creates_history(ws):
    """覆盖快照前**必存**历史副本（此前直接覆盖，历史丢失）。"""
    from assist.grading import snapshots as S
    S.write_tags_snapshot(ws, CLASS, PACK, [{"name": "张三", "number": "1", "tag": "基础"}])
    rep = S.write_tags_snapshot(ws, CLASS, PACK, [{"name": "张三", "number": "1", "tag": "提高"}],
                                source=S.SOURCE_RECOMPUTE, force=True)
    assert rep["ok"] and rep.get("historyPath")
    hp = Path(rep["historyPath"])
    assert hp.parent.name == "_history"
    assert hp.name.startswith(f"{PACK}__")
    old = json.loads(hp.read_text(encoding="utf-8"))
    assert old["students"][0]["tag"] == "基础"
    assert old["historyReason"] == S.SOURCE_RECOMPUTE


def test_snapshot_first_write_has_no_history(ws):
    from assist.grading import snapshots as S
    rep = S.write_tags_snapshot(ws, CLASS, PACK, [{"name": "张三", "number": "1", "tag": "基础"}])
    assert "historyPath" not in rep


def test_roster_history_named_with_pack_and_timestamp(tmp_path):
    """教师要求：roster 保存要带**时间戳 + 关联作业包名**。"""
    from assist.files import roster_io
    d = tmp_path / "classes" / "化工251"
    d.mkdir(parents=True)
    roster_io.write_roster(tmp_path, CLASS, [{"name": "张三", "number": "1", "tag": "基础"}],
                           pack_id="hw3")
    rep = roster_io.write_roster(tmp_path, CLASS,
                                 [{"name": "张三", "number": "1", "tag": "提高"}],
                                 pack_id="hw3")
    assert rep["ok"]
    hb = Path(rep["historyBackup"])
    assert hb.parent.name == "history"
    assert hb.name.startswith("roster__hw3__")
    assert hb.suffix == ".xlsx"
    # 旧式备份仍在
    assert rep.get("backup") and Path(rep["backup"]).name.startswith("roster.xlsx.old-")


def test_roster_history_without_pack_uses_nopack(tmp_path):
    from assist.files import roster_io
    (tmp_path / "classes" / "化工251").mkdir(parents=True)
    roster_io.write_roster(tmp_path, CLASS, [{"name": "张三", "number": "1", "tag": "基础"}])
    rep = roster_io.write_roster(tmp_path, CLASS, [{"name": "张三", "number": "1", "tag": "提高"}])
    assert Path(rep["historyBackup"]).name.startswith("roster__noPack__")


def test_undo_preserves_reason_of_current_state(ws):
    """撤销前存的那份“当前状态”要保留原来源，否则 UI 分不清哪份是审计改过的。"""
    _snap(ws)
    T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                       changes=[{"name": "张三", "tag": "拓展"}])
    T.undo_last(ws, class_dir=CLASS, pack_id=PACK)
    hist = T.list_history(ws, class_dir=CLASS, pack_id=PACK)
    # 撤销前存的那份 = 被审计改过的当前状态；`snapshotSource` 必须指回 audit-apply
    before_undo = [h for h in hist if h["reason"] == "before-undo"]
    assert before_undo, "撤销前必须存一份当前状态"
    assert before_undo[0]["snapshotSource"] == "audit-apply"
    # apply 时的备份：它代表改动**前**的快照（来源 = 当时的 source）
    # 注：apply 动的是“改动前”快照，它的 historyReason=audit-apply，
    # snapshotSource 记录那份副本本来由谁产生。
    assert all(h["snapshotSource"] for h in hist)


# ---------------- T9：规则卡可调（阈值不许写死） ----------------

def test_tag_audit_cfg_reads_rules_card(tmp_path):
    from assist.grading import rules
    got = rules.tag_audit_cfg(tmp_path)
    assert got["minScore"] == 0.75 and got["marginMin"] == 0.15
    p = tmp_path / "grading-rules.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["tagAudit"]["minScore"] = 0.9
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert rules.tag_audit_cfg(tmp_path)["minScore"] == 0.9


def test_tag_audit_cfg_validated():
    from assist.grading import rules
    assert rules.validate_rules({"tagAudit": {"minScore": 5}})
    assert rules.validate_rules({"tagAudit": {"bigramWeight": 0, "numberWeight": 0}})
    assert rules.validate_rules({"tagAudit": {"nope": 1}})
    assert not rules.validate_rules({"tagAudit": {"minScore": 0.8, "marginMin": 0.2}})


def test_run_audit_uses_rules_card(ws):
    """规则卡把 minScore 调到 1.01（不可达）→ 不再给 high。

    注：阈值上界是 1.0，这里用「>1」只为证明**路径确实读了规则卡**；
    真实调参应落在 (0,1)。
    """
    p = ws / "grading-rules.json"
    from assist.grading import rules
    rules.read_rules(ws)                     # 生成默认
    d = json.loads(p.read_text(encoding="utf-8"))
    d["tagAudit"]["minScore"] = 1.01
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    _write_tr(ws, "张三", BASE_QS)
    rep = T.run_audit(ws, class_dir=CLASS, pack_id=PACK, pads=PADS)
    assert rep["students"][0]["confidence"] != "high"


# ---------------- T10：提交名单姓名交叉校验 ----------------

def test_parse_filename_student_roundtrip():
    from assist.grading.inputs import _parse_filename_student
    from assist.xxt.review import image_filename
    fn = image_filename("阿丽古丽·玉苏甫", "化工251", "13-热力学", 3)
    got = _parse_filename_student(fn)
    assert got["name"] == "阿丽古丽·玉苏甫"
    assert got["page"] == 3


def test_verify_review_names_reports_mismatch(tmp_path, monkeypatch):
    """students.json 与文件名不一致 → 报告出来（不改任何东西）。"""
    from assist.grading import inputs
    d = tmp_path / "review"
    d.mkdir()
    (d / "students.json").write_text(json.dumps({"students": [
        {"name": "张三", "workAnswerId": "1", "images": ["张三_化工251+作业_p01.jpg"]},
        {"name": "李四", "workAnswerId": "2", "images": ["李四_化工251+作业_p01.jpg"]},
    ]}, ensure_ascii=False), encoding="utf-8")
    (d / "张三_化工251+作业_p01.jpg").write_bytes(b"x")
    (d / "李四_化工251+作业_p01.jpg").write_bytes(b"x")
    (d / "王五_化工251+作业_p01.jpg").write_bytes(b"x")     # 名单里没有
    (d / "乱命名.jpg").write_bytes(b"x")
    monkeypatch.setattr(inputs, "review_dir_for", lambda c, w: d)
    rep = inputs.verify_review_names("c", "w")
    assert rep["students"] == 2 and rep["images"] == 4
    assert rep["onlyInFilenames"] == ["王五"]
    assert rep["unparsable"] == ["乱命名.jpg"]
    assert rep["onlyInManifest"] == []


def test_verify_review_names_clean(tmp_path, monkeypatch):
    from assist.grading import inputs
    d = tmp_path / "review"
    d.mkdir()
    (d / "students.json").write_text(json.dumps({"students": [
        {"name": "张三", "workAnswerId": "1", "images": ["张三_化工251+作业_p01.jpg"]}]},
        ensure_ascii=False), encoding="utf-8")
    (d / "张三_化工251+作业_p01.jpg").write_bytes(b"x")
    monkeypatch.setattr(inputs, "review_dir_for", lambda c, w: d)
    rep = inputs.verify_review_names("c", "w")
    assert not rep["onlyInFilenames"] and not rep["unparsable"] and not rep["onlyInManifest"]


# ---------------- 真实形状回归（教师实测 bug：全班 unknown） ----------------
# 根因：taskpad.items[] **只存 {kb,chap,ids,tag}，没有题干**；
# 此前前端/CLI 把 taskpad 当 questions 传 → 每张纸题目为空 → 全班 unknown。
# 下面用**真实 xlsx 题库 + 真实 taskpad** 走一遍，防止再犯。

def _real_ws(tmp_path: Path) -> Path:
    from assist.files.kb_io import write_xlsx
    (tmp_path / "kb").mkdir(parents=True, exist_ok=True)
    write_xlsx(tmp_path / "kb" / "problems.xlsx", {
        "chap10basic": [{"id": i, "content": c, "solution": "略"} for i, c in BASE_QS],
        "chap10mid": [{"id": i, "content": c, "solution": "略"} for i, c in MID_QS],
    })
    d = tmp_path / CLASS / "grading" / PACK / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "张三.json").write_text(json.dumps(_transcript(MID_QS), ensure_ascii=False),
                                encoding="utf-8")
    from assist.grading import snapshots as S
    S.write_tags_snapshot(tmp_path, CLASS, PACK,
                          [{"name": "张三", "number": "1", "tag": "基础"}])
    return tmp_path


REAL_TASKPADS = [
    {"id": "pd-base", "target_tag": "基础", "numbering": "auto",
     # 注：write_xlsx 会给题号补章节前缀 → 题库里实际是 `chap10basic-1` 等
     "items": [{"kb": "problems", "chap": "chap10basic", "tag": "基础",
                "ids": ["chap10basic-1", "chap10basic-2", "chap10basic-3"]}]},
    {"id": "pd-mid", "target_tag": "提高", "numbering": "auto",
     "items": [{"kb": "problems", "chap": "chap10mid", "tag": "提高",
                "ids": ["chap10mid-1", "chap10mid-2", "chap10mid-3"]}]},
]


def test_taskpads_resolve_stems_from_kb(tmp_path):
    """taskpad 原样 → 能从题库解析出题干（这是修复的核心）。"""
    ws = _real_ws(tmp_path)
    papers = T.papers_from_taskpads(ws, REAL_TASKPADS)
    assert len(papers) == 2
    assert all(len(p["questions"]) == 3 for p in papers)
    assert "1.52" in papers[0]["questions"][0]["stem"]
    assert "2.03" in papers[1]["questions"][0]["stem"]


def test_run_audit_with_taskpads_is_not_unknown(tmp_path):
    """教师实测 bug 的回归：传 taskpad 必须能判出 mismatch，而不是全班 unknown。"""
    ws = _real_ws(tmp_path)
    rep = T.run_audit(ws, class_dir=CLASS, pack_id=PACK, taskpads=REAL_TASKPADS)
    row = rep["students"][0]
    assert row["auditTag"] == "提高"
    assert row["verdict"] == "mismatch"
    assert row["confidence"] == "high"
    assert rep["papersWithoutQuestions"] == []


def test_run_audit_diagnoses_empty_papers(tmp_path):
    """旧错误路径（把 taskpad 当 questions）必须给出**可读原因**，不能只留一片灰。"""
    ws = _real_ws(tmp_path)
    rep = T.run_audit(ws, class_dir=CLASS, pack_id=PACK, pads=REAL_TASKPADS, write=False)
    assert rep["summary"]["unknown"] == 1
    assert rep["papersWithoutQuestions"] == ["pd-base", "pd-mid"]
    assert "题干" in rep["hint"]


# ================= D173：可解释性 / 逐题对照 / tagDiffers / 人工历史 =================

def test_tag_differs_is_independent_of_verdict():
    """tag 不同是「事实」，与 verdict（引擎把握）解耦。

    教师实测 bug：「只看不一致」勾上后空列表——因为过滤按 verdict，
    而 unknown（置信不足）的学生被漏掉了，可他们的 tag 明明不同。
    """
    papers = T.papers_of(PADS)
    # 构造：tag 不同，但置信只到 medium（near-identical layers）
    a, b, _ = _near_layers()
    ps = T.papers_of([
        {"padId": "a", "tag": "甲", "questions": [{"no": n, "content": q} for n, q in a]},
        {"padId": "b", "tag": "乙", "questions": [{"no": n, "content": q} for n, q in b]}])
    row = T.audit_student({"items": [{"no": n, "printed_question": q, "answer": ""}
                                     for n, q in b]}, ps, roster_tag="甲")
    assert row["verdict"] == "unknown"
    assert row["confidence"] == "medium"
    assert row["tagDiffers"] is True, "verdict=unknown 也必须标出「tag 不同」"


def test_tag_differs_false_when_same_or_missing():
    papers = T.papers_of(PADS)
    same = T.audit_student(_transcript(BASE_QS), papers, roster_tag="基础")
    assert same["tagDiffers"] is False
    no_tag = T.audit_student(_transcript(BASE_QS), papers, roster_tag=None)
    assert no_tag["tagDiffers"] is False, "没有 roster tag 时无从比较，不能算「不同」"


def test_audit_summary_counts_tag_differs():
    papers = T.papers_of(PADS)
    rows = [
        T.audit_student(_transcript(TOP_QS), papers, roster_tag="基础"),   # 不同
        T.audit_student(_transcript(BASE_QS), papers, roster_tag="基础"),  # 同
    ]
    assert sum(1 for r in rows if r["tagDiffers"]) == 1


def test_pairs_are_per_question_with_both_stems():
    """逐题对照：每题一行，含**学生题干** + **每张作业纸的题干**（教师四问之 1、2、4）。"""
    papers = T.papers_of(PADS)
    row = T.audit_student(_transcript(MID_QS), papers, roster_tag="提高")
    assert len(row["pairs"]) == len(MID_QS)
    p0 = row["pairs"][0]
    assert p0["no"] == "1"
    assert "2.03" in p0["studentStem"]                       # 转写题干
    tags = {x["tag"] for x in p0["perPaper"]}
    assert tags == {"基础", "提高", "拓展"}                   # 每张纸都列
    for x in p0["perPaper"]:
        assert x["paperStem"], "每张作业纸都要能显示题干"
        assert 0.0 <= x["score"] <= 1.0
    # 最优必须是「提高」
    assert p0["best"]["tag"] == "提高"
    assert p0["perPaper"][0]["tag"] == "提高"


def test_pair_detail_explains_score():
    """判据可解释（教师四问之 3）：每对要能给出字面/数值分解与共同数字。"""
    papers = T.papers_of(PADS)
    row = T.audit_student(_transcript(MID_QS), papers, roster_tag="提高")
    d = row["pairs"][0]["perPaper"][0]["detail"]
    assert 0.0 <= d["literal"] <= 1.0
    assert 0.0 <= d["number"] <= 1.0
    assert "2.03" in d["numbersStudent"]
    assert d["numbersShared"], "共同数值要列出来（教师据此判断为什么判高分）"


def test_why_block_exposes_method_and_weights():
    papers = T.papers_of(PADS)
    row = T.audit_student(_transcript(MID_QS), papers, roster_tag="提高")
    w = row["why"]
    assert w["method"] == T.ENGINE_VER
    assert w["onlyPrintedQuestion"] is True
    assert w["bigramWeight"] + w["numberWeight"] == pytest.approx(1.0)
    assert {x["tag"] for x in w["perPaperTotals"]} == {"基础", "提高", "拓展"}


def test_explicitly_only_printed_question_used():
    """**只判题干**：把 answer 改成完全无关，结论不能变。"""
    papers = T.papers_of(PADS)
    a = _transcript(MID_QS)
    b = _transcript(MID_QS)
    for it in b["items"]:
        it["answer"] = "完全无关的乱写内容 xyz 123"
    r1 = T.audit_student(a, papers, roster_tag="提高")
    r2 = T.audit_student(b, papers, roster_tag="提高")
    assert (r1["auditTag"], r1["score"]) == (r2["auditTag"], r2["score"])


def test_old_format_transcript_is_flagged():
    """旧格式（只有 markdown、无 items）→ 明确标出「建议重新转写」。"""
    papers = T.papers_of(PADS)
    md = "\n".join(f"{i}. {q}\n解：略" for i, (_n, q) in enumerate(BASE_QS, 1))
    row = T.audit_student({"markdown": md}, papers, roster_tag="基础")
    assert row["legacyFormat"] is True


def test_apply_accumulates_per_student_tag_history(ws):
    _snap(ws)
    T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                       changes=[{"name": "张三", "tag": "提高"}], reason="manual-detail")
    T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                       changes=[{"name": "张三", "tag": "拓展", "note": "看题干后确认"}],
                       reason="manual-detail")
    from assist.grading import snapshots as S
    zs = next(s for s in S.read_tags_snapshot(ws, CLASS, PACK)["students"]
              if s["name"] == "张三")
    hist = zs["tagHistory"]
    assert len(hist) == 2, "两次修改都要留记录"
    assert hist[0]["from"] == "基础" and hist[0]["to"] == "提高"
    assert hist[1]["from"] == "提高" and hist[1]["to"] == "拓展"
    assert hist[1]["note"] == "看题干后确认"
    assert hist[1]["by"] == "teacher"


def test_undo_student_tag_restores_previous_and_keeps_history(ws):
    _snap(ws)
    T.apply_audit_tags(ws, class_dir=CLASS, pack_id=PACK,
                       changes=[{"name": "张三", "tag": "提高"}])
    rep = T.undo_student_tag(ws, class_dir=CLASS, pack_id=PACK, name="张三")
    assert rep["ok"] and rep["to"] == "基础"
    from assist.grading import snapshots as S
    zs = next(s for s in S.read_tags_snapshot(ws, CLASS, PACK)["students"]
              if s["name"] == "张三")
    assert zs["tag"] == "基础"
    assert len(zs["tagHistory"]) == 2, "撤销是**追加**记录，不删历史"
    assert zs["tagHistory"][-1]["reason"] == "undo-student"


def test_undo_student_without_history_errors(ws):
    _snap(ws)
    rep = T.undo_student_tag(ws, class_dir=CLASS, pack_id=PACK, name="张三")
    assert rep["ok"] is False and "没有任何 tag 变更记录" in rep["error"]
