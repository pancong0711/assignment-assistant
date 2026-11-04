"""grading_scores.py — D149：把「AI 批阅成绩」作为一种成绩源。

教师诉求：批阅好了就不必再去学习通下载这次作业的成绩，直接像勾选表格成绩一样
勾选批阅成绩；**每次作业包作为一列**，可加权到总成绩。

口径（教师拍板）：
- 一次作业包 = 一列（`source = "grading:<packId>"`）；
- **未批阅 / 未提交 → 记 0 分**（不是空白）；
- 同时返回 `submitted` / `graded` 标记，让 UI 能区分"真 0 分"与"没交"。

输出的行与现有成绩源完全同构（`{name, score, source, weight}`），
因此直接复用 `grouping.merge_scores()` 的加权聚合，不新增任何算法。
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger


class GradingScoreError(RuntimeError):
    """批阅成绩读取失败（可读业务错误）。"""


def _class_grading_dir(ws, class_dir: str) -> Path:
    ws_p = Path(ws).resolve()
    cd = str(class_dir or "").strip().strip("/")
    if not cd:
        raise GradingScoreError("班级目录不能为空（如 classes/化工25）")
    d = (ws_p / cd / "grading").resolve()
    try:
        d.relative_to((ws_p / "classes").resolve())
    except ValueError:
        raise GradingScoreError(f"路径越界：{class_dir!r}") from None
    return d


def list_grading_packs(ws, class_dir: str) -> list[dict]:
    """列出该班级**有评阅结果**的作业包（一次作业一列）。"""
    base = _class_grading_dir(ws, class_dir)
    out: list[dict] = []
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        if d.name.startswith("_"):          # _trend 等内部目录
            continue
        ev = d / "evaluations"
        if not ev.is_dir():
            continue
        files = [f for f in ev.glob("[!_]*.json")]
        if not files:
            continue
        name = d.name
        # 作业包名（读不到就用 id）
        try:
            from ..packs import read_pack
            pk = read_pack(Path(ws).resolve(), d.name) or {}
            name = str(pk.get("name") or d.name)
        except Exception:  # noqa: BLE001
            pass
        latest = ""
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                ts = str(data.get("timestamp") or "")
                if ts > latest:
                    latest = ts
            except Exception:  # noqa: BLE001
                continue
        out.append({"packId": d.name, "name": name, "graded": len(files),
                    "at": latest})
    return out


def grading_scores(ws, class_dir: str, pack_id: str, *,
                   students: "list[str] | None" = None) -> dict:
    """读某次作业包的批阅成绩 → 一列成绩行。

    `students`：名单（按姓名）。不传时只返回批阅产物里出现的学生。
    未批阅/未提交的学生 **记 0 分**（教师口径），并带 `submitted/graded=False`。
    """
    base = _class_grading_dir(ws, class_dir)
    pid = str(pack_id or "").strip()
    if not pid:
        raise GradingScoreError("作业包 id 不能为空")
    ev = (base / pid / "evaluations")
    if not ev.is_dir():
        raise GradingScoreError(f"该作业包没有评阅结果：{ev}")

    scored: dict[str, dict] = {}
    for f in sorted(ev.glob("[!_]*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[批阅成绩] 跳过坏文件 {f.name}: {exc}")
            continue
        name = str(d.get("student") or f.stem).strip()
        if not name:
            continue
        raw = d.get("total_score")
        try:
            score = float(raw) if raw is not None else 0.0
        except (TypeError, ValueError):
            score = 0.0
        scored[name] = {"name": name, "score": round(score, 2),
                        "source": f"grading:{pid}", "weight": 1.0,
                        "submitted": True, "graded": True}

    rows: list[dict] = []
    seen: set[str] = set()
    for nm in (students or []):
        n = str(nm or "").strip()
        if not n or n in seen:
            continue
        seen.add(n)
        rows.append(scored.get(n) or {
            # 名单里有、但没批阅/没提交 → 记 0 分（教师口径）
            "name": n, "score": 0.0, "source": f"grading:{pid}", "weight": 1.0,
            "submitted": False, "graded": False,
        })
    # 批阅产物里有、名单里没传的，也一并给出
    for n, row in scored.items():
        if n not in seen:
            rows.append(row)

    graded_n = sum(1 for r in rows if r.get("graded"))
    return {"ok": True, "packId": pid, "rows": rows, "total": len(rows),
            "graded": graded_n, "zeroFilled": len(rows) - graded_n}
