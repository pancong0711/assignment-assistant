"""点名册读取（轻量版）。迁移参照 _legacy/2603paperDesign/src/paperdesign/student/exceltools.py
（只取 ExcelWorkbook 必要能力；列名/name/number/class 或 中文表头 姓名/学号/班级 均可）。"""

from pathlib import Path

from loguru import logger
from openpyxl import load_workbook

_HEADER_MAP = {"姓名": "name", "学号": "number", "班级": "class", "tag": "tag"}
_HEADERS = ("name", "number", "class", "tag")


def read_roster(xlsx_path: Path) -> list[dict]:
    """读点名册为 [{name, number, class, tag?}]；按列名自适应。"""
    if not Path(xlsx_path).exists():
        raise FileNotFoundError(f"点名册不存在: {xlsx_path}")
    wb = load_workbook(Path(xlsx_path), read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip() if h else "" for h in rows[0]]
    key_map = [_HEADER_MAP.get(h, None) for h in headers]
    students = []
    for row in rows[1:]:
        stu = {}
        for i, key in enumerate(key_map):
            if key is None:
                continue
            v = row[i] if i < len(row) else None
            stu[key] = str(v).strip() if v is not None else ""
        if stu.get("name"):
            students.append({k: v for k, v in stu.items() if v})
    wb.close()
    return students
