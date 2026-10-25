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


def _to_plain(text: str) -> str:
    """md+html → 纯文本（复用 richdoc 的同一实现；失败则退化为去标签）。"""
    try:
        from ..paper.richdoc import strip_markup
        return strip_markup(text, limit=200)
    except Exception:  # noqa: BLE001
        import re
        return re.sub(r"<[^>]+>", "", str(text or ""))[:200]


def _normalize(d: dict) -> dict:
    d = d if isinstance(d, dict) else {}
    vs = [v for v in (d.get("versions") or []) if isinstance(v, dict) and str(v.get("text") or "").strip()]
    # 保证至多一个 pinned：取第一个 pinned 为准
    pinned_seen = False
    for v in vs:
        v["source"] = str(v.get("source") or "human")
        v["text"] = str(v.get("text") or "")
        # D105：text_plain = 纯文本派生（检索/摘要/xlsx solution 列）；
        # 显式传入则尊重（允许人工覆盖），否则由 text 现算。
        v["text_plain"] = str(v.get("text_plain") or "") or _to_plain(v["text"])
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
                kb: str = "", chap: str = "", pin: bool = False,
                pin_if_unpinned: bool = False) -> dict:
    """追加一版（不可覆盖）。默认 pin=False（不抢答案）；人可随后 pin。

    D100-T3：`pin_if_unpinned=True` = 「AI 作答默认成为生效答案」——仅当版本库
    **当前没有任何 pinned 版**时才自动置顶（等价"第一个答案即是答案"）。
    调用方（`solve_targets`）已改为显式 `pin=True`，本参数保留给"保守置顶"场景。
    """
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
        if pin_if_unpinned and not any(v.get("pinned") for v in cur["versions"]):
            pin = True
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


def _effective_of(doc: "dict | None", fallback: str = "") -> dict:
    """版本库文档 → 生效答案（纯函数，供单题/批量共用）。"""
    if doc and doc.get("versions"):
        chosen, frm = None, "latest"
        for v in doc["versions"]:
            if v.get("pinned"):
                chosen, frm = v, "pinned"
                break
        if chosen is None:
            chosen = doc["versions"][-1]
        return {"text": str(chosen.get("text") or ""),
                "text_plain": str(chosen.get("text_plain") or "") or _to_plain(chosen.get("text") or ""),
                "source": str(chosen.get("source") or ""),
                "model": str(chosen.get("model") or ""), "at": str(chosen.get("at") or ""),
                "version": str(chosen.get("id") or ""), "from": frm,
                "n_versions": len(doc["versions"]),
                "ai_versions": sum(1 for v in doc["versions"] if v.get("source") == "ai")}
    if str(fallback or "").strip():
        return {"text": str(fallback), "text_plain": str(fallback), "source": "", "model": "",
                "at": "", "version": "", "from": "fallback", "n_versions": 0, "ai_versions": 0}
    return {"text": "", "text_plain": "", "source": "", "model": "", "at": "", "version": "",
            "from": "xlsx", "n_versions": 0, "ai_versions": 0}


def effective_solution(ws, qid: str, fallback: str = "") -> dict:
    """生效答案（实时读）：pinned 版 > 最新版 > xlsx fallback（旧数据兼容）。

    返回 {text, source, model, at, version, from, n_versions, ai_versions}
    （from ∈ pinned|latest|fallback|xlsx）。
    """
    return _effective_of(read_solutions(ws, qid), fallback)


def effective_map(ws) -> dict:
    """**批量**生效答案索引：{qid: effective_solution(...)}（无 fallback）。

    D100-T1：供 PWA 一次拉全库（`GET /kb/solutions`）与 `assist sheet html` 出图共用，
    避免逐题读盘；语义与 `effective_solution` 逐条一致（同一 `_effective_of`）。
    """
    out: dict = {}
    for d in list_solutions(ws):
        qid = str(d.get("qid") or "").strip()
        if not qid:
            continue
        eff = _effective_of(d)
        if not str(eff.get("text") or "").strip():
            continue
        eff["id"] = eff.get("version") or ""
        out[qid] = eff
    return out


def solutions_digest(ws) -> float:
    """版本库最近修改时间（秒，无文件=0）——前端据此判断是否需要重拉索引。"""
    try:
        files = list(solutions_dir(ws).glob("*.json"))
    except OSError:
        return 0.0
    best = 0.0
    for f in files:
        try:
            best = max(best, f.stat().st_mtime)
        except OSError:
            continue
    return best
