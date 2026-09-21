"""sheet batch —— 变体编排（D23）：整班按 tag 自动选任务包生成作业纸（最小可用版）。

输入：带 tag 名单 xlsx（assist roster tag 产出）+ 若干任务包 JSON。
映射规则（无需人工填 map）：
- 任务包 target_tag 字段优先；
- 否则 items 中唯一 tag 即映射（混合 tag 的包需显式映射，报错提示加 --map）；
- 无任何命中 tag 的学生 → 用 --default 指定的任务包（可省）。

产出：classes/<class>/sheets/batch/<tag>/ 下每生一份 PDF。
"""

from pathlib import Path

from loguru import logger

from ..files.roster import read_roster
from .task import load_task, resolve_items
from ..files.kb_io import read_kb


def pad_tag(task: dict) -> str | None:
    """任务包归属 tag：target_tag 优先；items 唯一 tag 次之；否则 None（需显式映射）。"""
    direct = task.get("target_tag")
    if direct:
        return str(direct)
    tags = sorted({str(it.get("tag")) for it in task.get("items", []) if it.get("tag")})
    if len(tags) == 1:
        return tags[0]
    if len(tags) == 0:
        return "default"
    return None


def batch_sheets(roster_fn: Path, task_files: list[Path], ws: Path,
                 class_dir: str | None = None, out_root: Path | None = None,
                 mapping: dict[str, str] | None = None,
                 default_pad: str | None = None) -> list[Path]:
    """tag→任务包绑定后，按组生成整班作业纸。"""
    from .layout import make_pdf

    rows = read_roster(Path(roster_fn).expanduser().resolve())
    if not rows:
        raise FileNotFoundError(f"名单为空: {roster_fn}")

    pads: dict[str, dict] = {}
    pad_names: dict[str, str] = {}
    for f in task_files:
        task = load_task(Path(f).expanduser().resolve())
        tag = pad_tag(task)
        if tag is None and mapping:
            for t, pid in (mapping or {}).items():
                if Path(pid).name == Path(f).name or t + ".json" == Path(f).name:
                    tag = t
        if tag is None:
            raise RuntimeError(
                f"任务包 {f.name} 未与唯一 tag 绑定（target_tag 或 items 唯一 tag）"
                "——可用 --map 补充映射")
        if tag in pads:
            raise RuntimeError(f"tag={tag} 已绑定 {pad_names[tag]}，重复映射忽略 {f}")
        pads[tag] = task
        pad_names[tag] = f.name

    kb_dir = ws / "kb"
    kb_data = read_kb(kb_dir)
    out_dir = out_root or (ws / (class_dir or "classes") / "sheets" / "batch")
    out_dir.mkdir(parents=True, exist_ok=True)

    by_tag: dict[str, list[dict]] = {}
    for r in rows:
        by_tag.setdefault(str(r.get("tag") or "default"), []).append(r)

    generated: list[Path] = []
    seen = {}
    for tag, group in by_tag.items():
        pad = pads.get(tag) or (pads.get(default_pad) if default_pad else None)
        if pad is None:
            logger.warning(f"tag={tag} 无绑定任务包，跳过 {len(group)} 人（+assigned: {list(pads)}）")
            continue
        items = resolve_items(kb_data, pad.get("items", []), kb_dir)
        lay = pad.get("layout", {})
        stu = [{"name": r["name"], "number": r.get("number", ""),
                "class": r.get("class", "")} for r in group]
        out_tag = out_dir / tag
        files = make_pdf(
            stu, lambda _i: items, out_tag,
            orientation=lay.get("orientation", "portrait"),
            assets_dir=None,
            title=lay.get("header", {}).get("title", "大学物理-作业纸"),
            notes_prefix=f"{tag}:{pad.get('id', '')}",
            watermark=lay.get("watermark", {}).get("enabled", True) is not False,
            per_page=lay.get("per_page"),
        )
        generated += files
        seen[tag] = pad_names.get(tag, pad.get("id"))
    logger.info(f"batch 完成 {sum(len(v) for v in by_tag.values())} 名学生 ← {list(seen)}")
    return generated
