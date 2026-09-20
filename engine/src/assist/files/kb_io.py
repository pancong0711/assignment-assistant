"""kb 题库 I/O：xlsx 为 source of truth（05-D3）。

迁移改造自 _legacy/2603paperDesign/src/paperdesign/kb_reader/loader.py：
- 去掉硬编码路径，kb_dir 由 workspace 指定；
- 新增 write/export_json/snapshot（05-D3：写盘前自动快照到 kb/.history/）；
- 列结构保持兼容：id/content/img_path/page/related/type/solution/note。
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger
from openpyxl import Workbook, load_workbook

COLUMNS = ["id", "content", "img_path", "page", "related", "type", "solution", "note"]

EMPTY = ("", None)

# translation.xlsx 是例外表（表头中文，逐行拼成题目内容）——逻辑迁移自 loader.py
TRANSLATION_HEADERS = ("名言", "作者", "出处", "年份", "备注", "备注2")


def read_xlsx(xlsx_path: Path, kb_dir: Path) -> dict[str, list[dict]]:
    """读一个题库 xlsx，返回 {"chapXX": [条目dict,...], ...}（结构与旧 loader 一致）。"""
    if not xlsx_path.exists():
        logger.warning(f"题库文件不存在: {xlsx_path}")
        return {}
    wb = load_workbook(xlsx_path, read_only=True)
    result: dict[str, list[dict]] = {}
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows or len(rows) < 2:
            continue
        headers = [str(h).strip() if h else "" for h in rows[0]]
        entries = []
        for row in rows[1:]:
            entry: dict = {}
            for i, header in enumerate(headers):
                if not header:
                    continue
                val = row[i] if i < len(row) else None
                if val in EMPTY:
                    continue
                if header == "page":
                    try:
                        val = int(val)  # noqa
                    except (ValueError, TypeError):
                        pass
                entry[header] = str(val) if not isinstance(val, int) else val
            if entry.get("img_path"):
                # img_path 相对 kb/ 解析（迁移自 loader.py）
                p = (kb_dir / str(entry["img_path"]))
                entry["img_path"] = str(p.resolve()) if p.exists() else str(entry["img_path"])
            if entry:
                entries.append(entry)
        if entries:
            result[sheet_name] = entries
    wb.close()
    return result


def read_translation(xlsx_path: Path, kb_dir: Path) -> dict[str, list[dict]]:
    """translation 例外表（中文表头 → 统一题目条目）。迁移自 loader.py load_translation()。"""
    if not xlsx_path.exists():
        logger.warning(f"题库文件不存在: {xlsx_path}")
        return {}
    wb = load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    entries = []
    for row in rows[1:]:
        saying = str(row[0]).strip() if row and row[0] else ""
        if not saying:
            continue
        author = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        book = str(row[2]).strip() if len(row) > 2 and row[2] else ""
        year = str(row[3]).strip() if len(row) > 3 and row[3] else ""
        tmp = f"请翻译以下内容：\n{saying} (by {author}"
        if book:
            tmp += f", {book}"
        if year:
            tmp += f", {year}"
        tmp += ("）\n并回答：（1）介绍一下作者及相关理论，"
                "（2）结合个人经验谈一谈对上述内容的理解。")
        entries.append({"id": "translation", "content": tmp, "img_path": None})
    wb.close()
    return {"translation": entries}


def read_kb(kb_dir: Path) -> dict[str, dict[str, list[dict]]]:
    """读全部题库：{"problems": {...}, "copy": {...}, ...}；文件名去 .xlsx 即 kind。"""
    out = {}
    for fn in sorted(kb_dir.glob("*.xlsx")):
        if fn.name.startswith("~$"):
            continue
        kind = fn.stem
        out[kind] = read_translation(fn, kb_dir) if kind == "translation" else read_xlsx(fn, kb_dir)
    return out


# ---------------- 写回（xlsx 为主数据源） ----------------

def snapshot(kb_dir: Path, kinds: list[str] | None = None) -> list[Path]:
    """写盘前快照到 kb/.history/<ts习惯名>/（05-D3：弥补 xlsx 无版本历史）。"""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    hist = kb_dir / ".history" / ts
    made = []
    for fn in sorted(kb_dir.glob("*.xlsx")):
        if kinds and fn.stem not in kinds:
            continue
        dest = hist / fn.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fn, dest)
        made.append(dest)
    if made:
        logger.info(f"已快照 {len(made)} 个题库文件 → {hist}")
    return made


def write_xlsx(xlsx_path: Path, chapters: dict[str, list[dict]],
               columns: list[str] | None = None) -> Path:
    """把 {"chapXX": [条目,...]} 写回 xlsx（第一行表头 + 数据行）。"""
    columns = columns or COLUMNS
    wb = Workbook()
    wb.remove(wb.active)
    for sheet, entries in chapters.items():
        ws = wb.create_sheet(title=sheet)
        ws.append(columns)
        for e in entries:
            ws.append([_cell(e, c) for c in columns])
    wb.save(xlsx_path)
    return xlsx_path


def _cell(entry: dict, col: str):
    v = entry.get(col)
    if v is None:
        return None
    return v


def write_json(kb_dir: Path, kb: dict[str, dict[str, list[dict]]]) -> Path:
    """导出 JSON 副本（交换/AI 阅读/diff 基准，05-D3），写 kB/export/*.json。"""
    out_dir = kb_dir / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    for kind, chapters in kb.items():
        fn = out_dir / f"{kind}.json"
        fn.write_text(json.dumps(chapters, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_dir
