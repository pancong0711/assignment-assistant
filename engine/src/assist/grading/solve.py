"""D89-N5：题库 AI 作答 —— 对题库题目生成参考答案，写入 kb/solutions/<qid>.json。

定位（docs/42-D89）：**不是批阅**；输入=题库题目（章节+ids 或整章），输出=AI 解答文本。
- **不覆盖**原答案：每次作答经 solutions.add_version 追加一版；
- 版本带 source="ai" + model + at 时间戳（便于长期维护/多版本对照）；
- 默认**不置顶**（不抢占生效答案）；可 --pin 显式置顶；
- 默认 dry-run：只打印将作答的题目与提示，不调 LLM（--submit/--apply 才真跑）。
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from ..files import solutions as sol

SOLVE_SYSTEM_PROMPT = """你是一位大学物理助教。请对给定题目给出**规范、完整**的参考解答。

要求：
1. 先简述物理过程与所用原理，再逐步推导，最后给出结论；
2. 数学公式用 LaTeX：行内 $...$、行间 $$...$$；
3. 计算题给出最终数值时注明单位与有效数字；
4. 若题目信息不足，指出缺少的条件并给出在合理假设下的解法；
5. 只输出解答正文（Markdown），不要寒暄、不要重复题干。"""


def build_question_prompt(content: str, related: str = "", qtype: str = "") -> str:
    parts = [f"题目：{content}"]
    if qtype:
        parts.append(f"题型：{qtype}")
    if related:
        parts.append(f"关联知识点：{related}")
    return "\n".join(parts)


def list_targets(ws: Path, kb: str, chap: str = "", ids: "list[str] | None" = None) -> list[dict]:
    """从题库取待作答题目：[{id, content, related, type, chap, kb}]。"""
    from ..files.kb_io import read_kb
    kb_data = read_kb(Path(ws) / "kb")
    chapters = kb_data.get(kb, {})
    want = {str(i) for i in (ids or [])}
    out: list[dict] = []
    chaps = {chap: chapters.get(chap, [])} if chap else chapters
    for cname, entries in chaps.items():
        for e in entries:
            qid = str(e.get("id") or "")
            if not qid or (want and qid not in want):
                continue
            out.append({"id": qid, "content": str(e.get("content") or ""),
                        "related": str(e.get("related") or ""), "type": str(e.get("type") or ""),
                        "chap": cname, "kb": kb})
    return out


def _client(ws: Path, model: str = ""):
    """按 D86 provider/两段式取「评阅段」endpoint 构造 LLMClient（key 只在内存）。"""
    from .llm import LLMClient
    from .providers import stage_endpoint
    ep = stage_endpoint(ws, "evaluation")
    # 透传端点全部字段（含 type/cmd），否则 command 型 provider 会退化成 api 调用。
    settings = {**ep, "model": model or ep.get("model") or ""}
    return LLMClient(settings=settings), (model or ep.get("model") or "")


def solve_targets(ws: Path, targets: list[dict], *, model: str = "", apply: bool = False,
                  pin: bool = False, dry_run: bool = True, concurrency: int = 3) -> dict:
    """对 targets AI 作答（D98：并发）；apply=False 只预览。返回 {ok, planned, written, results[]}。"""
    plans = [{"id": t["id"], "prompt": build_question_prompt(t.get("content", ""),
                                                             t.get("related", ""), t.get("type", "")),
              "kb": t.get("kb", ""), "chap": t.get("chap", "")} for t in targets]
    if dry_run and not apply:
        return {"ok": True, "dryRun": True, "planned": len(plans), "plans": plans}
    client, used_model = _client(ws, model)

    def _one(p: dict) -> dict:
        """单题作答（每调用独立请求）。"""
        try:
            text = client.chat(system_prompt=SOLVE_SYSTEM_PROMPT, user_text=p["prompt"],
                               step="evaluation")
            if apply:
                r = sol.add_version(ws, p["id"], text, source="ai", model=used_model,
                                    kb=p.get("kb", ""), chap=p.get("chap", ""), pin=pin)
                return {"id": p["id"], "ok": bool(r.get("ok")), "chars": len(text),
                        "model": used_model, "error": r.get("error")}
            return {"id": p["id"], "ok": True, "chars": len(text), "model": used_model}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"AI 作答失败 {p['id']}: {type(exc).__name__}")
            return {"id": p["id"], "ok": False, "error": str(exc)[:200]}

    # D98：并发（复用 batchrun 的受控线程池；单题失败不阻断其余）
    from .batchrun import run_items
    items = [{"id": p["id"]} for p in plans]
    by_id = {p["id"]: p for p in plans}
    report = run_items(items, lambda it: _one(by_id[it["id"]]),
                       kind="solve", concurrency=concurrency)
    # run_items 的条目：{id, status: ok|fail, ms, ...extra(含 _one 的 ok/chars/model/error)}
    results = []
    for it in report.get("items") or []:
        item = {k: v for k, v in it.items() if k not in ("status",)}
        item["ok"] = (it.get("status") == "ok")
        if it.get("status") != "ok" and not item.get("error"):
            item["error"] = it.get("error") or "failed"
        results.append(item)
    written = sum(1 for r in results if r.get("ok")) if apply else 0
    return {"ok": True, "model": used_model, "planned": len(plans),
            "written": written, "results": results, "concurrency": concurrency,
            "failed": report.get("failed", 0)}
