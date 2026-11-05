"""kb_examples.py — D168-B5：`example`（例题库）的导入与统计。

## 为什么需要例题库（docs/112-D168 §2.1）

教师原话：
> 从课程资料整理出来的知识点共现应该只限于从**例题**中得出，而大纲、ppt、授课计划
> 应该不支持这样的数据。这个从课程例题整理出来的知识点共现图其实是**标准图**，
> 反映的是授课过程的特点，而作业题的共现图反映的是学生作答情况。

→ 共现需要"同一道题/同一个例子涉及多个知识点"这个**结构**；
   大纲/授课计划只有清单，没有结构，画不出共现。
→ 所以必须先把**例题**抽出来，单独成库。

## 定位

| 项 | 说明 |
|---|---|
| kind 名 | `example` |
| 数据源 | Atopia `example-extract` 任务的产物 |
| 用途 | **只做分析**（标准共现图 / 自然聚类），**不布置、不批阅** |
| 表结构 | 与其它题库一致（id/content/solution/related/type/note），复用全部既有能力 |
"""
from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

KIND = "example"


class ExampleError(RuntimeError):
    """例题库操作失败（可读业务错误）。"""


def _kb_dir(ws) -> Path:
    return Path(ws).resolve() / "kb"


def _norm_terms(value) -> list[str]:
    """`knowledge` 字段 → 术语列表（兼容 str/list/None；字符串按分隔符拆）。"""
    import re
    if value is None:
        return []
    if isinstance(value, str):
        parts = [x.strip() for x in re.split(r"[,，、;；/|]+", value)]
        return [x for x in parts if x]
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for v in value:
            for t in _norm_terms(v):
                if t not in out:
                    out.append(t)
        return out
    t = str(value).strip()
    return [t] if t else []


def examples_from_parsed(parsed: dict, *, chap: str = "examples") -> "list[dict]":
    """把 `example-extract` 的解析产物转成题库条目。

    产物形如 `{"examples": [{content, solution, knowledge[], source}]}`；
    兼容 `knowledge` 写成字符串、缺 `solution` 等真实情况。
    """
    items = []
    for i, e in enumerate((parsed or {}).get("examples") or [], start=1):
        if not isinstance(e, dict):
            continue
        content = str(e.get("content") or "").strip()
        if not content:
            continue                       # 没题干 = 不是例题，跳过
        terms = _norm_terms(e.get("knowledge"))
        src = str(e.get("source") or "").strip()
        note_parts = []
        if src:
            note_parts.append(f"来源：{src}")
        items.append({
            "id": f"ex-{i:03d}",
            "content": content,
            "solution": str(e.get("solution") or "").strip(),
            "related": ",".join(terms),
            "type": KIND,
            "note": "；".join(note_parts),
            "img_path": "",
            "page": "",
        })
    return items


def import_examples(ws, parsed: dict, *, chap: str = "examples",
                    replace: bool = False) -> dict:
    """把例题写入 `kb/example.xlsx` 的某章（默认整章替换或追加）。

    - `replace=True`：整章替换（默认 False = 追加并自动续号）；
    - 写前**自动快照**（复用 kb_io.snapshot），可回滚；
    - **只写 `kb/`，不碰 `materials/`**。
    """
    from ..files import kb_io
    items = examples_from_parsed(parsed, chap=chap)
    if not items:
        return {"ok": False, "error": "解析产物里没有可用例题（缺 content）"}
    kb_dir = _kb_dir(ws)
    xlsx = kb_dir / f"{KIND}.xlsx"
    kb_dir.mkdir(parents=True, exist_ok=True)
    existing = {}
    if xlsx.is_file():
        try:
            existing = kb_io.read_xlsx(xlsx, kb_dir)
        except Exception as exc:  # noqa: BLE001
            raise ExampleError(f"读取现有例题库失败：{exc}") from None
    cur = [] if replace else list(existing.get(chap) or [])
    # 续号：避免与已有 id 撞车
    if cur:
        max_n = 0
        for e in cur:
            qid = str(e.get("id") or "")
            tail = qid.rsplit("-", 1)[-1]
            if tail.isdigit():
                max_n = max(max_n, int(tail))
        for it in items:
            max_n += 1
            it["id"] = f"ex-{max_n:03d}"
    existing[chap] = cur + items
    snap = kb_io.snapshot(kb_dir)
    kb_io.write_chapters_preserving(xlsx, existing)
    logger.info(f"[例题库] 写入 {len(items)} 条 → kb/{KIND}.xlsx（章 {chap}）")
    return {"ok": True, "kind": KIND, "chap": chap, "count": len(items),
            "total": len(existing[chap]), "path": str(xlsx),
            "snapshot": [str(x) for x in snap]}


def load_examples(ws) -> "dict[str, list[dict]]":
    """读例题库（不存在的返回空 dict，不抛异常）。"""
    from ..files import kb_io
    xlsx = _kb_dir(ws) / f"{KIND}.xlsx"
    if not xlsx.is_file():
        return {}
    try:
        return kb_io.read_xlsx(xlsx, _kb_dir(ws))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[例题库] 读取失败：{exc}")
        return {}


def examples_as_records(ws, *, vocab: dict | None = None) -> "list[dict]":
    """把例题库转成**共现算法认识的记录形状**，供标准共现图使用。

    共现算法（`cooccurrence.py`）吃的是 `evaluations` 记录：
        {student, tag, analysis:{questions:[{id, errors:[{knowledge[]}]}]}}
    例题的"涉及知识点"等价于"这道题出错的知识点"——两者在共现语义上同构
    （都是"同一题内出现的知识点集合"）。这里做一个**显式**的适配，
    并标注 `source="example"`，避免与"作答共现图"混淆。
    """
    data = load_examples(ws)
    records: list[dict] = []
    for chap, entries in (data or {}).items():
        for e in (entries or []):
            if not isinstance(e, dict):
                continue
            terms = _norm_terms(e.get("related"))
            if not terms:
                continue
            qid = str(e.get("id") or "")
            records.append({
                "student": f"{chap}:{qid}",     # 例题没有"学生"，用出处做 key
                "tag": "",                       # 标准图不按 tag 拆（不是学生数据）
                "source": "example",
                "analysis": {"questions": [{
                    "id": f"{chap}-{qid}",
                    "errors": [{"knowledge": [t], "confidence": "high"} for t in terms],
                }]},
            })
    return records


def summary(ws) -> dict:
    """例题库概览（供 PWA 显示"标准共现图数据源是否就绪"）。"""
    data = load_examples(ws)
    chaps = {c: len(v or []) for c, v in (data or {}).items()}
    total = sum(chaps.values())
    terms = set()
    for entries in (data or {}).values():
        for e in (entries or []):
            terms.update(_norm_terms(e.get("related")))
    return {"ok": True, "kind": KIND, "chapters": chaps, "count": total,
            "terms": len(terms),
            "ready": total >= 2,      # 少于 2 条画不出共现
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}
