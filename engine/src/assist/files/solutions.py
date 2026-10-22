"""D89-N3：题库 solution 多版本库 —— <ws>/kb/solutions/<qid>.json。

动机（docs/42-D89 §1）：kb xlsx 的 `solution` 是单字符串列，无法记录 AI 作答/
多模型/多时间/置顶；而参考答案会随模型与教学经验长期演进（甚至多版本并存）。

schema（docs/42-D89 §4.2）：
    { qid, kb, chap, versions: [
        { id, text, source: human|ai, model, at, pinned } ] }

- 版本**追加不可覆盖**（AI 作答永不覆盖原答案）；
- `pinned` 至多一个 = 生效答案（"最新置顶版"）；
- 无版本文件时回落 xlsx `solution` 列（兼容旧数据）；
- 读取入口 `effective_solution(ws, qid, fallback)` 供作业包/批阅**实时**取最新置顶版。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from loguru import logger

SOLUTIONS_DIR = "solutions"
_QID_RE = re.compile(r"^[^\\/:*?\"<>|]{1,120}$")


def solutions_dir(ws) -> Path:
    d = Path(ws).resolve() / "kb" / SOLUTIONS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_qid(qid: str) -> str:
    q = str(qid or "").strip()
    if not q or q.strip(".") == "" or not _QID_RE.match(q):
        return ""
    return q


def _path(ws, qid: str) -> "Path | None":
    sid = _safe_qid(qid)
    return solutions_dir(ws) / f"{sid}.json" if sid else None


def read_solutions(ws, qid: str) -> "dict | None":
    p = _path(ws, qid)
    if not p or not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _next_version_id(versions: list[dict]) -> str:
    n = 1
    ids = {str(v.get("id") or "") for v in versions}
    while f"v{n}" in ids:
        n += 1
    return f"v{n}"


def _normalize(d: dict) -> dict:
    d = d if isinstance(d, dict) else {}
    vs = [v for v in (d.get("versions") or []) if isinstance(v, dict) and str(v.get("text") or "").strip()]
    # 保证至多一个 pinned：取第一个 pinned 为准
    pinned_seen = False
    for v in vs:
        v["source"] = str(v.get("source") or "human")
        v["text"] = str(v.get("text") or "")
        v["model"] = str(v.get("model") or "")
        v["at"] = str(v.get("at") or "")
        p = bool(v.get("pinned"))
        if p and not pinned_seen:
            pinned_seen = True
            v["pinned"] = True
        else:
            v["pinned"] = False
    return {"qid": str(d.get("qid") or ""), "kb": str(d.get("kb") or ""),
            "chap": str(d.get("chap") or ""), "versions": vs}


def list_solutions(ws) -> list[dict]:
    out = []
    for f in sorted(solutions_dir(ws).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict):
            d.setdefault("qid", f.stem)
            out.append(d)
    return out


def save_solutions(ws, qid: str, data: dict) -> dict:
    p = _path(ws, qid)
    if not p:
        return {"ok": False, "error": "题目 id 非法（1..120 字符，不含路径分隔符）"}
    payload = _normalize({**data, "qid": str(qid)})
    from ..filelock import atomic_write_text
    atomic_write_text(p, json.dumps(payload, ensure_ascii=False, indent=1))
    return {"ok": True, "solutions": payload, "file": str(p)}


def add_version(ws, qid: str, text: str, *, source: str = "ai", model: str = "",
                kb: str = "", chap: str = "", pin: bool = False) -> dict:
    """追加一版（不可覆盖）。AI 作答默认 pin=False（不抢答案）；人可随后 pin。"""
    if not str(text or "").strip():
        return {"ok": False, "error": "答案内容为空"}
    path = _path(ws, qid)
    if not path:
        return {"ok": False, "error": "题目 id 非法（1..120 字符，不含路径分隔符）"}
    # AI 批量作答可能并行写同一题：整段读-改-写锁内，避免版本号撞车/丢版本。
    from ..filelock import locked
    with locked(path):
        cur = read_solutions(ws, qid) or {"qid": str(qid), "kb": kb, "chap": chap, "versions": []}
        cur.setdefault("versions", [])
        vid = _next_version_id(cur["versions"])
        entry = {"id": vid, "text": str(text), "source": str(source or "ai"),
                 "model": str(model or ""), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "pinned": bool(pin)}
        if pin:
            for v in cur["versions"]:
                v["pinned"] = False
        cur["versions"].append(entry)
        if kb and not cur.get("kb"):
            cur["kb"] = kb
        if chap and not cur.get("chap"):
            cur["chap"] = chap
        res = save_solutions(ws, qid, cur)
    if res.get("ok"):
        res["added"] = entry
    return res


def pin_version(ws, qid: str, version_id: str) -> dict:
    path = _path(ws, qid)
    if not path:
        return {"ok": False, "error": "题目 id 非法"}
    from ..filelock import locked
    with locked(path):
        cur = read_solutions(ws, qid)
        if not cur:
            return {"ok": False, "error": f"题目无版本库：{qid}"}
        found = False
        for v in cur.get("versions", []):
            want = str(v.get("id")) == str(version_id)
            v["pinned"] = want
            found = found or want
        if not found:
            return {"ok": False, "error": f"版本不存在：{version_id}"}
        return save_solutions(ws, qid, cur)


def remove_version(ws, qid: str, version_id: str) -> dict:
    path = _path(ws, qid)
    if not path:
        return {"ok": False, "error": "题目 id 非法"}
    from ..filelock import locked
    with locked(path):
        cur = read_solutions(ws, qid)
        if not cur:
            return {"ok": False, "error": f"题目无版本库：{qid}"}
        before = len(cur.get("versions", []))
        cur["versions"] = [v for v in cur.get("versions", []) if str(v.get("id")) != str(version_id)]
        if len(cur["versions"]) == before:
            return {"ok": False, "error": f"版本不存在：{version_id}"}
        return save_solutions(ws, qid, cur)


def effective_solution(ws, qid: str, fallback: str = "") -> dict:
    """生效答案（实时读）：pinned 版 > 最新版 > xlsx fallback（旧数据兼容）。

    返回 {text, source, model, at, version, from}（from ∈ pinned|latest|fallback|xlsx）。
    """
    cur = read_solutions(ws, qid)
    if cur and cur.get("versions"):
        for v in cur["versions"]:
            if v.get("pinned"):
                return {"text": str(v.get("text") or ""), "source": str(v.get("source") or ""),
                        "model": str(v.get("model") or ""), "at": str(v.get("at") or ""),
                        "version": str(v.get("id") or ""), "from": "pinned"}
        v = cur["versions"][-1]
        return {"text": str(v.get("text") or ""), "source": str(v.get("source") or ""),
                "model": str(v.get("model") or ""), "at": str(v.get("at") or ""),
                "version": str(v.get("id") or ""), "from": "latest"}
    if str(fallback or "").strip():
        return {"text": str(fallback), "source": "", "model": "", "at": "",
                "version": "", "from": "fallback"}
    return {"text": "", "source": "", "model": "", "at": "", "version": "", "from": "xlsx"}
