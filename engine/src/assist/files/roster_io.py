"""D120：roster 落盘 / 读回（引擎权威路径）。

路径契约（唯一真源）：
    `<ws>/<class_dir>/roster/roster.xlsx`   ← 与 `grading/inputs.roster_file()` **完全一致**
    `<ws>/<class_dir>/roster/roster.json`   ← 同内容的 JSON（便于 diff/审计）

写入由**引擎**决定路径（前端不再猜），彻底避免 D120 那种
`<ws>/kb/classes/<班级>/roster/` 的错位。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from loguru import logger

# 与前端 ROSTER_COLUMNS 同口径（写入时恒用英文表头）
COLUMNS = ("name", "number", "class", "tag")


def safe_class_dir(raw: str) -> str:
    """classDir 归一：去首尾斜杠、禁 `..`、禁绝对路径。

    只允许 `<a>/<b>` 这种相对形态（如 `classes/化工25`）。
    """
    raw_s = str(raw or "").strip().replace("\\", "/")
    # 绝对路径 / 盘符：**先判后 strip**（否则 "/abs/path" 会被 strip 成 "abs/path" 蒙混过关）
    if raw_s.startswith("/") or (len(raw_s) > 1 and raw_s[1] == ":"):
        return ""
    s = raw_s.strip("/")
    if not s:
        return ""
    parts_raw = [p for p in s.split("/") if p]
    # 任何 `..` 一律拒绝（不做"悄悄过滤"——那会把恶意路径变成看似合法的路径）
    if any(p in (".", "..") for p in parts_raw):
        return ""
    parts = parts_raw
    # 防注入：每段只允许安全字符（中文/字母/数字/下划线/点/连字符）
    for p in parts:
        if not re.fullmatch(r"[\w\u4e00-\u9fff.\-]{1,80}", p):
            return ""
    return "/".join(parts)


def roster_dir(ws: Path, class_dir: str) -> "Path | None":
    cd = safe_class_dir(class_dir)
    if not cd:
        return None
    return Path(ws).resolve() / cd / "roster"


def roster_paths(ws: Path, class_dir: str) -> "tuple[Path, Path] | None":
    d = roster_dir(ws, class_dir)
    if d is None:
        return None
    return d / "roster.xlsx", d / "roster.json"


def _normalize_students(students) -> list[dict]:
    out: list[dict] = []
    for s in students or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "number": str(s.get("number") or "").strip(),
            "class": str(s.get("class") or "").strip(),
            "tag": str(s.get("tag") or "").strip(),
        })
    return out


def write_roster(ws: Path, class_dir: str, students) -> dict:
    """把名单写到 `<ws>/<class_dir>/roster/roster.xlsx` + `.json`。

    - 路径由本函数决定（引擎权威）；
    - 写前若已存在，备份为 `roster.xlsx.old-<ts>`（不覆盖即丢）；
    - 返回 {ok, path, count, backup?}。
    """
    paths = roster_paths(ws, class_dir)
    if paths is None:
        return {"ok": False, "error": f"classDir 非法：{class_dir!r}（应形如 classes/<班级>）"}
    xlsx, js = paths
    rows = _normalize_students(students)
    if not rows:
        return {"ok": False, "error": "名单为空，未写入（避免覆盖已有名单）"}
    xlsx.parent.mkdir(parents=True, exist_ok=True)
    # D120：**整段加锁**。前端是 800ms 防抖，但多标签页/CLI 并发仍可能撞车：
    # 不加锁时 8 个并发写只会留下 1 个备份且互相覆盖（实测）。
    from ..filelock import locked
    backup = None
    with locked(xlsx):
        if xlsx.is_file():
            backup = xlsx.with_name(f"roster.xlsx.old-{time.strftime('%Y%m%d-%H%M%S')}")
            n = 1
            while backup.exists():            # 同一秒多次 → 避免备份互相覆盖
                backup = xlsx.with_name(f"roster.xlsx.old-{time.strftime('%Y%m%d-%H%M%S')}-{n}")
                n += 1
            try:
                backup.write_bytes(xlsx.read_bytes())
            except OSError:
                backup = None
        try:
            from openpyxl import Workbook
            wb = Workbook()
            sh = wb.active
            sh.title = "roster"
            sh.append(list(COLUMNS))
            for r in rows:
                sh.append([r["name"], r["number"], r["class"], r["tag"]])
            for i, w in enumerate((14, 16, 18, 14), start=1):
                sh.column_dimensions[chr(64 + i)].width = w
            # 先写临时文件再原子替换，避免读到半截 xlsx
            tmp = xlsx.with_suffix(".xlsx.tmp")
            wb.save(tmp)
            tmp.replace(xlsx)
            from ..filelock import atomic_write_text
            atomic_write_text(js, json.dumps(rows, ensure_ascii=False, indent=1))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"写 roster 失败：{exc}")
            return {"ok": False, "error": str(exc)[:200]}
    logger.info(f"[roster] 已写入 {xlsx}（{len(rows)} 人）")
    return {"ok": True, "path": str(xlsx), "json": str(js), "count": len(rows),
            **({"backup": str(backup)} if backup else {})}


def read_roster_file(ws: Path, class_dir: str) -> dict:
    """读回 roster（PWA 丢失 localStorage 时可恢复）。"""
    paths = roster_paths(ws, class_dir)
    if paths is None:
        return {"ok": False, "error": f"classDir 非法：{class_dir!r}"}
    xlsx, js = paths
    if xlsx.is_file():
        try:
            from .roster import read_roster
            rows = read_roster(xlsx)
            return {"ok": True, "path": str(xlsx), "students": rows,
                    "count": len(rows), "source": "xlsx"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:200]}
    if js.is_file():
        try:
            rows = json.loads(js.read_text(encoding="utf-8"))
            return {"ok": True, "path": str(js), "students": _normalize_students(rows),
                    "count": len(rows), "source": "json"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:200]}
    return {"ok": False, "error": f"未找到 roster：{xlsx}"}
