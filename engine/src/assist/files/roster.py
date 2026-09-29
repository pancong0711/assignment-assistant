"""点名册读取（轻量版）。迁移参照 _legacy/2603paperDesign/src/paperdesign/student/exceltools.py
（只取 ExcelWorkbook 必要能力；列名/name/number/class 或 中文表头 姓名/学号/班级 均可）。"""

from pathlib import Path

from loguru import logger
from openpyxl import load_workbook

_HEADER_MAP = {"姓名": "name", "学号": "number", "班级": "class", "tag": "tag",
               # PWA rosterXlsx.writeRosterXlsx 恒写英文表头（rosterXlsx.ts ROSTER_COLUMNS）
               "name": "name", "number": "number", "class": "class"}
_HEADERS = ("name", "number", "class", "tag")


_NAME_TOKENS = {"姓名", "名字", "name", "学生", "student"}


def _map_from_matrix(rows: list[tuple], header_i: int) -> list[dict]:
    """表头行 + 数据行 → [{name, number, class, tag?}]（两级回退共用内核，PWA mapStudentsFromMatrix 同款）。"""
    headers = [str(h).strip() if h else "" for h in (rows[header_i] or ())]
    key_map = [_HEADER_MAP.get(h, None) for h in headers]
    students = []
    for row in rows[header_i + 1:]:
        stu = {}
        for i, key in enumerate(key_map):
            if key is None:
                continue
            v = row[i] if i < len(row) else None
            stu[key] = str(v).strip() if v is not None else ""
        if stu.get("name"):
            students.append({k: v for k, v in stu.items() if v})
    return students


def read_roster(xlsx_path: Path) -> list[dict]:
    """读点名册为 [{name, number, class, tag?}]；D46-1 两级回退（与 PWA rosterXlsx.readRosterXlsx 同语义）：
    ① 首行表头自适应；② 0 人时在前 15 行扫描含"姓名/名字/name/学生/student"的行作表头行重跑
    （zjxu 教务名册常见前 8~10 行为说明文字、无标准表头——旧 _legacy iloc[8:-3] 硬切片的稳健替代）。
    仍 0 人返回空列表并记 warning（CLI 侧由调用方报错给教师）。"""
    if not Path(xlsx_path).exists():
        raise FileNotFoundError(f"点名册不存在: {xlsx_path}")
    wb = load_workbook(Path(xlsx_path), read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []
    students = _map_from_matrix(rows, 0)
    if students:
        return students
    for hi in range(1, min(15, len(rows))):
        cells = {str(c).strip().lower() for c in (rows[hi] or ()) if c is not None}
        if cells & _NAME_TOKENS:
            students = _map_from_matrix(rows, hi)
            if students:
                logger.info(f"read_roster: 关键词定位表头行=第 {hi + 1} 行（前 {hi} 行为说明文字，已跳过）")
                return students
    preview = " | ".join(str(r[0]) if r and r[0] is not None else "" for r in rows[:3])
    logger.warning(f"read_roster: 两级回退均未识别姓名列（{xlsx_path.name}；前 3 行首列≈[{preview}]）→ 0 人")
    return []
