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


SYSTEM_PROMPT_NATIVE = """你是「Atopia」工作区里的助手，可以调用本项目的工具帮教师做事。

可用工具（**只能用这些**，未列出的命令一律不许尝试）：
{tool_list}

调用规则（必须遵守）：
1. 每次只做一件事；需要多个工具时一步一步来，先看结果再决定下一步。
2. 写操作（L2）会**转交教师确认**，你无法自己批准——不要假装已经完成。
3. L3 危险工具**不开放**，不要尝试（迁移/删除/更新引擎等）。
4. 不要编造工具返回的内容；结果以工具真实输出为准。
5. 如果任务不需要工具，直接用自然语言回答即可。"""


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


def _ensure_session_id(client, prefix: str) -> str:
    """D136：给本次**会话**分配一个稳定的 session id（多轮复用同一个）。

    若调用方已设置（例如上层需要跨多次 run 复用），保持不动。
    """
    import uuid
    cur = str(getattr(client, "session_id", "") or "")
    if cur:
        return cur
    sid = f"{prefix}-{uuid.uuid4().hex[:16]}"
    try:
        client.set_session_id(sid)
    except Exception:  # noqa: BLE001 —— 老客户端/测试替身没有该方法
        pass
    return sid


def run_session(client, ws, task: str, *, model: "str | None" = None,
                session: "L.Session | None" = None,
                confirm: "callable | None" = None,
                max_turns: int = MAX_TURNS) -> dict:
    """跑一次 Assistopia 会话。

    `confirm(tool_name, args)` → 返回确认来源字符串（空/None = 教师拒绝）。
    没有传 `confirm` 时，**L2 工具一律拒绝**（默认不批准）。
    """
    ws_p = Path(ws).resolve()
    _ensure_session_id(client, "atopia")
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
                              temperature=0.1, max_tokens=2048, step="atopia")
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
            logger.warning(f"[atopia] 拒绝：{exc}")
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


# ---------------- D135：原生 tools 协议（OpenAI 兼容 function calling） ----------------
#
# 安全红线（与 JSON 指令协议**完全相同**）：
# 两条路径最终都调 `RN.run_tool()`，因此 L3 拒绝 / L2 必须教师确认 /
# 参数白名单 / 护栏全部照旧生效。**原生只是"模型怎么表达意图"更规范，
# 不是绕过审批的通道。**
def build_tools_payload(tools) -> list[dict]:
    """把工具清单转成 OpenAI 兼容 `tools`（参数用宽松 object，最终由本侧白名单校验）。

    注意：JSON Schema 只用来**告诉模型**有哪些参数，
    **不承担安全职责**——真正的参数校验在 `registry.validate_args()`。
    """
    out: list[dict] = []
    for t in tools:
        props = {}
        for name, kind in (t.allowed_args or {}).items():
            if kind == "int":
                props[name] = {"type": "integer"}
            else:
                props[name] = {"type": "string"}
        out.append({
            "type": "function",
            "function": {
                "name": t.name.replace(".", "__"),   # OpenAI 函数名不允许点号
                "description": f"[{t.level}] {t.summary}",
                "parameters": {"type": "object", "properties": props,
                               "required": list(props.keys()) if props else [],
                               "additionalProperties": False},
            },
        })
    return out


def _name_from_function(fn_name: str, tools) -> str:
    """函数名 → 工具 id（把 `__` 还原成 `.`；必须命中登记表，否则原样返回由 Gate 拒绝）。"""
    for t in tools:
        if t.name.replace(".", "__") == fn_name:
            return t.name
    cand = str(fn_name or "").replace("__", ".")
    return cand


def run_session_native(client, ws, task: str, *, model: "str | None" = None,
                       session: "L.Session | None" = None,
                       confirm: "callable | None" = None,
                       max_turns: int = MAX_TURNS) -> dict:
    """原生 tools 协议会话。

    返回结构与 `run_session()` 一致；provider 不支持 tools 时抛
    `LLMAPIError`，由 `run_session_auto()` 降级。
    """
    from .registry import L2

    ws_p = Path(ws).resolve()
    _ensure_session_id(client, "atopia")
    sess = session or L.Session(session_id="agent", limits=L.read_limits(ws_p))
    tools = effective_tools(ws_p)
    usable = [t for t in tools if t.level != L3]
    payload_tools = build_tools_payload(usable)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT_NATIVE.format(
            tool_list=_tool_list_text(usable))},
        {"role": "user", "content": str(task)},
    ]
    steps: list[dict] = []

    for turn in range(max_turns):
        data = client.chat_with_tools(messages, payload_tools, model=model,
                                      step="atopia")
        calls = client.tool_calls_of(data)
        if not calls:
            answer = ""
            try:
                answer = str(data["choices"][0]["message"].get("content") or "")
            except Exception:  # noqa: BLE001
                answer = ""
            steps.append({"turn": turn, "action": "final", "protocol": "native"})
            return {"ok": True, "answer": answer.strip(), "steps": steps,
                    "protocol": "native"}

        # 记录 assistant 的本轮 tool_calls（按协议原样回填，否则下一轮上下文不成立）
        messages.append(data["choices"][0]["message"])
        for call in calls:
            fn = call.get("function") or {}
            tool_name = _name_from_function(str(fn.get("name") or ""), tools)
            raw_args = fn.get("arguments")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            steps.append({"turn": turn, "action": "tool", "tool": tool_name,
                          "args": args, "protocol": "native"})
            # ---- 统一 Gate：与 CLI / JSON 指令协议走同一个 run_tool ----
            try:
                t = next((x for x in tools if x.name == tool_name), None)
                if t is None:
                    raise ToolDenied(f"模型请求了未登记的工具：{tool_name!r}（已拒绝）")
                confirmed_by = ""
                if t.level == L2:
                    if confirm is None:
                        raise ToolDenied(
                            f"{tool_name} 属 L2 写入工具，需要教师确认，"
                            f"但本次会话没有确认通道")
                    confirmed_by = str(confirm(tool_name, args) or "").strip()
                    if not confirmed_by:
                        raise ToolDenied(f"教师未确认 {tool_name}，已跳过")
                rep = RN.run_tool(ws_p, tool_name, args, session=sess,
                                  confirmed_by=confirmed_by)
                steps[-1].update({"ok": rep["ok"], "status": rep["status"],
                                  "exit": rep["exit"], "ms": rep["ms"],
                                  "out": _brief(rep["stdout"]),
                                  "err": _brief(rep["stderr"])})
                messages.append({
                    "role": "tool", "tool_call_id": str(call.get("id") or ""),
                    "content": _brief(rep["stdout"] or rep["stderr"] or "(无输出)"),
                })
            except ToolDenied as exc:
                steps[-1].update({"ok": False, "denied": True, "reason": str(exc)})
                logger.warning(f"[atopia] 拒绝：{exc}")
                return {"ok": False, "error": str(exc), "steps": steps,
                        "protocol": "native",
                        "answer": f"该操作被安全策略拒绝：{exc}"}
            except L.LimitExceeded as exc:
                steps[-1].update({"ok": False, "limit": True, "reason": str(exc)})
                return {"ok": False, "error": str(exc), "steps": steps,
                        "protocol": "native"}

    return {"ok": False, "error": f"超过最大轮数 {max_turns}，会话中止",
            "steps": steps, "protocol": "native"}


# 只在"确实是协议不支持"的信号上降级。**必须同时命中"工具相关"与"不支持"**，
# 否则 401/鉴权/网络等故障会被误当成"不支持 tools"而静默换协议——
# 那会把"配置错了"伪装成"换条路试试"，故障被掩盖、行为不可预期。
_TOOL_HINTS = ("tools", "tool_choice", "function calling", "function_call")
_UNSUPPORTED_HINTS = ("unsupported", "not supported", "does not support",
                      "unknown parameter", "unrecognized", "invalid_request_error",
                      "not implemented")
# 明确的"不是协议问题"信号：命中即**绝不**降级
_FATAL_HINTS = ("401", "403", "invalid api key", "authentication", "unauthorized",
                "insufficient", "quota", "timeout", "timed out", "connection")


def run_session_auto(client, ws, task: str, *, model: "str | None" = None,
                     session: "L.Session | None" = None,
                     confirm: "callable | None" = None,
                     max_turns: int = MAX_TURNS,
                     prefer: str = "native") -> dict:
    """先试原生 tools；provider 不支持时**自动降级**到 JSON 指令协议。

    降级判定只在"明显是协议不支持"的报错上做（`tools`/`function`/400 等），
    其它异常照常抛出——不能把网络/鉴权故障当成"不支持"而静默换协议。
    """
    from .limits import LimitExceeded

    if prefer == "json":
        rep = run_session(client, ws, task, model=model, session=session,
                          confirm=confirm, max_turns=max_turns)
        rep.setdefault("protocol", "json")
        return rep
    try:
        return run_session_native(client, ws, task, model=model, session=session,
                                  confirm=confirm, max_turns=max_turns)
    except LimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        fatal = any(h in msg for h in _FATAL_HINTS)
        looks_like_protocol = (any(h in msg for h in _TOOL_HINTS)
                               and any(h in msg for h in _UNSUPPORTED_HINTS))
        if fatal or not looks_like_protocol:
            raise
        logger.info(f"[atopia] 原生 tools 不受支持，降级 JSON 指令协议：{str(exc)[:160]}")
        rep = run_session(client, ws, task, model=model, session=session,
                          confirm=confirm, max_turns=max_turns)
        rep.setdefault("protocol", "json")
        rep["degraded"] = True
        rep["degradedReason"] = str(exc)[:200]
        return rep
