"""D87 §2：水印样式库（命名样式 / 默认样式 / 与作业纸类型关联）。

- 样式文件：`<assets_dir>/watermark/styles/<样式名>.json`
  `{name, enabled, pageText, default, items:[{image,pos,ratio,alpha}], updatedAt}`
- 图片：`<assets_dir>/watermark/<文件名>`；`items[].image` 用**相对 assets_dir** 的
  `watermark/<文件名>`（兼容旧值 `assets/watermark/<文件名>`）；
- 解析优先级（作业纸 → 生效水印）：
  `pad.watermark.items`（包内显式） > `pad.watermark.style_ref`（命名样式） >
  默认样式（default=true，或名为 `_default`） > 引擎内置三槽默认。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from loguru import logger

DEFAULT_STYLE_NAME = "_default"
_NAME_RE = re.compile(r"^[^\\/:*?\"<>|]{1,40}$")


def _safe_name(name: str) -> str:
    n = str(name or "").strip()
    # 拒绝纯点（"."/".." 路径穿越）与非法字符/超长
    if not n or n.strip(".") == "":
        return ""
    return n if _NAME_RE.match(n) else ""


def list_styles(assets_dir: Path) -> list[dict]:
    from .assets import styles_dir
    out: list[dict] = []
    for f in sorted(styles_dir(assets_dir).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(d, dict):
            continue
        d.setdefault("name", f.stem)
        out.append(d)
    return out


def read_style(assets_dir: Path, name: str) -> "dict | None":
    from .assets import styles_dir
    n = _safe_name(name)
    if not n:
        return None
    p = styles_dir(assets_dir) / f"{n}.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001
        return None


def save_style(assets_dir: Path, name: str, data: dict, *, make_default: bool = False) -> dict:
    from .assets import styles_dir
    n = _safe_name(name)
    if not n:
        return {"ok": False, "error": "样式名非法（1..40 字符，不含路径分隔符）"}
    payload = {
        "name": n,
        "enabled": bool((data or {}).get("enabled", True)),
        "pageText": bool((data or {}).get("pageText", True)),
        "default": bool((data or {}).get("default", False)) or make_default,
        "items": [i for i in ((data or {}).get("items") or []) if isinstance(i, dict)],
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    p = styles_dir(assets_dir) / f"{n}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if payload["default"]:
        set_default(assets_dir, n)
    return {"ok": True, "style": payload, "file": str(p)}


def delete_style(assets_dir: Path, name: str) -> dict:
    from .assets import styles_dir
    n = _safe_name(name)
    p = styles_dir(assets_dir) / f"{n}.json" if n else None
    if not p or not p.is_file():
        return {"ok": False, "error": f"样式不存在：{name}"}
    p.unlink()
    return {"ok": True, "deleted": n}


def rename_style(assets_dir: Path, old: str, new: str) -> dict:
    from .assets import styles_dir
    o, nw = _safe_name(old), _safe_name(new)
    if not (o and nw):
        return {"ok": False, "error": "样式名非法"}
    src = styles_dir(assets_dir) / f"{o}.json"
    if not src.is_file():
        return {"ok": False, "error": f"样式不存在：{old}"}
    d = read_style(assets_dir, o) or {}
    d["name"] = nw
    res = save_style(assets_dir, nw, d)
    src.unlink()
    if (read_style(assets_dir, o) or {}).get("default"):
        set_default(assets_dir, nw)
    return res


def set_default(assets_dir: Path, name: str) -> dict:
    """单选默认样式（其余样式 default=false）。"""
    n = _safe_name(name)
    for st in list_styles(assets_dir):
        want = (str(st.get("name")) == n)
        if bool(st.get("default")) != want:
            save_style(assets_dir, str(st.get("name")), {**st, "default": want})
    return {"ok": True, "default": n}


def default_style(assets_dir: Path) -> "dict | None":
    for st in list_styles(assets_dir):
        if st.get("default"):
            return st
    return read_style(assets_dir, DEFAULT_STYLE_NAME)


def normalize_image_ref(image: str) -> str:
    """`assets/watermark/x.png` → `watermark/x.png`（统一相对 assets_dir 的口径）。"""
    s = str(image or "").strip().replace("\\", "/")
    if "/" not in s:
        return f"watermark/{s}" if s else ""
    if s.startswith("assets/"):
        return s[len("assets/"):]
    return s


def resolve_pad_watermark(assets_dir: Path, pad_watermark: "dict | None") -> dict:
    """按优先级解析某作业纸生效的水印（返回 {enabled,pageText,items,source}）。"""
    wm = pad_watermark if isinstance(pad_watermark, dict) else {}
    items = wm.get("items") if isinstance(wm.get("items"), list) else []
    if items:
        return {"enabled": bool(wm.get("enabled", True)),
                "pageText": bool(wm.get("pageText", True)),
                "items": [dict(i) for i in items], "source": "pad-items"}
    ref = str(wm.get("style_ref") or "").strip()
    if ref:
        st = read_style(assets_dir, ref)
        if st:
            return {"enabled": bool(st.get("enabled", True)),
                    "pageText": bool(st.get("pageText", True)),
                    "items": [dict(i) for i in (st.get("items") or [])], "source": f"style:{ref}"}
        logger.warning(f"作业纸引用的水印样式不存在：{ref}（回落默认样式）")
    st = default_style(assets_dir)
    if st:
        return {"enabled": bool(st.get("enabled", True)),
                "pageText": bool(st.get("pageText", True)),
                "items": [dict(i) for i in (st.get("items") or [])],
                "source": f"default:{st.get('name')}"}
    return {"enabled": bool(wm.get("enabled", True)), "pageText": True, "items": [], "source": "builtin"}
