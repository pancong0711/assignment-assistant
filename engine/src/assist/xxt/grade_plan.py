"""D193 §2：上传前的「已批阅」三态对照（纯函数，不触网）。

教师诉求：上传前要检查学生批阅状态——
- **未批阅** → 正常上传；
- **已批阅** → 先对照平台当前分数/批语与本地要上传的内容：
  - 一致 → `unchanged`（跳过，不打扰）；
  - 不一致 → `conflict`（必须教师显式确认才覆盖）；
- 本地没有可上传内容 → `skipped`。

纯函数设计：平台侧读数由 `read_back(page)` 提供，这里只做比对与决策，
便于离线单测（不启动浏览器、不读真实学生数据）。
"""
from __future__ import annotations

import re

# 决策常量（前端/CLI/清单共用同一套字符串）
NEW = "new"                    # 未批阅 → 可上传
UNCHANGED = "unchanged"        # 已批阅且内容一致 → 跳过
CONFLICT = "conflict"          # 已批阅且内容不同 → 需显式确认覆盖
SKIPPED = "skipped"            # 没有可上传内容
ALREADY = "already-reviewed"   # 兼容旧口径（不带 force 时的拒绝值）

_TAG_RE = re.compile(r"<[^>]+>")


def text_of(html: str) -> str:
    """批语 HTML → 归一纯文本（去标签/实体空白/多余空白），仅用于**比对**。"""
    s = str(html or "")
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", s)
    s = _TAG_RE.sub(" ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
         .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\u3000]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join([ln for ln in lines if ln]).strip()


def _num(v):
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f


def same_score(a, b, tol: float = 0.005) -> bool:
    fa, fb = _num(a), _num(b)
    if fa is None and fb is None:
        return True
    if fa is None or fb is None:
        return False
    return abs(fa - fb) <= tol


def same_comment(a, b) -> bool:
    return text_of(a) == text_of(b)


def platform_snapshot(readback: "dict | None") -> dict:
    """把 `marking.read_back(page)` 的结果压成可比较的快照（不含长文本全文）。"""
    rb = readback if isinstance(readback, dict) else {}
    comment = str(rb.get("comment") or "")
    return {
        "score": _num(rb.get("score")),
        "commentText": text_of(comment),
        "commentLength": len(text_of(comment)),
        "commentImages": int(rb.get("commentImages") or 0),
    }


def decide(*, status: str = "", local_score=None, local_comment: str = "",
           platform: "dict | None" = None, has_local_content: bool = True,
           force: bool = False) -> dict:
    """决定本次上传动作。

    - `status`：平台批阅列表里的状态文字（含“已批阅”即已批阅）；
    - `platform`：`platform_snapshot(read_back(...))`；未批阅时通常为 None；
    - `force`：教师已在上传前确认覆盖（`conflict` 才会真正覆盖）。

    返回 `{decision, reason, needsConfirm, upload, platformBefore}`
    """
    local_text = text_of(local_comment)
    if not has_local_content or (local_score is None and not local_text):
        return {"decision": SKIPPED, "reason": "本地没有可上传的分数/批语",
                "needsConfirm": False, "upload": False, "platformBefore": None}
    reviewed = "已批阅" in str(status or "")
    if not reviewed:
        return {"decision": NEW, "reason": "平台未批阅，直接上传",
                "needsConfirm": False, "upload": True,
                "platformBefore": platform_snapshot(platform) if platform else None}
    snap = platform_snapshot(platform)
    score_same = same_score(snap.get("score"), local_score)
    comment_same = same_comment(snap.get("commentText"), local_text)
    if score_same and comment_same:
        return {"decision": UNCHANGED,
                "reason": "平台已是相同分数与批语，无需重复上传",
                "needsConfirm": False, "upload": False, "platformBefore": snap}
    diffs = []
    if not score_same:
        diffs.append(f"分数 {snap.get('score')} → {_num(local_score)}")
    if not comment_same:
        diffs.append(f"批语长度 {snap.get('commentLength')} → {len(local_text)}")
    if not force:
        return {"decision": CONFLICT,
                "reason": "平台已批阅且内容不同（" + "；".join(diffs) + "），需确认覆盖",
                "needsConfirm": True, "upload": False, "platformBefore": snap}
    return {"decision": CONFLICT,
            "reason": "教师已确认覆盖（" + "；".join(diffs) + "）",
            "needsConfirm": False, "upload": True, "platformBefore": snap}


def summarize(results: "list[dict] | None") -> dict:
    """批量上传汇总：applied / unchanged / skipped / conflict / failed 五类计数。"""
    rows = [r for r in (results or []) if isinstance(r, dict)]
    buckets = {"applied": [], "unchanged": [], "skipped": [],
               "conflict": [], "failed": []}
    for r in rows:
        name = str(r.get("student") or r.get("draftKey") or "")
        decision = str(r.get("decision") or "")
        if decision == SKIPPED:
            # 没有可上传内容：不算失败（教师没填分数/批语，或内容一致已跳过）
            buckets["skipped"].append(name)
        elif not r.get("ok"):
            buckets["conflict" if decision == CONFLICT else "failed"].append(name)
        elif decision == UNCHANGED:
            buckets["unchanged"].append(name)
        elif decision in (SKIPPED,):
            buckets["skipped"].append(name)
        elif decision == NEW:
            buckets["applied"].append(name)
        else:
            # 没有显式 decision（旧调用/单生上传成功）计入 applied
            buckets["applied"].append(name)
    return {
        "count": len(rows),
        "applied": buckets["applied"], "unchanged": buckets["unchanged"],
        "skipped": buckets["skipped"], "conflict": buckets["conflict"],
        "failed": buckets["failed"],
        "counts": {k: len(v) for k, v in buckets.items()},
        "ok": not buckets["conflict"] and not buckets["failed"] and bool(rows),
    }
