"""D75-1：批阅预览数据（解析已归档的 review 列表 HTML，只读、纯函数）。

存档命名：`v2-review-<classId>-<workId>.html`（D63 提取产物）。
当前只解析「列表页」：学生、分数、状态、评阅链接；
单生照片/评语需要 review-work 详情页（下一步，见 docs/26 D75-1）。
"""
from __future__ import annotations

import html as _html
import re
from pathlib import Path

_REVIEW_RE = re.compile(r"v2-review-(\d+)-(\d+)\.html$")
_TAG_RE = re.compile(r"<[^>]+>")


def _text(raw: str) -> str:
    return _html.unescape(_TAG_RE.sub("", raw or "")).strip()


def list_review_archives(home) -> list[dict]:
    """扫描 pages/ 与旧 xxt-pages/ 下的 review 列表存档。"""
    from . import layout
    home = Path(home)
    dirs = [layout.pages_dir(home), home / "xxt-pages"]
    seen: dict[tuple[str, str], Path] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("v2-review-*.html")):
            m = _REVIEW_RE.match(p.name)
            if not m:
                continue
            key = (m.group(1), m.group(2))
            seen.setdefault(key, p)     # 新 pages/ 优先
    return [{"classId": cid, "workId": wid, "file": str(p),
             "mtime": p.stat().st_mtime}
            for (cid, wid), p in sorted(seen.items())]


def parse_review_list(html: str) -> list[dict]:
    """把 review 列表 HTML 解析为学生行（姓名/分数/状态/评阅链接）。"""
    students: list[dict] = []
    for block in re.split(r'<ul[^>]*class="[^"]*dataBody_td', html)[1:]:
        block = block.split("</ul>")[0]
        name_m = re.search(r'class="py_name"[^>]*>(.*?)</div>', block, re.S)
        name = _text(name_m.group(1)) if name_m else ""
        if not name:
            continue
        sid_m = re.search(r'id="(\d+)"', block)
        score_m = re.search(r'class="[^"]*scoreInput[^"]*"[^>]*\bvalue="([^"]*)"', block)
        status = ""
        for s in ("已批阅", "待批阅", "补交", "未交", "已交"):
            if s in block:
                status = s
                break
        link_m = re.search(r'data="([^"]*review-work[^"]*)"', block)
        score = _text(score_m.group(1)) if score_m else ""
        # 列表页通常不做逐行状态文本；用「是否有分数」推断已批阅/待批阅
        if not status:
            status = "已批阅" if score else "待批阅"
        students.append({
            "studentId": sid_m.group(1) if sid_m else "",
            "name": name,
            "score": score,
            "status": status,
            "graded": bool(score),
            "review_path": _html.unescape(link_m.group(1)) if link_m else "",
        })
    return students


def preview_students(home, class_id: str, work_id: str) -> dict:
    """按 classId/workId 找存档并解析；找不到返回 ok=False。"""
    target = None
    for item in list_review_archives(home):
        if item["classId"] == str(class_id) and item["workId"] == str(work_id):
            target = item
            break
    if target is None:
        return {"ok": False, "error": "no archived review list",
                "hint": "该作业没有本地 review 列表存档"}
    try:
        html = Path(target["file"]).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"read failed: {exc}"}
    students = parse_review_list(html)
    scored = sum(1 for s in students if s.get("score"))
    return {"ok": True, "classId": str(class_id), "workId": str(work_id),
            "count": len(students), "scored": scored, "students": students}
