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

# D110：题号在不同章节会重复（如 chap04/c1 与 chap05/c1），而答案文件原先只按 qid 命名，
# 导致两章的 c1 写进同一个 c1.json、互相覆盖/串答案。
# 现改为 `<kb>__<chap>__<qid>.json`（三段都做文件名安全化），并保留旧 `<qid>.json`
# 作为「无章节上下文」的兼容读取（旧数据/CLI 只给 qid 时仍可读）。
_SCOPE_SEP = "__"


def solutions_dir(ws) -> Path:
    d = Path(ws).resolve() / "kb" / SOLUTIONS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_qid(qid: str) -> str:
    q = str(qid or "").strip()
    if not q or q.strip(".") == "" or not _QID_RE.match(q):
        return ""
    return q


def _safe_part(v: str) -> str:
    """kb/chap 片段：去掉路径分隔符与 _SCOPE_SEP，避免拼出歧义文件名。"""
    t = str(v or "").strip()
    if not t:
        return ""
    t = re.sub(r"[\\/]", "-", t)
    while _SCOPE_SEP in t:
        t = t.replace(_SCOPE_SEP, "_")
    return t.strip(".") if t.strip(".") else ""


def scope_id(kb: str = "", chap: str = "", qid: str = "") -> str:
    """把 (kb, chap, qid) 归一成一个「作用域 id」。

    - 有 kb+chap：`kb__chap__qid`（唯一，避免跨章撞名）；
    - 缺 chap 但有 kb：`kb__qid`；
    - 都没有：`qid`（旧兼容）。
    """
    q = _safe_qid(qid)
    if not q:
        return ""
    k, c = _safe_part(kb), _safe_part(chap)
    if k and c:
        return f"{k}{_SCOPE_SEP}{c}{_SCOPE_SEP}{q}"
    if k:
        return f"{k}{_SCOPE_SEP}{q}"
    return q


def _path(ws, qid: str, kb: str = "", chap: str = "") -> "Path | None":
    sid = scope_id(kb, chap, qid)
    return solutions_dir(ws) / f"{sid}.json" if sid else None


def _candidate_paths(ws, qid: str, kb: str = "", chap: str = "") -> list[Path]:
    """读取时按优先级返回候选文件：精确作用域 → 只带 kb → 旧 qid。"""
    out: list[Path] = []
    for sid in (scope_id(kb, chap, qid), scope_id(kb, "", qid), scope_id("", "", qid)):
        if not sid:
            continue
        p = solutions_dir(ws) / f"{sid}.json"
        if p not in out:
            out.append(p)
    return out


def _mark_migrated(legacy: Path, target: Path) -> None:
    """把旧文件标记为已迁移到 target（保留内容以便回滚，但读取时跳过）。"""
    try:
        d = json.loads(legacy.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return
        d["migratedTo"] = str(target)
        from ..filelock import atomic_write_text
        atomic_write_text(legacy, json.dumps(d, ensure_ascii=False, indent=1))
        logger.info(f"答案版本库已迁移：{legacy.name} → {target.name}")
    except Exception:  # noqa: BLE001
        pass


def read_solutions(ws, qid: str, kb: str = "", chap: str = "") -> "dict | None":
    """读取某题的版本库。

    D110：先找「精确作用域」文件（kb__chap__qid），再回落 kb__qid / 旧 qid.json。
    """
    for p in _candidate_paths(ws, qid, kb, chap):
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and not d.get("migratedTo"):
            return d
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


def save_solutions(ws, qid: str, data: dict, kb: str = "", chap: str = "") -> dict:
    kb = str(kb or data.get("kb") or "")
    chap = str(chap or data.get("chap") or "")
    p = _path(ws, qid, kb, chap)
    if not p:
        return {"ok": False, "error": "题目 id 非法（1..120 字符，不含路径分隔符）"}
    payload = _normalize({**data, "qid": str(qid)})
    from ..filelock import atomic_write_text
    atomic_write_text(p, json.dumps(payload, ensure_ascii=False, indent=1))
    return {"ok": True, "solutions": payload, "file": str(p),
            "scope": scope_id(kb, chap, qid)}


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
    path = _path(ws, qid, kb, chap)
    if not path:
        return {"ok": False, "error": "题目 id 非法（1..120 字符，不含路径分隔符）"}
    # AI 批量作答可能并行写同一题：整段读-改-写锁内，避免版本号撞车/丢版本。
    from ..filelock import locked
    with locked(path):
        cur = read_solutions(ws, qid, kb, chap) or {"qid": str(qid), "kb": kb, "chap": chap, "versions": []}
        # D110：若命中的是**旧的无章节文件**（或上一级 kb-only 文件），本次写入会落到
        # 更精确的作用域文件。此时把旧文件标记为「已迁移」，避免它继续作为
        # 其它章节的兜底答案被读到（那正是"跨章答案相同"的成因之一）。
        legacy = next((p for p in _candidate_paths(ws, qid, kb, chap)
                       if p.is_file() and p != path), None)
        if legacy is not None and (kb or chap):
            _mark_migrated(legacy, path)
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
        # D110：kb/chap 为准入参数（作答时已知上下文），不再"仅当为空才写"——
        # 否则旧文件里残留的 chap 会让跨章写入串味。
        if kb:
            cur["kb"] = kb
        if chap:
            cur["chap"] = chap
        res = save_solutions(ws, qid, cur, kb=kb, chap=chap)
    if res.get("ok"):
        res["added"] = entry
    return res


def pin_version(ws, qid: str, version_id: str, kb: str = "", chap: str = "") -> dict:
    path = _path(ws, qid, kb, chap)
    if not path:
        return {"ok": False, "error": "题目 id 非法"}
    from ..filelock import locked
    with locked(path):
        cur = read_solutions(ws, qid, kb, chap)
        if not cur:
            return {"ok": False, "error": f"题目无版本库：{qid}"}
        found = False
        for v in cur.get("versions", []):
            want = str(v.get("id")) == str(version_id)
            v["pinned"] = want
            found = found or want
        if not found:
            return {"ok": False, "error": f"版本不存在：{version_id}"}
        return save_solutions(ws, qid, cur, kb=kb, chap=chap)


def remove_version(ws, qid: str, version_id: str, kb: str = "", chap: str = "") -> dict:
    path = _path(ws, qid, kb, chap)
    if not path:
        return {"ok": False, "error": "题目 id 非法"}
    from ..filelock import locked
    with locked(path):
        cur = read_solutions(ws, qid, kb, chap)
        if not cur:
            return {"ok": False, "error": f"题目无版本库：{qid}"}
        before = len(cur.get("versions", []))
        cur["versions"] = [v for v in cur.get("versions", []) if str(v.get("id")) != str(version_id)]
        if len(cur["versions"]) == before:
            return {"ok": False, "error": f"版本不存在：{version_id}"}
        return save_solutions(ws, qid, cur, kb=kb, chap=chap)


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


def effective_solution(ws, qid: str, fallback: str = "",
                       kb: str = "", chap: str = "") -> dict:
    """生效答案（实时读）：pinned 版 > 最新版 > xlsx fallback（旧数据兼容）。

    D110：`kb`/`chap` 用于消除跨章同号（chap04/c1 vs chap05/c1）；
    不传则回落旧行为（只按 qid 找 `<qid>.json`）。

    返回 {text, source, model, at, version, from, n_versions, ai_versions}
    （from ∈ pinned|latest|fallback|xlsx）。
    """
    return _effective_of(read_solutions(ws, qid, kb, chap), fallback)


def effective_map(ws) -> dict:
    """**批量**生效答案索引（无 fallback），按 qid 索引（向后兼容旧前端）。

    D110：同一 qid 出现在多章时，只有第一条保留答案内容，其余标记
    `ambiguous=True`，避免前端把 A 章的答案显示到 B 章。
    需要精确定位请用 `effective_by_key()`。
    """
    by_qid: dict = {}
    for eff in effective_by_key(ws).values():
        qid = eff["qid"]
        if qid in by_qid:
            by_qid[qid] = {**by_qid[qid], "ambiguous": True}
            continue
        by_qid[qid] = eff
    return by_qid


def effective_by_key(ws) -> dict:
    """D110：精确索引 `{"kb__chap__qid": eff}`（PWA/CLI 按章节取答案的首选）。"""
    out: dict = {}
    for d in list_solutions(ws):
        qid = str(d.get("qid") or "").strip()
        if not qid:
            continue
        eff = _effective_of(d)
        if not str(eff.get("text") or "").strip():
            continue
        eff["id"] = eff.get("version") or ""
        eff["qid"] = qid
        eff["kb"] = str(d.get("kb") or "")
        eff["chap"] = str(d.get("chap") or "")
        out[scope_id(eff["kb"], eff["chap"], qid)] = eff
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
