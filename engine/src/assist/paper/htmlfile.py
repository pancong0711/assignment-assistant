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
from .grid import grid_body_style, grid_line_styles, normalize_per_page, resolve_grid
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


def _normalize_figure_pos(pos) -> str:
    """D83-2：题图位置四态归一 + 旧值兼容（与 paper/layout.normalize_figure_pos 同口径）。"""
    p = str(pos or "text-right").strip().lower()
    p = {"lt": "text-left", "rt": "text-right", "center": "below-right"}.get(p, p)
    return p if p in ("text-right", "text-left", "below-left", "below-right") else "text-right"


def _normalize_indent(indent) -> str:
    """D83-3：题号缩进三态（none 默认 / first / hanging）。"""
    i = str(indent or "none").strip().lower()
    return i if i in ("none", "first", "hanging") else "none"


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
    try:  # D87 兼容：'assets/watermark/x' → 'watermark/x'
        from .watermark_styles import normalize_image_ref
        nr = normalize_image_ref(hint)
        if nr and nr != hint:
            cands += [ws / nr, ws / "assets" / nr]
            if assets_dir:
                cands.append(assets_dir / nr)
    except Exception:  # noqa: BLE001
        pass
    if assets_dir:
        cands += [assets_dir / hint, assets_dir / "watermark" / p.name]
    for c in cands:
        if c.exists():
            return c
    return None


def _grid_lines(rows: int, cols: int) -> list[dict]:
    """HTML 页内虚线（generic：竖线 left%，横线 top%；D61 rows×cols）。"""
    return grid_line_styles(rows, cols)


def _watermark_items(task: dict, ws: Path, assets_dir: Path | None,
                     orientation: str) -> list[dict]:
    """水印图层 → 模板行（b64 内嵌或占位标记）。

    三形态（PWA parseWatermark 同口径）：
    1) watermark.items 列表（image/pos/ratio/alpha）；
    2) legacy 三槽 university/text/boat（str 路径 | {path,pos,ratio,alpha}）
       → university→rt、text→lm、boat→lb；
    3) 空 = engine 默认三槽占位（rt/lm/lb），能找到 engine assets logo 则内嵌。

    D87 §3.2：作业纸仅给 `style_ref`（无内联 items）时，按优先级
    `items > style_ref > 默认样式 > 内置三槽` 解析为 items（与 PDF 通道同口径）。
    """
    wm = task.get("watermark") or {}
    raw_items: list[dict] = []
    # D87：无内联 items 且声明了 style_ref（或存在默认样式）→ 样式库解析
    if not (isinstance(wm.get("items"), list) and wm.get("items")):
        try:
            from .watermark_styles import resolve_pad_watermark
            spec = resolve_pad_watermark(Path(assets_dir) if assets_dir else
                                         Path(ws) / "assets", wm)
            if spec.get("source") not in ("builtin",) and spec.get("items"):
                for it in spec["items"]:
                    if not isinstance(it, dict) or not it.get("image"):
                        continue
                    raw_items.append({
                        "image": str(it.get("image")),
                        "pos": str(it.get("pos") or "mm"),
                        "ratio": float(it.get("ratio") or 0.2),
                        "alpha": float(it.get("alpha") if it.get("alpha") is not None else 0.5)})
        except Exception:  # noqa: BLE001
            raw_items = []
    if raw_items:
        pass
    elif isinstance(wm.get("items"), list) and wm.get("items"):
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


def expand_items_html(task: dict, kb_dir: Path, numbering: str = "auto") -> list[dict]:
    """任务包 items → 模板题帧（no/content/solution/img，img_path 相对 kb/）。

    D82：题号规则与 PDF/PWA 同口径（auto=连续 1./2.；id=题库 id；labels 覆盖优先，
    经 resolve_items 统一展开）。模板渲染改为「题号+题干」悬挂缩进 + 图右上两列。
    """
    from ..files import read_kb
    from .task import resolve_items
    kb_data = read_kb(kb_dir)
    # 参考答案按题库 id 建索引（resolve_items 返回 4 元组不含 solution，与 PDF 同契约）
    sol_by_id: dict[str, str] = {}
    for chapters in kb_data.values():
        for entries in chapters.values():
            for e in entries:
                qid = str(e.get("id") or "")
                if qid:
                    sol_by_id[qid] = str(e.get("solution") or "")
    out: list[dict] = []
    # 用带序号的展开（auto/id/labels 与 PDF/PWA 同口径）
    qid_seq = _resolved_ids(kb_data, task)
    resolved = resolve_items(kb_data, task.get("items", []), kb_dir, numbering,
                             seed=task.get("random_seed"),
                             target_tag=str(task.get("target_tag") or ""))
    for (content, img, tag, no), qid in zip(resolved, qid_seq):
        img_hint = str(img) if img else ""
        b64 = mime = None
        if img_hint and Path(img_hint).exists():
            got = _b64_image(Path(img_hint))
            if got:
                b64, mime = got
            else:
                img_hint = ""
        out.append({"id": str(qid), "no": str(no or ""), "tag": str(tag or ""),
                    "content": str(content or ""),
                    "solution": sol_by_id.get(str(qid), ""),
                    "img_b64": b64, "img_mime": mime,
                    "img_label": "" if (b64 or not img_hint) else img_hint})
    if not out:
        logger.warning("任务包未选中任何题目（HTML 输出将只有版式框）")
    return out


def _resolved_ids(kb_data: dict, task: dict) -> list[str]:
    """与 resolve_items 同序的题库 id 列表（供模板携带 id 列 + 参考答案索引）。"""
    # resolve_items 返回 4 元组不含 id，这里按相同过滤逻辑重算 id 序列
    ids_out: list[str] = []
    for spec in task.get("items", []):
        kind = spec.get("kb", "problems")
        chap = spec.get("chap")
        want = {str(i) for i in (spec.get("ids") or [])}
        chapters = kb_data.get(kind, {})
        entries = list(chapters.get(chap, [])) if chap else \
            [e for chs in chapters.values() for e in chs]
        if want:
            entries = [e for e in entries if str(e.get("id")) in want]
        for e in entries:
            ids_out.append(str(e.get("id") or ""))
    # 兜底：长度不符时用空串补齐/截断（保持 zip 安全）
    return ids_out


def build_context(task: dict, students: list[dict], kb_dir: Path, ws: Path,
                  assets_dir: Path | None = None, no_watermark: bool = False,
                  date: str | None = None) -> dict:
    """任务包 + 名单 → 模板上下文（模板零业务逻辑；TS sheetHtml.ts 同构）。"""
    lay = task.get("layout", {}) or {}
    orientation = "landscape" if lay.get("orientation") == "landscape" else "portrait"
    per_page = normalize_per_page(lay.get("per_page"), orientation)
    grid = resolve_grid(orientation, per_page,
                        lay.get("grid_rows"), lay.get("grid_cols"))
    frames = expand_items_html(task, kb_dir, str(lay.get("numbering") or "auto"))
    wm_raw = task.get("watermark") or {}
    wm_enabled = (not no_watermark) and wm_raw.get("enabled", True) is not False
    wm = {"enabled": wm_enabled,
          "page_text": wm_raw.get("pageText", True) is not False,
          "items": _watermark_items(task, ws, assets_dir, orientation) if wm_enabled else []}
    doc = {
        "id": str(task.get("id") or "assignment"),
        "title": str((lay.get("header") or {}).get("title") or "作业纸"),
        "course": str(task.get("course") or ""),
        # D88-c：班级显示 = 学生自身 class → task.class（调用方给的班级名）→ 空
        # （不再回落硬编码 "classA"）
        "class_name": str(task.get("class") or ""),
        "date": date or f"{datetime.now():%Y-%m-%d}",
        "orientation": orientation,
        "per_page": per_page,
        "grid_rows": grid["rows"],
        "grid_cols": grid["cols"],
        "grid_order": grid["order"],
        "grid_capacity": grid["capacity"],
        "grid": f"{grid['rows']}x{grid['cols']}",   # D61：与 PWA sheetHtml data-grid 同口径（去 grid 前缀）
        "grid_body_style": grid_body_style(grid["rows"], grid["cols"], grid["order"]),
        "footer_text": str((lay.get("footer") or {}).get("text") or ""),
        "figure": {
            "scale": float((lay.get("figure") or {}).get("scale") or 1.0),
            "pos": _normalize_figure_pos((lay.get("figure") or {}).get("pos")),
            "max_w_mm": float((lay.get("figure") or {}).get("max_w_mm") or 45.0),
            "max_h_mm": float((lay.get("figure") or {}).get("max_h_mm") or 60.0),
        },
        "indent": _normalize_indent(lay.get("indent")),
        "katex_version": KATEX_VERSION,
    }
    stu_out = []
    n_total_pages_total = 0
    for stu in students:
        pages = [frames[i:i + per_page] for i in range(0, len(frames), per_page)] or [[]]
        n_total_pages_total += len(pages)
        page_lines = _grid_lines(grid["rows"], grid["cols"])
        stu_out.append({
            "name": str(stu.get("name") or ""),
            "number": str(stu.get("number") or ""),
            "class_display": str(stu.get("class") or doc["class_name"]),
            "tag": str(stu.get("tag") or ""),
            "pages": [{"n": i + 1, "total": len(pages), "last": False,
                       "grid_lines": page_lines,
                       "frames": pg}
                      for i, pg in enumerate(pages)],
        })
    # 最后一名学生的最后一页 page-break-after:auto（避免末尾空白页）
    if stu_out:
        stu_out[-1]["pages"][-1]["last"] = True
    logger.info(f"HTML 上下文：{len(stu_out)} 生 × 共 {n_total_pages_total} 页"
                f"（{orientation} per_page={per_page} grid={grid['rows']}x{grid['cols']} order={grid['order']}）")
    return {"doc": doc, "watermark": wm, "students": stu_out}


def render_assignment_html(task: dict, students: list[dict], kb_dir: Path, ws: Path,
                           assets_dir: Path | None = None, no_watermark: bool = False,
                           date: str | None = None,
                           include_solution: bool = True,
                           blank_header: bool = False) -> str:
    """渲染自包含 HTML 字符串（CLI 与单测共用入口）。

    D43 遗留①：include_solution（参考答案开关）与 blank_header（空白学籍页眉）在此统一
    灌入 doc —— StrictUndefined 下模板引用必须始终有定义（demo/测试路径也安全）。
    """
    ctx = build_context(task, students, kb_dir, ws, assets_dir, no_watermark, date)
    ctx["doc"]["include_solution"] = include_solution
    ctx["doc"]["blank_header"] = blank_header
    ctx["doc"].setdefault("katex_mode", "cdn")
    tpl = _env().get_template(TEMPLATE_NAME)
    return tpl.render(**ctx)


def default_out_path(ws: Path, task: dict) -> Path:
    """缺省输出：classes/<班级>/sheets/html/<任务包 id>.html。"""
    class_dir = str(task.get("class_dir") or "classes").strip("/ ") or "classes"
    return ws / class_dir / "sheets" / "html" / f"{task.get('id', 'assignment')}.html"


def sheet_html_from_task(task_path: Path, ws: Path, out_path: Path | None = None,
                         roster_path: str | None = None,
                         no_watermark: bool = False,
                         include_solution: bool = True,
                         students_mode: str = "roster",
                         katex_mode: str = "cdn",
                         assets_dir: Path | None = None
                         ) -> tuple[Path, int, int]:
    """CLI 主入口：任务包 + 可选 roster → 自包含 HTML。

    roster 缺失/为空时用合成 学生A/B（informational，不写真实学生信息）。
    D43 遗留①（docs/13 D43-A1 parity）：`include_solution`（--no-solution 参考答案开关，
    与 PWA ③段「显示参考答案」同语义）与 `students_mode`（--students roster|sample|blank，
    blank = 单份空白模板：页眉学籍三空位，与 PWA「显示学生示例」未勾同语义）。
    返回 (输出路径, 学生数, 总页数)。
    """
    task = load_task(Path(task_path).expanduser().resolve())
    ws = Path(ws).expanduser().resolve()
    kb_dir = ws / "kb"
    synthetic = False
    blank_mode = False
    students: list[dict] = []
    if roster_path:
        rp = Path(roster_path).expanduser().resolve()
        if rp.exists():
            students = read_roster(rp)
    if students_mode == "blank":
        # 单份空白模板（与 PWA「显示学生示例」未勾同语义；页脚页码仍正常）
        students = [{"name": "", "number": "", "class": "", "tag": ""}]
        blank_mode = True
        logger.info("--students blank → 单份空白模板（页眉学籍三空位，docs/13 D43-A1）")
    elif students_mode == "sample":
        synthetic = True
        students = [dict(s) for s in SYNTHETIC_STUDENTS]
        logger.info("--students sample → 合成 学生A/B 两份（informational）")
    if not students:
        synthetic = True
        students = [dict(s) for s in SYNTHETIC_STUDENTS]
        logger.info("未提供 roster（或名单为空）→ 使用合成学生 学生A/学生B（informational，"
                    "整班输出请 --roster 指向带 tag 名单 xlsx）")
    ctx = build_context(task, students, kb_dir, ws,
                        assets_dir=assets_dir or ASSIST_ROOT / "assets",
                        no_watermark=no_watermark)
    doc = ctx["doc"]
    doc["include_solution"] = include_solution
    doc["blank_header"] = blank_mode
    doc["katex_mode"] = katex_mode if katex_mode in ("cdn", "local") else "cdn"
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
