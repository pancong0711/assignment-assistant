"""extensions.py — D132-T18：`<ws>/extensions/` 用户扩展（升级**永不触碰**）。

布局（docs/81 §5）：
    <ws>/extensions/
        tools/*.json            ← 工具级别（只能升不能降）
        rules/grading-rules.json← 覆盖内置评阅规则
        knowledge-terms.json    ← 覆盖受控词表

两条硬规则：
1. **升级流程不写、不删、不移动** `extensions/` 内任何文件（本模块只读）；
2. 工具级别只能**调高**（安全关键，见 registry.load_overrides）。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from loguru import logger

EXT = "extensions"


def root(ws) -> Path:
    return Path(ws).resolve() / EXT


def ensure(ws) -> Path:
    """创建扩展目录骨架（只新建，不覆盖已有内容）。"""
    r = root(ws)
    for sub in ("tools", "rules"):
        (r / sub).mkdir(parents=True, exist_ok=True)
    return r


def read_json_override(ws, rel: str) -> "dict | None":
    """读 `extensions/<rel>`；不存在/损坏返回 None（回落内置默认）。"""
    p = root(ws) / rel
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning(f"[atopia] 扩展 {rel} 顶层不是对象，已忽略")
            return None
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[atopia] 扩展 {rel} 解析失败，已忽略：{exc}")
        return None


# ---------------- 评阅规则覆盖 ----------------
RULES_REL = "rules/grading-rules.json"


def rules_override(ws) -> "dict | None":
    """`extensions/rules/grading-rules.json` → 覆盖当前 `<ws>/grading-rules.json`。

    语义：**深合并**（用户只写想改的字段），但 `types.<kind>.mode` 这类
    "算法名"不允许被扩展改（只读项，docs/78 §3.4）。
    """
    data = read_json_override(ws, RULES_REL)
    if data is None:
        return None
    cleaned = json.loads(json.dumps(data))
    for kind, cfg in list((cleaned.get("types") or {}).items()):
        if isinstance(cfg, dict) and "mode" in cfg:
            # 算法名是只读项（改了会让计分与提示词不一致）
            logger.warning(f"[atopia] 扩展不得修改 types.{kind}.mode，已忽略该字段")
            cfg.pop("mode", None)
    return cleaned


def effective_rules(ws) -> dict:
    """内置默认 ← 当前规则文件 ← `extensions/` 覆盖（深合并）。"""
    from ..grading import rules as R
    base = R.read_rules(ws)
    return effective_rules_from(ws, base)


def effective_rules_from(ws, base: dict) -> dict:
    """把 `extensions/` 覆盖叠加到**已读到的**规则上（供 rules.read_rules 复用，
    避免 read_rules → extensions → read_rules 的递归）。"""
    ov = rules_override(ws)
    if not ov:
        return base
    merged = json.loads(json.dumps(base))

    def deep(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                deep(dst[k], v)
            else:
                dst[k] = v

    deep(merged, ov)
    return merged


# ---------------- 词表覆盖 ----------------
VOCAB_REL = "knowledge-terms.json"


def vocab_override(ws) -> "dict | None":
    return read_json_override(ws, VOCAB_REL)


def effective_vocab(ws) -> dict:
    """内置（工作区词表）← `extensions/knowledge-terms.json`（按 term 合并，扩展优先）。"""
    from ..grading import vocab as V
    base = V.load_vocab(ws)
    ov = vocab_override(ws)
    if not ov or not isinstance(ov.get("terms"), list):
        return base
    by_term = {str(t.get("term")): t for t in (base.get("terms") or []) if t.get("term")}
    for t in ov["terms"]:
        if isinstance(t, dict) and t.get("term"):
            by_term[str(t["term"])] = t
    out = dict(base)
    out["terms"] = list(by_term.values())
    return out


# ---------------- 升级安全 ----------------
def snapshot(ws) -> dict:
    """记录 extensions/ 下所有文件（路径+大小+sha256），供升级前后比对。"""
    from ..files.materials import sha256_of
    r = root(ws)
    if not r.is_dir():
        return {}
    return {str(p.relative_to(r)).replace("\\", "/"): {"bytes": p.stat().st_size,
                                                      "sha256": sha256_of(p)}
            for p in sorted(r.rglob("*")) if p.is_file()}


def assert_untouched(before: dict, after: dict) -> "list[str]":
    """比对快照，返回被改动/删除的文件列表（空 = 升级未触碰扩展）。"""
    problems: list[str] = []
    for rel, meta in (before or {}).items():
        cur = (after or {}).get(rel)
        if cur is None:
            problems.append(f"被删除：{rel}")
        elif cur.get("sha256") != meta.get("sha256"):
            problems.append(f"被修改：{rel}")
    return problems
