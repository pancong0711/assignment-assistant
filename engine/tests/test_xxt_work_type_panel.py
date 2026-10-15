"""D85 §1：新建作业题型面板（直接列表 → 「更多」弹层 → 成功判据）回归（stub，无浏览器）。

真机事实：不同课程「添加题目」直接题型集合不同（C2Z 班没有简答题直钮，只在
#addQTypeBtn 的 .morePop 里）；外层 span/li[title] 常被 0×0/overflow 裁剪，
内层 <a> 才可点 → 实现为「多定位器 click + DOM click 兜底」。
"""

from assist.xxt.work import _ensure_question_type


class _Loc:
    def __init__(self, n, ok, name):
        self._n, self._ok, self.name = n, ok, name

    def count(self):
        return self._n

    def nth(self, _i):
        return self

    @property
    def first(self):
        return self

    def click(self, timeout=None):  # noqa: ARG002
        if not self._ok:
            raise RuntimeError(f"{self.name}: element is not visible")

    def evaluate(self, js, arg=None):  # noqa: ARG002
        if not self._ok:
            raise RuntimeError(f"{self.name}: dom click failed")


class _StubPage:
    def __init__(self, *, direct=True, more=True, more_item=True, evidence=True,
                 evidence_after="direct"):
        self.cfg = {"direct": direct, "more": more, "more_item": more_item}
        self.evidence = evidence
        self.evidence_after = evidence_after   # "direct"：直点即成功；"more"：只有走「更多」后才成功

    def locator(self, sel):
        if "addQTypeBtn" in sel or ".moreCon" in sel:
            if self.evidence_after == "more":
                self.evidence = True          # 进入「更多」路径后判据才成立
        if ".addTitle" in sel:
            return _Loc(1 if self.cfg["direct"] else 0, self.cfg["direct"], "direct")
        if "addQTypeBtn" in sel or ".moreCon" in sel:
            return _Loc(1 if self.cfg["more"] else 0, self.cfg["more"], "more-btn")
        if ".morePop" in sel:
            return _Loc(1 if self.cfg["more_item"] else 0, self.cfg["more_item"], "more-item")
        return _Loc(0, False, "none")

    def evaluate(self, js, arg=None):  # noqa: ARG002
        if ".eidt_stem" in js:
            if self.evidence and self.evidence_after != "never":
                return {"stem": "1\n简答题 ", "workid": "draft-1", "stemHas": True, "hasWid": True}
            return {"stem": "", "workid": "", "stemHas": False, "hasWid": False}
        return None

    def wait_for_timeout(self, _ms):
        pass


def test_direct_path_used_when_clickable():
    res = _ensure_question_type(_StubPage(), "简答题")
    assert res["ok"] and res["usedPath"] == "direct"
    assert res["evidence"]["hasWid"]


def test_falls_back_to_more_popup():
    """C2Z 场景：直接列表点不到 → 「更多」→ 弹层内点。"""
    res = _ensure_question_type(_StubPage(direct=False), "简答题")
    assert res["ok"] and res["usedPath"] == "more"
    assert [a["path"] for a in res["attempts"]] == ["direct", "open-more", "more"]


def test_force_more_skips_direct():
    """测试钩子：force_more 直接走「更多」分支（用于白名单班验证）。"""
    res = _ensure_question_type(_StubPage(), "简答题", force_more=True)
    assert res["ok"] and res["usedPath"] == "more"
    assert res["attempts"][0]["path"] == "open-more"      # 跳过直点路径


def test_reports_failure_when_more_item_not_clickable():
    res = _ensure_question_type(_StubPage(direct=False, more_item=False), "简答题")
    assert res["ok"] is False and "更多" in res["error"]


def test_reports_failure_when_no_evidence_after_click():
    res = _ensure_question_type(_StubPage(evidence=False), "简答题", timeout_s=0.01)
    assert res["ok"] is False and "均未成功创建题目" in res["error"]


def test_direct_click_without_evidence_falls_through_to_more():
    """直点"点了但没创建出题目" → 必须继续走「更多」，不能误报成功。"""
    res = _ensure_question_type(_StubPage(direct=True, evidence=False, evidence_after="more"), "简答题")
    assert res["ok"] and res["usedPath"] == "more"
    assert any(a.get("note") == "clicked-but-no-evidence" for a in res["attempts"])
