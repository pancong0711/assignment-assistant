"""D85 §3：本地批阅草稿（人工批阅栏的本地保存）。

存储：`<xxt_home>/grade-drafts/<classId>/<workId>.json`
结构：`{ "<学生key>": {"score": 88, "comment": "文字", "images": [{"name","data_b64"}],
                      "updatedAt": "2026-10-15 15:00:00"} }`
学生 key：`workAnswerId` 优先，回落姓名（与批阅清单同口径；两者都可作为查询键）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

_SAFE = re.compile(r"[0-9A-Za-z\-_]{1,40}")


def drafts_root(home=None) -> Path:
    """**旧布局**根目录 `<xxt_home>/grade-drafts`（仅为兼容/迁移保留）。"""
    if home is None:
        from .session import xxt_home
        home = xxt_home()
    d = Path(home) / "grade-drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def legacy_draft_file(home, class_id: str, work_id: str) -> "Path | None":
    if not _SAFE.fullmatch(str(class_id)) or not _SAFE.fullmatch(str(work_id)):
        return None
    return drafts_root(home) / str(class_id) / f"{work_id}.json"


def grading_drafts_dir(ws, class_dir: str, task_id: str) -> "Path | None":
    """D119 新布局：`<ws>/<class_dir>/grading/<taskId>/drafts/`。"""
    tid = str(task_id or "").strip()
    cd = str(class_dir or "").strip().strip("/")
    if not tid or not cd:
        return None
    safe_tid = re.sub(r"[\\/:*?\"<>|]", "_", tid).strip(" .") or "task"
    return Path(ws).resolve() / cd / "grading" / safe_tid / "drafts"


def draft_file(ws=None, class_id: str = "", work_id: str = "",
               *, class_dir: str = "", task_id: str = "",
               home=None) -> "Path | None":
    """草稿文件路径（D119）。

    - 给了 `task_id` + `class_dir` + `ws` → **新布局**（写这里）；
    - 否则 → 旧布局（兼容既有调用方）。
    """
    if not _SAFE.fullmatch(str(class_id)) or not _SAFE.fullmatch(str(work_id)):
        return None
    if task_id and class_dir and ws is not None:
        d = grading_drafts_dir(ws, class_dir, task_id)
        if d is not None:
            d.mkdir(parents=True, exist_ok=True)
            return d / f"{work_id}.json"
    return legacy_draft_file(home, class_id, work_id)


def _candidate_draft_files(ws=None, class_id: str = "", work_id: str = "",
                           *, class_dir: str = "", task_id: str = "",
                           alt_task_ids: "list[str] | None" = None,
                           home=None) -> "list[Path]":
    """读取候选顺序：新布局 → **兼容目录**（alt_task_ids）→ 旧布局。

    D127-FIX：批阅目录键曾一度在「作业纸 id」与「作业包 id」之间漂移，
    导致"写了草稿但逐生审核读不到"。这里允许调用方传入兼容 id 列表
    （如 padId），让历史数据仍可读，教师无需手动迁移。
    """
    out: list[Path] = []
    tids = [str(task_id or "").strip()]
    for a in (alt_task_ids or []):
        a = str(a or "").strip()
        if a and a not in tids:
            tids.append(a)
    if class_dir and ws is not None:
        for tid in tids:
            d = grading_drafts_dir(ws, class_dir, tid)
            if d is not None:
                out.append(d / f"{work_id}.json")
    legacy = legacy_draft_file(home, class_id, work_id)
    if legacy is not None:
        out.append(legacy)
    return out


def read_drafts(home=None, class_id: str = "", work_id: str = "", *,
                ws=None, class_dir: str = "", task_id: str = "",
                alt_task_ids: "list[str] | None" = None) -> dict:
    """读草稿（**原始结构**）：新布局优先，其次旧布局（兼容未迁移数据）。

    注意：返回的是磁盘上的原样结构，可能是 D92 之前的单套 `{score, comment}`。
    需要统一双套 `{ai, human, humanMode, revision}` 请用 `read_drafts_normalized`。
    """
    for p in _candidate_draft_files(ws, class_id, work_id,
                                    class_dir=class_dir, task_id=task_id,
                                    alt_task_ids=alt_task_ids, home=home):
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict):
            return d
    return {}


def read_drafts_normalized(home=None, class_id: str = "", work_id: str = "", *,
                           ws=None, class_dir: str = "", task_id: str = "",
                           alt_task_ids: "list[str] | None" = None) -> dict:
    """读草稿并逐条 `normalize_draft`（统一为双套 `{ai, human, humanMode, revision}`）。

    D126-FIX：给「逐生审核」这类**按 `ai.transcript` / `ai.comment` 取值**的消费方用。
    旧的 D85 单套草稿是 `{score, comment}` 形状，直接读会让前端取值全部落空 →
    弹窗显示「无 AI 批语 / 暂无转写」，而列表页因 `drafts[k].score` 兜底仍显示「✓」，
    看起来"已批阅却看不到内容"。
    """
    raw = read_drafts(home, class_id, work_id, ws=ws,
                      class_dir=class_dir, task_id=task_id,
                      alt_task_ids=alt_task_ids)
    return {str(k): (normalize_draft(v) if isinstance(v, dict) else v)
            for k, v in raw.items()}
def save_draft(home, class_id: str, work_id: str, key: str, *,
               score=None, comment: str = "", comment_text: str = "",
               images: "list[dict] | None" = None, extra: "dict | None" = None,
               ws=None, class_dir: str = "", task_id: str = "") -> dict:
    """写单个学生的本地批阅草稿（合并式更新；score=None 表示不改分数）。

    D119：传 `ws`+`class_dir`+`task_id` → 写入**新布局**
    `<ws>/<class_dir>/grading/<taskId>/drafts/<workId>.json`（不同作业批次互不覆盖）。
    """
    p = draft_file(ws, class_id, work_id, class_dir=class_dir, task_id=task_id, home=home)
    if p is None:
        return {"ok": False, "error": "非法 classId/workId"}
    k = str(key or "").strip()
    if not k:
        return {"ok": False, "error": "缺少学生 key（workAnswerId 或姓名）"}
    # 读-改-写必须整体在锁内：AI/脚本并行写同一份草稿文件时不丢更新、不留半截 JSON。
    from ..filelock import update_json
    box: dict = {}

    def _mutate(data: dict) -> None:
        cur = data.get(k) if isinstance(data.get(k), dict) else {}
        if score is not None:
            try:
                cur["score"] = float(score)
            except (TypeError, ValueError):
                box["error"] = f"分数非法：{score}"
                return
        if comment:
            cur["comment"] = str(comment)
        if comment_text:
            cur["comment_text"] = str(comment_text)
        if images is not None:
            cur["images"] = [{"name": str(i.get("name") or ""), "data_b64": str(i.get("data_b64") or "")}
                             for i in images if isinstance(i, dict)]
        if extra:
            for kk, vv in extra.items():
                cur[str(kk)] = vv
        cur["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        data[k] = cur
        box["draft"] = cur

    update_json(p, _mutate, default={})
    if "error" in box:
        return {"ok": False, "error": box["error"]}
    return {"ok": True, "key": k, "draft": box["draft"], "file": str(p)}


def normalize_draft(d: dict) -> dict:
    """D92-R2：把草稿归一为**双套**结构 {ai, human, humanMode, revision, revised}。

    兼容旧单套 {score, comment, comment_text, images, source}：
    source 以 'human' 开头 → 视作人工套，humanMode='replace'；否则视作 ai 套。
    """
    d = d if isinstance(d, dict) else {}
    if isinstance(d.get("ai"), dict) or isinstance(d.get("human"), dict):
        out = dict(d)
        out.setdefault("ai", d.get("ai") if isinstance(d.get("ai"), dict) else {})
        out.setdefault("human", d.get("human") if isinstance(d.get("human"), dict) else {})
        out.setdefault("humanMode", d.get("humanMode") or "none")
        out.setdefault("revision", d.get("revision") if isinstance(d.get("revision"), dict) else {})
        out["revised"] = _is_revised(out)
        return out
    # 旧单套
    src = str(d.get("source") or "")
    payload = {"score": d.get("score"), "comment": d.get("comment") or "",
               "comment_text": d.get("comment_text") or "", "images": d.get("images") or []}
    out = {"ai": {}, "human": {}, "humanMode": "none", "revision": {},
           "student": d.get("student") or "", "tag": d.get("tag") or "",
           "updatedAt": d.get("updatedAt") or ""}
    if src.startswith("human"):
        out["human"] = {**payload, "used": True}
        out["ai"] = {}
        out["humanMode"] = "replace"
    else:
        out["ai"] = payload
    out["source"] = src
    out["revised"] = _is_revised(out)
    return out


def _is_revised(out: dict) -> bool:
    rev = out.get("revision") or {}
    text = str(rev.get("text") or "").strip()
    ai_comment = str((out.get("ai") or {}).get("comment") or "").strip()
    return bool(text) and text != ai_comment


def save_draft_sets(home, class_id: str, work_id: str, key: str, *,
                    ai: "dict | None" = None, human: "dict | None" = None,
                    human_mode: "str | None" = None, revision: "dict | None" = None,
                    student: str = "", tag: str = "",
                    ws=None, class_dir: str = "", task_id: str = "") -> dict:
    """D92-R2：写双套草稿（ai/human 各自合并；human_mode 可选；revision 可选）。

    D119：传 `ws`+`class_dir`+`task_id` → 写入新布局（按作业纸隔离）。
    """
    p = draft_file(ws, class_id, work_id, class_dir=class_dir, task_id=task_id, home=home)
    if p is None:
        return {"ok": False, "error": "非法 classId/workId"}
    k = str(key or "").strip()
    if not k:
        return {"ok": False, "error": "缺少学生 key"}
    from ..filelock import update_json
    box: dict = {}

    def _mutate(data: dict) -> None:
        cur = normalize_draft(data.get(k) if isinstance(data.get(k), dict) else {})
        if ai is not None:
            cur["ai"] = {**(cur.get("ai") or {}),
                         **{kk: vv for kk, vv in ai.items() if vv is not None}}
        if human is not None:
            cur["human"] = {**(cur.get("human") or {}),
                            **{kk: vv for kk, vv in human.items() if vv is not None}}
            if human:
                cur["human"]["used"] = True
        if human_mode is not None:
            cur["humanMode"] = str(human_mode or "none")
        if revision is not None:
            cur["revision"] = {**(cur.get("revision") or {}), **revision}
            cur["revision"].setdefault("at", time.strftime("%Y-%m-%d %H:%M:%S"))
        if student:
            cur["student"] = student
        if tag:
            cur["tag"] = tag
        cur["revised"] = _is_revised(cur)
        cur["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        data[k] = cur
        box["draft"] = cur

    update_json(p, _mutate, default={})
    return {"ok": True, "key": k, "draft": box["draft"], "file": str(p)}


def delete_draft(home, class_id: str, work_id: str, key: str, *,
                 ws=None, class_dir: str = "", task_id: str = "") -> dict:
    p = draft_file(ws, class_id, work_id, class_dir=class_dir, task_id=task_id, home=home)
    if p is None or not p.is_file():
        return {"ok": False, "error": "无草稿文件"}
    from ..filelock import update_json
    box: dict = {"found": False}

    def _mutate(data: dict) -> None:
        if str(key) in data:
            data.pop(str(key), None)
            box["found"] = True

    update_json(p, _mutate, default={})
    if not box["found"]:
        return {"ok": False, "error": f"草稿不存在：{key}"}
    return {"ok": True, "key": str(key)}


def student_key(student: dict) -> str:
    """草稿键：workAnswerId 优先，回落姓名（与批阅清单一致）。"""
    wa = str((student or {}).get("workAnswerId") or "").strip()
    return wa or str((student or {}).get("name") or "").strip()
