"""D121-G5：一键备份（workspace + 浏览器数据），**密钥强制脱敏**。

范围（D3 已拍板）：
- 收录：`kb/`、`classes/`、`tasks/`、`packs/`、`sheets/`、`settings.local.json`（脱敏）
- **不收录** `.runtime/`（可重建；作答原件可重新下载，体积大）

产物：`<out>/assignment-assistant-backup-<ts>.zip`
    manifest.json          版本/时间/workspace/统计/脱敏声明
    workspace/...          上述目录
    browser/...            PWA 传入的 localStorage 导出
"""
from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from loguru import logger

INCLUDE_DIRS = ("kb", "classes", "tasks", "packs", "sheets")
EXCLUDE_DIRS = (".runtime", "node_modules", ".git", ".history")
# 备份里**必须**脱敏的键（大小写不敏感，含子串匹配）
SECRET_KEYS = ("api_key", "apikey", "secret", "password", "passwd", "token",
               "access_key", "private_key")


def _is_secret_key(key: str) -> bool:
    k = str(key or "").lower()
    return any(s in k for s in SECRET_KEYS)


def redact(obj, *, _path: str = ""):
    """递归把密钥字段替换为 "***"（保留键名，便于教师知道该补什么）。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_secret_key(k) and isinstance(v, (str, int, float)) and str(v):
                out[k] = "***"
            else:
                out[k] = redact(v, _path=f"{_path}.{k}")
        return out
    if isinstance(obj, list):
        return [redact(v, _path=_path) for v in obj]
    return obj


def _iter_files(root: Path):
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in f.parts):
            continue
        if f.name.startswith("~$"):          # Office 临时文件
            continue
        yield f


def create_backup(ws, out_zip: "Path | None" = None,
                  browser_data: "dict | None" = None) -> dict:
    """生成备份 zip。返回 {ok, path, bytes, stats, redactedKeys}。"""
    ws = Path(ws).resolve()
    if out_zip is None:
        out_zip = ws / "backups" / f"assignment-assistant-backup-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    out_zip = Path(out_zip).expanduser().resolve()
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    stats: dict[str, int] = {}
    redacted: list[str] = []
    try:
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in INCLUDE_DIRS:
                d = ws / name
                if not d.is_dir():
                    continue
                n = 0
                for f in _iter_files(d):
                    rel = f.relative_to(ws)
                    zf.write(f, f"workspace/{rel.as_posix()}")
                    n += 1
                stats[name] = n

            # settings.local.json —— 强制脱敏
            st = ws / "settings.local.json"
            if st.is_file():
                try:
                    data = json.loads(st.read_text(encoding="utf-8"))
                    clean = redact(data)
                    zf.writestr("workspace/settings.local.json",
                                json.dumps(clean, ensure_ascii=False, indent=1))
                    stats["settings.local.json"] = 1
                    redacted.append("settings.local.json")
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"settings.local.json 脱敏失败，跳过：{exc}")

            # 浏览器数据（PWA 传入）
            if browser_data:
                clean_b = redact(browser_data)
                zf.writestr("browser/data.json",
                            json.dumps(clean_b, ensure_ascii=False, indent=1))
                stats["browser"] = len(browser_data)
                redacted.append("browser/data.json")

            manifest = {
                "kind": "assignment-assistant-backup",
                "version": 1,
                "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                "workspace": str(ws),
                "includedDirs": [n for n in INCLUDE_DIRS if n in stats],
                "excludedDirs": list(EXCLUDE_DIRS),
                "stats": stats,
                "redacted": redacted,
                "note": "密钥类字段已替换为 ***；.runtime/ 未收录（可重建）",
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}

    size = out_zip.stat().st_size if out_zip.is_file() else 0
    return {"ok": True, "path": str(out_zip), "bytes": size,
            "human": f"{size / 1024 / 1024:.1f} MB",
            "stats": stats, "redacted": redacted}


def verify_no_secrets(zip_path) -> dict:
    """自检：备份里不得出现真实密钥值。"""
    import re
    hits: list[str] = []
    try:
        with zipfile.ZipFile(Path(zip_path)) as zf:
            for name in zf.namelist():
                if not name.endswith(".json"):
                    continue
                try:
                    text = zf.read(name).decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    continue
                for m in re.finditer(r'"[^"]*(?:api_key|apikey|secret|password|token)[^"]*"\\s*:\\s*"([^"]*)"',
                                     text, re.I):
                    val = m.group(1).strip()
                    if val and val != "***":
                        hits.append(f"{name}: {val[:8]}…")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": not hits, "hits": hits}
