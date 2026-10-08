"""D63 T4 纯函数回归：wid15 计数解析 + 未交差集 + 锚点检查（不触网）。"""

from assist.xxt.extractor import anchor_check, parse_count_token, submitted_name_set, unsubmitted_diff

LI = ('<div class="wid15"><p class="piyuePcon color3"><span class="color1">'
      '<em class="fs28" style="margin-right:5px">0</em>待批 </span>'
      '<span>59 已交</span><span>6 未交</span></p></div>')


def test_parse_count_token():
    assert parse_count_token(LI, "已交") == 59
    assert parse_count_token(LI, "未交") == 6
    assert parse_count_token(LI, "待批") == 0
    assert parse_count_token("<span>已交</span>", "已交") is None


def test_unsubmitted_diff():
    roster = [{"name": "王冬梅"}, {"name": "刘智博"}, {"name": "范心怡"}, {"name": "张三"}]
    work = {"submitted": 3, "unsubmitted": 1,
            "submitted_names": [{"name": "王冬梅", "status": ""}, {"name": "刘智博", "status": ""},
                                {"name": "X先罗", "status": ""}]}
    d = unsubmitted_diff(roster, work)
    assert d["unsubmitted_names"] == ["张三", "范心怡"]
    assert d["sub_not_in_roster"] == ["X先罗"]


def test_anchor_check():
    work = {"submitted": 2, "unsubmitted": 1,
            "submitted_names": [{"name": "a"}, {"name": "b"}]}
    r = anchor_check(work, roster_total=3)
    assert r["ok"] and r["roster_delta"] == 0 and r["names_vs_submitted"]
    r2 = anchor_check({**work, "submitted": 5}, roster_total=3)
    assert not r2["ok"]
    r3 = anchor_check(work, roster_total=10)   # delta=7 → 灰注
    assert r3["ok"] and any("roster_delta=7" in n for n in r3["notes"])


def test_submitted_name_set():
    assert submitted_name_set({"submitted_names": [{"name": " a "}, {"name": ""},
                                                   {"name": "b"}]}) == {"a", "b"}
