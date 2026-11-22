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
    # D210-FIX：原实现只认中文“已批阅”，真实平台还会返回
    # “已完成 / Completed / Completed（教师提交）/ Reviewed”，
    # 会被误判成“未批阅”→ 跳过覆盖确认，直接覆盖平台已有批阅。
    reviewed = is_reviewed_status(status)
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


# ---------------- D196：上传范围（只传已提交学生）+ 批语缺失提醒 ----------------

READY = "ready"            # 已提交 + 有可上传内容（报告图/批语/分数）→ 可上传
NO_COMMENT = "no-comment"  # 兼容旧值：无可上传内容（保留给外部调用方）
NO_REPORT = "no-report"    # 已提交但没有报告图，也没有批语/分数 → 请先生成报告
ALIGN_MISMATCH = "align-mismatch"  # D217：疑似错卷（程序对齐 mismatch）→ 默认不上传
NOT_SUBMITTED = "not-submitted"  # 平台未提交 → 不上传批阅报告
NO_DRAFT = "no-draft"      # 已提交但本地没有草稿 → 先批阅


_PENDING_RE = r"待批阅|unreview|未完成|unsubmitted|to be reviewed"
_REVIEWED_RE = r"已批阅|补交|reviewed|completed|完成|教师提交"


def is_reviewed_status(status: str) -> bool:
    """D210：平台状态是否表示“已批阅”（覆盖中英文多种文案）。"""
    import re as _re
    st = str(status or "")
    if _re.search(_PENDING_RE, st, _re.I):
        return False
    return bool(_re.search(_REVIEWED_RE, st, _re.I))


def is_pending_status(status: str) -> bool:
    """D210：平台状态是否明确表示“未批阅”。"""
    import re as _re
    return bool(_re.search(_PENDING_RE, str(status or ""), _re.I))


def is_submitted(row: "dict | None") -> bool:
    """平台行是否“已提交（有作答）”。

    学习通批阅清单只列出有作答的学生（行内有 `a.cz_py` → workAnswerId）；
    “未交/未提交”的学生不在该清单里，**不应上传批阅报告**。
    `status` 含“未交/未提交”也判未提交（防御性判断）。
    """
    row = row if isinstance(row, dict) else {}
    status = str(row.get("status") or "")
    if "未交" in status or "未提交" in status:
        return False
    if row.get("submitted") is False:
        return False
    return bool(str(row.get("workAnswerId") or "").strip()) or bool(
        str(row.get("review_path") or "").strip()) or "已批阅" in status or "待批阅" in status \
        or "已交" in status or "补交" in status


def upload_readiness(*, platform_rows: "list[dict] | None" = None,
                     payloads: "list[dict] | None" = None) -> dict:
    """D196：把“平台已提交名单”和“本地可上传内容”对照成上传就绪表。

    - 平台未提交（不在清单/状态含未交）→ `not-submitted`：**不上传**；
    - 已提交但没有本地草稿 → `no-draft`：提醒先去批阅；
    - 已提交有草稿，但**报告图、批语、分数都没有** → `no-report`：提醒先生成报告；
    - 已提交且有任一可上传内容 → `ready`。

    D200：**报告图本身就是可上传内容**。教师的工作流是「上传批阅报告图片 + 打分」，
    平台批语框由报告图承载，并不需要再单独上传原始批语文本。旧实现只看 `comment`
    文本 → 有报告图但没批语文本时被误判成“批语为空”（现场 48 人）。

    返回 `{rows, ready, noComment, noDraft, notSubmitted, summary}`
    """
    by_name: dict[str, dict] = {}
    for p in payloads or []:
        name = str(p.get("student") or p.get("key") or "").strip()
        if name:
            by_name[name] = p
    rows: list[dict] = []
    seen: set[str] = set()
    for prow in (platform_rows or []):
        name = str(prow.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        p = by_name.get(name) or {}
        submitted = is_submitted(prow)
        comment = text_of(p.get("comment") or "")
        score = p.get("score")
        images = [i for i in (p.get("images") or []) if isinstance(i, dict)]
        has_image = bool(images)
        has_report = has_image or bool((p.get("report") or {}).get("version"))
        has_score = score is not None
        align = (p.get("align") or {}) if isinstance(p.get("align"), dict) else {}
        align_bad = str(align.get("verdict") or "") == "mismatch"
        if not submitted:
            state, why = NOT_SUBMITTED, "平台未提交/无作答，无需上传批阅报告"
        elif not p:
            state, why = NO_DRAFT, "已提交但本地没有草稿：请先「转写+评阅」或人工批阅"
        elif align_bad:
            # D217：疑似错卷 → 默认不上传（分数/批语来自另一份卷）
            _bt = str(align.get("bestTag") or "").strip()
            state = ALIGN_MISMATCH
            why = ("题目疑似与作业纸不匹配"
                   + (f"（建议 tag：{_bt}）" if _bt else "")
                   + "；默认不上传，请先核对/修改 tag 后重新批阅")
        elif has_image:
            # 主路径：只上传报告图 + 分数（报告图已包含排版好的批语）
            state, why = READY, "可上传（报告图 + 分数；批语文本不重复上传）"
        elif comment:
            state, why = READY, "可上传（批语文本 + 分数）"
        elif has_score:
            state, why = READY, "可上传（仅分数；无报告图/批语）"
        else:
            state, why = NO_REPORT, "已提交但没有报告图、批语或分数：请先生成批阅报告"
        rows.append({"student": name, "submitted": submitted, "state": state,
                     "reason": why, "score": score, "hasComment": bool(comment),
                     "commentLength": len(comment), "hasReport": has_report,
                     "hasImage": has_image, "hasScore": has_score,
                     "imageCount": len(images),
                     "uploadMode": "report-only" if has_image else "text",
                     "reportVersion": str((p.get("report") or {}).get("version") or ""),
                     "status": str(prow.get("status") or ""),
                     "source": "platform"})
    # 本地有草稿但平台清单里没有的学生：视为未提交（不上传）
    for name, p in by_name.items():
        if name in seen:
            continue
        rows.append({"student": name, "submitted": False, "state": NOT_SUBMITTED,
                     "reason": "平台名单中无此学生（可能未提交）：不上传批阅报告",
                     "score": p.get("score"),
                     "hasComment": bool(text_of(p.get("comment") or "")),
                     "commentLength": len(text_of(p.get("comment") or "")),
                     "hasReport": bool((p.get("report") or {}).get("version")),
                     "reportVersion": str((p.get("report") or {}).get("version") or ""),
                     "status": "", "source": "local-only"})
    buckets = {READY: [], ALIGN_MISMATCH: [], NO_REPORT: [], NO_COMMENT: [],
               NO_DRAFT: [], NOT_SUBMITTED: []}
    for r in rows:
        buckets.setdefault(r["state"], []).append(r["student"])
    # 兼容旧字段名：noComment 现在等价于 no-report（没有可上传内容）
    no_content = buckets[NO_REPORT] + buckets.get(NO_COMMENT, [])
    empty_comment = [r["student"] for r in rows
                     if r["state"] == READY and not r["hasComment"]]
    return {"ok": True, "rows": rows,
            "ready": buckets[READY], "noReport": buckets[NO_REPORT],
            "noComment": no_content, "emptyComment": empty_comment,
            "noDraft": buckets[NO_DRAFT], "notSubmitted": buckets[NOT_SUBMITTED],
            "alignMismatch": buckets[ALIGN_MISMATCH],
            "summary": {READY: len(buckets[READY]), NO_REPORT: len(buckets[NO_REPORT]),
                        NO_DRAFT: len(buckets[NO_DRAFT]),
                        ALIGN_MISMATCH: len(buckets[ALIGN_MISMATCH]),
                        NOT_SUBMITTED: len(buckets[NOT_SUBMITTED])},
            "hint": ("将上传 %d 名已提交的学生（有报告图的上传报告图+分数）" % len(buckets[READY])
                     + (("；%d 名已提交但**没有报告图/批语/分数**，请先生成批阅报告"
                         % len(buckets[NO_REPORT])) if buckets[NO_REPORT] else "")
                     + (("；%d 名**疑似错卷**（默认不上传，请先改 tag 重批）"
                         % len(buckets[ALIGN_MISMATCH])) if buckets[ALIGN_MISMATCH] else "")
                     + (("；%d 名已提交但**没有本地草稿**" % len(buckets[NO_DRAFT]))
                        if buckets[NO_DRAFT] else "")
                     + (("；%d 名未提交（不上传）" % len(buckets[NOT_SUBMITTED]))
                        if buckets[NOT_SUBMITTED] else ""))}
