"""成绩源适配器（M5，docs/05-D19）——把"固定格式"四类源 + 自定义源统一成
read_score_xlsx 的输出（{name, score, weight, source}）。

固定格式（移植自 _legacy/2603paperDesign 的对应解析逻辑）：
- roster      教务点名册（姓名/学号/班级，作为 tag 的接表用，不入分数）
- exam        教务期末成绩表：列"期末(必填)"
- xuexitong_assignment 学习通"作业统计"：前 8 行扫描含"成绩"的行，其上一行为作业标题
- xuexitong_stat       学习通统计文件：按 sheet 关键字（默认"章节测验"）匹配，
                       在第 4 行找"成绩"列，非 0 取平均
- rainclass   雨课堂班级数据汇总表：header=None，第 2 行为列标题（含满分），
              前 3 列学号/姓名/汇总，其后每课 2 列（方式/得分）→ 计算签到得分均值
- custom      自定义：教师给列名 list（可多列加权）或点选列
"""

from pathlib import Path

from loguru import logger
from openpyxl import load_workbook


def _rows_of(path: Path, sheet: int | str | None = None, header_row: int = 0):
    wb = load_workbook(path, read_only=True)
    name = sheet if isinstance(sheet, int) else None
    if name is None and isinstance(sheet, str):
        # 按关键词匹配 sheet 名（迁移 _addScoreExamStat 的 sheet_keyword 语义）
        name = next((s for s in wb.sheetnames if sheet in s), 0)
    ws = wb.worksheets[int(name) if name is not None else 0]
    out = list(ws.iter_rows(values_only=True))
    wb.close()
    return out


def _col_score(rows: list, score_i: int, name_i: int, source: str,
               weight: float, skip_zero: bool = False) -> list[dict]:
    out = []
    for r in rows:
        try:
            v = float(r[score_i])
        except (TypeError, ValueError, IndexError):
            continue
        if skip_zero and v == 0:
            continue
        name = str(r[name_i]).strip() if r[name_i] is not None else ""
        if not name:
            continue
        out.append({"name": name, "score": v, "weight": weight, "source": source})
    return out


def read_exam(path: Path, col: str = "期末", weight: float = 1.0) -> list[dict]:
    """教务期末成绩表（迁移 _addScoreExam：姓名/学号/期末(必填)）。"""
    rows = _rows_of(path)
    if len(rows) < 2:
        return []
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    name_i = next((i for i, h in enumerate(headers) if h in ("姓名", "name")), 0)
    score_i = next((i for i, h in enumerate(headers) if col and (col in h)), None)
    if score_i is None:
        logger.warning(f"{path} 未找到{col}列；回退数字列")
        return read_flex(path, cols=col, weight=weight)
    return _col_scores(rows, score_i, name_i, f"exam:{col}", weight)


def read_xuexitong_assignment(path: Path, weight: float = 1.0,
                              sheet: str = "作业统计") -> list[dict]:
    """学习通"作业统计"：前 8 行找"成绩"行（迁移 _addScoreAssignment 的扫描逻辑），
    该行上一行是作业标题（作为 source），数据在下一行起；每个"成绩"列取该生各作业均分。"""
    rows = _rows_of(path, sheet)
    score_row = None
    for i in range(min(8, len(rows))):
        for j, v in enumerate(rows[i]):
            if isinstance(v, str) and "成绩" in v:
                score_row = (i, j)
                break
        if score_row:
            break
    if not score_row:
        logger.warning(f"{path}: \"作业统计\"未见成绩行，跳过")
        return []
    sr, sj = score_row
    name_i, num_i = 0, 1
    titles = rows[sr - 1] if sr > 0 else ["col"] * len(rows[0])
    per_stu: dict[str, list[float]] = {}
    for k in range(len(rows[0])):
        v = rows[sr][k]
        if isinstance(v, str) and "成绩" in v:
            title = rows[sr - 1][k] if sr > 0 and k < len(rows[sr - 1]) else k
            for r in rows[sr + 1:]:
                try:
                    sc = float(r[k])
                except (TypeError, IndexError):
                    continue
                name = str(r[name_i]).strip()
                if name:
                    per_stu.setdefault(name, []).append(sc)
    return [{"name": nm, "score": sum(v) / len(v), "weight": weight,
             "source": f"{Path(path).name}#作业统计均值({len(v)})"} for nm, v in per_stu.items()]


def read_xuexitong_stat(path: Path, sheet_keyword: str = "章节测验",
                        weight: float = 1.0) -> list[dict]:
    """学习通统计文件：匹配 sheet，在第 4 行（索引3）找"成绩"列，非 0 取平均。
    迁移自 _addScoreExamStat。"""
    rows = _rows_of(path, sheet_keyword)
    if len(rows) <= 3:
        return []
    heads = rows[3]
    cols = [j for j, v in enumerate(heads) if isinstance(v, str) and "成绩" in v]
    name_i = 0
    per_stu: dict[str, list] = {}
    for r in rows[4:]:
        if not r or r[name_i] is None:
            continue
        name = str(r[name_i]).strip()
        if not name:
            continue
        for j in cols:
            try:
                v = float(r[j])
            except (TypeError, IndexError):
                continue
            if v == 0:  # 迁移语义：非 0 才计入
                continue
            per_stu.setdefault(name, []).append(v)
    return [{"name": k, "score": sum(v) / len(v), "weight": weight,
             "source": f"{Path(path).name}#{sheet_keyword}"} for k, v in per_stu.items()]


def read_rainclass(path: Path, weight: float = 1.0) -> list[dict]:
    """雨课堂班级数据汇总表（header=None；前3列=学号/姓名/汇总；其后每课2列：签到方式+得分）。
    迁移自 _legacy/2603paperDesign/src/paperdesign/rainclass/analyze_attendance.py 的表结构假设。"""
    rows = _rows_of(path, 0)
    if len(rows) < 3:
        return []
    # 第2行(index 1) 是列标题（含满分信息），学生数据从第3行(index 2) 开始
    body = rows[2:]
    n_courses = (len(rows[1]) - 3) // 2 if len(rows) > 2 else 0
    out = []
    for r in body[1:]:
        if not r or r[1] is None:
            continue
        name = str(r[1]).strip()
        if not name:
            continue
        per_scores = []
        for c in range(n_courses):
            j = 3 + 2 * c + 1  # 每课得分列
            try:
                per_scores.append(float(r[j]))
            except (TypeError, ValueError, IndexError):
                continue
        if per_scores:
            out.append({"name": name, "score": sum(per_scores) / len(per_scores),
                        "weight": weight, "source": f"{Path(path).name}#雨课堂{n_courses}课均"})
    return out


def read_flex(path: Path, cols: list[str] | str | None = None, weight: float = 1.0) -> list[dict]:
    """自定义成绩源（用户给定列名或列名 list；多列等权平均）。"""
    if isinstance(cols, str):
        cols = [cols] if cols else None
    rows = _rows_of(path)
    if len(rows) < 2:
        return []
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    name_i = next((i for i, h in enumerate(headers) if h in ("姓名", "name")), 0)
    if cols:
        idxs = [i for i, h in enumerate(headers) if h in (cols or [])]
    else:
        idxs = None
    if not idxs:
        return read_flex_auto(headers, rows[1:], path, weight, name_i)
    out = []
    for r in rows[1:]:
        if not r or r[name_i] is None:
            continue
        vals = []
        for i in idxs:
            try:
                vals.append(float(r[i]))
            except (TypeError, ValueError):
                pass
        if vals:
            out.append({"name": str(r[name_i]).strip(), "score": sum(vals) / len(vals),
                        "weight": weight,
                        "source": f"{Path(path).name}#{'|'.join(cols)})"})
    return out


def read_flex_auto(headers, body, path, weight, name_i):
    best = (0, None)
    for i, h in enumerate(headers):
        if i == name_i or not h:
            continue
        nums = sum(1 for r in body[:20] if i < len(r) and _try_float(r[i]) is not None)
        if nums > best[0]:
            best = (nums, i)
    score_i = best[1]
    if score_i is None:
        return []
    out = []
    for r in body:
        if not r or r[name_i] is None:
            continue
        v = _try_float(r[score_i])
        if v is not None:
            hd = headers[score_i] if score_i < len(headers) else f"col{score_i}"
            out.append({"name": str(r[name_i]).strip(), "score": v, "weight": weight,
                        "source": f"{Path(path).name}#{hd}"})
    return out


def _try_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _col_scores(rows, score_i, name_i, source, weight):
    out = []
    for r in rows[1:]:
        if not r or r[name_i] is None:
            continue
        try:
            v = float(r[score_i])
        except (TypeError, ValueError, IndexError):
            continue
        out.append({"name": str(r[name_i]).strip(), "score": v,
                    "weight": weight, "source": source})
    return out


ADAPTERS = {
    "exam": read_exam,
    "xuexitong_assignment": read_xuexitong_assignment,
    "xuexitong_stat": read_xuexitong_stat,
    "rainclass": read_rainclass,
    "custom": read_flex,
}


def read_source(spec: dict) -> list[dict]:
    """spec: {family, file, col?, weight?, cols?}（D19 成绩读入统一入口）。"""
    family = spec.get("family", "custom")
    if family not in ADAPTERS:
        logger.warning(f"未知 family {family}，按 custom 解析")
        fn = ADAPTERS["custom"]
    else:
        fn = ADAPTERS[family]
    return fn(Path(spec["file"]), **{k: v for k, v in spec.items()
                                     if k in ("col", "weight", "cols")})
