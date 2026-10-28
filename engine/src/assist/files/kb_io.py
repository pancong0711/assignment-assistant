"""kb 题库 I/O：xlsx 为 source of truth（05-D3）。

迁移改造自 _legacy/2603paperDesign/src/paperdesign/kb_reader/loader.py：
- 去掉硬编码路径，kb_dir 由 workspace 指定；
- 新增 write/export_json/snapshot（05-D3：写盘前自动快照到 kb/.history/）；
- 列结构保持兼容：id/content/img_path/page/related/type/solution/note。
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger
from openpyxl import Workbook, load_workbook

COLUMNS = ["id", "content", "img_path", "page", "related", "type", "solution", "note"]

# ---------------- D111：题库题号全局唯一（自动章节前缀） ----------------
# 背景：题号只在**章内**唯一（真实题库里 `01` 在 9 个章节重复），导致
# ①答案版本库按 qid 存储时跨章串味；②批阅报告按 qid 关联会错配。
# 现约定：题库 id = `<chap>-<原id>`（如 chap04-01），读入即自动补齐（幂等）。
_ID_PREFIX_RE = re.compile(r"^[0-9A-Za-z_\-\u4e00-\u9fff.]+$")
_SCOPE_PREFIX_SEP = "-"


def safe_id_part(v: str) -> str:
    """id/章节名片段的文件名安全化（去掉路径分隔符与控制字符）。"""
    t = str(v or "").strip()
    t = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "-", t)
    return t.strip() or ""


def scope_question_id(chap: str, qid: str) -> str:
    """把 `<chap>` + 原始题号拼成全局唯一 id（幂等）。

    - 已带本章前缀（`chap04-01` 且 chap=chap04）→ 原样返回；
    - 空题号 → 返回空（由调用方跳过）；
    - 其它 → `<safe(chap)>-<原id>`。

    幂等性很重要：读写往返多次不会变成 `chap04-chap04-01`。
    """
    q = safe_id_part(qid)
    if not q:
        return ""
    c = safe_id_part(chap)
    if not c:
        return q
    head = f"{c}{_SCOPE_PREFIX_SEP}"
    if q == c or q.startswith(head):
        return q
    return f"{head}{q}"


def find_duplicate_ids(chapters: dict[str, list[dict]]) -> dict[str, list[str]]:
    """返回 `{id: [chap, ...]}`：**加前缀后**仍重复的 id（应视为数据错误）。"""
    seen: dict[str, list[str]] = {}
    for cname, entries in (chapters or {}).items():
        for e in entries or []:
            qid = scope_question_id(cname, str((e or {}).get("id") or ""))
            if not qid:
                continue
            # 计数（append 不去重）：同一 sheet 内重复也能被检出
            seen.setdefault(qid, []).append(cname)
    return {k: v for k, v in seen.items() if len(v) > 1}


def normalize_question_ids(chapters: dict[str, list[dict]],
                           *, with_report: bool = False):
    """就地给每个条目补章节前缀（幂等）。返回 (chapters, changed) 或含 report。

    `changed` 列表形如 `[{"chap","old","new"}]`，供 CLI/UI 展示"已自动加前缀"。
    """
    changed: list[dict] = []
    out: dict[str, list[dict]] = {}
    for cname, entries in (chapters or {}).items():
        rows = []
        for e in entries or []:
            row = dict(e or {})
            old = str(row.get("id") or "").strip()
            new = scope_question_id(cname, old)
            if new:
                row["id"] = new
                if new != old:
                    changed.append({"chap": cname, "old": old, "new": new})
            rows.append(row)
        out[cname] = rows
    if with_report:
        return out, {"changed": changed, "duplicates": find_duplicate_ids(out)}
    return out, changed

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
    # D111：题库 id 全局唯一（自动章节前缀）；幂等，已带前缀不变
    result, _changed = normalize_question_ids(result)
    if _changed:
        logger.debug(f"{xlsx_path.name}: 已为 {len(_changed)} 个题号补章节前缀")
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


_KNOWN_KINDS = ("problems", "copy", "qa", "summary", "distinguish",
                 "innovation", "translation", "copySp", "copyOnly")


def _kind_of_xlsx(fn: Path) -> "tuple[str, bool]":
    """返回 (kind, is_example)；兼容 problems-example.xlsx / example-problems.xlsx。"""
    stem = fn.stem
    if stem in _KNOWN_KINDS:
        return stem, False
    for k in _KNOWN_KINDS:
        if stem == f"{k}-example" or stem == f"example-{k}":
            return k, True
    return stem, False


def read_kb(kb_dir: Path) -> dict[str, dict[str, list[dict]]]:
    """读全部题库；同名 exact 文件优先于 *-example/example-* 示例文件。"""
    out: dict[str, dict[str, list[dict]]] = {}
    examples: dict[str, Path] = {}
    for fn in sorted(kb_dir.glob("*.xlsx")):
        if fn.name.startswith("~$"):
            continue
        kind, is_example = _kind_of_xlsx(fn)
        if is_example:
            examples.setdefault(kind, fn)
            continue
        out[kind] = read_translation(fn, kb_dir) if kind == "translation" else read_xlsx(fn, kb_dir)
    for kind, fn in examples.items():
        if kind not in out:
            out[kind] = read_translation(fn, kb_dir) if kind == "translation" else read_xlsx(fn, kb_dir)
    # D111：加前缀后仍撞号 → 数据错误，明确告警（不静默改名，避免错配答案/报告）
    for kind, chapters in out.items():
        dups = find_duplicate_ids(chapters)
        if dups:
            sample = ", ".join(f"{qid}@{'/'.join(ch)}" for qid, ch in list(dups.items())[:5])
            logger.warning(f"题库 {kind} 存在重复题号（{len(dups)} 个）：{sample}；"
                           f"请用 `assist kb normalize` 检查")
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


# D105：xlsx 的 solution 列降级为「纯文本摘要」（答案真源在 kb/solutions/<qid>.json）
SOLUTION_COLUMN_NOTE = "solution（摘要，完整答案见 kb/solutions/<id>.json）"
SUMMARY_LIMIT = 200


def summarize_solutions(ws, chapters: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """把每题的**生效答案**派生为纯文本摘要，回填到 `solution` 列（单向派生）。

    - 答案真源 = `kb/solutions/<qid>.json`（`effective_solution`：置顶版 > 最新版 > xlsx 旧值）
    - 只写摘要（≤200 字），不会丢失 json 中的完整 md+html
    - 无版本库时保留 xlsx 原值（兼容旧题库）
    """
    from .solutions import effective_solution
    out: dict[str, list[dict]] = {}
    for sheet, entries in (chapters or {}).items():
        rows = []
        for e in entries:
            row = dict(e)
            # D111：传入的 chapters 可能是尚未规范化的裸 id，这里补前缀保证命中
            qid = scope_question_id(sheet, str(row.get("id") or ""))
            if qid:
                row["id"] = qid
                # 作用域用 sheet 名兜底（kb kind 在调用方未知时为空即可，
                # 精确作用域文件命中不了会自动回落到裸 id 文件）
                eff = effective_solution(ws, qid, str(row.get("solution") or ""), chap=sheet)
                summary = str(eff.get("text_plain") or "").strip()
                if summary:
                    row["solution"] = summary[:SUMMARY_LIMIT]
            rows.append(row)
        out[sheet] = rows
    return out


def write_xlsx(xlsx_path: Path, chapters: dict[str, list[dict]],
               columns: list[str] | None = None) -> Path:
    """把 {"chapXX": [条目,...]} 写回 xlsx（第一行表头 + 数据行）。"""
    columns = columns or COLUMNS
    wb = Workbook()
    wb.remove(wb.active)
    for sheet, entries in chapters.items():
        ws = wb.create_sheet(title=sheet)
        # D105：solution 列表头加注（说明这里是摘要，完整答案在 json）
        ws.append([SOLUTION_COLUMN_NOTE if c == "solution" else c for c in columns])
        for e in entries:
            ws.append([_cell(e, c) for c in columns])
    wb.save(xlsx_path)
    return xlsx_path


def _cell(entry: dict, col: str):
    v = entry.get(col)
    if v is None:
        return None
    return v


# Excel sheet 名限制：≤31 字符，不含 []:*?/\，且不能为空/不能是历史保留名
# （openpyxl 会直接抛异常，这里提前给出可读错误）。
_SHEET_NAME_FORBIDDEN = set("[]:*?/\\")


def validate_sheet_name(name: str) -> str:
    """校验 Excel sheet 名；返回错误文案（合法返回空串）。

    规则对齐 Excel/openpyxl：非空、≤31 字符、不含 []:*?/\\ 这六个字符。
    （`validate_sheet_name` 只做静态校验，不检查重名——由 openpyxl 负责。）
    """
    n = str(name or "")
    if not n.strip():
        return "章节名不能为空"
    if len(n) > 31:
        return f"章节名过长（{len(n)} > 31 字符）：{n}"
    bad = sorted({c for c in n if c in _SHEET_NAME_FORBIDDEN})
    if bad:
        return f"章节名含非法字符 {''.join(bad)}：{n}"
    return ""


def write_chapters_preserving(xlsx_path: Path, chapters: dict[str, list[dict]],
                              columns: list[str] | None = None) -> Path:
    """把 {sheet: [条目,...]} 写回现有 xlsx，**保留单元格样式**（B4）。

    PWA 端 SheetJS 写回会丢失字体/边框/列宽等样式；当引擎在线或教师用
    ``assist kb write`` 时走本函数：
    1. openpyxl 加载原工作簿（不存在则新建）；
    2. 按现有表头映射列，仅改 cell.value（不重建 Cell 对象，样式/列宽/批注保留）；
    3. 删除新增数据行之后的旧行，并移除本次未提供的旧 sheet。
    """
    bad = [(name, err) for name in chapters if (err := validate_sheet_name(name))]
    if bad:
        raise ValueError("; ".join(f"{n}: {e}" for n, e in bad))
    columns = columns or COLUMNS
    if xlsx_path.exists():
        wb = load_workbook(xlsx_path)
    else:
        wb = Workbook()
        wb.remove(wb.active)

    for sheet, entries in chapters.items():
        ws = wb[sheet] if sheet in wb.sheetnames else wb.create_sheet(title=sheet)

        # 确保表头含全部标准列：已有标准列名保留原单元格（连带样式），缺失列追加。
        col_idx: dict[str, int] = {}
        for ci in range(1, ws.max_column + 1):
            h = str(ws.cell(1, ci).value or "").strip()
            if h in columns and h not in col_idx:
                col_idx[h] = ci
        for col in columns:
            if col not in col_idx:
                ci = ws.max_column + 1
                ws.cell(1, ci, value=col)
                col_idx[col] = ci

        for ri, entry in enumerate(entries, start=2):
            for col in columns:
                cell = ws.cell(ri, col_idx[col])
                val = _cell(entry, col)
                if cell.value != val:
                    cell.value = val  # 只改值，不重建 Cell，样式保留

        last_wanted = len(entries) + 1
        if ws.max_row > last_wanted:
            ws.delete_rows(last_wanted + 1, ws.max_row - last_wanted)

    for name in list(wb.sheetnames):
        if name not in chapters:
            del wb[name]
    if not wb.sheetnames:
        wb.create_sheet("Sheet1")
    wb.save(xlsx_path)
    return xlsx_path


def write_json(kb_dir: Path, kb: dict[str, dict[str, list[dict]]]) -> Path:
    """导出 JSON 副本（交换/AI 阅读/diff 基准，05-D3），写 kB/export/*.json。"""
    out_dir = kb_dir / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    for kind, chapters in kb.items():
        fn = out_dir / f"{kind}.json"
        fn.write_text(json.dumps(chapters, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_dir

def catalog(kb_dir: Path, *, with_content: bool = True, content_max: int = 400) -> dict:
    """D92-R1：题库目录（下拉数据源）—— kinds → chapters → 题号(+内容预览)。

    返回 {"kinds": [{"kind", "chapters": [{"chap", "count", "ids":[{"id","content"}]}]}]}。
    content 截断到 content_max（题目预览框用，单行可滚动）。
    """
    data = read_kb(Path(kb_dir))
    kinds = []
    for kind in sorted(data):
        chapters = []
        for chap in sorted(data[kind]):
            ids = []
            for e in data[kind][chap]:
                qid = str(e.get("id") or "")
                if not qid:
                    continue
                item = {"id": qid}
                if with_content:
                    item["content"] = str(e.get("content") or "")[:content_max]
                ids.append(item)
            chapters.append({"chap": chap, "count": len(ids), "ids": ids})
        kinds.append({"kind": kind, "chapters": chapters})
    return {"kinds": kinds}
