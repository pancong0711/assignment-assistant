"""D81：Workspace / kb 管理（路径显示、默认题库创建、旧题库迁移）。"""
from __future__ import annotations

import shutil
from pathlib import Path


def _default_workspace() -> Path:
    from ..workspace import DEFAULT_WORKSPACE
    return Path(DEFAULT_WORKSPACE).expanduser().resolve()


def workspace_info(ws=None) -> dict:
    from ..workspace import find_workspace
    from .allowlist import workspace as _ws
    cur = _ws(ws)
    default = _default_workspace()
    kb = cur / "kb"
    xlsx = sorted(p.name for p in kb.glob("*.xlsx")) if kb.is_dir() else []
    return {
        "ok": True,
        "workspace": str(cur),
        "defaultWorkspace": str(default),
        "isDefault": cur == default,
        "kbPath": str(kb),
        "kbExists": kb.is_dir(),
        "xlsx": xlsx,
        "xlsxCount": len(xlsx),
        "figDir": str(kb / "fig"),
        "historyDir": str(kb / ".history"),
        "exportDir": str(kb / "export"),
    }


def create_default_kb(ws=None) -> dict:
    """创建默认 kb 骨架（不安装依赖）。"""
    from .allowlist import workspace as _ws
    from ..bootstrap import bootstrap
    cur = _ws(ws)
    bootstrap(str(cur), sync_deps=False, quiet=True)
    return workspace_info(cur)


def migrate_kb(ws, src_dir: str) -> dict:
    """把旧 kb 目录（全部 xlsx + fig/.history/export）迁移到 <workspace>/kb。"""
    from .allowlist import workspace as _ws
    cur = _ws(ws)
    src = Path(str(src_dir)).expanduser().resolve()
    if not src.is_dir():
        return {"ok": False, "error": f"旧题库目录不存在：{src}"}
    dst = cur / "kb"
    dst.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    errors: list[str] = []
    # 全部 xlsx
    for p in src.glob("*.xlsx"):
        try:
            target = dst / p.name
            if target.exists():
                target = dst / f"{p.stem}-imported-{target.stat().st_mtime_ns}{p.suffix}"
            shutil.copy2(p, target)
            copied.append(target.name)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{p.name}: {e}")
    for sub in ("fig", ".history", "export"):
        s = src / sub
        if not s.is_dir():
            continue
        try:
            d = dst / sub
            d.mkdir(parents=True, exist_ok=True)
            for p in s.rglob("*"):
                if not p.is_file():
                    continue
                rel = p.relative_to(s)
                t = d / rel
                t.parent.mkdir(parents=True, exist_ok=True)
                if t.exists():
                    t = t.with_name(f"{t.stem}-imported-{t.stat().st_mtime_ns}{t.suffix}")
                shutil.copy2(p, t)
                copied.append(str(Path(sub) / rel))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sub}: {e}")
    return {"ok": not errors, "source": str(src), "target": str(dst),
            "copied": copied[:200], "copiedCount": len(copied), "errors": errors}
