"""D63 T2：25C1（化工24/环24）canonical master 花名册构建。

数据源（docs/16 §17-R2）：
- 主源：学习通官方统计导出 xlsx（学习通-25C1-<班>-0621.xlsx）——含 学号/姓名/院系/专业/班级；
- 交叉源：得失分统计表-25C1.xlsx 的 <班>-分析 sheet（仅姓名）；
- 口径：学号为主键（legacy merge-on-name 欠账的补偿，winning：交叉只看交集名册/异常行）；
- 插班标注：学号前缀 != 主流年份（众数）→ note="插班(yyyy级)"；
- 布局要点：超星导出的表头标签错位（函授站=院系、层次=专业、专业=班级），按标签字面映射并留证。

隐私：输出 xlsx 含姓名+学号，默认落 .scratch/（gitignored），**不入库**。
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from openpyxl import Workbook, load_workbook

HEADER_MAP = {"学生姓名": "name", "姓名": "name", "name": "name",
              "学号/工号": "number", "学号": "number", "number": "number",
              "院系": "dept", "dept": "dept", "班级": "class", "class": "class"}


def _classify_extra(v: str) -> "str | None":
    """超星导出列标签双重错位（函授站=院系、层次=专业、专业=班级），按值形态分类：
    学院 → dept；(本) 等学历后缀 → major；`前缀+末尾2~3位数字`（如 化工242）→ class。"""
    import re
    if not v:
        return None
    if "学院" in v or "大学" in v:
        return "dept"
    if "(本)" in v or "（本）" in v or "专科" in v or "本科" in v:
        return "major"
    if re.fullmatch(r"[^\s]+\d{2,3}", v) and not re.fullmatch(r"\d{8,}", v):
        return "class"
    return None
_ID_RE = r"\d{8,}"
_SCORE_JUNK = {"ideal", "rate", "满分", "平均", "全班", "合计", "总", "班"}


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def _locate_header(rows, tokens: set[str], scan: int = 15) -> int:
    for i, r in enumerate(rows[:scan]):
        cells = {_s(c) for c in (r or ())}
        if tokens <= cells:
            return i
    raise ValueError(f"未在前 {scan} 行定位表头（含 {tokens}）")


def read_rows(xlsx_path: Path, sheet: "str | None" = None) -> list[tuple]:
    wb = load_workbook(Path(xlsx_path), read_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        return list(ws.iter_rows(values_only=True))
    finally:
        wb.close()


def parse_export_banner(rows) -> dict:
    for r in rows[:10]:
        text = " ".join(_s(c) for c in (r or ()))
        if "课程：" in text and "班级：" in text:
            import re
            course = re.search(r"课程：([^ ]+)", text)
            cls = re.search(r"班级：([^ ]+)", text)
            teacher = re.search(r"任课教师：([^\s]+)", text)
            at = re.search(r"导出时间：([0-9\- :]+)", text)
            return {"course": course.group(1) if course else "",
                    "class": cls.group(1) if cls else "",
                    "teacher": teacher.group(1) if teacher else "",
                    "exported_at": at.group(1).strip() if at else ""}
    return {}


def parse_stat_export(xlsx_path: Path, sheet: "str | None" = None) -> dict:
    """学习通统计导出 → {"source","banner","students":[{name,number,dept,major,class}],"other_rows"}"""
    rows = read_rows(xlsx_path, sheet)
    hdr = _locate_header(rows, {"学生姓名", "学号/工号"})
    headers = [_s(c) for c in (rows[hdr] or ())]
    key_of = [HEADER_MAP.get(h) if h in {"学生姓名", "姓名", "name", "学号/工号", "学号", "number"}
              else None for h in headers]
    banner = parse_export_banner(rows)
    students, other = [], []
    for r in rows[hdr + 1:]:
        cells = [c for c in (r or ())]
        name = _s(next((cells[i] for i, k in enumerate(key_of) if k == "name"), "")) \
            if any(k == "name" for k in key_of) else ""
        if not name:
            continue
        import re
        number = ""
        for i, k in enumerate(key_of):
            if k == "number":
                v = _s(cells[i])
                if re.fullmatch(_ID_RE, v):
                    number = v
                break
        stu = {"name": name, "number": number}
        if number:
            extra = {}
            for i in range(len(cells)):
                if i < len(key_of) and key_of[i]:
                    continue
                v = _s(cells[i])
                if v and v not in extra.values():
                    kind = _classify_extra(v)
                    if kind and kind not in extra:
                        extra[kind] = v
            stu.update(extra)
            students.append(stu)
        else:
            other.append(name)  # 无学号的行（合计/ideal/rate 等），留痕不入册
    return {"source": Path(xlsx_path).name, "sheet": sheet or Path(xlsx_path).name,
            "banner": banner, "students": students, "other_rows": other}


def annotate_years(students: list[dict]) -> Counter:
    """学号前缀主流年份为基准；插班行加 note。返回年份分布。"""
    years = Counter(s["number"][:4] for s in students if s.get("number"))
    if not years:
        return years
    base = years.most_common(1)[0][0]
    for s in students:
        y = s.get("number", "")[:4]
        s["note"] = "" if y == base else f"插班({y}级)"
    return years


def score_sheet_names(xlsx_path: Path, sheet: str) -> set[str]:
    """得失分统计表 <班>-分析 sheet：第 0 列姓名（跳过表头行下的汇总词 ideal/rate 等）。"""
    rows = read_rows(xlsx_path, sheet)
    names = set()
    for r in rows[2:]:
        v = _s(r[0]) if r else ""
        if not v or v.lower() in _SCORE_JUNK or all(ord(c) < 128 for c in v):
            continue
        names.add(v)
    return names


def cross_check(students: list[dict], score_names: set[str]) -> dict:
    master = {s["name"] for s in students}
    return {"both": len(master & score_names),
            "only_master": sorted(master - score_names),
            "only_scores": sorted(score_names - master)}


def build(class_sources: dict[str, Path],
          cross_sources: "dict[str, tuple[Path, str]] | None" = None,
          out_xlsx: "Path | str" = None) -> dict:
    """多班合并 → df-container 形态 xlsx（sheet namelist_df）+ summary。"""
    all_rows, summary = [], {"classes": {}}
    cols = ["name", "number", "class", "dept", "major", "source", "note"]
    for cls, path in (class_sources or {}).items():
        parsed = parse_stat_export(path)
        years = annotate_years(parsed["students"])
        item = {"source": parsed["source"], "banner": parsed["banner"],
                "students": len(parsed["students"]), "years": dict(years),
                "other_rows": parsed["other_rows"]}
        if cross_sources and cls in cross_sources:
            xf, sheet = cross_sources[cls]
            item["cross"] = cross_check(parsed["students"], score_sheet_names(xf, sheet))
        summary["classes"][cls] = item
        for s in parsed["students"]:
            all_rows.append({"name": s["name"], "number": s["number"],
                             "class": s.get("class", "") or cls,
                             "dept": s.get("dept", ""), "major": s.get("major", ""),
                             "source": parsed["source"], "note": s.get("note", "")})
    if out_xlsx:
        out_xlsx = Path(out_xlsx)
        out_xlsx.parent.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        ws = wb.active
        ws.title = "namelist_df"
        ws.append(cols)
        for r in all_rows:
            ws.append([r.get(c, "") for c in cols])
        ws2 = wb.create_sheet("summary")
        import json as _json
        ws2.append(["类", "值"])
        for cls, item in summary["classes"].items():
            for k in ("source", "students", "years", "cross", "banner", "other_rows"):
                ws2.append([f"{cls}.{k}", _json.dumps(item.get(k), ensure_ascii=False)])
        wb.save(out_xlsx)
    summary["total"] = len(all_rows)
    summary["out"] = str(out_xlsx) if out_xlsx else ""
    return summary
