"""D193 §3：批阅报告的**内容哈希版本**（不是文件名时间戳）。

设计目标（教师诉求：报告要与上传/分数对得上、新版覆盖旧版、历史可回溯）：

- 稳定路径：`reports/<学生>.md|.html|.png` **始终是最新**（覆盖写）——
  前端、上传、预览、历史引用都不用改路径；
- 版本号 = `sha256(markdown)[:6]`（内容哈希）→ **幂等**：内容没变不产生新版本，
  不会每点一次生成就多一份；
- 历史：`reports/.versions/<学生>/<YYYYmmdd-HHMMSS>-<ver>.{md,html,png}`；
- 索引：`reports/.versions/index.json`，记录
  `{student, version, ts, kind, score, sha256, reason, files}`；
- 草稿回写 `human.report = {version, sha256, generatedAt, file}`，
  上传清单与报告页脚用同一个版本号，教师能直接对照。

纯函数 + 文件操作，不依赖 playwright（PNG 由调用方渲染后交给 `record()`）。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

INDEX_NAME = "index.json"
VERSIONS_DIR = ".versions"
_MAX_KEEP = 30          # 每生最多保留的历史版本数（超出删最旧）
_SAFE = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+")


def safe_stem(name: str) -> str:
    """学生名 → 可用作文件名/目录名的稳定串（保留中文）。"""
    s = _SAFE.sub("_", str(name or "").strip()).strip(" ._")
    return s or "student"


def content_digest(md: str) -> str:
    """报告版本号：markdown 内容的 sha256 前 6 位（稳定、幂等、可校验）。"""
    return hashlib.sha256(str(md or "").encode("utf-8")).hexdigest()[:6]


def version_tag(ts: float | None = None, version: str = "") -> str:
    """人类可读版本标签：`20261118-140302-ab12cd`（报告页脚/清单展示用）。"""
    t = time.localtime(ts if ts is not None else time.time())
    return f"{time.strftime('%Y%m%d-%H%M%S', t)}-{str(version or '')[:6]}"


def read_index(reports_dir) -> dict:
    p = Path(reports_dir) / VERSIONS_DIR / INDEX_NAME
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 缺省/损坏都当作空索引
        return {"items": []}
    if not isinstance(data, dict):
        return {"items": []}
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    return data


def _write_index(reports_dir, data: dict) -> None:
    from ..filelock import atomic_write_text
    p = Path(reports_dir) / VERSIONS_DIR / INDEX_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps(data, ensure_ascii=False, indent=1))


def latest_entry(reports_dir, student: str) -> "dict | None":
    """某学生最新一条版本记录（没有则 None）。"""
    name = str(student or "")
    hits = [x for x in read_index(reports_dir).get("items") or []
            if isinstance(x, dict) and str(x.get("student") or "") == name]
    if not hits:
        return None
    return max(hits, key=lambda x: (float(x.get("ts") or 0), str(x.get("version") or "")))


def record(reports_dir, student: str, md: str, *, kind: str = "", score=None,
           reason: str = "", files: "list[Path] | None" = None,
           copy_files: "list[Path] | None" = None) -> dict:
    """登记一次报告生成；内容未变时**不产生新版本**（但仍刷新 mtime 与 latest）。

    参数：
      md         报告 markdown（版本号来源）
      files      本次写出的“最新”文件（md/html/png，会被复制进 .versions）
      copy_files 显式指定要归档的文件（缺省=files）
    返回：{version, sha256, tag, ts, changed, entry, latestFiles}
    """
    reports_dir = Path(reports_dir)
    version = content_digest(md)
    digest = hashlib.sha256(str(md or "").encode("utf-8")).hexdigest()
    ts = time.time()
    prev = latest_entry(reports_dir, student)
    changed = not (prev and str(prev.get("sha256") or "") == digest)
    tag = version_tag(ts, version)

    entry = {
        "student": str(student or ""),
        "version": version,
        "sha256": digest,
        "tag": tag,
        "ts": ts,
        "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
        "kind": str(kind or ""),
        "score": score if isinstance(score, (int, float)) else None,
        "reason": str(reason or ""),
        "files": [],
    }
    srcs = [Path(f) for f in (copy_files if copy_files is not None else (files or []))]
    if changed and srcs:
        stem = safe_stem(student)
        vdir = reports_dir / VERSIONS_DIR / stem
        vdir.mkdir(parents=True, exist_ok=True)
        for src in srcs:
            if not src.is_file():
                continue
            dst = vdir / f"{tag}{src.suffix}"
            try:
                dst.write_bytes(src.read_bytes())
                entry["files"].append(dst.name)
            except OSError:
                continue
        # 历史上限：超出删最旧
        olds = sorted([p for p in vdir.iterdir() if p.is_file()],
                      key=lambda p: p.stat().st_mtime)
        for p in olds[:max(0, len(olds) - _MAX_KEEP * 3)]:
            try:
                p.unlink()
            except OSError:
                pass

    data = read_index(reports_dir)
    items = [x for x in data.get("items") or []
             if isinstance(x, dict) and not (
                 str(x.get("student") or "") == str(student or "")
                 and str(x.get("sha256") or "") == digest)]
    items.append(entry)
    # 每生最多保留 _MAX_KEEP 条索引
    per: dict[str, list] = {}
    for x in items:
        per.setdefault(str(x.get("student") or ""), []).append(x)
    trimmed: list = []
    for _stu, rows in per.items():
        rows.sort(key=lambda x: float(x.get("ts") or 0), reverse=True)
        trimmed.extend(rows[:_MAX_KEEP])
    data["items"] = sorted(trimmed, key=lambda x: float(x.get("ts") or 0))
    try:
        _write_index(reports_dir, data)
    except Exception:  # noqa: BLE001 —— 索引落盘失败不影响报告本身
        pass
    return {"version": version, "sha256": digest, "tag": tag,
            "ts": int(ts), "changed": changed, "entry": entry,
            "latestFiles": [str(Path(f)) for f in (files or [])]}


def history(reports_dir, student: str) -> "list[dict]":
    """某生的版本历史（新→旧）。"""
    rows = [x for x in read_index(reports_dir).get("items") or []
            if isinstance(x, dict) and str(x.get("student") or "") == str(student or "")]
    return sorted(rows, key=lambda x: float(x.get("ts") or 0), reverse=True)


def index_stats(reports_dir, *, keep_students: "list[str] | None" = None) -> dict:
    """D198：索引构成诊断——区分“**版本记录数**”与“**学生数**”。

    现场误解：清理后仍显示 106 条，教师以为是 106 名学生；实际是
    53 名学生 × 2 个内容版本 = 106 条**记录**，按名单清理自然一条都不用删。

    返回：
      totalRecords      索引总记录数
      studentCount      索引涉及的学生数（去重）
      avgVersions       平均每生几条
      historyRecords    各生“最新”之外的历史版本记录数
      inRosterRecords   属于当前名单的记录数（无名单时等于 totalRecords）
      orphanRecords     不属于当前名单的记录数
      orphanStudents    不属于当前名单的学生名（最多 50）
    """
    reports_dir = Path(reports_dir)
    items = [x for x in (read_index(reports_dir).get("items") or [])
             if isinstance(x, dict)]
    names = {str(x).strip() for x in (keep_students or []) if str(x).strip()}
    by_student: dict[str, int] = {}
    for x in items:
        stu = str(x.get("student") or "")
        by_student[stu] = by_student.get(stu, 0) + 1
    student_count = len(by_student)
    history = sum(max(0, n - 1) for n in by_student.values())
    orphan_students = sorted(s for s in by_student if names and s not in names)
    orphan_records = sum(by_student[s] for s in orphan_students)
    return {"ok": True, "totalRecords": len(items), "studentCount": student_count,
            "avgVersions": round(len(items) / student_count, 2) if student_count else 0.0,
            "historyRecords": history,
            "inRosterRecords": len(items) - orphan_records if names else len(items),
            "orphanRecords": orphan_records,
            "orphanStudents": orphan_students[:50],
            "byStudent": by_student}


def compact_index(reports_dir, *, keep_latest: int = 1,
                  keep_students: "list[str] | None" = None,
                  dry_run: bool = True,
                  delete_history_files: bool = False) -> dict:
    """D198：**压缩版本历史**——每生只保留最新 N 条索引（默认 1）。

    用于“索引条数太多”但并没有凑数学生的场景：106 条 = 53 人 × 2 版。
    默认只压缩索引；`delete_history_files=True` 时一并删除被压缩掉的
    `.versions/<学生>/` 历史文件（谨慎，默认关）。

    返回 `{ok, dryRun, before, after, removed, students, filesDeleted}`
    """
    reports_dir = Path(reports_dir)
    keep_latest = max(1, int(keep_latest or 1))
    items = [x for x in (read_index(reports_dir).get("items") or [])
             if isinstance(x, dict)]
    names = {str(x).strip() for x in (keep_students or []) if str(x).strip()}
    # 按学生分组，组内按时间新→旧；名单外的学生**不压缩**（交给 cleanup 处理）
    groups: dict[str, list[dict]] = {}
    for x in items:
        stu = str(x.get("student") or "")
        groups.setdefault(stu, []).append(x)
    keep_items: list[dict] = []
    dropped: list[dict] = []
    files_deleted = 0
    vroot = reports_dir / VERSIONS_DIR
    for stu, rows in groups.items():
        rows.sort(key=lambda x: float(x.get("ts") or 0), reverse=True)
        if names and stu not in names:
            keep_items.extend(rows)   # 不在名单：保持原样
            continue
        keep_items.extend(rows[:keep_latest])
        for old in rows[keep_latest:]:
            dropped.append({"student": stu, "version": str(old.get("version") or ""),
                            "tag": str(old.get("tag") or "")})
            if not dry_run and delete_history_files:
                for f in (old.get("files") or []):
                    fp = vroot / safe_stem(stu) / str(f)
                    try:
                        if fp.is_file():
                            fp.unlink()
                            files_deleted += 1
                    except OSError:
                        pass
    if not dry_run and dropped:
        data = read_index(reports_dir)
        data["items"] = sorted(keep_items, key=lambda x: float(x.get("ts") or 0))
        _write_index(reports_dir, data)
    return {"ok": True, "dryRun": bool(dry_run), "keepLatest": keep_latest,
            "before": len(items), "after": len(items) - len(dropped),
            "removed": len(dropped), "removedItems": dropped[:50],
            "filesDeleted": files_deleted,
            "students": len(groups)}


def prune_index(reports_dir, *, keep_students: "list[str] | None" = None,
                drop_missing_files: bool = True) -> dict:
    """D197：清理版本索引（`.versions/index.json`）里**不属于本次名单**的记录。

    现场问题：清理报告文件后，“报告版本”里仍然显示 106 条——因为旧实现只删文件、
    从不清理索引；索引把历史批次的学生“固定”下来了，没有按本次作业提交名单核对。

    规则：
      - `keep_students` 非空：删除 `student` 不在名单里的所有条目；
      - `drop_missing_files=True`：条目声明的文件全部不存在 → 视为孤儿条目删除；
      - 只改索引，不动任何报告文件。

    返回 `{ok, removed, kept, count}`（`removed` 为被删条目摘要）。
    """
    reports_dir = Path(reports_dir)
    data = read_index(reports_dir)
    items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
    keep = {str(x).strip() for x in (keep_students or []) if str(x).strip()}
    vroot = reports_dir / VERSIONS_DIR
    removed: list[dict] = []
    kept: list[dict] = []
    for it in items:
        stu = str(it.get("student") or "")
        if keep and stu not in keep:
            removed.append({"student": stu, "version": str(it.get("version") or ""),
                            "reason": "不在当前名单"})
            continue
        if drop_missing_files:
            files = [str(f) for f in (it.get("files") or [])]
            if files and not any((vroot / safe_stem(stu) / f).is_file() for f in files):
                removed.append({"student": stu, "version": str(it.get("version") or ""),
                                "reason": "历史文件已不存在"})
                continue
        kept.append(it)
    data["items"] = kept
    if removed:
        _write_index(reports_dir, data)
    return {"ok": True, "removed": removed, "kept": len(kept), "count": len(removed),
            "before": len(items), "after": len(kept)}


def cleanup_reports(reports_dir, *, keep_students: "list[str] | None" = None,
                    dry_run: bool = True) -> dict:
    """D195/D197：清理“重复/不在名单”的报告文件 + 同步清理版本索引。

    触发场景：历史上同一学生按两个草稿键生成了两份报告，写进同名文件；
    或作业包换过、reports/ 里残留了旧学生名；或版本索引残留上一批次记录。

    D197：`keep_students` **必须有值**才允许真正删除——空名单意味着前端没读到
    当前作业的提交学生，此时按“全部都是多余的”删会误删，宁可报错让教师先读取名单。
    """
    reports_dir = Path(reports_dir)
    keep = {str(x).strip() for x in (keep_students or []) if str(x).strip()}
    if not keep:
        return {"ok": False, "dryRun": bool(dry_run),
                "error": "缺少本次名单（keep_students 为空）：请先在「逐生审核」读取学生清单后再清理",
                "removed": [], "kept": [], "count": 0}
    if not reports_dir.is_dir():
        return {"ok": True, "dryRun": bool(dry_run), "removed": [], "kept": [],
                "count": 0, "indexRemoved": 0, "indexBefore": 0, "indexAfter": 0}
    removed: list[dict] = []
    kept: list[str] = []
    for f in sorted(reports_dir.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        if f.suffix.lower() not in (".md", ".html", ".png"):
            continue
        stem = f.stem
        # D197-FIX：`_teacher_report.md` / `_global_report.md` 等**班级级汇总产物**
        # 不是“某学生的报告”，不参与按名单清理（它们是可再生的统计报告，删了会让人困惑）。
        if stem.startswith("_"):
            kept.append(f.name)
            continue
        if stem not in keep:
            removed.append({"name": f.name, "reason": "不在本次名单"})
            if not dry_run:
                try:
                    f.unlink()
                except OSError:
                    pass
        else:
            kept.append(f.name)
    # 版本历史目录：只保留名单内学生
    vroot = reports_dir / VERSIONS_DIR
    if vroot.is_dir():
        for d in sorted(vroot.iterdir()):
            if not d.is_dir():
                continue
            if d.name in keep:
                continue
            removed.append({"name": f"{VERSIONS_DIR}/{d.name}/",
                            "reason": "历史版本（不在本次名单）"})
            if not dry_run:
                for f in sorted(d.iterdir()):
                    try:
                        f.unlink()
                    except OSError:
                        pass
                try:
                    d.rmdir()
                except OSError:
                    pass
    # D197：索引同步清理（旧实现漏了这一步 → 版本列表长期显示旧批次记录）
    if dry_run:
        # dry-run 只统计“将会删多少索引条目”，**绝不改索引**（旧实现这里误写盘了）
        items = [x for x in (read_index(reports_dir).get("items") or [])
                 if isinstance(x, dict)]
        would = [x for x in items if str(x.get("student") or "") not in keep]
        idx = {"removed": would, "count": len(would),
               "before": len(items), "after": len(items) - len(would),
               "kept": len(items) - len(would)}
    else:
        idx = prune_index(reports_dir, keep_students=list(keep), drop_missing_files=True)
    stats = index_stats(reports_dir, keep_students=list(keep))
    # D198：把“为什么索引没减”说清楚——106 条常常是 53 人 × 2 版，不是 106 名学生。
    parts: list[str] = []
    if removed:
        parts.append(f"删除报告文件 {len(removed)} 个")
    if idx.get("count"):
        parts.append(f"版本索引记录 {idx.get('count', 0)} 条")
    if not parts:
        parts.append("没有“多余学生”的报告文件")
    if stats["historyRecords"] > 0:
        parts.append(
            f"名单内 {stats['studentCount']} 名学生共 {stats['totalRecords']} 条版本记录，"
            f"其中 {stats['historyRecords']} 条为**历史版本**（不是多余学生）；"
            f"若要减少记录数请用「🗜 压缩版本历史」（每生保留最新 1 版）")
    elif not idx.get("count"):
        parts.append(
            f"名单内 {stats['studentCount']} 名学生共 {stats['totalRecords']} 条记录，没有多余内容")
    hint = "；".join(parts) + "。"
    return {"ok": True, "dryRun": bool(dry_run), "removed": removed, "kept": kept,
            "count": len(removed),
            "indexRemoved": idx.get("count", 0),
            "indexBefore": idx.get("before", 0),
            "indexAfter": idx.get("after", 0),
            "indexRemovedItems": idx.get("removed", [])[:50],
            "stats": stats, "hint": hint}
