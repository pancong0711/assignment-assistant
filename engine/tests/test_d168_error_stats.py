"""D168 §1：知识点加权失误率统计。

教师口径（docs/112-D168 §1）：
- 扣分制、无固定每题满分 → **不用得分率**，用**失误次数**；
- 同一题同一知识点错 2 次 → **记 2 次**；
- 按 tag 算失误率 → 按「已提交人数」占比加权；
- 任何失误率**必须与提交率成对出现**。
"""
from __future__ import annotations

import pytest

from assist.grading import error_stats as E


def _rec(student, tag, questions):
    """questions: [(qid, [knowledge...])]"""
    return {"student": student, "tag": tag,
            "analysis": {"questions": [
                {"id": qid, "errors": [{"knowledge": k, "confidence": "high"} for k in ks]}
                for qid, ks in questions]}}


# ---------------- 失误次数 ----------------

def test_same_question_same_term_counted_twice():
    """**核心口径**：同一题同一知识点错 2 次 → 记 2 次（发生在不同步骤）。"""
    st = E.collect_errors([_rec("张三", "top", [("1", [["库仑定律"], ["库仑定律"]])])])
    assert st["byTerm"]["库仑定律"]["count"] == 2


def test_multiple_terms_in_one_error():
    st = E.collect_errors([_rec("张三", "top", [("1", [["库仑定律", "电场强度"]])])])
    assert st["byTerm"]["库仑定律"]["count"] == 1
    assert st["byTerm"]["电场强度"]["count"] == 1


def test_low_confidence_excluded():
    rec = {"student": "张三", "tag": "top", "analysis": {"questions": [
        {"id": "1", "errors": [{"knowledge": ["A"], "confidence": "low"}]}]}}
    st = E.collect_errors([rec])
    assert st["byTerm"] == {}


def test_string_knowledge_not_split_into_chars():
    """`knowledge` 是字符串时必须按分隔符拆，不能逐字遍历（历史 bug）。"""
    rec = {"student": "张三", "tag": "top", "analysis": {"questions": [
        {"id": "1", "errors": [{"knowledge": "动量守恒，库仑定律"}]}]}}
    st = E.collect_errors([rec])
    assert set(st["byTerm"]) == {"动量守恒", "库仑定律"}


# ---------------- 别名归并 + 词表外 ----------------

def test_alias_merge():
    vocab = {"terms": [{"term": "动量守恒", "aliases": ["动量守恒定律"]}]}
    st = E.collect_errors([
        _rec("张三", "top", [("1", [["动量守恒"]])]),
        _rec("李四", "top", [("1", [["动量守恒定律"]])]),
    ], vocab=vocab, only_known=True)
    assert st["byTerm"]["动量守恒"]["count"] == 2
    assert st["byTerm"]["动量守恒"]["students"] == {"张三", "李四"}


def test_unknown_terms_go_to_unclassified():
    """词表外术语**不进主统计**，单独计数（docs/112-D168 §4.3）。"""
    vocab = {"terms": [{"term": "动量守恒"}]}
    st = E.collect_errors([_rec("张三", "top", [("1", [["动量守恒", "自造概念"]])])],
                          vocab=vocab, only_known=True)
    assert "自造概念" not in st["byTerm"]
    assert st["unclassified"]["自造概念"] == 1


# ---------------- 加权失误率 ----------------

def test_weighted_rate_by_tag():
    """按 tag 失误率 → 按已提交人数占比加权。"""
    by_tag_counts = {"top": {"A": 2}, "middle": {"A": 1}}
    submitted = {"top": 2, "middle": 1}
    r = E.weighted_error_rate(by_tag_counts, submitted)
    # top: 2/2=1.0, middle: 1/1=1.0 → 加权 1.0
    assert r["terms"]["A"]["rate"] == 1.0
    assert r["weights"] == {"top": round(2 / 3, 4), "middle": round(1 / 3, 4)}


def test_weighted_rate_respects_tag_size():
    """人多的 tag 权重大（教师 §1.3 的核心关切）。"""
    by_tag_counts = {"top": {"A": 0}, "middle": {"A": 4}}
    submitted = {"top": 4, "middle": 4}
    r = E.weighted_error_rate(by_tag_counts, submitted)
    # top: 0/4=0, middle: 4/4=1.0 → 各占 50% → 0.5
    assert r["terms"]["A"]["rate"] == 0.5


def test_weighted_rate_zero_submitted():
    assert E.weighted_error_rate({"top": {"A": 1}}, {})["totalSubmitted"] == 0


def test_submitted_is_denominator_not_class_size():
    """分母是**已提交人数**，不是班级人数（教师 §1.3）。"""
    by_tag_counts = {"top": {"A": 3}}
    r = E.weighted_error_rate(by_tag_counts, {"top": 3})
    assert r["terms"]["A"]["rate"] == 1.0          # 3/3
    r2 = E.weighted_error_rate(by_tag_counts, {"top": 30})
    assert r2["terms"]["A"]["rate"] == 0.1         # 3/30


# ---------------- 可信度 ----------------

def test_confidence_low_when_submit_rate_low():
    c = E.confidence(submit_rate=0.1, submitted=2)
    assert c["level"] == "low"
    assert any("提交率" in x for x in c["reasons"])


def test_confidence_low_when_sample_small():
    c = E.confidence(submit_rate=0.9, submitted=3)
    assert c["level"] == "low"
    assert any("提交人数" in x for x in c["reasons"])


def test_confidence_ok():
    assert E.confidence(submit_rate=0.9, submitted=30)["level"] == "ok"


# ---------------- 跨包归一（教师拍板：按总题数） ----------------

def test_cross_pack_total_questions_denominator():
    """跨包 = Σ失误次数 / Σ总题数（不是按包平均）。"""
    packs = [
        {"packId": "P1", "byTerm": {"A": 4}, "totalQuestions": 4},
        {"packId": "P2", "byTerm": {"A": 2}, "totalQuestions": 2},
    ]
    r = E.cross_pack_rate(packs)
    assert r["totalQuestions"] == 6
    assert r["terms"]["A"]["errorCount"] == 6
    assert r["terms"]["A"]["rate"] == 1.0
    assert r["terms"]["A"]["packs"] == {"P1": 4, "P2": 2}


def test_cross_pack_weights_by_question_count():
    """题多的包影响大（按总题数归一的必然结果）。"""
    packs = [
        {"packId": "big", "byTerm": {"A": 1}, "totalQuestions": 10},
        {"packId": "small", "byTerm": {"A": 1}, "totalQuestions": 2},
    ]
    r = E.cross_pack_rate(packs)
    assert r["terms"]["A"]["rate"] == round(2 / 12, 4)


def test_cross_pack_empty():
    assert E.cross_pack_rate([])["totalQuestions"] == 0


# ---------------- 一站式报告 ----------------

def test_build_report_pairs_rate_with_submit():
    recs = [
        _rec("张三", "top", [("1", [["A"]])]),
        _rec("李四", "middle", [("1", [["A"], ["A"]])]),
    ]
    rep = E.build_report(recs, submitted_by_tag={"top": 1, "middle": 1})
    assert rep["ok"]
    item = rep["items"][0]
    assert item["term"] == "A"
    assert item["errorCount"] == 3
    # top: 1/1=1.0; middle: 2/1=2.0 → 各 50% → 1.5
    assert item["rate"] == 1.5
    assert item["byTag"] == {"top": 1.0, "middle": 2.0}
    assert rep["totalSubmitted"] == 2


def test_build_report_marks_unclassified():
    rep = E.build_report([_rec("张三", "top", [("1", [["自造"]])])],
                         submitted_by_tag={"top": 1},
                         vocab={"terms": [{"term": "A"}]})
    assert rep["items"] == []
    assert rep["unclassified"]["自造"] == 1


def test_empty_vocab_does_not_zero_out_stats():
    """**回归**：词表为空时不能把所有术语都当"词表外"（否则统计全空）。"""
    st = E.collect_errors([_rec("张三", "top", [("1", [["库仑定律"]])])],
                          vocab={"terms": []}, only_known=True)
    assert st["byTerm"]["库仑定律"]["count"] == 1
    assert st["unclassified"] == {}
