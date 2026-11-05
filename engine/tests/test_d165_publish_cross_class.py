"""D165：跨班发布被误判"已发布，禁止重新发布"。

根因：发布设置页 URL **只带 courseid，没带 clazzid** →
平台按**课程**维度判断"该作业库条目是否已发布"，
于是在同课程其它班发过就拒绝，哪怕目标班还没发。

同文件的其它 URL（作业库列表/详情/已发布列表）都带 clazzid，只有这个漏了。
"""
from __future__ import annotations

import inspect
import re

import pytest

from assist.xxt import work as W


def _src(fn) -> str:
    return inspect.getsource(fn)


def test_publish_url_includes_clazzid():
    """**核心**：发布设置页 URL 必须带 clazzid。"""
    src = _src(W.publish_work)
    assert "work/library/setting" in src
    # 找到拼接该 URL 的片段
    seg = src[src.index("work/library/setting"):src.index("work/library/setting") + 400]
    assert "clazzid=" in seg, f"发布 URL 未带 clazzid：{seg[:200]}"


def test_other_urls_also_have_clazzid():
    """对照组：其它学习通页面 URL 一直是带的（说明这是遗漏，不是约定）。"""
    assert "clazzid=" in _src(W.class_works_url)
    assert "clazzid=" in _src(W.list_folders)


def test_dup_check_is_per_class():
    """重复校验必须**逐班**做（此前只查 targets[0]）。

    D170-T5：还要**按 classId 自行过滤**——平台列表可能只按 courseid 过滤，
    直接取 workLibraryId 集合会让"逐班校验"变成假逐班（单班/多班都误报）。
    """
    src = _src(W.publish_work)
    assert "for cid in targets" in src, "重复校验应遍历所有目标班"
    # D170-T5：必须拿到原始条目并自行按班级过滤（而不是只取 id 集合）
    assert "list_class_works(storage, course_id, cid" in src
    assert "classId" in src, "必须按 classId 自行过滤（不能信任服务端过滤）"


def test_failure_carries_page_hint():
    """失败时必须能带出页面提示文字（否则只有 ok:false）。"""
    src = _src(W.publish_work)
    assert "pageHint" in src
    assert "禁止" in src or "校验未通过" in src


def test_no_request_means_frontend_blocked():
    """点击后没有任何请求 → 明确提示"前端校验未通过"。"""
    src = _src(W.publish_work)
    assert "没有发出任何请求" in src
