"""agent.py — D132-T16：LLM function calling（含降级），**全部经过分级Gate**。

两条路径（docs/81 §6）：
1. **原生 tools**：provider 支持 OpenAI 兼容 `tools` / `tool_choice` → 直接暴露工具；
2. **降级 JSON 指令**：provider 不支持/报 400 → 要求模型输出
   `{"tool": "...", "args": {...}}`，我方解析后执行。

**安全关键**：降级路径**不比原生路径宽松**——两者最终都调
`runner.run_tool()`，因此 L3 拒绝、L2 二次确认、参数白名单、护栏全部照旧生效。
降级只是"模型怎么表达意图"不同，**不是**绕过审批的通道。
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from . import limits as L
from . import runner as RN
from .registry import (L2, L3, LEVEL_LABEL, ToolDenied, effective_tools,
                       level_at_least)

MAX_TURNS = 6

SYSTEM_PROMPT = """你是「Assistopia」工作区里的助手，可以调用本项目的工具帮教师做事。

可用工具（**只能用这些**，未列出的命令一律不许尝试）：
{tool_list}

调用规则（必须遵守）：
1. 每次只做一件事；需要多个工具时**一步一步**来，先看结果再决定下一步。
2. 写操作（L2）会**转交教师确认**，你无法自己批准——不要假装已经完成。
3. L3 危险工具**不开放**，不要尝试（迁移/删除/更新引擎等）。
4. 不要编造工具返回的内容；结果以工具真实输出为准。
5. 如果任务不需要工具，直接回答即可。

**输出格式（严格 JSON，二选一）**
- 要调用工具：{{"action": "tool", "tool": "<工具名>", "args": {{...}}, "why": "为什么调它"}}
- 要结束并回答：{{"action": "final", "answer": "给教师的答复"}}
不要输出其他任何内容。"""


def _tool_list_text(tools) -> str:
    lines = []
    for t in tools:
        args = ", ".join(f"{k}:{v}" for k, v in t.allowed_args.items()) or "无"
        lines.append(f"- {t.name} [{t.level} {LEVEL_LABEL[t.level]}] {t.summary}"
                     f"（参数：{args}）")
    return "\n".join(lines)


def _parse_json_reply(raw: str) -> "dict | None":
    """从模型回复里取出 JSON（容忍 ```json 包裹与前后废话）。"""
    s = str(raw or "").strip()
    if s.startswith("```"):
        s = s.split("```")[1] if "```" in s[3:] else s.lstrip("`")
        if s.lstrip().startswith("json"):
            s = s.lstrip()[4:]
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    i, j = s.find("{"), s.rfind("}")
    if 0 <= i < j:
        try:
            data = json.loads(s[i:j + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def run_session(client, ws, task: str, *, model: "str | None" = None,
                session: "L.Session | None" = None,
                confirm: "callable | None" = None,
                max_turns: int = MAX_TURNS) -> dict:
    """跑一次 Assistopia 会话。

    `confirm(tool_name, args)` → 返回确认来源字符串（空/None = 教师拒绝）。
    没有传 `confirm` 时，**L2 工具一律拒绝**（默认不批准）。
    """
    ws_p = Path(ws).resolve()
    sess = session or L.Session(session_id="agent", limits=L.read_limits(ws_p))
    tools = effective_tools(ws_p)
    usable = [t for t in tools if t.level != L3]
    tool_list = _tool_list_text(usable)
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(tool_list=tool_list)},
                {"role": "user", "content": str(task)}]
    steps: list[dict] = []

    for turn in range(max_turns):
        try:
            raw = client.chat(system_prompt=messages[0]["content"],
                              user_text=_transcript(messages), model=model,
                              temperature=0.1, max_tokens=2048, step="assistopia")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"模型调用失败：{str(exc)[:200]}",
                    "steps": steps}

        data = _parse_json_reply(raw)
        if data is None:
            # 模型没按格式给 JSON：当作最终回答（不猜测意图执行工具）
            steps.append({"turn": turn, "action": "final(unparsed)", "raw": str(raw)[:500]})
            return {"ok": True, "answer": str(raw or "").strip(),
                    "steps": steps, "note": "模型未按 JSON 格式回复，按最终回答处理"}

        action = str(data.get("action") or "").strip().lower()
        if action == "final":
            steps.append({"turn": turn, "action": "final"})
            return {"ok": True, "answer": str(data.get("answer") or ""), "steps": steps}

        tool_name = str(data.get("tool") or "").strip()
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        steps.append({"turn": turn, "action": "tool", "tool": tool_name, "args": args,
                      "why": str(data.get("why") or "")})

        # ---- 统一 Gate：与 CLI 走同一个 run_tool（降级路径不比原生宽松） ----
        try:
            t = next((x for x in tools if x.name == tool_name), None)
            if t is None:
                raise ToolDenied(f"模型请求了未登记的工具：{tool_name!r}（已拒绝）")
            confirmed_by = ""
            if t.level == L2:
                if confirm is None:
                    raise ToolDenied(
                        f"{tool_name} 属 L2 写入工具，需要教师确认，但本次会话没有确认通道")
                confirmed_by = str(confirm(tool_name, args) or "").strip()
                if not confirmed_by:
                    raise ToolDenied(f"教师未确认 {tool_name}，已跳过")
            rep = RN.run_tool(ws_p, tool_name, args, session=sess,
                              confirmed_by=confirmed_by)
            steps[-1].update({"ok": rep["ok"], "status": rep["status"],
                              "exit": rep["exit"], "ms": rep["ms"],
                              "out": _brief(rep["stdout"]),
                              "err": _brief(rep["stderr"])})
            messages.append({"role": "assistant",
                             "content": json.dumps({"action": "tool", "tool": tool_name,
                                                    "args": args}, ensure_ascii=False)})
            messages.append({"role": "user",
                             "content": "【工具结果】\n" + _brief(rep["stdout"] or rep["stderr"])})
        except ToolDenied as exc:
            steps[-1].update({"ok": False, "denied": True, "reason": str(exc)})
            logger.warning(f"[assistopia] 拒绝：{exc}")
            return {"ok": False, "error": str(exc), "steps": steps,
                    "answer": f"该操作被安全策略拒绝：{exc}"}
        except L.LimitExceeded as exc:
            steps[-1].update({"ok": False, "limit": True, "reason": str(exc)})
            return {"ok": False, "error": str(exc), "steps": steps}

    return {"ok": False, "error": f"超过最大轮数 {max_turns}，会话中止", "steps": steps}


def _transcript(messages: list[dict]) -> str:
    """把多轮上下文压成一段 user_text（chat 接口只有单轮 user_text）。"""
    out = []
    for m in messages[1:]:
        role = "助手" if m["role"] == "assistant" else "结果/要求"
        out.append(f"[{role}] {m['content']}")
    return "\n\n".join(out)


def _brief(text: str, n: int = 800) -> str:
    return str(text or "")[:n]
