"""D86 §7：LLM batch 通道（Aliyun DashScope / OpenAI 兼容）。

设计口径（2026-10-15 讨论）：
- 先做**一般提交**闭环（实时+并发，已在 `LLMClient.batch_chat`），batch 作为可选加速/降本；
- batch 主要用于**评阅段（纯文本）**；转写（多模态）仍走实时；
- 本模块默认 **dry-run**：生成 JSONL + 使用说明，不发起网络请求；
  真正提交/轮询/下载需显式 `--submit/--poll/--download`；
- **无法在本机联网实测**（教师机实测）→ 一切失败都返回完整诊断：
  HTTP 状态、响应体原文、请求 URL、批次 id、JSONL 路径，便于把报错发回。

JSONL 行结构（OpenAI Batch 兼容）：
{"custom_id": "<学生>", "method": "POST", "url": "/v1/chat/completions",
 "body": {"model": "...", "messages": [...], "response_format": {"type": "json_object"}}}
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from loguru import logger

BATCH_ENDPOINT = "/v1/chat/completions"


def build_jsonl(items: list[dict], out_path, *, model: str, url: str = BATCH_ENDPOINT) -> Path:
    """items=[{custom_id, system_prompt, user_text, temperature?, response_format?}] → JSONL。"""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for it in items:
        body = {
            "model": str(it.get("model") or model or ""),
            "messages": ([{"role": "system", "content": str(it.get("system_prompt") or "")}]
                         if it.get("system_prompt") else [])
            + [{"role": "user", "content": str(it.get("user_text") or "")}],
            "temperature": float(it.get("temperature", 0.2)),
        }
        rf = it.get("response_format")
        if rf:
            body["response_format"] = rf
        lines.append(json.dumps({"custom_id": str(it.get("custom_id") or f"item-{len(lines)}"),
                                 "method": "POST", "url": url, "body": body},
                                ensure_ascii=False))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def provider_public(prov: dict) -> dict:
    """对外视图：**只保留掩码 key**（防明文泄漏到 stdout/日志）。"""
    out = {k: v for k, v in (prov or {}).items() if k != "api_key"}
    out["api_key"] = _mask(str((prov or {}).get("api_key") or ""))
    return out


def _mask(key: str) -> str:
    k = str(key or "")
    if not k:
        return ""
    return "****" if len(k) <= 8 else f"{k[:3]}****{k[-4:]}"


def write_instructions(jsonl_path: Path, *, provider: dict, out_dir: "Path | None" = None) -> Path:
    """输出 batch 提交/轮询/下载说明（含本机无法实测的提示），供教师照做。"""
    d = Path(out_dir) if out_dir else jsonl_path.parent
    d.mkdir(parents=True, exist_ok=True)
    p = d / "BATCH-README.txt"
    base = str(provider.get("base_url") or "")
    p.write_text(f"""LLM batch 使用说明（D86 §7）
provider   : {provider.get('name')}    batch_support={provider.get('batch_support')}
base_url   : {base}
JSONL      : {jsonl_path}

1) 上传文件（拿到 file_id）：
   curl -s -X POST "{base}/files" -H "Authorization: Bearer $KEY" \\
        -F purpose=batch -F file=@{jsonl_path}
2) 创建批次（拿到 batch id）：
   curl -s -X POST "{base}/batches" -H "Authorization: Bearer $KEY" \\
        -H "Content-Type: application/json" \\
        -d '{{"input_file_id":"<file_id>","endpoint":"/v1/chat/completions",
             "completion_window":"24h"}}'
3) 轮询：GET "{base}/batches/{{batch_id}}"
4) 下载：GET "{base}/files/{{output_file_id}}/content"

引擎侧命令（同口径，失败会打印完整诊断）：
  assist llm batch --jsonl {jsonl_path} --provider {provider.get('name')} [--submit]
  assist llm batch --provider {provider.get('name')} --poll <batch_id>
  assist llm batch --provider {provider.get('name')} --download <output_file_id> --out results.jsonl

注意：batch 是否支持当前模型/多模态需以服务商文档为准；本机无法联网实测，
若报错请把命令输出（含 HTTP 状态与响应原文）回传。
""", encoding="utf-8")
    return p


def _request(url: str, key: str, *, method: str = "GET", data: "bytes | None" = None,
             headers: "dict | None" = None, timeout: int = 60) -> dict:
    """HTTP 调用 + 完整诊断（绝不打印 key）。"""
    hdrs = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return {"ok": True, "status": resp.status, "text": raw[:4000], "url": url}
    except urllib.error.HTTPError as e:  # noqa: PERF203
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:2000]
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "status": e.code, "text": body, "url": url,
                "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": None, "text": "", "url": url, "error": str(e)[:300]}


def _provider(ws, name: str) -> dict:
    from . import providers
    p = next((x for x in providers.list_providers(ws, mask=False) if x["name"] == name), None)
    if not p:
        raise RuntimeError(f"provider 不存在：{name}")
    if not p.get("base_url"):
        raise RuntimeError(f"provider {name} 未配置 base_url")
    return p


def submit(ws, provider_name: str, jsonl_path) -> dict:
    """真正提交 batch（需 provider 标记 batch_support）。返回 file_id/batch_id 或诊断。"""
    prov = _provider(ws, provider_name)
    if not prov.get("batch_support"):
        return {"ok": False, "error": f"provider {provider_name} 未标记 batch_support",
                "hint": "到 AI 设置区勾选『该 provider 支持 batch』"}
    base = str(prov["base_url"]).rstrip("/")
    key = str(prov.get("api_key") or "")
    if not key and not prov.get("has_key"):
        return {"ok": False, "error": "该 provider 未配置 api_key"}
    p = Path(jsonl_path)
    if not p.is_file():
        return {"ok": False, "error": f"JSONL 不存在：{p}"}
    # 文件上传（multipart 手工拼装，避免额外依赖）
    boundary = "----assistbatch" + str(int(time.time()))
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nbatch\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{p.name}\"\r\nContent-Type: application/jsonl\r\n\r\n").encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    body = head + p.read_bytes() + tail
    up = _request(f"{base}/files", key, method="POST", data=body,
                  headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    if not up["ok"]:
        return {"ok": False, "stage": "upload", **up, "jsonl": str(p), "hint": "见 BATCH-README.txt"}
    try:
        file_id = json.loads(up["text"]).get("id")
    except Exception:  # noqa: BLE001
        file_id = None
    if not file_id:
        return {"ok": False, "stage": "upload", "error": "响应中未找到 file id", **up}
    payload = json.dumps({"input_file_id": file_id, "endpoint": "/v1/chat/completions",
                          "completion_window": "24h"}).encode()
    cb = _request(f"{base}/batches", key, method="POST", data=payload)
    if not cb["ok"]:
        return {"ok": False, "stage": "create", "file_id": file_id, **cb}
    batch_id = None
    try:
        batch_id = json.loads(cb["text"]).get("id")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": bool(batch_id), "file_id": file_id, "batch_id": batch_id,
            "status": "submitted" if batch_id else "no-batch-id", "response": cb["text"][:1000],
            "jsonl": str(p)}


def poll(ws, provider_name: str, batch_id: str) -> dict:
    prov = _provider(ws, provider_name)
    base = str(prov["base_url"]).rstrip("/")
    r = _request(f"{base}/batches/{batch_id}", str(prov.get("api_key") or ""))
    out = {"ok": r["ok"], **r, "batch_id": batch_id}
    try:
        data = json.loads(r["text"])
        out.update({"status": data.get("status"), "output_file_id": data.get("output_file_id"),
                    "request_counts": data.get("request_counts")})
    except Exception:  # noqa: BLE001
        pass
    return out


def download(ws, provider_name: str, output_file_id: str, out_path) -> dict:
    prov = _provider(ws, provider_name)
    base = str(prov["base_url"]).rstrip("/")
    r = _request(f"{base}/files/{output_file_id}/content", str(prov.get("api_key") or ""),
                 timeout=120)
    if not r["ok"]:
        return {"ok": False, **r}
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(r["text"], encoding="utf-8")
    return {"ok": True, "out": str(p), "bytes": len(r["text"])}


def plan_batch_items(ws, task_path, *, provider_name: str = "", mode: str = "optimized",
                     limit: int = 0) -> dict:
    """从 plan + 转录产物生成 batch 输入（评阅段）。返回 {items, model, dir}。"""
    from . import inputs as _inputs
    from . import providers as _prov
    from .flow import grading_dir, _paths
    task_path = Path(task_path).expanduser().resolve()
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task_id = str(task.get("id") or "task")
    plan = _inputs.load_plan(Path(ws), task_id) or {}
    st = _prov.stages(ws).get("evaluation", {})
    pname = provider_name or str(st.get("provider") or "")
    model = str(st.get("model") or "")
    base = grading_dir(Path(ws), task)
    paths = _paths(base)
    items = []
    students = plan.get("students") or []
    if limit:
        students = students[:limit]
    names = {str(s.get("name")) for s in students} if students else set()
    for tf in sorted(paths["transcripts"].glob("[!_]*.json")):
        if names and tf.stem not in names:
            continue
        try:
            tr = json.loads(tf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        student = str(tr.get("student") or tf.stem)
        stu = next((s for s in students if str(s.get("name")) == student), {})
        from .prompts import ANALYSIS_PROMPT, build_evaluate_prompt
        items.append({"custom_id": student, "system_prompt": ANALYSIS_PROMPT,
                      "user_text": build_evaluate_prompt(
                          questions=stu.get("questions") or [],
                          markdown_text=str(tr.get("markdown") or ""),
                          tag=str(stu.get("tag") or "")),
                      "response_format": {"type": "json_object"}})
    return {"items": items, "model": model, "provider": pname, "dir": str(paths["reports"].parent)}
