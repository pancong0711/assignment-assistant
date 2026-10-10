"""D73-9：旧 run / targets JSON 导入到当前工件路径契约。

背景：D63/D72 早期提取产物可能落在 `.scratch/`、仓库根目录或任意位置，
schema 与当前 run 接近但路径不在 `xxt_home()/runs/`，导致 PWA 看不到。
本模块只做“规范化 + 复制到 runs/”，不触网、不重命名业务字段。

安全：导入内容视为教师本机隐私数据，仅写本地 workspace，不参与任何上传/入库。
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

# run_id 必须与 serve 的路径校验 / 文件名契约一致
_RUN_ID_RE = re.compile(r"^xxt-[0-9A-Za-z][0-9A-Za-z\-]*$")

_KNOWN_COURSE = ("name", "courseId", "cpi", "classes")
_KNOWN_CLASS = ("name", "classId", "cpi", "status", "notes", "works", "roster", "notices")
_KNOWN_WORK = ("name", "workId", "pending", "submitted", "unsubmitted", "answer_window",
               "mark_href", "source", "submitted_names", "unsubmitted_names",
               "sub_not_in_roster", "anchor")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def normalize_run_id(data: "dict | None", fallback_id: "str | None" = None) -> str:
    """返回合法且稳定的 run_id：优先 data.run_id，其次文件名前缀，最后生成新 id。"""
    rid = str((data or {}).get("run_id") or "").strip()
    if _RUN_ID_RE.match(rid):
        return rid
    if fallback_id:
        stem = Path(str(fallback_id)).stem
        m = re.match(r"^(xxt-[0-9A-Za-z][0-9A-Za-z\-]*)", stem)
        if m and _RUN_ID_RE.match(m.group(1)):
            return m.group(1)
    return f"xxt-{time.strftime('%Y%m%d-%H%M%S')}-import-{secrets.token_hex(2)}"


def normalize_legacy_run(data: "dict", fallback_id: "str | None" = None) -> dict:
    """把旧 run（或 targets）规整成当前 run schema；保留已知字段，丢弃未知噪声。"""
    if not isinstance(data, dict):
        raise ValueError("run JSON 顶层必须是对象")
    courses = data.get("courses")
    if not isinstance(courses, list):
        raise ValueError("run JSON 缺少 courses[]（既不是 run 也不是 targets 清单）")

    out: dict = {
        "run_id": normalize_run_id(data, fallback_id),
        "mode": str(data.get("mode") or "readonly"),
        "ts_start": data.get("ts_start") or _now(),
        "ts_end": data.get("ts_end") or _now(),
        "courses": [],
        "failures": data.get("failures") if isinstance(data.get("failures"), list) else [],
        "session": data.get("session") if isinstance(data.get("session"), dict) else {},
        "imported": True,
        "imported_at": _now(),
    }
    for c in courses:
        if not isinstance(c, dict):
            continue
        cc = {k: c.get(k) for k in _KNOWN_COURSE if k in c}
        cc["courseId"] = str(cc.get("courseId") or "")
        cc["name"] = str(cc.get("name") or cc["courseId"] or "未命名课程")
        classes: list[dict] = []
        for cl in c.get("classes") or []:
            if not isinstance(cl, dict):
                continue
            ncl = {k: cl.get(k) for k in _KNOWN_CLASS if k in cl}
            ncl["classId"] = str(ncl.get("classId") or "")
            ncl["name"] = str(ncl.get("name") or ncl["classId"] or "未命名班级")
            works: list[dict] = []
            for w in ncl.get("works") or []:
                if not isinstance(w, dict):
                    continue
                works.append({k: w.get(k) for k in _KNOWN_WORK if k in w})
            ncl["works"] = works
            if not isinstance(ncl.get("notices"), list):
                ncl["notices"] = []
            if not isinstance(ncl.get("notes"), list):
                ncl["notes"] = []
            classes.append(ncl)
        cc["classes"] = classes
        out["courses"].append(cc)
    if not out["courses"]:
        raise ValueError("run JSON courses[] 为空，无法导入")
    return out


def _summary(run: dict, path: Path) -> dict:
    return {
        "run_id": run.get("run_id"),
        "out": str(path),
        "courses": len(run.get("courses") or []),
        "classes": sum(len(c.get("classes") or []) for c in run.get("courses") or []),
        "works": sum(len(cl.get("works") or [])
                     for c in run.get("courses") or [] for cl in c.get("classes") or []),
        "failures": len(run.get("failures") or []),
        "imported": True,
    }


def import_run_data(data: dict, fallback_id: "str | None" = None,
                    home: "Path | str | None" = None) -> dict:
    """规范化并写入 `runs/<run_id>.json`；重名自动加 `-2`/`-3` 后缀。"""
    from .layout import runs_dir
    run = normalize_legacy_run(data, fallback_id)
    d = runs_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    base_rid = run["run_id"]
    rid, n = base_rid, 1
    while (d / f"{rid}.json").exists():
        n += 1
        rid = f"{base_rid}-{n}"
    run["run_id"] = rid
    p = d / f"{rid}.json"
    p.write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    return _summary(run, p)


def import_run_file(src: "Path | str", home: "Path | str | None" = None) -> dict:
    """从单个 JSON 文件导入（run 或 targets 均可）。"""
    src = Path(src)
    data = json.loads(src.read_text(encoding="utf-8"))
    return import_run_data(data, fallback_id=src.name, home=home)


def scan_legacy_run_files(src_dir: "Path | str", pattern: str = "xxt-*.json") -> list[Path]:
    """扫描目录下的候选旧 run 文件（不读取内容，便于 CLI/serve 先列后导）。"""
    d = Path(src_dir)
    if not d.is_dir():
        return []
    out = [p for p in sorted(d.glob(pattern)) if p.is_file()]
    return [p for p in out if p.name not in {
        "xxt-readonly.json", "xxt-notices.json", "xxt-session-check.json",
        "xxt-storage.json", "xxt-login-state.json",
    } and "login-state" not in p.name]
