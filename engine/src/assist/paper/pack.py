"""D127：作业包上下文（pack context）—— **唯一**“包内按 tag 取作业纸”入口。

背景：此前四套取题逻辑各写各的（整班预览 / 作业纸生成 / 变体 zip / 批阅 plan），
且都从**全库已保存作业纸**按 tag 反推 → 同一 tag 存在于多个批次时会串到别的作业。
D127 决策：**作业包是唯一作业批次载体**（单张作业纸也必须属于某个包），
任何“该生用哪张作业纸”的判断都必须限定在**当前包内**。
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger


def _norm_tag(t: str) -> str:
    """tag 归一：去空白、全角转半角、统一小写（防止 'QA ' / 'qa' / 'ｑａ' 互不匹配）。"""
    s = str(t or "").strip()
    if not s:
        return ""
    out = []
    for ch in s:
        code = ord(ch)
        # 全角 ASCII → 半角
        if 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out).strip().lower()


def load_pad(ws, pad_id: str) -> "dict | None":
    """读单张作业纸（taskpad）。与 PWA 保存位置一致：`<ws>/tasks/<id>.taskpad.json`。"""
    pid = str(pad_id or "").strip()
    if not pid:
        return None
    root = Path(ws) / "tasks"
    for cand in (root / f"{pid}.taskpad.json", root / f"{pid}.json"):
        if cand.is_file():
            try:
                d = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    return d
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[pack] 读取作业纸失败 {cand}：{exc}")
    return None


def pad_tag_of(pad: dict) -> str:
    """作业纸归属 tag：target_tag 优先；items 唯一 tag 次之。"""
    direct = str((pad or {}).get("target_tag") or "").strip()
    if direct:
        return direct
    tags = sorted({str(it.get("tag")) for it in ((pad or {}).get("items") or [])
                   if isinstance(it, dict) and it.get("tag")})
    return tags[0] if len(tags) == 1 else ""


def pack_context(ws, pack: "dict | None", *, explicit_pads: "list[dict] | None" = None) -> dict:
    """构建包上下文。

    Args:
        ws: workspace 根。
        pack: 包定义 `{id, name, pads:[{padId, tag}]}`；可为 None（此时只用 explicit_pads）。
        explicit_pads: PWA 直接注入的作业纸 JSON 列表（优先于磁盘读取）。

    Returns:
        {
          "packId": str, "name": str,
          "pads": [{padId, tag, pad, items}],       # 按 tag 归一后的索引
          "by_tag": {norm_tag: entry},
          "dangling": [padId...],                    # 包内引用但找不到的作业纸
        }
    """
    pack = pack or {}
    pack_id = str(pack.get("id") or "")
    explicit = {}
    for p in (explicit_pads or []):
        if isinstance(p, dict) and p.get("id"):
            explicit[str(p["id"])] = p

    entries: list[dict] = []
    dangling: list[str] = []
    seen_tag: dict[str, str] = {}
    for ref in (pack.get("pads") or []):
        if not isinstance(ref, dict):
            continue
        pad_id = str(ref.get("padId") or ref.get("id") or "").strip()
        if not pad_id:
            continue
        pad = explicit.get(pad_id) or load_pad(ws, pad_id)
        if not isinstance(pad, dict):
            dangling.append(pad_id)
            continue
        # 包里的 tag 声明优先，其次作业纸自身
        tag = str(ref.get("tag") or "").strip() or pad_tag_of(pad)
        entries.append({"padId": pad_id, "tag": tag, "pad": pad,
                        "items": pad.get("items") or []})
        nt = _norm_tag(tag)
        if nt:
            if nt in seen_tag:
                logger.warning(f"[pack] tag「{tag}」在包内被多张作业纸占用"
                               f"（{seen_tag[nt]} / {pad_id}），取先出现的")
            else:
                seen_tag[nt] = pad_id
    # 未在包内登记、但 explicit 传入了的（PWA 兼容路径）：按自身 tag 兜底索引
    for pad_id, pad in explicit.items():
        if any(e["padId"] == pad_id for e in entries):
            continue
        tag = pad_tag_of(pad)
        nt = _norm_tag(tag)
        if nt and nt not in seen_tag:
            entries.append({"padId": pad_id, "tag": tag, "pad": pad,
                            "items": pad.get("items") or []})
            seen_tag[nt] = pad_id

    by_tag = {(_norm_tag(e["tag"])): e for e in entries if _norm_tag(e["tag"])}
    return {"packId": pack_id, "name": str(pack.get("name") or pack_id),
            "pads": entries, "by_tag": by_tag, "dangling": dangling}


def pick_pad_for_tag(ctx: dict, tag: str, *, fallback_pad_id: str = "") -> "dict | None":
    """在包内为该 tag 选作业纸。

    顺序：tag 精确（归一）→ 显式兜底作业纸（`--default` 语义）→ None。
    **绝不**回退到包外/全库的其他作业纸（D127 D3）。
    """
    nt = _norm_tag(tag)
    if nt:
        hit = (ctx.get("by_tag") or {}).get(nt)
        if hit:
            return hit
    fb = str(fallback_pad_id or "").strip()
    if fb:
        for e in (ctx.get("pads") or []):
            if str(e.get("padId")) == fb:
                return e
    return None


def tags_without_pad(ctx: dict, tags) -> list[str]:
    """返回包内**没有对应作业纸**的 tag 列表（用于前置预警，避免评阅时才发现）。"""
    have = set((ctx.get("by_tag") or {}).keys())
    return [str(t) for t in (tags or []) if _norm_tag(t) and _norm_tag(t) not in have]
