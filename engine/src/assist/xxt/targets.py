"""D72 targets 模式：课程/班级勾选清单的规范化与安全校验（纯函数，可测）。"""
from __future__ import annotations

import re

# 学习通 courseId/classId 实测为纯数字串；放宽到字母数字以兼容未来形态。
TARGET_ID_RE = re.compile(r"^[0-9A-Za-z]{1,32}$")


def sanitize_targets(raw) -> "tuple[list[dict] | None, str | None]":
    """把 PWA 勾选结果规整为 `{"courses": [...]}` 可写文件的结构。

    只接受 courseId/classId/name 三个字段；任一 id 非法即整体拒绝，
    避免把任意内容写进引擎侧 targets 文件。
    返回 (targets, None) 或 (None, 错误信息)。
    """
    if not isinstance(raw, list) or not raw:
        return None, "targets 必须是非空数组"
    out: list[dict] = []
    for c in raw:
        if not isinstance(c, dict):
            return None, "targets[] 元素必须是对象"
        cid = str(c.get("courseId") or "").strip()
        if not TARGET_ID_RE.match(cid):
            return None, f"非法 courseId: {cid[:32]!r}"
        classes: list[dict] = []
        for cl in c.get("classes") or []:
            if not isinstance(cl, dict):
                return None, "classes[] 元素必须是对象"
            kid = str(cl.get("classId") or "").strip()
            if not TARGET_ID_RE.match(kid):
                return None, f"非法 classId: {kid[:32]!r}"
            classes.append({"name": str(cl.get("name") or kid)[:80], "classId": kid})
        if not classes:
            continue
        out.append({"name": str(c.get("name") or cid)[:80], "courseId": cid,
                    "classes": classes})
    if not out:
        return None, "未选择任何班级"
    return out, None
