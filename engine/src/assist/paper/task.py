"""作业纸任务包 → PDF（阶段1）。

任务包即 CLI 的固化参数（05-D2：CLI 参数/Web 实体/执行历史三合一）。
schema 见 docs/04 §1：layout.orientation / per_page / items[{kb,chap,ids,tag}]。
"""

import json
from pathlib import Path

from loguru import logger

from ..files import read_kb
from ..files.roster import read_roster
from .layout import make_pdf


def load_task(task_path: Path) -> dict:
    return json.loads(Path(task_path).read_text(encoding="utf-8"))


def resolve_items(kb_data: dict, task_items: list[dict], kb_dir: Path) -> list[tuple]:
    """按任务包 items 展开 [kind/chap/ids/tag] → [(content, img_abspath, tag)]。

    迁移自 _legacy/2603paperDesign/src/paperdesign/kbtools.py 的按 id 抽题逻辑
    （_oneChap：遍历题库 sheet，匹配 ids）；ids 为空则整章全收。
    """
    out = []
    for spec in task_items:
        kind = spec.get("kb", "problems")
        chap = spec.get("chap")
        ids = spec.get("ids")
        tag = spec.get("tag", kind)
        chapters = kb_data.get(kind, {})
        if chap:
            entries = list(chapters.get(chap, []))
        else:
            entries = [e for chs in chapters.values() for e in chs]
        if ids:
            entries = [e for e in entries if str(e.get("id")) in {str(i) for i in ids}]
        else:
            entries = entries
        for e in entries:
            img = e.get("img_path")
            if img and not str(img).startswith("/"):
                img = str(kb_dir / str(img))
            out.append((e.get("content"), img, tag))
    if not out:
        logger.warning("任务包未选中任何题目")
    return out


def sheets_from_task(task_path: Path, ws: Path, out_dir: Path | None = None,
                     title_default: str = "大学物理-作业纸", assets_dir=None,
                     no_watermark: bool = False,
                     roster_path: str | None = None) -> list[Path]:
    """根据任务包生成每个学生一份 pdf。"""
    task = load_task(task_path)
    kb_dir = ws / "kb"
    kb_data = read_kb(kb_dir)
    items = resolve_items(kb_data, task.get("items", []), kb_dir)
    lay = task.get("layout", {})
    orientation = lay.get("orientation", "portrait")
    title = lay.get("header", {}).get("title", title_default)

    roster_fn = ws / task.get("class_dir", "classes") / "roster" / f"{task['id']}-roster.xlsx"
    if not roster_fn.parent.exists():
        roster_fn.parent.mkdir(parents=True, exist_ok=True)
    r_path = None
    if roster_path:
        r_path = Path(roster_path).expanduser().resolve()
    elif task.get("roster"):
        r_path = (ws / task["roster"]).resolve()
    if r_path is None or not r_path.exists():
        r_path = roster_fn if roster_fn.exists() else None
    if r_path is None:
        raise FileNotFoundError("缺少点名册：--roster 或 classes/<class>/roster/<id>-roster.xlsx")

    students = read_roster(r_path)
    if not students:
        raise ValueError(f"点名册为空: {r_path}")

    out = out_dir or (ws / task.get("class_dir", "classes") / "sheets" / "out")
    return make_pdf(
        students,
        lambda i: items, out,
        orientation=orientation,
        assets_dir=assets_dir,
        title=title,
        notes_prefix=f"{task['id']}",
        watermark=not no_watermark and True,
    )


def roster_fn_exists(fn: Path) -> bool:
    return fn.exists()


def out_dir_mkdir(out: Path):
    Path(out).mkdir(parents=True, exist_ok=True)
