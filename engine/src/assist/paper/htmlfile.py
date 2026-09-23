"""作业纸 HTML 打印主通道（docs/14 §VB-1/2/3，docs/05-D30 输出主通道）。

`assist sheet html --task <taskpad.json> [--roster xlsx]`：
任务包 + 名单 → **单个自包含 HTML 文件**（整班多页）：
- 每生分页块（`page-break-after: always`；最后一块 auto，避免末尾空白页）；
- 横/竖版 `@page { size: A4 landscape/portrait }`；
- per_page 2/3/4 网格（行/列/十字），分隔虚线与 CSS 预览、引擎 PDF 同口径；
- 题图 base64 内嵌（img_path 相对 kb/ 解析；缺失时占位框）；
- 水印 items 逐层（PNG base64 内嵌；找不到图片时占位标记）+ 页码大字；
- KaTeX CDN 渲染题干/答案 `$..$`（离线时源码降级，不报错）。

模板单一事实源 = engine/templates/assignment.html.j2；PWA 同构实现 =
app/src/lib/sheetHtml.ts（D1 超集铁律：CLI 与 PWA 输出同一模板/同一 CSS）。
"""

import base64
import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from loguru import logger

from .. import ASSIST_ROOT
from ..files.roster import read_roster
from .task import load_task

TEMPLATE_NAME = "assignment.html.j2"
KATEX_VERSION = "0.16.4"

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
         ".bmp": "image/bmp"}

# 合成学生（无 roster 时的 informational 演示名单，与 `assist sheet demo` 同风格）
SYNTHETIC_STUDENTS = [
    {"name": "学生A", "number": "2026xxxx01", "class": "classA", "tag": ""},
    {"name": "学生B", "number": "2026xxxx02", "class": "classB", "tag": ""},
]

# 页宽 mm（@page A4；水印 ratio 相对页宽，engine logo_draw 同口径）
_PAGE_W_MM = {"portrait": 210.0, "landscape": 297.0}


def template_dirs() -> list[Path]:
    """模板搜索路径：engine/templates（仓库/源码形态）→ 包内 templates
    （wheel 安装形态，pyproject force-include 落到 assist/templates）。"""
    return [ASSIST_ROOT / "templates", Path(__file__).resolve().parents[1] / "templates"]


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader([str(d) for d in template_dirs() if d.exists()]),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
    )
    return env


def _b64_image(path: Path) -> tuple[str, str] | None:
    """读图片 → (base64, mime)；读失败返回 None。"""
    mime = _MIME.get(path.suffix.lower())
    if not mime:
        return None
    try:
        return base64.b64encode(path.read_bytes()).decode("ascii"), mime
    except OSError as e:
        logger.warning(f"图片读取失败 {path}: {e}")
        return None


def _resolve_asset(ws: Path, hint: str, assets_dir: Path | None) -> Path | None:
    """水印/资源路径 hint 解析：绝对路径 → ws/<hint> → ws/assets/watermark/<名>
    → engine assets/watermark/<名>（engine assets 的 fallback 思路同 watermark.py）。"""
    p = Path(hint)
    if p.is_absolute():
        return p if p.exists() else None
    cands = [ws / hint, ws / "assets" / hint, ws / "assets" / "watermark" / p.name,
             ws / "kb" / hint]
    if assets_dir:
        cands += [assets_dir / hint, assets_dir / "watermark" / p.name]
    for c in cands:
        if c.exists():
            return c
    return None


def _grid_key(orientation: str, per_page: int) -> str:
    """data-grid 键（与 app SheetLayoutView gridClass 同口径）：
    4=十字；3=竖版行/横版列；1/2=竖版行/横版列。"""
    if per_page == 4:
        return "cross"
    if per_page == 3:
        return "rows3" if orientation == "portrait" else "cols3"
    return "rows2" if orientation == "portrait" else "cols2"


def _grid_lines(orientation: str, per_page: int) -> list[str]:
    """页内虚线分隔线类（镜像 engine layout.grid_lines / app sf-line 口径）。"""
    if per_page == 4:
        return ["v", "h"]
    if per_page == 3:
        return ["v31", "v32"] if orientation == "landscape" else ["h31", "h32"]
    if per_page == 2:
        return ["v"] if orientation == "landscape" else ["h"]
    return []


def _watermark_items(task: dict, ws: Path, assets_dir: Path | None,
                     orientation: str) -> list[dict]:
    """水印图层 → 模板行（b64 内嵌或占位标记）。

    三形态（PWA parseWatermark 同口径）：
    1) watermark.items 列表（image/pos/ratio/alpha）；
    2) legacy 三槽 university/text/boat（str 路径 | {path,pos,ratio,alpha}）
       → university→rt、text→lm、boat→lb；
    3) 空 = engine 默认三槽占位（rt/lm/lb），能找到 engine assets logo 则内嵌。
    """
    wm = task.get("watermark") or {}
    raw_items: list[dict] = []
    if isinstance(wm.get("items"), list) and wm.get("items"):
        for it in wm["items"]:
            if not isinstance(it, dict) or not it.get("image"):
                continue
            raw_items.append({"image": str(it.get("image")),
                              "pos": str(it.get("pos") or "mm"),
                              "ratio": float(it.get("ratio") or 0.2),
                              "alpha": float(it.get("alpha") if it.get("alpha") is not None else 0.5)})
    else:
        legacy = [("university", "rt", 0.125, 0.5), ("text", "lm", 0.1, 0.3),
                  ("boat", "lb", 0.3, 0.5)]
        for slot, pos, ratio, alpha in legacy:
            v = wm.get(slot)
            if v is None or isinstance(v, bool) or v == "":
                # 未自定义：仍渲染默认三槽占位（与引擎 PDF 默认水印一致），稍后补 logo
                raw_items.append({"image": f"{slot}", "pos": pos, "ratio": ratio,
                                  "alpha": alpha, "_default_logo": slot})
                continue
            o = v if isinstance(v, dict) else {"path": str(v)}
            img = str(o.get("path") or o.get("image") or "")
            if not img:
                continue
            raw_items.append({"image": img, "pos": str(o.get("pos") or pos),
                              "ratio": float(o.get("ratio") or ratio),
                              "alpha": float(o.get("alpha") if o.get("alpha") is not None else alpha)})
    page_w = _PAGE_W_MM.get(orientation, 210.0)
    out = []
    for it in raw_items:
        b64 = mime = None
        if it.get("_default_logo"):
            logo = {"university": "logo-university.png", "text": "logo-text.png",
                    "boat": "logo-boat.png"}[it["_default_logo"]]
            p = _resolve_asset(ws, logo, assets_dir)
            label = f"{it['_default_logo']}（默认槽 logo：{logo}）"
        else:
            p = _resolve_asset(ws, it["image"], assets_dir)
            label = it["image"]
        if p is not None:
            got = _b64_image(p)
            if got:
                b64, mime = got
                label = str(p.name)
        if not (b64 and mime):
            logger.warning(f"水印图缺失，占位标记: {it['image']}")
        out.append({"pos": it["pos"], "ratio": it["ratio"], "alpha": it["alpha"],
                    "width_mm": round(page_w * it["ratio"], 1),
                    "b64": b64, "mime": mime, "label": label})
    return out


def expand_items_html(task: dict, kb_dir: Path) -> list[dict]:
    """任务包 items → 模板题帧（id/content/solution/img，img_path 相对 kb/）。"""
    from ..files import read_kb
    kb_data = read_kb(kb_dir)
    out: list[dict] = []
    for spec in task.get("items", []):
        kind = spec.get("kb", "problems")
        chap = spec.get("chap")
        ids = {str(i) for i in (spec.get("ids") or [])}
        tag = spec.get("tag", kind)
        chapters = kb_data.get(kind, {})
        if chap:
            entries = list(chapters.get(chap, []))
        else:
            entries = [e for chs in chapters.values() for e in chs]
        if ids:
            entries = [e for e in entries if str(e.get("id")) in ids]
        for e in entries:
            img_hint = str(e.get("img_path") or "")
            img_p = Path(img_hint)
            b64 = mime = None
            if img_hint:
                cand = img_p if img_p.is_absolute() else kb_dir / img_hint
                got = _b64_image(cand) if cand.exists() else None
                if got:
                    b64, mime = got
            out.append({"id": str(e.get("id") or ""), "tag": str(tag or ""),
                        "content": str(e.get("content") or ""),
                        "solution": str(e.get("solution") or ""),
                        "img_b64": b64, "img_mime": mime,
                        "img_label": "" if (b64 or not img_hint) else img_hint})
    if not out:
        logger.warning("任务包未选中任何题目（HTML 输出将只有版式框）")
    return out


def build_context(task: dict, students: list[dict], kb_dir: Path, ws: Path,
                  assets_dir: Path | None = None, no_watermark: bool = False,
                  date: str | None = None) -> dict:
    """任务包 + 名单 → 模板上下文（模板零业务逻辑；TS sheetHtml.ts 同构）。"""
    lay = task.get("layout", {}) or {}
    orientation = "landscape" if lay.get("orientation") == "landscape" else "portrait"
    per_page = lay.get("per_page")
    try:
        per_page = int(per_page) if per_page else (2 if orientation == "landscape" else 1)
    except (TypeError, ValueError):
        per_page = 2 if orientation == "landscape" else 1
    per_page = max(1, min(4, per_page))
    frames = expand_items_html(task, kb_dir)
    wm_raw = task.get("watermark") or {}
    wm_enabled = (not no_watermark) and wm_raw.get("enabled", True) is not False
    wm = {"enabled": wm_enabled,
          "page_text": wm_raw.get("pageText", True) is not False,
          "items": _watermark_items(task, ws, assets_dir, orientation) if wm_enabled else []}
    doc = {
        "id": str(task.get("id") or "assignment"),
        "title": str((lay.get("header") or {}).get("title") or "作业纸"),
        "course": str(task.get("course") or ""),
        "class_name": str(task.get("class") or (students[0].get("class") if students else "") or "classA"),
        "date": date or f"{datetime.now():%Y-%m-%d}",
        "orientation": orientation,
        "per_page": per_page,
        "grid": _grid_key(orientation, per_page),
        "footer_text": str((lay.get("footer") or {}).get("text") or ""),
        "katex_version": KATEX_VERSION,
    }
    stu_out = []
    n_total_pages_total = 0
    for stu in students:
        pages = [frames[i:i + per_page] for i in range(0, len(frames), per_page)] or [[]]
        n_total_pages_total += len(pages)
        stu_out.append({
            "name": str(stu.get("name") or ""),
            "number": str(stu.get("number") or ""),
            "class_display": str(stu.get("class") or doc["class_name"]),
            "tag": str(stu.get("tag") or ""),
            "pages": [{"n": i + 1, "total": len(pages), "last": False,
                       "grid_lines": _grid_lines(orientation, per_page),
                       "frames": pg}
                      for i, pg in enumerate(pages)],
        })
    # 最后一名学生的最后一页 page-break-after:auto（避免末尾空白页）
    if stu_out:
        stu_out[-1]["pages"][-1]["last"] = True
    logger.info(f"HTML 上下文：{len(stu_out)} 生 × 共 {n_total_pages_total} 页"
                f"（{orientation} per_page={per_page}）")
    return {"doc": doc, "watermark": wm, "students": stu_out}


def render_assignment_html(task: dict, students: list[dict], kb_dir: Path, ws: Path,
                           assets_dir: Path | None = None, no_watermark: bool = False,
                           date: str | None = None) -> str:
    """渲染自包含 HTML 字符串（CLI 与单测共用入口）。"""
    ctx = build_context(task, students, kb_dir, ws, assets_dir, no_watermark, date)
    tpl = _env().get_template(TEMPLATE_NAME)
    return tpl.render(**ctx)


def default_out_path(ws: Path, task: dict) -> Path:
    """缺省输出：classes/<班级>/sheets/html/<任务包 id>.html。"""
    class_dir = str(task.get("class_dir") or "classes").strip("/ ") or "classes"
    return ws / class_dir / "sheets" / "html" / f"{task.get('id', 'assignment')}.html"


def sheet_html_from_task(task_path: Path, ws: Path, out_path: Path | None = None,
                         roster_path: str | None = None,
                         no_watermark: bool = False,
                         assets_dir: Path | None = None) -> tuple[Path, int, int]:
    """CLI 主入口：任务包 + 可选 roster → 自包含 HTML。

    roster 缺失/为空时用合成 学生A/B（informational，不写真实学生信息）。
    返回 (输出路径, 学生数, 总页数)。
    """
    task = load_task(Path(task_path).expanduser().resolve())
    ws = Path(ws).expanduser().resolve()
    kb_dir = ws / "kb"
    synthetic = False
    students: list[dict] = []
    if roster_path:
        rp = Path(roster_path).expanduser().resolve()
        if rp.exists():
            students = read_roster(rp)
    if not students:
        synthetic = True
        students = [dict(s) for s in SYNTHETIC_STUDENTS]
        logger.info("未提供 roster（或名单为空）→ 使用合成学生 学生A/学生B（informational，"
                    "整班输出请 --roster 指向带 tag 名单 xlsx）")
    ctx = build_context(task, students, kb_dir, ws,
                        assets_dir=assets_dir or ASSIST_ROOT / "assets",
                        no_watermark=no_watermark)
    html = _env().get_template(TEMPLATE_NAME).render(**ctx)
    out = (Path(out_path).expanduser().resolve() if out_path
           else default_out_path(ws, task))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    n_pages = sum(len(s["pages"]) for s in ctx["students"])
    logger.info(f"HTML 已写出 → {out}（{out.stat().st_size} bytes）")
    return out, len(students), n_pages


def taskpad_json_hint(task: dict) -> str:
    """CLI 提示行（D1 超集：同一任务包可走 PDF/HTML 双通道）。"""
    return json.dumps({"id": task.get("id")}, ensure_ascii=False)
