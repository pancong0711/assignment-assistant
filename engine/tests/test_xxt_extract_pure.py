"""D63 T4 纯函数回归：wid15 计数解析 + 未交差集 + 锚点检查（不触网）。"""

from assist.xxt.extractor import (
    DEFAULT_DISCOVER_COURSE_TYPES, anchor_check, extract_image_urls_from_html, html_to_text,
    parse_count_token, platform_unsubmitted, readonly_route_decision, submitted_name_set,
    unsubmitted_diff,
)

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

def test_readonly_route_decision_whitelists_courselist_post():
    assert readonly_route_decision("GET", "https://mooc2-ans.chaoxing.com/visit/interaction") == "continue"
    assert readonly_route_decision(
        "POST", "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata") == "continue"
    assert readonly_route_decision(
        "POST", "https://mooc2-ans.chaoxing.com/mooc2-ans/work/submit") == "abort"
    assert readonly_route_decision("DELETE", "https://mooc2-ans.chaoxing.com/x") == "abort"


def test_discover_defaults_to_teacher_courses_only():
    """D73-10：默认只扫描“我教的课”，不默认扫描“我学的课”。"""
    assert DEFAULT_DISCOVER_COURSE_TYPES == ("0",)
    assert "1" not in DEFAULT_DISCOVER_COURSE_TYPES


def test_platform_unsubmitted_filters_status():
    rows = [
        {"name": "甲", "status": "未提交"},
        {"name": "乙", "status": "已批阅"},
        {"name": "丙", "status": "未交"},
        {"name": "丁", "status": ""},
        "bad",
    ]
    assert platform_unsubmitted(rows) == ["丙", "甲"]


def test_extract_image_urls_from_html():
    h = ('<p>很好</p><img src="/star3/x.png">'
         '<img data-original="https://cdn.example.com/a.jpg"><img src="/star3/x.png">')
    assert extract_image_urls_from_html(h) == [
        "https://mooc2-ans.chaoxing.com/star3/x.png",
        "https://cdn.example.com/a.jpg",
    ]
    assert html_to_text("<p>很好</p><br>继续").replace("\n\n", "\n") == "很好\n继续"
