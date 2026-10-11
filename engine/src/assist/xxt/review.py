"""D75-1c/d：批阅图片 + 两栏批语的落盘、目录索引与按时长清理。

存储：`xxt_home()/pages/review/<classId>/<workId>/`
图片：`{学生}_{班级}+{作业}_pNN.ext`（沿用旧代码 path_utils.build_image_path 的友好命名）
清单：`students.json`（映射 studentId/name/workAnswerId + 旧命名文件名 + 两栏批语 + 分数）
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def review_root(home=None) -> Path:
    from . import layout
    return layout.pages_dir(home) / "review"


def work_dir(home, class_id: str, work_id: str) -> Path:
    return review_root(home) / str(class_id) / str(work_id)


def sanitize_filename(name) -> str:
    """清理 Windows/Unix 文件名非法字符（沿用旧代码口径）。"""
    return re.sub(r'[\\/*?:"<>|]', "_", str(name or "")).strip() or "unknown"


def image_filename(student_name: str, class_name: str, work_name: str,
                   page: int, ext: str = ".jpg") -> str:
    ext = ext if str(ext).startswith(".") else "." + str(ext)
    if ext.lower() not in IMAGE_EXTS:
        ext = ".jpg"
    return (f"{sanitize_filename(student_name)}_"
            f"{sanitize_filename(class_name)}+{sanitize_filename(work_name)}_p{page:02d}{ext}")


def safe_work_dir(home, class_id: str, work_id: str) -> "Path | None":
    """防目录穿越：classId/workId 只允许数字/字母/-/_。"""
    for v in (str(class_id), str(work_id)):
        if not re.fullmatch(r"[0-9A-Za-z\-_]{1,40}", v):
            return None
    return work_dir(home, class_id, work_id)


def safe_image_path(home, class_id: str, work_id: str, fname: str) -> "Path | None":
    d = safe_work_dir(home, class_id, work_id)
    if d is None or not re.fullmatch(r"[0-9A-Za-z\u4e00-\u9fff（）()+\-_. ]{1,120}", str(fname)):
        return None
    p = (d / fname).resolve()
    if not str(p).startswith(str(d.resolve())):
        return None
    return p if p.is_file() else None


def write_manifest(home, class_id: str, work_id: str, manifest: dict) -> Path:
    d = work_dir(home, class_id, work_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "students.json"
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def read_manifest(home, class_id: str, work_id: str) -> "dict | None":
    p = work_dir(home, class_id, work_id) / "students.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def list_review_works(home=None) -> list[dict]:
    """返回按班级/作业组织的批阅图片目录索引（不含图片字节）。"""
    root = review_root(home)
    out: list[dict] = []
    if not root.is_dir():
        return out
    for cd in sorted(root.iterdir()):
        if not cd.is_dir():
            continue
        for wd in sorted(cd.iterdir()):
            if not wd.is_dir():
                continue
            manifest = read_manifest(home, cd.name, wd.name) or {}
            images = sorted(p.name for p in wd.iterdir()
                            if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
            total = sum(p.stat().st_size for p in wd.rglob("*") if p.is_file())
            students = manifest.get("students") or []
            out.append({
                "classId": cd.name, "workId": wd.name,
                "courseId": str(manifest.get("courseId") or ""),
                "courseName": str(manifest.get("courseName") or ""),
                "className": str(manifest.get("className") or ""),
                "workName": str(manifest.get("workName") or ""),
                "count": len(images), "students": len(students), "bytes": total,
                "mtime": wd.stat().st_mtime,
                "generated_at": manifest.get("generated_at") or "",
                "images": images,
            })
    return sorted(out, key=lambda x: x["mtime"], reverse=True)


def review_stats(home=None) -> dict:
    items = list_review_works(home)
    return {"works": len(items), "images": sum(i["count"] for i in items),
            "bytes": sum(i["bytes"] for i in items)}


def prune_review(home=None, months: int = 6) -> dict:
    """按作业目录 mtime 清理超过 months 个月的批阅图片（独立于 run 历史）。"""
    root = review_root(home)
    cutoff = time.time() - max(0, int(months)) * 30 * 24 * 3600
    removed: list[str] = []
    for item in list_review_works(home):
        if item["mtime"] >= cutoff:
            continue
        d = work_dir(home, item["classId"], item["workId"])
        shutil.rmtree(d, ignore_errors=True)
        removed.append(f'{item["classId"]}/{item["workId"]}')
    # 顺手删空的班级目录
    if root.is_dir():
        for cd in list(root.iterdir()):
            if cd.is_dir() and not any(cd.iterdir()):
                try:
                    cd.rmdir()
                except Exception:  # noqa: BLE001
                    pass
    return {"removed": removed, "removed_count": len(removed),
            "months": months, "stats": review_stats(home)}
