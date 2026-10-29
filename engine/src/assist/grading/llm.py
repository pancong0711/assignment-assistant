"""llm.py — OpenAI 兼容 chat completions 客户端（httpx）。

迁移自 _legacy/2601playwright/src/llm/client.py，改动：
- requests → httpx（07 §4 配套纪律）；
- base_url / model / temperature / timeout / retries 可配置；
- API key 从 workspace settings.local.json 的 "llm" 段读（绝不入代码/日志，
  报错与 header 快照一律脱敏）。

settings.local.json 示例（不入库）：
  { "llm": { "base_url": "https://.../v1",
             "api_key": "sk-...",
             "model": "deepseek-chat",
             "transcription_model": "glm-5v",
             "evaluation_model": "deepseek-chat",
             "temperature": 0.3, "timeout_s": 120, "retries": 2 } }
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import httpx
from loguru import logger

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_VISION_MODEL = "glm-5v"

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".gif": "image/gif", ".webp": "image/webp"}


class LLMConfigError(RuntimeError):
    """LLM 配置缺失/非法（提示教师如何修 settings.local.json，而非甩原始堆栈）。"""


class LLMAPIError(RuntimeError):
    """LLM 请求失败（阈值/限流/网络），错误文本已脱敏（不含 key）。"""


def load_llm_settings(ws: Path) -> dict:
    """从 workspace settings.local.json 读 llm 段；key 绝不放进日志。"""
    fn = ws / "settings.local.json"
    if not fn.exists():
        raise LLMConfigError(
            f"未找到 {fn}。请在 workspace 根目录创建 settings.local.json 并填写 "
            '"llm": {"base_url": "...", "api_key": "sk-...", "model": "..."} '
            "（该文件在 .gitignore 中，不会入库）")
    try:
        cfg = json.loads(fn.read_text(encoding="utf-8"))
    except Exception as e:
        raise LLMConfigError(f"settings.local.json 解析失败: {e}") from e
    llm = cfg.get("llm", {})
    if not isinstance(llm, dict) or not llm.get("api_key"):
        raise LLMConfigError(
            'settings.local.json 缺少 "llm"."api_key"。请补齐后再运行批阅。')
    if not llm.get("base_url"):
        llm["base_url"] = DEFAULT_BASE_URL
    return llm


def _llm_raw(ws: Path) -> dict:
    """读原始 settings.local.json 的 llm 段（供 D82-F 旧覆盖读取）。"""
    try:
        from ..settings_store import read_settings
        llm = (read_settings(ws) or {}).get("llm") or {}
        return llm if isinstance(llm, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _settings_from_workspace(ws: Path, *, stage: str = "") -> dict:
    """构造 LLMClient settings：优先 provider 两段式（含 command），回退旧单层 llm 段。

    **D125 关键修复**：过去这里只返回「一套 base_url/api_key + 两个 model 名」——
    base_url/api_key 取的是 `stage_endpoint(默认 evaluation)` 那套，于是
    转录请求会被发往**评阅段的端点**（转录/评阅用不同 provider 时必然 400
    "Model is unavailable"）。

    现在改为返回**两段各自的完整 endpoint**（base_url/api_key/model/type/cmd…），
    `LLMClient._step_base_key()` 按 step 取对应那一套，互不串用。

    返回结构：
        {
          "transcription": {...完整 endpoint...},
          "evaluation":    {...完整 endpoint...},
          # 兼容旧调用方的平铺字段（= 该 stage 的 endpoint）
          "base_url": ..., "api_key": ..., "model": ...,
          "transcription_model": ..., "evaluation_model": ...,
        }
    """
    try:
        from . import providers as _prov
        provs = _prov.list_providers(ws)
        if provs:
            use_stage = stage if stage in ("transcription", "evaluation") else "evaluation"
            eps = {st: _prov.stage_endpoint(ws, st) for st in ("transcription", "evaluation")}
            ep = eps[use_stage]
            return {
                # D125：两段各一套完整配置（关键）
                "transcription": eps["transcription"],
                "evaluation": eps["evaluation"],
                # D82-F 旧覆盖（llm.transcription / llm.evaluation 的部分字段）：
                # 存到独立键，_step_endpoint 会**优先**采用它（保持旧行为）
                "_legacy_override": {
                    st: dict(raw) for st, raw in
                    ((st, (_llm_raw(ws).get(st) or {})) for st in ("transcription", "evaluation"))
                    if isinstance(raw, dict)
                },
                # 兼容字段
                **ep,
                "transcription_model": eps["transcription"].get("model") or "",
                "evaluation_model": eps["evaluation"].get("model") or "",
            }
    except Exception:  # noqa: BLE001
        pass
    return load_llm_settings(ws)


class LLMClient:
    """OpenAI 兼容 chat completions 客户端（文本 + 多模态图片）。"""

    def __init__(self, settings: dict | None = None, ws: Path | None = None,
                 stage: str = ""):
        if settings is None:
            if ws is None:
                raise LLMConfigError("LLMClient 需要 settings 或 workspace 参数")
            # D98：优先用 provider/两段式配置（含 type=command），旧单层配置仅作回退。
            settings = _settings_from_workspace(Path(ws), stage=stage)
        self._llm_settings = dict(settings or {})
        self.base_url = str(settings.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = str(settings.get("api_key") or "")
        self.model = settings.get("model") or DEFAULT_MODEL
        self.transcription_model = settings.get("transcription_model") or self.model
        self.evaluation_model = settings.get("evaluation_model") or self.model
        self.temperature = float(settings.get("temperature", 0.3))
        self.timeout = float(settings.get("timeout_s", 120))
        self.retries = int(settings.get("retries", 2))  # 失败重试次数（默认 2）
        # D98-B3：command 型 provider（无 key 回环外部 agent CLI）；见 provider_command.py
        self.provider_type = str(settings.get("type") or "api")
        self.command = dict(settings) if self.provider_type == "command" else {}
        if self.provider_type == "command":
            # command 模式：**完全忽略配置里的默认模型**（D98 裁决 7：默认用 agent 当前模型）。
            # 只有调用方显式传 `request(model=...)` / 用户 `--model` 才会传下去。
            self.model = ""
            self.transcription_model = ""
            self.evaluation_model = ""
        # D106：图片压缩模式（'auto' 分段压缩 | 'original' 原图直发）
        import os as _os
        self.image_mode = str(settings.get("image_mode")
                              or _os.environ.get("ASSIST_IMAGE_MODE") or "auto")
        # D106：最近一次多模态调用的图片压缩元数据（供 transcript 记录）
        self.last_image_meta: list[dict] = []
        # D98：token 用量累计（用于"省 token"度量；provider 不返回 usage 时则为 None）
        self.usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                            "calls": 0, "calls_with_usage": 0}

    def _step_cfg(self, step: str | None) -> dict:
        """取某段的**完整** endpoint 配置（D125）。

        优先级：
        1. `settings[step]`（新结构：两段各一套完整 endpoint，由 `_settings_from_workspace` 填充）；
        2. `settings[step]` 若只是旧 D82-F 的部分覆盖（只有 model 等），与平铺字段合并；
        3. 都没有 → {} （由 `_step_base_key` 回退到平铺字段，保持旧单层配置可用）。
        """
        if not step:
            return {}
        raw = self._llm_settings.get(step)
        return dict(raw) if isinstance(raw, dict) else {}

    def _step_endpoint(self, step: str | None) -> dict:
        """D125：返回该段生效的 {base_url, api_key, model, type, cmd, ...}。"""
        cfg = self._step_cfg(step)
        # D82-F：llm.<step> 里的部分字段（base_url/api_key/model）优先于 stages
        legacy = (self._llm_settings.get("_legacy_override") or {}).get(step or "") or {}
        if isinstance(legacy, dict) and legacy:
            cfg = {**cfg, **legacy}
        # 旧单层配置（没有 stages）：所有段共用平铺字段
        merged = {
            "provider": cfg.get("provider") or "",
            "base_url": cfg.get("base_url") or self.base_url,
            "api_key": cfg.get("api_key") or self.api_key,
            "model": cfg.get("model") or (
                self.transcription_model if step == "transcription" else self.evaluation_model),
            "type": cfg.get("type") or getattr(self, "provider_type", "api"),
            "cmd": cfg.get("cmd") if isinstance(cfg.get("cmd"), list) else None,
            "input_mode": cfg.get("input_mode"),
            "output_mode": cfg.get("output_mode"),
            "timeout_s": cfg.get("timeout_s"),
        }
        return merged

    def _step_base_key(self, step: str | None) -> "tuple[str, str, str]":
        ep = self._step_endpoint(step)
        return (str(ep["base_url"] or "").rstrip("/"), str(ep["api_key"] or ""),
                str(ep["model"] or ""))

    # ---- core request -------------------------------------------------
    def request(self, messages: list[dict], model: str | None = None,
                temperature: float | None = None,
                response_format: dict | None = None,
                max_tokens: int = 8192, step: str | None = None) -> dict:
        """发送请求并返回原始响应 dict；重试 retries 次，错误信息脱敏。

        provider_type=command 时不走 HTTP，改为子进程回环（每次新进程=天然隔离）。
        """
        # D125：command 型也**按段**取配置（转录/评阅可能一个 api 一个 command）
        step_ep = self._step_endpoint(step)
        if str(step_ep.get("type") or "api") == "command":
            return self._request_via_command(messages, model=model, max_tokens=max_tokens,
                                             endpoint=step_ep)
        base_url, api_key, step_model = self._step_base_key(step)
        payload = {
            "model": model or step_model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        last_err = None
        # D125：报错带上「用的哪一段/哪个 provider/base/model」，便于一眼定位配置错配
        where = (f"（step={step or 'evaluation'}, provider={step_ep.get('provider') or '-'}, "
                 f"base_url={base_url}, model={payload.get('model')}）")
        for attempt in range(self.retries + 1):
            try:
                resp = httpx.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}",
                             "Content-Type": "application/json"},
                    json=payload, timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._record_usage(data)
                    return data
                if resp.status_code == 429:
                    wait = 2 ** attempt * 5
                    logger.warning(f"LLM 限流(429)，等待 {wait}s 后重试")
                    time.sleep(wait)
                    last_err = "API 限流(429)，多次重试后仍失败"
                    continue
                # D125：**确定性错误不重试**（模型不可用/请求非法/鉴权失败，重试毫无意义）
                body = resp.text[:400]
                if resp.status_code in (400, 401, 403, 404) or "Model is unavailable" in body:
                    raise LLMAPIError(
                        f"LLM API 请求失败(status={resp.status_code}): {body}{where}")
                # NOK：脱敏 —— 只带前 400 字符 body，绝不含 Authorization/key
                raise LLMAPIError(
                    f"LLM API 请求失败(status={resp.status_code}): {body}{where}")
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt < self.retries:
                    wait = 2 ** attempt * 5
                    logger.warning(f"LLM 网络异常({type(e).__name__})，等待 {wait}s 重试")
                    time.sleep(wait)
                    last_err = f"网络异常({type(e).__name__})，重试 {self.retries} 次后仍失败"
                    continue
                last_err = last_err or f"网络异常: {type(e).__name__}（检查 base_url<-{self.base_url}> 与网络）"
        raise LLMAPIError(last_err or "LLM API 请求失败")

    def _request_via_command(self, messages: list[dict], *, model: str | None,
                             max_tokens: int, endpoint: "dict | None" = None) -> dict:
        """command provider：把 messages 压成 stdin 契约，子进程返回文本。

        - 只取 system + user 文本/图片；**每次新进程，无历史** → 结构性隔离；
        - 返回 OpenAI 兼容的伪响应 `{choices:[{message:{content:...}}]}`，
          这样上游 `extract_text` 无需改动。
        """
        from .provider_command import build_payload, run_command
        system = ""
        texts: list[str] = []
        images: list[str] = []
        for m in messages:
            role = m.get("role")
            content = m.get("content")
            if role == "system" and isinstance(content, str):
                system = content
            elif role == "user":
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        if part.get("type") == "text":
                            texts.append(str(part.get("text") or ""))
                        elif part.get("type") == "image_url":
                            url = str(((part.get("image_url") or {}).get("url")) or "")
                            if url.startswith("data:") and ";base64," in url:
                                # data-url → 临时文件（省管道体积）
                                import base64
                                import tempfile
                                head, b64 = url.split(";base64,", 1)
                                mime = head.split("data:", 1)[-1]
                                ext = {"image/png": ".png", "image/jpeg": ".jpg",
                                       "image/webp": ".webp", "image/gif": ".gif"}.get(mime, ".img")
                                fd, tmp = tempfile.mkstemp(suffix=ext)
                                with __import__("os").fdopen(fd, "wb") as fh:
                                    fh.write(base64.b64decode(b64))
                                images.append(tmp)
                            elif url:
                                images.append(url)
        # 模型：**只传显式指定**；否则留空 → 用 agent 当前模型（用户裁决 7）。
        # 注意不能用 self.evaluation_model/transcription_model（那是 API 模式的默认值，
        # 传给外部 CLI 会覆盖其自身模型选择）。
        payload = build_payload(
            item_id="llm-client", prompt="\n\n".join(texts), system=system,
            model=model or "", images=images, temperature=self.temperature,
            max_tokens=max_tokens)
        # D125：command 型按段取 cmd（转录/评阅可能配了不同 agent CLI）
        prov = dict(self.command or {})
        if isinstance(endpoint, dict) and isinstance(endpoint.get("cmd"), list) \
                and endpoint["cmd"]:
            prov = {**prov, "cmd": [str(x) for x in endpoint["cmd"]]}
        if isinstance(endpoint, dict) and endpoint.get("timeout_s"):
            prov = {**prov, "timeout_s": int(endpoint["timeout_s"])}
        res = run_command(prov, payload)
        if not res.get("ok"):
            raise LLMAPIError(f"command provider 调用失败：{res.get('error')}")
        usage = res.get("usage") or {}
        data: dict = {"choices": [{"message": {"content": res["text"]}}], "_command": True,
                      "_ms": res.get("ms")}
        if usage.get("prompt_tokens") or usage.get("completion_tokens"):
            # 让 command 调用也进入 token 度量（适配器回传 usage 时）
            data["usage"] = {"prompt_tokens": int(usage.get("prompt_tokens") or 0),
                             "completion_tokens": int(usage.get("completion_tokens") or 0),
                             "total_tokens": int(usage.get("prompt_tokens") or 0)
                                             + int(usage.get("completion_tokens") or 0)}
        self._record_usage(data)
        return data

    def _record_usage(self, data: dict) -> None:
        """累计 usage（OpenAI 兼容：data["usage"]）；缺失则只计 calls。"""
        self.usage["calls"] = int(self.usage.get("calls", 0)) + 1
        u = data.get("usage") if isinstance(data, dict) else None
        if isinstance(u, dict):
            self.usage["calls_with_usage"] = int(self.usage.get("calls_with_usage", 0)) + 1
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                try:
                    self.usage[k] = int(self.usage.get(k, 0)) + int(u.get(k) or 0)
                except (TypeError, ValueError):
                    pass

    def usage_summary(self) -> dict:
        """本次 client 生命周期内的用量摘要（供 batch-report / CLI 打印）。"""
        return dict(self.usage)

    def extract_text(self, data: dict) -> str:
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMAPIError(f"LLM 响应格式异常: {e}；响应片段: "
                              f"{json.dumps(data, ensure_ascii=False)[:300]}") from e

    # ---- convenience ---------------------------------------------------
    def chat(self, system_prompt: str, user_text: str, model: str | None = None,
             temperature: float | None = None,
             response_format: dict | None = None, max_tokens: int = 8192,
             step: str = "evaluation") -> str:
        data = self.request(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": user_text}],
            model=model or self.evaluation_model,
            temperature=temperature, response_format=response_format,
            max_tokens=max_tokens, step=step)
        return self.extract_text(data)

    def chat_with_images(self, system_prompt: str, user_text: str,
                         image_paths: list[str | Path], model: str | None = None,
                         temperature: float | None = None,
                         max_tokens: int = 8192,
                         step: str = "transcription") -> str:
        """多模态：图片 base64 data-url + 文本（迁移自 client.chat_with_images）。"""
        content: list[dict] = [{"type": "text", "text": user_text}]
        # D106：分段压缩（mode='original' 可关闭，便于对比转录效果）；原图永不修改
        from .imageprep import compress_for_model
        img_mode = str(getattr(self, "image_mode", "auto") or "auto")
        self.last_image_meta = []
        for img_path in image_paths:
            path = Path(img_path)
            if not path.exists():
                logger.warning(f"图片不存在，跳过: {path}")
                continue
            data, mime, meta = compress_for_model(path, mode=img_mode)  # type: ignore[arg-type]
            meta = {**meta, "file": path.name}
            self.last_image_meta.append(meta)
            b64 = base64.b64encode(data).decode("utf-8")
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}})
        data = self.request(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": content}],
            model=model or self.transcription_model, temperature=temperature,
            max_tokens=max_tokens, step=step)
        return self.extract_text(data)

    # ---- D82-F: batch API -------------------------------------------------
    def batch_chat(self, items: list[dict], step: str = "evaluation",
                   workers: int = 3) -> list[str]:
        """通用批量调用：items=[{system_prompt,user_text,model?,response_format?}]。

        当前实现以受控并发调用普通 chat；后续 provider batch 端点可替换实现，
        调用方不需要改。
        """
        from concurrent.futures import ThreadPoolExecutor
        out: list[str] = [""] * len(items)
        def one(i: int, it: dict) -> "tuple[int,str]":
            txt = self.chat(
                str(it.get("system_prompt") or ""),
                str(it.get("user_text") or ""),
                model=it.get("model"),
                response_format=it.get("response_format"),
                max_tokens=int(it.get("max_tokens") or 8192),
                step=str(it.get("step") or step),
            )
            return i, txt
        with ThreadPoolExecutor(max_workers=max(1, min(8, int(workers or 3)))) as ex:
            for i, txt in ex.map(lambda p: one(*p), list(enumerate(items))):
                out[i] = txt
        return out
