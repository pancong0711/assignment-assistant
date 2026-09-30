"""D55-H3 口径回归：引擎 merge_scores = 原始分加权平均（无班内最高分归一），
与 PWA computeScoresFiltered 同口径（PWA 侧由 app/tests/selfcheck-roster-fig.mjs E 块保障）。"""

from assist.roster.grouping import merge_scores


def test_merge_scores_raw_weighted_average():
    students = [{"name": "学生A"}, {"name": "学生B"}]
    rows = [
        {"name": "学生A", "score": 110, "weight": 1},   # 语文
        {"name": "学生A", "score": 108, "weight": 1},   # 数学
        {"name": "学生B", "score": 100, "weight": 1},
        {"name": "学生B", "score": 90, "weight": 1},
    ]
    out = merge_scores(students, rows, weight_normalize=True)
    assert out["学生A"]["mean"] == 109.0    # (110+108)/2 —— 不做 /max 归一
    assert out["学生B"]["mean"] == 95.0


def test_merge_scores_column_weight_2_1():
    students = [{"name": "学生A"}]
    rows = [
        {"name": "学生A", "score": 110, "weight": 2},
        {"name": "学生A", "score": 108, "weight": 1},
    ]
    out = merge_scores(students, rows, weight_normalize=True)
    assert out["学生A"]["mean"] == 109.33   # (110*2+108)/3


def test_merge_scores_single_column_equals_raw():
    students = [{"name": "学生A"}]
    out = merge_scores(students, [{"name": "学生A", "score": 85, "weight": 1}], weight_normalize=True)
    assert out["学生A"]["mean"] == 85.0
