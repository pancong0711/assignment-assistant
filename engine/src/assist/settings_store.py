"""D86 §2：workspace 配置读写（非敏感 settings.local.json + 敏感 settings.local.secrets.json）。

拆分理由：密钥与非敏感配置分离，避免备份/同步/排错时连带泄漏 key。
- `settings.local.json`      ：xxt.*（白名单/附件名单/class_map）、watermark、llm 段（非敏感部分）
- `settings.local.secrets.json`：llm.providers[].api_key（0600）
两个文件都已被 .gitignore 覆盖（`settings.local.json` / `settings.local.*.json`）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SETTINGS_FILE = "settings.local.json"
SECRETS_FILE = "settings.local.secrets.json"


def workspace(ws=None) -> Path:
    if ws is not None:
        return Path(ws).resolve()
    try:
        from .workspace import find_workspace
        return Path(find_workspace(None)).resolve()
    except Exception:  # noqa: BLE001
        return Path.cwd().resolve()


def settings_path(ws=None) -> Path:
    return workspace(ws) / SETTINGS_FILE


def secrets_path(ws=None) -> Path:
    return workspace(ws) / SECRETS_FILE


def _read_json(p: Path) -> dict:
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _write_json(p: Path, data: dict, *, secret: bool = False) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if secret:
        try:
            os.chmod(p, 0o600)
        except Exception:  # noqa: BLE001
            pass
    return p


def read_settings(ws=None) -> dict:
    return _read_json(settings_path(ws))


def write_settings(ws, data: dict) -> Path:
    return _write_json(settings_path(ws), data)


def read_secrets(ws=None) -> dict:
    return _read_json(secrets_path(ws))


def write_secrets(ws, data: dict) -> Path:
    return _write_json(secrets_path(ws), data, secret=True)


def update_settings(ws, fn) -> dict:
    """读取 → fn(dict) 就地修改 → 写回；返回新 dict。"""
    data = read_settings(ws)
    fn(data)
    write_settings(ws, data)
    return data


def update_secrets(ws, fn) -> dict:
    data = read_secrets(ws)
    fn(data)
    write_secrets(ws, data)
    return data
