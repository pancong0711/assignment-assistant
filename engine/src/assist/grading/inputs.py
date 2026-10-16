"""D86 §3/§4：批阅输入装配（"批阅任务清单" plan）。

把三个来源合成一份 plan（PWA/CLI 共享）：
1. **班级↔工作区映射**（`xxt.classmap`）→ class_dir；
2. **带 tag 名单**（`classes/<dir>/roster/*.xlsx`，`read_roster` 返回 tag）；
3. **作业包（按 tag）**：`<ws>/tasks/*.taskpad.json`（或 PWA 显式传入）→ 该 tag 的题目/参考答案；
4. **作答（批阅下载）**：`<xxt_home>/pages/review/<classId>/<workId>/students.json` + 图片。

plan 结构：
{
  "taskId": ..., "classDir": ..., "courseId":..., "classId":..., "workId":...,
  "mode": "optimized"|"brute", "questionsByTag": {"<tag>": [{no,content,solution}]},
  "students": [{name, number, tag, workAnswerId, images:[abs paths], questions:[...]}],
  "tags": [...], "generatedAt": ...
}
落盘：`classes/<dir>/grading/<taskId>/plan.json`。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROSTER_EXTS = (".xlsx", ".xls")


def roster_file(ws, class_dir: str) -> "Path | None":
    """班级名单：优先 roster/roster.xlsx，其次 roster 目录里第一个 xlsx。"""
    base = Path(ws) / class_dir / "roster"
    if not base.is_dir():
        return None
    first = base / "roster.xlsx"
    if first.is_file():
        return first
    for f in sorted(base.iterdir()):
        if f.is_file() and f.suffix.lower() in ROSTER_EXTS and not f.name.startswith("~$"):
            return f
    return None


def students_with_tags(ws, class_dir: str) -> list[dict]:
    from ..files.roster import read_roster
    fn = roster_file(ws, class_dir)
    if fn is None:
        return []
    out = []
    for s in read_roster(fn):
        out.append({"name": str(s.get("name") or ""), "number": str(s.get("number") or ""),
                    "tag": str(s.get("tag") or "")})
    return [s for s in out if s["name"]]


def _questions_of(task: dict, ws=None) -> list[dict]:
    from ..paper.task import resolve_items
    from ..files.solutions import effective_solution
    # 用 items（含 tag/id）直接取题目，避免依赖 kb 展开（无 kb 时也能出题面）
    out: list[dict] = []
    for it in (task.get("items") or []):
        if not isinstance(it, dict):
            continue
        qid = str(it.get("no") or it.get("id") or "")
        fallback = str(it.get("solution") or "")
        # D89-N3：有 ws 且有 qid → 实时读最新置顶版
        sol = effective_solution(ws, qid, fallback).get("text", fallback) if (ws and qid) else fallback
        out.append({"no": str(it.get("no") or ""), "content": str(it.get("content") or ""),
                    "solution": sol,
                    "tag": str(it.get("tag") or task.get("target_tag") or "")})
    return out


def pads_by_tag(ws, explicit: "dict[str, dict] | None" = None,
                tasks_dir: "Path | None" = None) -> dict[str, dict]:
    """tag → {padId, questions[]}。explicit 优先（PWA 直接注入），否则扫 <ws>/tasks/*.taskpad.json。"""
    from ..paper.batch import pad_tag
    out: dict[str, dict] = {}
    if explicit:
        for tag, task in explicit.items():
            if isinstance(task, dict):
                out[str(tag)] = {"padId": str(task.get("id") or ""), "questions": _questions_of(task, ws)}
    root = Path(tasks_dir) if tasks_dir else (Path(ws) / "tasks")
    if root.is_dir():
        for f in sorted(root.glob("*.taskpad.json")):
            try:
                task = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            tag = pad_tag(task) or str(task.get("target_tag") or "")
            if tag and tag not in out:
                out[tag] = {"padId": str(task.get("id") or f.stem), "questions": _questions_of(task, ws)}
    return out


def review_dir_for(class_id: str, work_id: str) -> Path:
    from ..xxt import layout
    return layout.pages_dir() / "review" / str(class_id) / str(work_id)


def read_review_students(class_id: str, work_id: str) -> tuple[Path, list[dict]]:
    """读批阅下载清单：返回 (目录, [{name, workAnswerId, images:[abs], score}])。"""
    d = review_dir_for(class_id, work_id)
    man = d / "students.json"
    if not man.is_file():
        return d, []
    try:
        data = json.loads(man.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d, []
    students = data.get("students") if isinstance(data, dict) else None
    out: list[dict] = []
    for s in (students or []):
        if not isinstance(s, dict) or not s.get("name"):
            continue
        imgs = []
        for name in (s.get("images") or []):
            p = d / str(name)
            if p.is_file():
                imgs.append(str(p))
        out.append({"name": str(s["name"]), "workAnswerId": str(s.get("workAnswerId") or ""),
                    "images": imgs, "score": s.get("score") or ""})
    return d, out


def build_plan(ws, *, task_id: str, class_dir: str, class_id: str = "", work_id: str = "",
               mode: str = "optimized", tags: "list[str] | None" = None,
               explicit_pads: "dict[str, dict] | None" = None,
               tasks_dir: "Path | None" = None,
               review_students: "list[dict] | None" = None) -> dict:
    """合成批阅任务清单（students 按 tag 关联题目；tags 过滤）。"""
    tag_pads = pads_by_tag(ws, explicit_pads, tasks_dir)
    roster = students_with_tags(ws, class_dir)
    _, rev = (Path(""), []) if review_students is not None else read_review_students(class_id, work_id)
    review = review_students if review_students is not None else rev
    by_name = {r["name"]: r for r in review}

    want = {str(t) for t in (tags or []) if str(t).strip()}
    students: list[dict] = []
    for s in roster:
        tag = s.get("tag") or ""
        if want and tag not in want:
            continue
        r = by_name.get(s["name"]) or {}
        students.append({
            "name": s["name"], "number": s.get("number") or "", "tag": tag,
            "workAnswerId": r.get("workAnswerId") or "",
            "images": list(r.get("images") or []),
            "questions": list((tag_pads.get(tag) or {}).get("questions") or []),
            "padId": (tag_pads.get(tag) or {}).get("padId") or "",
        })
    # 批阅下载里有、但名单里没有的学生（补进来，tag 空）
    for r in review:
        if not any(x["name"] == r["name"] for x in students):
            if want:
                continue
            students.append({"name": r["name"], "number": "", "tag": "",
                             "workAnswerId": r.get("workAnswerId") or "",
                             "images": list(r.get("images") or []), "questions": [], "padId": ""})
    return {
        "taskId": str(task_id), "classDir": str(class_dir),
        "courseId": str(class_id), "classId": str(class_id), "workId": str(work_id),
        "mode": "brute" if str(mode).startswith("brute") else "optimized",
        "tags": sorted({s["tag"] for s in students if s["tag"]}),
        "questionsByTag": {t: v["questions"] for t, v in tag_pads.items()},
        "students": students,
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def plan_path(ws, class_dir: str, task_id: str) -> Path:
    return Path(ws) / class_dir / "grading" / str(task_id) / "plan.json"


def save_plan(ws, class_dir: str, plan: dict) -> Path:
    p = plan_path(ws, class_dir, plan.get("taskId") or "task")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load_plan(ws, task_id: str, class_dir: str = "") -> "dict | None":
    if class_dir:
        p = plan_path(ws, class_dir, task_id)
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    base = Path(ws)
    for f in base.glob("classes/*/grading/*/plan.json"):
        if f.parent.name == str(task_id):
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
    return None


def plan_summary(plan: dict) -> dict:
    students = plan.get("students") or []
    no_img = [s["name"] for s in students if not s.get("images")]
    no_q = [s["name"] for s in students if not s.get("questions")]
    return {"taskId": plan.get("taskId"), "classDir": plan.get("classDir"),
            "mode": plan.get("mode"), "tags": plan.get("tags") or [],
            "students": len(students), "withImages": len(students) - len(no_img),
            "noImages": no_img, "noQuestions": no_q}
