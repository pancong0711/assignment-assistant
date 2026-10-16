"""D87 §1：素材目录解析（workspace 优先，engine 内置兜底）。

```
<workspace>/assets/
  watermark/            # 水印图片 + styles/<样式名>.json
  fonts/                # 可选：用户字体覆盖
  report/               # 预留：报告模板/封面
```

解析顺序：显式 `assets_dir` > `<ws>/assets`（存在 watermark/ 或 fonts/ 时）> 引擎内置 `engine/assets`。
"""
from __future__ import annotations

from pathlib import Path


def workspace_assets(ws) -> Path:
    return Path(ws).expanduser().resolve() / "assets"


def has_workspace_assets(ws) -> bool:
    d = workspace_assets(ws)
    return (d / "watermark").is_dir() or (d / "fonts").is_dir()


def resolve_assets_dir(ws=None, explicit=None):
    """返回 (assets_dir, source)；source ∈ {"explicit","workspace","engine"}。"""
    from .. import ASSETS_DIR
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_absolute() else (Path(ws).expanduser().resolve() / p), "explicit"
    if ws is not None:
        try:
            if has_workspace_assets(ws):
                return workspace_assets(ws), "workspace"
        except Exception:  # noqa: BLE001
            pass
    return Path(ASSETS_DIR), "engine"


def watermark_dir(assets_dir: Path) -> Path:
    return Path(assets_dir) / "watermark"


def styles_dir(assets_dir: Path) -> Path:
    d = watermark_dir(assets_dir) / "styles"
    d.mkdir(parents=True, exist_ok=True)
    return d
