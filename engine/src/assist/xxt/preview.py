"""D75-1 / D76：批阅预览数据（解析已归档的 review 列表 HTML，只读、纯函数）。

存档命名：
- 新契约（D73-11 起）：`pages/runs/<run_id>/v2-review-<classId>-<workId>.html`
- 旧契约（兼容）：`pages/v2-review-*.html`、`xxt-pages/v2-review-*.html`

D76：除列表存档外，找不到 HTML 时回退到已下载的
`pages/review/<classId>/<workId>/students.json` manifest，
让“已下载图片/批语”的作业也能直接打开学生列表预览。
"""
from __future__ import annotations

import html as _html
import re
from pathlib import Path

_REVIEW_RE = re.compile(r"v2-review-([0-9A-Za-z\-_]{1,40})-([0-9A-Za-z\-_]{1,40})\.html$")
_TAG_RE = re.compile(r"<[^>]+>")


def _text(raw: str) -> str:
    return _html.unescape(_TAG_RE.sub("", raw or "")).strip()


def _scan_review_dir(d: Path) -> list[tuple[tuple[str, str], Path]]:
    """扫描单个目录下的 review 列表存档，返回 ((classId, workId), path)。"""
    out: list[tuple[tuple[str, str], Path]] = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("v2-review-*.html")):
        m = _REVIEW_RE.match(p.name)
        if m:
            out.append(((m.group(1), m.group(2)), p))
    return out


def _merge_entries(entries: list[tuple[tuple[str, str], Path]]) -> dict[tuple[str, str], tuple[float, Path]]:
    """同一 class/work 多份存档时取 mtime 最新的一份。"""
    chosen: dict[tuple[str, str], tuple[float, Path]] = {}
    for key, p in entries:
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        old = chosen.get(key)
        if old is None or mtime > old[0]:
            chosen[key] = (mtime, p)
    return chosen


def _review_archive_dirs(home: Path) -> list[Path]:
    """按优先级返回所有可能含 review 列表存档的目录（已去重）。"""
    from . import layout

    pages = layout.pages_dir(home)
    dirs: list[Path] = [pages, home / "xxt-pages"]
    for runs in (pages / "runs", home / "xxt-pages" / "runs"):
        if runs.is_dir():
            dirs.extend(sorted((p for p in runs.iterdir() if p.is_dir()),
                               key=lambda p: p.name))
    seen: set[Path] = set()
    unique: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def _all_entries(home: Path) -> dict[tuple[str, str], tuple[float, Path]]:
    entries: list[tuple[tuple[str, str], Path]] = []
    for d in _review_archive_dirs(home):
        entries.extend(_scan_review_dir(d))
    return _merge_entries(entries)


def list_review_archives(home) -> list[dict]:
    """扫描所有可能目录，返回按 class/work 归一后的 review 列表存档索引。"""
    home = Path(home)
    chosen = _all_entries(home)
    return [{"classId": cid, "workId": wid, "file": str(p), "mtime": mtime}
            for (cid, wid), (mtime, p) in sorted(chosen.items())]


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


def _manifest_students(home: Path, class_id: str, work_id: str) -> "dict | None":
    """回退：从已下载的 students.json manifest 生成学生列表。"""
    from .review import read_manifest

    manifest = read_manifest(home, class_id, work_id)
    if not manifest:
        return None
    students: list[dict] = []
    for s in manifest.get("students") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()
        if not name:
            continue
        score_raw = s.get("score")
        score = "" if score_raw is None else str(score_raw).strip()
        comment = str(s.get("comment") or "").strip()
        graded = bool(score) or bool(comment)
        students.append({
            "studentId": str(s.get("studentId") or ""),
            "name": name,
            "score": score,
            "status": "已批阅" if graded else "待批阅",
            "graded": graded,
            "review_path": str(s.get("review_path") or ""),
        })
    return {
        "ok": True,
        "classId": str(class_id),
        "workId": str(work_id),
        "count": len(students),
        "scored": sum(1 for x in students if x.get("score")),
        "students": students,
        "source": "manifest",
    }


def preview_students(home, class_id: str, work_id: str, run_id: "str | None" = None) -> dict:
    """按 classId/workId（可选 run_id）找存档并解析；找不到返回 ok=False。

    查找顺序：
    1. 指定 run 的专属存档目录；
    2. 全局最新存档（新 run 目录优先于旧根目录，按 mtime 取新）；
    3. 已下载的 students.json manifest。
    """
    from . import layout

    home = Path(home)
    key = (str(class_id), str(work_id))
    if run_id and not re.fullmatch(r"[0-9A-Za-z\-_]{1,80}", str(run_id)):
        run_id = None
    target: "tuple[float, Path] | None" = None

    if run_id:
        entries: list[tuple[tuple[str, str], Path]] = []
        entries.extend(_scan_review_dir(layout.run_pages_dir(str(run_id), home)))
        target = _merge_entries(entries).get(key)

    if target is None:
        target = _all_entries(home).get(key)

    if target is not None:
        try:
            html = target[1].read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"read failed: {exc}"}
        students = parse_review_list(html)
        scored = sum(1 for s in students if s.get("score"))
        return {"ok": True, "classId": str(class_id), "workId": str(work_id),
                "count": len(students), "scored": scored, "students": students,
                "source": "archive", "file": str(target[1])}

    manifest = _manifest_students(home, class_id, work_id)
    if manifest is not None:
        return manifest

    return {"ok": False, "error": "no archived review list",
            "hint": "该作业没有本地 review 列表存档，也没有已下载的 students.json 清单"}
