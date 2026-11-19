"""D208：上传/打分代码审核发现的 4 个问题。

1) 【高危】姓名子串兜底可能把批阅写到**另一个学生**（王伟 → 王伟伟）。
2) 【高危】前端「按对照表上传」传入的确认名单被忽略 → 实际上传全部草稿。
3) 【中】提交按钮兜底可能点到「提交并进入下一份」→ 批阅串到下一个学生。
4) 【中】重试前不复验 → 平台列表延迟时可能重复提交。
"""
from __future__ import annotations

from pathlib import Path

from assist.xxt.grade_upload import find_payload, find_student_row, match_students


# ---------------- 1) 学生匹配安全 ----------------

def test_fuzzy_match_does_not_pick_similar_name():
    """核心回归：给“王伟”上传不得命中“王伟伟”。"""
    rows = [{"name": "王伟伟", "workAnswerId": "wa2"}]
    assert find_student_row(rows, "王伟") is None


def test_exact_match_still_wins():
    rows = [{"name": "王伟伟", "workAnswerId": "wa2"},
            {"name": "王伟", "workAnswerId": "wa1"}]
    assert find_student_row(rows, "王伟")["workAnswerId"] == "wa1"


def test_unique_fuzzy_still_allowed():
    """唯一模糊命中（如名单里只有“张三(补交)”）仍可用。"""
    rows = [{"name": "张三(补交)", "workAnswerId": "wa3"}]
    assert find_student_row(rows, "张三")["workAnswerId"] == "wa3"


def test_ambiguous_fuzzy_blocked():
    rows = [{"name": "王伟伟", "workAnswerId": "wa2"},
            {"name": "王伟强", "workAnswerId": "wa3"}]
    assert find_student_row(rows, "王伟") is None


def test_match_students_reports_candidates():
    rows = [{"name": "王伟伟", "workAnswerId": "wa2"},
            {"name": "王伟强", "workAnswerId": "wa3"}]
    info = match_students(rows, "王伟")
    assert info["exact"] is None
    assert info["fuzzy"] == []          # 不参与匹配
    assert {r["name"] for r in info["similar"]} == {"王伟伟", "王伟强"}  # 仅用于诊断


def test_workanswerid_exact_match():
    rows = [{"name": "任意名字", "workAnswerId": "54761942"}]
    assert find_student_row(rows, "54761942")["workAnswerId"] == "54761942"


def test_find_payload_blocks_similar_name():
    payloads = [{"student": "王伟伟", "key": "wa2"}]
    assert find_payload(payloads, "王伟") is None


def test_find_payload_exact_and_key():
    payloads = [{"student": "王伟", "key": "wa1"},
                {"student": "王伟伟", "key": "wa2"}]
    assert find_payload(payloads, "王伟")["key"] == "wa1"
    assert find_payload(payloads, "wa2")["key"] == "wa2"


# ---------------- 2) 确认名单必须生效 ----------------

def test_cli_supports_students_filter():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/cli.py").read_text(
        encoding="utf-8")
    assert '"--students"' in src
    assert "students_filter" in src
    assert "指定的学生名单在本地草稿中不存在" in src
    # 必须真的用于过滤 payloads
    body = src.split("want = [str(x).strip() for x in (students_filter or [])")[1][:600]
    assert "payloads = [p for p in payloads" in body


def test_serve_forwards_students_list():
    src = (Path(__file__).resolve().parents[1] / "src/assist/serve.py").read_text(
        encoding="utf-8")
    assert 'payload.get("students")' in src
    assert 'args += ["--students", _s]' in src


def test_frontend_passes_only_list_to_engine():
    repo = Path(__file__).resolve().parents[2]
    view = (repo / "app/src/components/AiGradingPanel.vue").read_text(encoding="utf-8")
    client = (repo / "app/src/lib/engineClient.ts").read_text(encoding="utf-8")
    assert "students?: string[]" in client
    assert "students: only && only.length ? only : undefined" in view
    assert "正在上传已确认的" in view


# ---------------- 3) 不得点“进入下一份” ----------------

def test_fallback_skips_next_student_button():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/marking.py").read_text(
        encoding="utf-8")
    assert "next-student" in src
    assert "/next|下一|下一位|下份/i" in src


# ---------------- 4) 重试前复验 ----------------

def test_retry_rechecks_before_resubmitting():
    src = (Path(__file__).resolve().parents[1] / "src/assist/xxt/grade_upload.py").read_text(
        encoding="utf-8")
    assert "afterSubmitRecheck" in src
    assert "if ver2.get(\"ok\"):" in src
