"""D98-B3：`type=command` provider —— 回环调用外部 agent CLI（无 API key 场景）。

设计（docs/51 §7.3）：
- 通用契约：**stdin 收 JSON、stdout 出 JSON**（也支持 `output_mode="stdout-text"`）；
- **每次调用起新子进程** → 天然隔离，不存在上一名学生上下文串入；
- 图片：优先**写临时文件传路径**（`images` 字段），agent 不支持路径时由调用方回退 base64；
- 模型可换：`--model`/item.model 缺省则**不传**（用 agent 当前模型）；
- 单条失败只标记该条，不阻断其余（由批处理层收集）。
- 安全：命令只来自 workspace 配置，绝不来自网络输入。

stdin JSON 形状（固定契约）：
    {"id": "...", "prompt": "...", "system": "...", "model": "...",
     "images": ["/abs/a.png", "/abs/b.png"], "temperature": 0.2, "max_tokens": 8192}

stdout 期望（output_mode=stdout-json，任一即可）：
    {"text": "..."}                      # 最常见
    {"choices":[{"message":{"content":"..."}}]}   # OpenAI 兼容
    {"content": "..."}
  stdout-text：整段 stdout 即文本。
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from loguru import logger


class CommandProviderError(RuntimeError):
    """command provider 调用失败（带可读诊断，不含敏感信息）。"""


def build_payload(*, item_id: str, prompt: str, system: str = "", model: str = "",
                  images: "list[str] | None" = None, temperature: float = 0.2,
                  max_tokens: int = 8192) -> dict:
    """构造 stdin 契约 JSON（只含本条 item 的内容——结构性隔离）。"""
    return {
        "id": str(item_id),
        "prompt": str(prompt),
        "system": str(system or ""),
        "model": str(model or ""),
        "images": [str(p) for p in (images or [])],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }


def _parse_stdout(text: str, output_mode: str) -> str:
    if output_mode == "stdout-text":
        return text.strip()
    try:
        data = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        raise CommandProviderError(f"stdout 不是 JSON：{str(exc)[:120]}；前 200 字：{text[:200]!r}")
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ("text", "content", "answer", "output"):
            if isinstance(data.get(key), str) and data[key].strip():
                return data[key]
        ch = data.get("choices")
        if isinstance(ch, list) and ch and isinstance(ch[0], dict):
            msg = ch[0].get("message") or {}
            if isinstance(msg.get("content"), str):
                return msg["content"]
            if isinstance(ch[0].get("text"), str):
                return ch[0]["text"]
    raise CommandProviderError(f"stdout JSON 未找到文本字段；keys={list(data)[:8] if isinstance(data, dict) else type(data).__name__}")


def run_command(prov: dict, payload: dict) -> dict:
    """执行一次 command provider 调用。返回 {ok, text, error, ms, exitCode, stderr}。

    - 超时/非零退出/解析失败 → ok=False + 可读 error（不抛，交给上层标记该条失败）；
    - 绝不把 stdin 内容写日志（可能含学生作答）。
    """
    cmd = [str(x) for x in (prov.get("cmd") or [])]
    if not cmd:
        return {"ok": False, "error": "provider 未配置 cmd", "text": ""}
    # 模型占位替换：{model}（缺省不传 → 用 agent 当前模型）
    model = str(payload.get("model") or "")
    argv = [a.replace("{model}", model) for a in cmd]
    if not model:
        # 去掉只由 {model} 构成的参数（避免传空模型名）
        argv = [a for a in argv if a.strip()]

    timeout_s = int(prov.get("timeout_s") or 300)
    output_mode = str(prov.get("output_mode") or "stdout-json")
    t0 = time.time()
    try:
        cp = subprocess.run(
            argv, input=json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, timeout=timeout_s, encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"调用超时（{timeout_s}s）", "text": "",
                "ms": int((time.time() - t0) * 1000)}
    except FileNotFoundError:
        return {"ok": False, "error": f"命令不存在：{argv[0]}（检查 PATH 或 provider.cmd）",
                "text": "", "ms": int((time.time() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"执行异常：{exc.__class__.__name__}: {str(exc)[:160]}",
                "text": "", "ms": int((time.time() - t0) * 1000)}
    ms = int((time.time() - t0) * 1000)
    if cp.returncode != 0:
        return {"ok": False, "text": "", "exitCode": cp.returncode,
                "error": f"命令退出码 {cp.returncode}：{(cp.stderr or '')[:300]}", "ms": ms}
    try:
        text = _parse_stdout(cp.stdout or "", output_mode)
    except CommandProviderError as exc:
        return {"ok": False, "error": str(exc), "text": "", "ms": ms}
    if not text:
        return {"ok": False, "error": "命令返回空文本", "text": "", "ms": ms}
    # 可选 usage（适配器可回 {"text":..., "usage":{prompt_tokens,completion_tokens}}）
    usage = {}
    try:
        parsed = json.loads(cp.stdout or "{}")
        if isinstance(parsed, dict) and isinstance(parsed.get("usage"), dict):
            u = parsed["usage"]
            usage = {k: int(u.get(k) or 0) for k in ("prompt_tokens", "completion_tokens")}
    except Exception:  # noqa: BLE001
        usage = {}
    return {"ok": True, "text": text, "ms": ms, "exitCode": 0, "usage": usage}
