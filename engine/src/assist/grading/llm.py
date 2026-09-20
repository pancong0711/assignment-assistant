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


class LLMClient:
    """OpenAI 兼容 chat completions 客户端（文本 + 多模态图片）。"""

    def __init__(self, settings: dict | None = None, ws: Path | None = None):
        if settings is None:
            if ws is None:
                raise LLMConfigError("LLMClient 需要 settings 或 workspace 参数")
            settings = load_llm_settings(Path(ws))
        self.base_url = str(settings.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = str(settings.get("api_key") or "")
        self.model = settings.get("model") or DEFAULT_MODEL
        self.transcription_model = settings.get("transcription_model") or self.model
        self.evaluation_model = settings.get("evaluation_model") or self.model
        self.temperature = float(settings.get("temperature", 0.3))
        self.timeout = float(settings.get("timeout_s", 120))
        self.retries = int(settings.get("retries", 2))  # 失败重试次数（默认 2）

    # ---- core request -------------------------------------------------
    def request(self, messages: list[dict], model: str | None = None,
                temperature: float | None = None,
                response_format: dict | None = None,
                max_tokens: int = 8192) -> dict:
        """发送请求并返回原始响应 dict；重试 retries 次，错误信息脱敏。"""
        payload = {
            "model": model or self.evaluation_model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        last_err = None
        for attempt in range(self.retries + 1):
            try:
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                    json=payload, timeout=self.timeout,
                )
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429:
                    wait = 2 ** attempt * 5
                    logger.warning(f"LLM 限流(429)，等待 {wait}s 后重试")
                    time.sleep(wait)
                    last_err = "API 限流(429)，多次重试后仍失败"
                    continue
                # NOK：脱敏 —— 只带前 400 字符 body，绝不含 Authorization/key
                raise LLMAPIError(
                    f"LLM API 请求失败(status={resp.status_code}): {resp.text[:400]}")
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt < self.retries:
                    wait = 2 ** attempt * 5
                    logger.warning(f"LLM 网络异常({type(e).__name__})，等待 {wait}s 重试")
                    time.sleep(wait)
                    last_err = f"网络异常({type(e).__name__})，重试 {self.retries} 次后仍失败"
                    continue
                last_err = last_err or f"网络异常: {type(e).__name__}（检查 base_url<-{self.base_url}> 与网络）"
        raise LLMAPIError(last_err or "LLM API 请求失败")

    def extract_text(self, data: dict) -> str:
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMAPIError(f"LLM 响应格式异常: {e}；响应片段: "
                              f"{json.dumps(data, ensure_ascii=False)[:300]}") from e

    # ---- convenience ---------------------------------------------------
    def chat(self, system_prompt: str, user_text: str, model: str | None = None,
             temperature: float | None = None,
             response_format: dict | None = None, max_tokens: int = 8192) -> str:
        data = self.request(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": user_text}],
            model=model or self.evaluation_model,
            temperature=temperature, response_format=response_format,
            max_tokens=max_tokens)
        return self.extract_text(data)

    def chat_with_images(self, system_prompt: str, user_text: str,
                         image_paths: list[str | Path], model: str | None = None,
                         temperature: float | None = None,
                         max_tokens: int = 8192) -> str:
        """多模态：图片 base64 data-url + 文本（迁移自 client.chat_with_images）。"""
        content: list[dict] = [{"type": "text", "text": user_text}]
        for img_path in image_paths:
            path = Path(img_path)
            if not path.exists():
                logger.warning(f"图片不存在，跳过: {path}")
                continue
            b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
            mime = _MIME.get(path.suffix.lower(), "image/jpeg")
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}})
        data = self.request(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": content}],
            model=model or self.transcription_model, temperature=temperature,
            max_tokens=max_tokens)
        return self.extract_text(data)
