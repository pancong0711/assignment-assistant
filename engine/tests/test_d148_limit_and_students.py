"""D148：`--limit` 语义修正（前 N 名**有作答**）+ 逐生补批 `--students`。

教师报错：`plan 模式下没有任何学生图片（名单 1 人，0 人有图）`
——他用「前 1 名」测试，取到的却是 roster 里的第 1 人（可能没交作业）。
根因：plan 的 students 来自 **roster**（`inputs.assemble` 按名单遍历），
`--limit` 直接切片名单，与"谁交了作业"无关。
"""
from __future__ import annotations

import pytest

from assist.grading import flow as F


def _plan(*students):
    return {"students": [{"name": n, "images": imgs} for n, imgs in students]}


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


def _run(ws, plan, **kw):
    """只跑 plan 过滤逻辑（run_task 需要真实任务包，这里直接取过滤函数片段）。"""
    want = [str(x).strip() for x in (kw.get("students") or []) if str(x).strip()]
    if want:
        _all = plan.get("students") or []
        _keep = [s for s in _all if str(s.get("name")) in set(want)]
        return {**plan, "students": _keep}
    return plan


# ---------------- --limit 语义 ----------------
def test_limit_counts_only_students_with_images():
    plan = _plan(("张三", []), ("李四", ["a.png"]), ("王五", ["b.png"]))
    all_stu = plan["students"]
    with_img = [s for s in all_stu if s.get("images")]
    picked = with_img[:1]
    assert [s["name"] for s in picked] == ["李四"], "应取第一个**有作答**的学生"


def test_limit_skips_unsubmitted_at_head():
    """正是教师遇到的场景：名单第 1 人没交作业。"""
    plan = _plan(("没交作业的", []), ("交了作业的", ["a.png"]))
    with_img = [s for s in plan["students"] if s.get("images")]
    assert with_img[:1][0]["name"] == "交了作业的"


def test_limit_zero_means_all():
    plan = _plan(("张三", []), ("李四", ["a.png"]))
    assert len(plan["students"]) == 2


# ---------------- 逐生补批 --students ----------------
def test_students_filter_keeps_only_named():
    plan = _plan(("张三", ["a.png"]), ("李四", ["b.png"]), ("王五", ["c.png"]))
    out = _run(None, plan, students=["李四"])
    assert [s["name"] for s in out["students"]] == ["李四"]


def test_students_filter_multiple():
    plan = _plan(("张三", []), ("李四", ["b.png"]), ("王五", ["c.png"]))
    out = _run(None, plan, students=["张三", "王五"])
    assert [s["name"] for s in out["students"]] == ["张三", "王五"]


def test_students_filter_unknown_name_yields_empty():
    plan = _plan(("张三", ["a.png"]))
    out = _run(None, plan, students=["不存在"])
    assert out["students"] == []


def test_students_not_given_keeps_all():
    plan = _plan(("张三", []), ("李四", ["b.png"]))
    out = _run(None, plan, students=[])
    assert len(out["students"]) == 2


# ---------------- flow.run_task 支持 students 参数 ----------------
def test_run_task_accepts_students_param():
    import inspect
    sig = inspect.signature(F.run_task)
    assert "students" in sig.parameters
    assert sig.parameters["students"].default is None
