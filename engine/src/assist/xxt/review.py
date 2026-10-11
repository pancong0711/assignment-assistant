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


def comment_image_filename(student_name: str, class_name: str, work_name: str,
                           page: int, ext: str = ".jpg", qidx: "int | None" = None) -> str:
    """D75-7：评语图片命名（与学生作答同口径，带 comment / q{n} 标记）。"""
    ext = ext if str(ext).startswith(".") else "." + str(ext)
    if ext.lower() not in IMAGE_EXTS:
        ext = ".jpg"
    mid = f"_q{qidx}" if qidx else ""
    return (f"{sanitize_filename(student_name)}_"
            f"{sanitize_filename(class_name)}+{sanitize_filename(work_name)}"
            f"_comment{mid}_p{page:02d}{ext}")


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
            comment_images = [n for n in images if "_comment" in n]
            answer_images = [n for n in images if "_comment" not in n]
            total = sum(p.stat().st_size for p in wd.rglob("*") if p.is_file())
            students = manifest.get("students") or []
            with_img = [s for s in students if s.get("images")]
            zero = [s.get("name") or s.get("studentId") or "?" for s in students if not s.get("images")]
            out.append({
                "classId": cd.name, "workId": wd.name,
                "courseId": str(manifest.get("courseId") or ""),
                "courseName": str(manifest.get("courseName") or ""),
                "className": str(manifest.get("className") or ""),
                "workName": str(manifest.get("workName") or ""),
                "count": len(answer_images), "comment_count": len(comment_images),
                "students": len(students), "bytes": total,
                "images_deleted": bool(manifest.get("images_deleted")),
                "mtime": wd.stat().st_mtime,
                "generated_at": manifest.get("generated_at") or "",
                "images": images,
                # D75-1e：0 图诊断
                "students_total": len(students),
                "students_with_images": len(with_img),
                "zero_image_count": len(zero),
                "zero_image_students": zero[:20],
            })
    return sorted(out, key=lambda x: x["mtime"], reverse=True)


def review_stats(home=None) -> dict:
    items = list_review_works(home)
    return {"works": len(items),
            "images": sum(i["count"] for i in items),
            "comment_images": sum(i.get("comment_count", 0) for i in items),
            "bytes": sum(i["bytes"] for i in items)}


def prune_review(home=None, months: int = 6) -> dict:
    """按作业 mtime 清理超过 months 个月的批阅图片：删图片、留 students.json 清单。"""
    cutoff = time.time() - max(0, int(months)) * 30 * 24 * 3600
    removed: list[str] = []
    images = 0
    for item in list_review_works(home):
        if item["mtime"] >= cutoff:
            continue
        res = delete_work_images(home, item["classId"], item["workId"])
        if res.get("ok"):
            removed.append(f'{item["classId"]}/{item["workId"]}')
            images += int(res.get("deleted_answer") or 0) + int(res.get("deleted_comment") or 0)
    return {"removed": removed, "removed_count": len(removed), "deleted_images": images,
            "months": months, "stats": review_stats(home)}


def purge_review_work(home, class_id: str, work_id: str) -> dict:
    """彻底删除某次作业批阅目录（含 students.json 清单）。"""
    d = safe_work_dir(home, class_id, work_id)
    if d is None or not d.is_dir():
        return {"ok": False, "error": "no such work"}
    had_manifest = (d / "students.json").is_file()
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True, "classId": str(class_id), "workId": str(work_id),
            "purged": True, "had_manifest": had_manifest}



def latest_probe(home=None) -> "dict | None":
    """D75-1e：最近一次 review-probe JSON（供 PWA 读取，无需 terminal）。"""
    from . import layout
    d = layout.pages_dir(home)
    if not d.is_dir():
        return None
    files = sorted(d.glob("review-probe-*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    try:
        data = json.loads(files[-1].read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data["_file"] = str(files[-1])
            return data
    except Exception:  # noqa: BLE001
        return None
    return None


# ============ D75-11：删除某次作业的图片（保留 students.json 清单） ============

def delete_work_images(home, class_id: str, work_id: str) -> dict:
    """删除该次作业的作答/评语图片与子目录；保留 students.json 并追加删除记录。"""
    d = safe_work_dir(home, class_id, work_id)
    if d is None or not d.is_dir():
        return {"ok": False, "error": "no such work"}
    manifest = read_manifest(home, class_id, work_id) or {}
    ans = com = 0
    for p in list(d.iterdir()):
        if p.is_file() and p.name != "students.json" and p.suffix.lower() in IMAGE_EXTS:
            if "_comment_" in p.name or re.search(r"_q\d+_p\d+", p.name):
                com += 1
            else:
                ans += 1
            try:
                p.unlink()
            except Exception:  # noqa: BLE001
                pass
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    for stu in manifest.get("students") or []:
        if isinstance(stu, dict):
            if stu.get("images"):
                stu["deleted_images"] = list(stu.get("images") or [])
                stu["images"] = []
            if stu.get("comment_images"):
                stu["deleted_comment_images"] = list(stu.get("comment_images") or [])
                stu["comment_images"] = []
            if stu.get("per_question_comment_images"):
                stu["deleted_per_question_comment_images"] = list(stu.get("per_question_comment_images") or [])
                stu["per_question_comment_images"] = []
    manifest.update({
        "images_deleted": True,
        "images_deleted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "deleted_answer_images": ans,
        "deleted_comment_images": com,
        "delete_note": "手工删除该次作业图片（保留清单）",
    })
    write_manifest(home, class_id, work_id, manifest)
    return {"ok": True, "classId": str(class_id), "workId": str(work_id),
            "deleted_answer": ans, "deleted_comment": com}
