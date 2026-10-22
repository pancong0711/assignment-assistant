"""D86 §2：LLM provider 管理（统一设置一次）+ 两段式引用（勾选 provider + 模型名）。

- provider 列表：`{name, base_url, models[], batch_support}` 存 `settings.local.json → llm.providers[]`；
- **api_key 每 provider 一份**，存 `settings.local.secrets.json → llm.providers{name: key}`（0600）；
- 两段式：`llm.stages.transcription / evaluation = {provider, model, batch?}`；
- 模型名"填写即记录"：按 provider 累积 `models[]`（去重，上限 20），供下次下拉勾选；
- 兼容旧配置 `llm.base_url / api_key / model` → 迁移为 `providers[0]`（name="默认"）。

安全：对外只回显掩码 `sk-****abcd`；日志只记 provider 名与 base_url host，绝不记 key。
"""
from __future__ import annotations

from pathlib import Path

MAX_MODELS = 20
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LEGACY_PROVIDER_NAME = "默认"


def mask_key(key: str) -> str:
    """`sk-abcdefgh1234` → `sk-****1234`（太短则全掩）。"""
    k = str(key or "")
    if not k:
        return ""
    if len(k) <= 8:
        return "****"
    return f"{k[:3]}****{k[-4:]}"


def host_of(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(str(url or "")).netloc or ""
    except Exception:  # noqa: BLE001
        return ""


def _read(ws):
    from ..settings_store import read_secrets, read_settings
    return read_settings(ws), read_secrets(ws)


def _providers_out(data: dict) -> list[dict]:
    raw = ((data.get("llm") or {}).get("providers")) or []
    return [dict(p) for p in raw if isinstance(p, dict)]


def _secrets_map(sec: dict) -> dict:
    raw = ((sec.get("llm") or {}).get("providers")) or {}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def list_providers(ws=None, *, mask: bool = True) -> list[dict]:
    """provider 列表（含 key 掩码）；mask=False 仅内部使用（引擎调用 LLM 时）。"""
    data, sec = _read(ws)
    keys = _secrets_map(sec)
    out: list[dict] = []
    for p in _providers_out(data):
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        key = keys.get(name, "")
        out.append({
            "name": name,
            "type": str(p.get("type") or "api"),
            "base_url": str(p.get("base_url") or ""),
            "cmd": [str(x) for x in (p.get("cmd") or [])] if isinstance(p.get("cmd"), list) else [],
            "input_mode": str(p.get("input_mode") or "stdin"),
            "output_mode": str(p.get("output_mode") or "stdout-json"),
            "timeout_s": int(p.get("timeout_s") or 300),
            "supports_images": bool(p.get("supports_images", True)),
            "models": [str(m) for m in (p.get("models") or [])][:MAX_MODELS],
            "batch_support": bool(p.get("batch_support")),
            "api_key": mask_key(key) if mask else key,
            "has_key": bool(key),
        })
    return out


# 常见 agent CLI（用于 doctor 能力探测：有则可走 `type=command` 回环）。
KNOWN_AGENT_CLIS = ("opencode", "codex", "claude", "cursor-agent", "aider", "gemini")


def capabilities(ws=None) -> dict:
    """D98-B2：LLM 能力探测（供 doctor / skill 判断该走哪条路径）。

    返回：
      {
        "api":    {"available": bool, "providers": [names...]},           # base_url+key
        "command":{"available": bool, "providers": [names...]},           # type=command
        "batch":  {"available": bool, "providers": [names...]},           # batch_support
        "agentCli": [{"name": ..., "path": ...}],                         # 本机检测到的 agent CLI
        "recommendedPath": "api" | "command" | "subagent-or-manual"
      }
    """
    import shutil
    provs = list_providers(ws, mask=False)
    api_names = [p["name"] for p in provs
                 if p.get("base_url") and (p.get("has_key") or p.get("api_key"))]
    cmd_names = [p["name"] for p in provs if str(p.get("type") or "") == "command"]
    batch_names = [p["name"] for p in provs if p.get("batch_support")]
    clis = []
    for name in KNOWN_AGENT_CLIS:
        pth = shutil.which(name)
        if pth:
            clis.append({"name": name, "path": pth})

    if api_names:
        recommended = "api"
    elif cmd_names or clis:
        recommended = "command"
    else:
        recommended = "subagent-or-manual"

    warnings = _capability_warnings(provs, ws)
    return {
        "api": {"available": bool(api_names), "providers": api_names},
        "command": {"available": bool(cmd_names), "providers": cmd_names},
        "batch": {"available": bool(batch_names), "providers": batch_names},
        "agentCli": clis,
        "recommendedPath": recommended,
        "warnings": warnings,
    }


def _capability_warnings(provs: list[dict], ws=None) -> list[dict]:
    """能力组合的风险提示（doctor 展示；不改变执行）。

    最重要一条：**转录段用了 command 但该 CLI 不支持读图** → 转录拿不到图。
    应把 transcription 段换成 type=api 的视觉模型（D98 讨论结论）。
    """
    warns: list[dict] = []
    by_name = {str(p.get("name")): p for p in provs}
    # 1) 转录段实际引用的 provider 不支持图片
    try:
        tr = (stages(ws).get("transcription") or {}).get("provider") or ""
    except Exception:  # noqa: BLE001
        tr = ""
    p = by_name.get(str(tr))
    if p and str(p.get("type") or "") == "command" and p.get("supports_images") is False:
        warns.append({
            "level": "warn", "code": "transcription_command_no_images",
            "provider": p.get("name"),
            "message": (f"转录段使用 command provider「{p.get('name')}」，但其不支持图片："
                        "转录会读不到作答图。请把 transcription 段改为 type=api 的视觉模型，"
                        "或确认该 CLI 能读取图片路径（然后重设为 supports_images=true）。"),
        })
    # 2) 所有 command 且明确不支持图片的 provider 提示一次（信息级）
    for p in provs:
        if str(p.get("type") or "") == "command" and p.get("supports_images") is False \
                and str(p.get("name")) != str(tr):
            warns.append({
                "level": "info", "code": "command_no_images",
                "provider": p.get("name"),
                "message": f"provider「{p.get('name')}」不支持图片，仅用于纯文本任务（如批阅）。",
            })
    return warns


def get_provider(ws, name: str) -> "dict | None":
    """取单个 provider 的**内部**完整配置（含明文 key）——仅供引擎内部 LLM 调用；
    **绝不可**回传 PWA/写入日志。找不到返回 None。"""
    target = str(name or "").strip()
    if not target:
        return None
    for p in list_providers(ws, mask=False):
        if str(p.get("name")) == target:
            return p
    return None


def stages(ws=None) -> dict:
    from ..settings_store import read_settings
    data = read_settings(ws)
    st = ((data.get("llm") or {}).get("stages")) or {}
    return {str(k): dict(v) for k, v in st.items() if isinstance(v, dict)} if isinstance(st, dict) else {}


def migrate_legacy(ws=None) -> dict:
    """旧单层 llm.{base_url,api_key,model} → providers[0] + stages（幂等）。"""
    from ..settings_store import read_secrets, read_settings, update_secrets, update_settings
    data = read_settings(ws)
    llm = data.get("llm") or {}
    if _providers_out(data):
        return {"migrated": False, "reason": "providers-exists"}
    base_url = str(llm.get("base_url") or "")
    model = str(llm.get("model") or "")
    api_key = str(llm.get("api_key") or "")
    if not (base_url or api_key or model):
        return {"migrated": False, "reason": "nothing-to-migrate"}
    prov = {"name": LEGACY_PROVIDER_NAME, "base_url": base_url or DEFAULT_BASE_URL,
            "models": [model] if model else [], "batch_support": False}

    def _fn(d: dict) -> None:
        l = d.setdefault("llm", {})
        l.setdefault("providers", []).append(prov)
        l.pop("api_key", None)                    # key 移入 secrets
        st = l.setdefault("stages", {})
        for stage in ("transcription", "evaluation"):
            cur = st.get(stage) or {}
            st[stage] = {"provider": cur.get("provider") or LEGACY_PROVIDER_NAME,
                         "model": cur.get("model") or model}
    update_settings(ws, _fn)
    if api_key:
        def _sfn(sec: dict) -> None:
            l = sec.setdefault("llm", {})
            l.setdefault("providers", {})[LEGACY_PROVIDER_NAME] = api_key
        update_secrets(ws, _sfn)
    return {"migrated": True, "provider": LEGACY_PROVIDER_NAME}


def save_provider(ws, name: str, *, base_url: str = "", api_key: "str | None" = None,
                  batch_support: "bool | None" = None, model: str = "",
                  forget_model: str = "", provider_type: str = "", cmd: "list[str] | None" = None,
                  input_mode: str = "", output_mode: str = "",
                  timeout_s: "int | None" = None, supports_images: "bool | None" = None) -> dict:
    """新增/更新一个 provider。api_key=None 表示不改；'' 表示清除。

    支持 `provider_type="api"|"command"`：command 型用 `cmd` 回环调用外部 agent CLI
    （D98-B3），此时不需要 base_url/api_key。
    """
    from ..settings_store import update_secrets, update_settings
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "provider 名称必填"}
    holder: dict = {}

    def _fn(d: dict) -> None:
        l = d.setdefault("llm", {})
        provs = [p for p in (l.get("providers") or []) if isinstance(p, dict)]
        cur = next((p for p in provs if str(p.get("name")) == name), None)
        if cur is None:
            cur = {"name": name, "models": []}
            provs.append(cur)
        if base_url:
            cur["base_url"] = str(base_url)
        if provider_type:
            if provider_type not in ("api", "command"):
                holder["error"] = f"provider_type 只能是 api/command：{provider_type}"
                return
            cur["type"] = provider_type
        if cmd is not None:
            cur["cmd"] = [str(x) for x in cmd]
        if input_mode:
            cur["input_mode"] = input_mode
        if output_mode:
            cur["output_mode"] = output_mode
        if timeout_s is not None:
            cur["timeout_s"] = int(timeout_s)
        if supports_images is not None:
            cur["supports_images"] = bool(supports_images)
        if batch_support is not None:
            cur["batch_support"] = bool(batch_support)
        if forget_model:
            models = [str(m) for m in (cur.get("models") or []) if str(m) != str(forget_model)]
            cur["models"] = models
        if model:
            models = [str(m) for m in (cur.get("models") or [])]
            if model in models:
                models.remove(model)
            models.insert(0, model)
            cur["models"] = models[:MAX_MODELS]
        l["providers"] = provs
        holder["provider"] = cur
    update_settings(ws, _fn)

    if api_key is not None:
        def _sfn(sec: dict) -> None:
            l = sec.setdefault("llm", {})
            pm = l.setdefault("providers", {})
            if api_key:
                pm[name] = str(api_key)
            else:
                pm.pop(name, None)
        update_secrets(ws, _sfn)
    if holder.get("error"):
        return {"ok": False, "error": holder["error"]}
    return {"ok": True, "provider": {k: v for k, v in holder.get("provider", {}).items() if k != "api_key"}}


def delete_provider(ws, name: str) -> dict:
    from ..settings_store import update_secrets, update_settings
    name = str(name or "").strip()
    found = {"v": False}

    def _fn(d: dict) -> None:
        l = d.setdefault("llm", {})
        provs = [p for p in (l.get("providers") or []) if str(p.get("name")) != name]
        if len(provs) != len(l.get("providers") or []):
            found["v"] = True
        l["providers"] = provs
    update_settings(ws, _fn)

    def _sfn(sec: dict) -> None:
        pm = ((sec.get("llm") or {}).get("providers")) or {}
        if isinstance(pm, dict):
            pm.pop(name, None)
    update_secrets(ws, _sfn)
    return {"ok": found["v"], "deleted": name}


def set_stage(ws, stage: str, *, provider: str, model: str = "", batch: "bool | None" = None) -> dict:
    """设置某段的 provider/模型（并"填写即记录"模型到该 provider 的 models[]）。"""
    from ..settings_store import update_settings
    stage = str(stage or "").strip().lower()
    if stage not in ("transcription", "evaluation"):
        return {"ok": False, "error": "stage 只能是 transcription / evaluation"}
    names = {p["name"] for p in list_providers(ws)}
    if provider and provider not in names:
        return {"ok": False, "error": f"provider 不存在：{provider}（先到 Provider 管理区添加）"}

    def _fn(d: dict) -> None:
        l = d.setdefault("llm", {})
        st = l.setdefault("stages", {})
        cur = dict(st.get(stage) or {})
        if provider:
            cur["provider"] = provider
        if model:
            cur["model"] = model
        if batch is not None:
            cur["batch"] = bool(batch)
        st[stage] = cur
    update_settings(ws, _fn)
    if provider and model:
        save_provider(ws, provider, model=model)   # 填写即记录（模型历史）
    return {"ok": True, "stage": stage, "config": stages(ws).get(stage, {})}


def public_config(ws=None) -> dict:
    """给 PWA 的安全视图：provider（掩码）+ 两段式选择。"""
    return {"providers": list_providers(ws, mask=True), "stages": stages(ws),
            "default_base_url": DEFAULT_BASE_URL}


def stage_endpoint(ws, stage: str) -> dict:
    """取某段最终生效的 (base_url, api_key, model)，供 LLMClient 使用（含旧配置回落）。"""
    from ..settings_store import read_secrets, read_settings
    data = read_settings(ws)
    sec = read_secrets(ws)
    llm = data.get("llm") or {}
    st = (llm.get("stages") or {}).get(stage) or {}
    name = str(st.get("provider") or LEGACY_PROVIDER_NAME)
    prov = next((p for p in _providers_out(data) if str(p.get("name")) == name), None) or {}
    key = _secrets_map(sec).get(name, "")
    base = str(prov.get("base_url") or llm.get("base_url") or DEFAULT_BASE_URL)
    model = str(st.get("model") or llm.get(f"{stage}_model") or llm.get("model") or "")
    return {"provider": name, "base_url": base, "api_key": key or str(llm.get("api_key") or ""),
            "model": model, "batch": bool(st.get("batch")), "host": host_of(base),
            # D98-B3：command 型 provider（无 key 回环），供 LLMClient 判定走子进程
            "type": str(prov.get("type") or "api"),
            "cmd": [str(x) for x in (prov.get("cmd") or [])] if isinstance(prov.get("cmd"), list) else [],
            "input_mode": str(prov.get("input_mode") or "stdin"),
            "output_mode": str(prov.get("output_mode") or "stdout-json"),
            "timeout_s": int(prov.get("timeout_s") or 300)}
