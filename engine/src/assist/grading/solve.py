"""D89-N5：题库 AI 作答 —— 对题库题目生成参考答案，写入 kb/solutions/<qid>.json。

定位（docs/42-D89）：**不是批阅**；输入=题库题目（章节+ids 或整章），输出=AI 解答文本。
- **不覆盖**原答案：每次作答经 solutions.add_version 追加一版；
- 版本带 source="ai" + model + at 时间戳（便于长期维护/多版本对照）；
- **默认置顶**（D100-T3：AI 重新生成即成为生效答案；旧版仍在版本库，可一键 pin 回）；
  需要"不抢答案"时显式 `--no-pin` / 请求体 `pin:false`；
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


def build_question_prompt(content: str, related: str = "", qtype: str = "",
                          extra_requirement: str = "") -> str:
    """构造单题 prompt。

    D104：`extra_requirement` = 教师在界面里填写的**作答要求**（可选），
    例如"请画出示意图""输出为 HTML 文档""用表格列出各步"。它被放在最后，
    并明确标注为"优先满足"，避免被系统提示里的默认风格盖过。
    """
    parts = [f"题目：{content}"]
    if qtype:
        parts.append(f"题型：{qtype}")
    if related:
        parts.append(f"关联知识点：{related}")
    req = str(extra_requirement or "").strip()
    if req:
        parts.append("\n教师额外作答要求（优先满足）：\n" + req)
    return "\n".join(parts)


def list_targets(ws: Path, kb: str, chap: str = "", ids: "list[str] | None" = None) -> list[dict]:
    """从题库取待作答题目：[{id, content, related, type, chap, kb}]。

    D110：`chap` 为空且 `ids` 为空 = **整个题库**（调用方务必先确认；
    CLI 要求 `--all`，serve 要求显式 `all: true`）。
    """
    from ..files.kb_io import read_kb
    kb_data = read_kb(Path(ws) / "kb")
    chapters = kb_data.get(kb, {})
    from ..paper.task import item_id_matches
    want = [str(i) for i in (ids or [])]
    out: list[dict] = []
    chaps = {chap: chapters.get(chap, [])} if chap else chapters
    for cname, entries in chaps.items():
        for e in entries:
            qid = str(e.get("id") or "")
            # D111：ids 可能是裸题号或全局 id
            if not qid or (want and not item_id_matches(str(cname), want, qid)):
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
                  pin: bool = True, dry_run: bool = True, concurrency: int = 3,
                  requirement: str = "", with_rubric: bool = False,
                  tag_knowledge: bool = False) -> dict:
    """对 targets AI 作答（D98：并发）；apply=False 只预览。返回 {ok, planned, written, results[]}。

    D100-T3：`pin=True`（默认）= 作答后置顶为新生效答案（"AI 生成内容默认置顶"）；
    传 False 则只追加版本（等价旧行为，不抢原答案）。

    D152：`tag_knowledge=True`（需同时 with_rubric）→ 把 AI 产出的 `knowledge[]`
    汇总后写回题库（`rubric.apply_related`，走 `kb/knowledge/`，改前自动快照）。

    D133：`with_rubric=True` → 一次产出「参考解答 + 评阅要点 + 知识点」，
    写入答案版本库（走 `rubric.build_rubric_prompt`，**带该题型规则摘要**）。
    要点与解答**同源同次生成**，避免"答案一套口径、要点另一套口径"。
    注意：要点未经教师确认，按 D130 验收 5 **默认不置顶**；
    是否置顶仍由 `pin` 决定，因此 CLI/serve 在 with_rubric 时应显式传 `pin=False`
    （除非教师明确要求"生成即生效"）。
    """
    plans = [{"id": t["id"], "prompt": build_question_prompt(t.get("content", ""),
                                                             t.get("related", ""), t.get("type", ""),
                                                             requirement),
              "content": t.get("content", ""), "related": t.get("related", ""),
              "kb": t.get("kb", ""), "chap": t.get("chap", "")} for t in targets]
    if dry_run and not apply:
        return {"ok": True, "dryRun": True, "planned": len(plans), "plans": plans,
                "withRubric": bool(with_rubric)}
    client, used_model = _client(ws, model)

    def _one(p: dict) -> dict:
        """单题作答（每调用独立请求）。

        D141：**每题一个 client（= 一个对话/一个 session）**。
        此前整批共用一个 `client`，导致：
        - 所有题的请求挤在同一个 `x-opencode-session` 下（路由把无关题归成一坨）；
        - 并发线程会争抢修改 `client.session_id`（共享可变状态，线程不安全）。
        `_client()` 只是读配置构造对象，开销可忽略。
        """
        try:
            cli = client
            try:
                cli, _m = _client(ws, model)
                if used_model:
                    cli.set_session_id(f"solve-{p['id']}")
            except Exception:  # noqa: BLE001 —— 构造失败时退回共享 client（旧行为）
                cli = client
            if with_rubric:
                # D133：一次调用产出「解答 + 要点 + 知识点」（带题型规则摘要）
                from . import rubric as RB
                rub = RB.generate_rubric(
                    cli, ws=ws, kind=str(p.get("kb") or "problems"),
                    content=str(p.get("content") or ""),
                    related=str(p.get("related") or ""), model=model or None)
                text = RB.rubric_to_text(rub)
                if not text.strip():
                    return {"id": p["id"], "ok": False, "error": "模型未给出参考解答/要点"}
                points = len([x for x in (rub.get("rubric_points") or [])
                              if isinstance(x, dict)])
                if apply:
                    # D133：要点版**默认不置顶**（未经教师确认，见 D130 验收 5）。
                    # 置顶与否完全由调用方的 `pin` 决定——调用方不传 pin=False 就置顶，
                    # 所以 CLI/serve 在 with_rubric 时必须显式传 pin=False（默认）。
                    r = sol.add_version(ws, p["id"], text, source="ai", model=used_model,
                                        kb=p.get("kb", ""), chap=p.get("chap", ""),
                                        pin=bool(pin))
                    return {"id": p["id"], "ok": bool(r.get("ok")), "chars": len(text),
                            "model": used_model, "withRubric": True,
                            "rubricPoints": points, "pinned": bool(pin),
                            "error": r.get("error")}
                return {"id": p["id"], "ok": True, "chars": len(text),
                        "model": used_model, "withRubric": True, "rubricPoints": points,
                        "knowledge": [str(x) for x in (rub.get("knowledge") or [])],
                        "kb": p.get("kb", ""), "chap": p.get("chap", "")}
            # D151：作答 system prompt 可用模板覆盖（不选模板 = 内置）
            from ..files.prompts import system_prompt as _sp
            _sys = _sp(ws, "solve", SOLVE_SYSTEM_PROMPT)
            text = cli.chat(system_prompt=_sys, user_text=p["prompt"],
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
    # D152：把 AI 产出的知识点写回题库（仅当 with_rubric + apply + tag_knowledge）
    knowledge_written = None
    if with_rubric and apply and tag_knowledge:
        try:
            from . import rubric as RB
            ups = []
            for r in results:
                if not r.get("ok"):
                    continue
                terms = [str(x).strip() for x in (r.get("knowledge") or [])
                         if str(x).strip()]
                if not terms:
                    continue
                ups.append({"kb": str(r.get("kb") or ""),
                            "chap": str(r.get("chap") or ""),
                            "qid": str(r.get("id") or ""),
                            "related": "，".join(terms),
                            "meta": {"source": "ai", "ai_suggested": "，".join(terms),
                                     "pinned_by": ""}})
            knowledge_written = RB.apply_related(ws, ups) if ups else {"ok": True, "written": 0}
        except Exception as exc:  # noqa: BLE001 —— 标注失败不影响作答结果
            logger.warning(f"[AI 作答] 知识点写回失败：{exc}")
            knowledge_written = {"ok": False, "error": str(exc)[:200]}
    return {"ok": True, "model": used_model, "planned": len(plans),
            "written": written, "results": results, "concurrency": concurrency,
            "failed": report.get("failed", 0),
            "knowledgeWritten": knowledge_written}
