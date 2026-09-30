"""rainclass 签到明细分析（M5 补强，阶段5-B1）。

解析迁移自 _legacy/2603paperDesign/src/paperdesign/rainclass/analyze_attendance.py
（read_class_data/extract_attendance_and_scores 的语义，去 pandas）：

汇总表结构（固定格式，docs/05-D19 family=rainclass）：
- 行0 课程标题，行1 列标题（各次课"签到方式/得分"成对出现，含"总:xx分"满分），
  行2 起为学生；列0 学号 / 列1 姓名 / 列2 汇总得分；
- 每课从列N开始（首课约列9），奇/偶列并无绝对顺序以"签到方式/得分"子串判断。

输出（`assist roster rain`）：per-学生 {姓名, 学号, 汇总分, 出勤分布(普答/普答异常/
请假/旷课/未签到/未知), 得分率均值}，可写 xlsx 与 JSON。
"""

import re
from collections import Counter
from pathlib import Path

from loguru import logger
from openpyxl import load_workbook

METHOD_SCAN_START = 9  # 迁移语义：前3列学号/姓名/汇总 + 6 列其他统计，其后每课2列


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_rainclass(path: Path) -> list[dict]:
    """解析一个雨课堂汇总表 → per-学生明细 [{"name","number","total","events","rate"}]。"""
    path = Path(path)
    wb = load_workbook(path, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if len(rows) < 3:
        logger.warning(f"雨课堂汇总表结构异常（不足3行）: {path}")
        return []

    headers = [str(h) if h is not None else "" for h in rows[1]]
    # 找 (method_col, score_col, max_score) 对（"签到方式"子列名优先，完美迁移 legacy 启发式）
    pairs = []
    i = 3   # 迁移注释：前3列为学号/姓名/汇总；实际课数据从列>=3 开始（宽松扫描）
    while i < len(headers):
        name = headers[i]
        if "签到方式" in name and i + 1 < len(headers):
            m = re.search(r"总[:：]([\d.]+)分", headers[i + 1])
            pairs.append({"method_col": i, "score_col": i + 1,
                          "max": float(m.group(1)) if m else 10.0})
            i += 2
        elif "得分" in name and i - 1 >= 3:
            m = re.search(r"总[:：]([\d.]+)分", name)
            pairs.append({"method_col": i - 1, "score_col": i,
                          "max": float(m.group(1)) if m else 10.0})
            i += 1
        else:
            i += 1
    if not pairs:
        logger.warning(f"未识别雨课堂签到列结构: {path}")
        return []

    out = []
    for row in rows[2:]:
        if not row or len(row) < 3 or row[1] is None or not str(row[1]).strip():
            continue
        sid = str(row[0] or "").strip()
        name = str(row[1]).strip()
        try:
            total = float(row[2])
        except (TypeError, ValueError):
            total = 0.0
        events: Counter = Counter()
        rates: list[float] = []
        for info in pairs:
            mc, sc = info["method_col"], info["score_col"]
            method = row[mc] if mc < len(row) else None
            method = str(method).strip() if method is not None else "未知"
            if not method:
                method = "未知"
            events[method] += 1
            try:
                s = float(row[sc]) if sc < len(row) else 0.0
            except (TypeError, ValueError):
                s = 0.0
            rates.append(min(1.0, s / info["max"] if info["max"] else 0.0))
        out.append({
            "number": sid, "name": name, "total": round(total, 2),
            "events": dict(events),
            "rate": round(sum(rates) / len(rates), 3) if rates else 0.0,
            "n_courses": len(pairs),
        })
    logger.info(f"{path.name}: 解析 {len(out)} 名学生 / {len(pairs)} 次课")
    return out


def summarize(per_students: list[dict]) -> dict:
    """多表聚合（可选）：同一名单多文件时按姓名取均值。"""
    from collections import defaultdict
    acc: dict[str, list[float]] = defaultdict(list)
    num: dict[str, str] = {}
    events_acc: dict[str, dict] = {}
    for d in per_students:
        acc.setdefault(d["name"], []).append(d["rate"])
        num[d["name"]] = d["number"]
        for k, v in d["events"].items():
            events_acc.setdefault(d["name"], {}).update({k: events_acc[d["name"]].get(k, 0) + v})
    out = []
    for name, rates in acc.items():
        out.append({"number": num[name], "name": name,
                    "rate_mean": round(sum(rates) / len(rates), 3),
                    "events": events_acc.get(name, {}),
                    "tables": len(rates)})
    out.sort(key=lambda d: -d["rate_mean"])
    return {"rows": out}


def to_xlsx(path: Path, summary: dict) -> Path:
    """结果写 xlsx（姓名/学号/出勤率均值/明细事件）。"""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "rainclass-summary"
    ws.append(["姓名", "学号", "出勤率均值", "签到事件", "数据表数"])
    import json
    for r in summary.get("rows", []):
        ws.append([r["name"], r["number"], r["rate_mean"],
                   json.dumps(r["events"], ensure_ascii=False), r["tables"]])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
