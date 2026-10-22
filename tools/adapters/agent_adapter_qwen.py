#!/usr/bin/env python3
"""assist `type=command` provider ↔ Qwen Code CLI 适配器。

实测依据（qwen 0.13.2，本机 `qwen --help` / `qwen -p ... -o json`）：
  - 非交互：`qwen -p "<prompt>"`（或位置参数）；stdin 文本会追加到输入
  - 模型：`-m/--model`
  - 系统提示：`--system-prompt`
  - **结构化输出**：`-o json` → stdout 为 JSON 数组，结果项形如
      {"type":"result","is_error":false,"result":"答案文本",
       "usage":{"input_tokens":N,"output_tokens":M}}
    失败项：{"type":"result","is_error":true,"error":{"message":"..."}}
  - 另有 `--input-format stream-json`（本适配器暂用文本 stdin，保持简单）

本适配器遵守 assist 的固定契约：
  stdin : {"id","prompt","system","model","images":[...],"temperature","max_tokens"}
  stdout: {"text":"...", "usage":{"prompt_tokens","completion_tokens"}}  或 {"error":"..."}

图片：qwen CLI 未见图片参数（help 无 image/attach）；
  → 把图片绝对路径写进 prompt，让 agent 用其文件读取工具打开（若其支持）。
  → 若需真正多模态直传，请改用 type=api 的视觉模型做转录。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

CLI = "qwen"


def _parse_qwen_json(stdout: str) -> tuple[str, dict, str]:
    """解析 `qwen -o json` 输出。返回 (text, usage, error)。"""
    raw = (stdout or "").strip()
    if not raw:
        return "", {}, "qwen 返回空输出"
    try:
        data = json.loads(raw)
    except Exception:
        # 兜底：某些版本可能直接输出纯文本
        return raw, {}, ""
    items = data if isinstance(data, list) else [data]
    result_items = [x for x in items if isinstance(x, dict) and x.get("type") == "result"]
    if not result_items:
        return "", {}, f"qwen 输出无 result 项（前 200 字：{raw[:200]!r}）"
    last = result_items[-1]
    if last.get("is_error"):
        err = last.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
        return "", {}, f"qwen 报错：{str(msg)[:300]}"
    text = str(last.get("result") or "").strip()
    u = last.get("usage") or {}
    usage = {}
    try:
        usage = {"prompt_tokens": int(u.get("input_tokens") or 0),
                 "completion_tokens": int(u.get("output_tokens") or 0)}
    except (TypeError, ValueError):
        usage = {}
    return text, usage, ("" if text else "qwen 返回空 result")


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"stdin 不是 JSON：{exc}"}))
        return 1

    exe = shutil.which(CLI) or CLI
    prompt = str(d.get("prompt") or "")
    images = [str(x) for x in (d.get("images") or [])]
    if images:
        prompt += ("\n\n【待读取的图片文件】\n" + "\n".join(images)
                   + "\n请读取上述图片内容后再作答。")

    args = [exe, "-p", prompt, "-o", "json"]
    if d.get("model"):
        args += ["-m", str(d["model"])]
    if d.get("system"):
        args += ["--system-prompt", str(d["system"])]

    try:
        cp = subprocess.run(args, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        print(json.dumps({"error": f"未找到 {CLI} 命令（检查 PATH）"}))
        return 1
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "qwen 调用超时（600s）"}))
        return 1

    text, usage, err = _parse_qwen_json(cp.stdout or "")
    if not text:
        detail = err or f"退出码 {cp.returncode}"
        if cp.stderr:
            detail += f"；stderr：{cp.stderr.strip()[:200]}"
        print(json.dumps({"error": detail}, ensure_ascii=False))
        return 1
    out = {"text": text}
    if usage:
        out["usage"] = usage
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
