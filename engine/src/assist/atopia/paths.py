"""paths.py — D134-T2：Atopia 专用工作区 `<ws>/atopia/` 的**唯一路径出口** + 幂等迁移。

设计口径（docs/83 §1/§3）：
    <ws>/atopia/                 ← Atopia 专用工作区（**可整体删除**，删后回内置默认）
      limits.json                ← 护栏
      journal.jsonl              ← 审计
      extensions/                ← 教师写给 Atopia 的配置（AI 只读）

**硬性质**：删掉 `<ws>/atopia/` 后，引擎仍能启动、评阅仍能跑、护栏回默认、
工具级别回内置、扩展不生效；且**不得**影响 `materials/` 与 `<ws>/grading-rules.json`。

因此本模块只负责 Atopia 自己的状态；**规则本体**（`<ws>/grading-rules.json`）
与**教师原件**（`<ws>/materials/`）永远不在这里（否则"删 Atopia 连评阅/原件一起没"）。

历史包袱：D132 时期这些散在 workspace 根——
`<ws>/assistopia/limits.json`、`<ws>/assistopia/journal.jsonl`、`<ws>/extensions/`。
本模块提供**幂等**迁移：先复制、成功后再删除源；冲突时**新目录优先**，
旧的改名为 `<name>.bak-<时间戳>` 保留（不静默合并——配置静默合并最危险）。
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from loguru import logger

ROOT = "atopia"
LIMITS_FILE = "limits.json"
JOURNAL_FILE = "journal.jsonl"
EXTENSIONS_DIR = "extensions"

# 旧位置（D132）
LEGACY_ROOT = "assistopia"
LEGACY_EXTENSIONS = "extensions"


def atopia_root(ws) -> Path:
    return Path(ws).resolve() / ROOT


def limits_path(ws) -> Path:
    return atopia_root(ws) / LIMITS_FILE


def journal_path(ws) -> Path:
    return atopia_root(ws) / JOURNAL_FILE


def extensions_dir(ws) -> Path:
    return atopia_root(ws) / EXTENSIONS_DIR


def ensure_root(ws) -> Path:
    """创建 `atopia/` 骨架（只新建，不覆盖）。"""
    r = atopia_root(ws)
    r.mkdir(parents=True, exist_ok=True)
    return r


def _ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _move_aside(p: Path, *, what: str) -> str:
    """把冲突的旧路径改名为 `<name>.bak-<ts>`（不删，留痕）。"""
    dest = p.with_name(f"{p.name}.bak-{_ts()}")
    n = 1
    while dest.exists():
        dest = p.with_name(f"{p.name}.bak-{_ts()}-{n}")
        n += 1
    p.rename(dest)
    logger.warning(f"[atopia] 迁移冲突：{what} 保留旧副本 → {dest.name}（新目录优先）")
    return dest.name


def _copy_file_if_absent(src: Path, dst: Path) -> "str | None":
    """src → dst：dst 存在则不覆盖（新目录优先），返回保留的旧副本名或 None。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return None                     # 新目录已有：直接丢旧（不覆盖）
    shutil.copy2(src, dst)
    return None


def migrate_legacy(ws, *, journal: bool = True) -> dict:
    """把 D132 的旧位置迁到 `<ws>/atopia/`。**幂等**：无旧路径时直接返回 done。

    返回 {"ok": bool, "moved": [...], "keptOld": [...], "skipped": [...]}。
    """
    ws_p = Path(ws).resolve()
    moved: list[str] = []
    kept: list[str] = []
    skipped: list[str] = []

    legacy_root = ws_p / LEGACY_ROOT
    legacy_ext = ws_p / LEGACY_EXTENSIONS
    if not legacy_root.exists() and not legacy_ext.exists():
        return {"ok": True, "moved": [], "keptOld": [], "skipped": ["无旧目录"]}

    try:
        ensure_root(ws_p)
    except OSError as exc:
        # 只读 workspace（如 XXT_HOME 挂载）：迁移不能致命
        logger.warning(f"[atopia] 无法创建 atopia/（{exc}），跳过迁移")
        return {"ok": True, "moved": [], "keptOld": [], "skipped": [f"只读：{exc}"]}

    # --- 1) <ws>/assistopia/{limits.json,journal.jsonl} → <ws>/atopia/ ---
    if legacy_root.is_dir():
        for name in (LIMITS_FILE, JOURNAL_FILE):
            src = legacy_root / name
            if not src.is_file():
                continue
            dst = atopia_root(ws_p) / name
            if dst.exists():
                # 新目录优先：旧文件留 .bak（不删，审计可查）
                try:
                    kept.append(_move_aside(src, what=str(name)))
                except OSError as exc:
                    skipped.append(f"{name}: {exc}")
                continue
            try:
                _copy_file_if_absent(src, dst)
                src.unlink()
                moved.append(f"{LEGACY_ROOT}/{name} → {ROOT}/{name}")
            except OSError as exc:
                skipped.append(f"{name}: {exc}")
        # 旧根目录空了就删掉（里面还有别的东西就留着）
        try:
            if not any(legacy_root.iterdir()):
                legacy_root.rmdir()
        except OSError:
            pass

    # --- 2) <ws>/extensions/ → <ws>/atopia/extensions/ ---
    if legacy_ext.is_dir():
        dst = extensions_dir(ws_p)
        if dst.exists():
            # 两边都有扩展：**不静默合并**（教师无法判断哪条生效）
            try:
                kept.append(f"{LEGACY_EXTENSIONS} → {_move_aside(legacy_ext, what='extensions/')}")
            except OSError as exc:
                skipped.append(f"extensions/: {exc}")
        else:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(legacy_ext), str(dst))
                moved.append(f"{LEGACY_EXTENSIONS}/ → {ROOT}/{EXTENSIONS_DIR}/")
            except OSError as exc:
                skipped.append(f"extensions/: {exc}")

    ok = not skipped
    if journal and (moved or kept):
        try:
            _append_migration_journal(ws_p, {"ts": _now(), "moved": moved, "keptOld": kept})
        except OSError:
            pass
    return {"ok": ok, "moved": moved, "keptOld": kept, "skipped": skipped}


_migrated: set[str] = set()


def ensure_migrated(ws) -> dict:
    """进程内**只迁一次**的入口（给 CLI/serve 的热路径调）。

    迁移失败/只读环境**不抛**：Atopia 是覆盖层，旧目录留在原地也能继续用。
    """
    key = str(Path(ws).resolve()) if ws is not None else ""
    if not key or key in _migrated:
        return {"ok": True, "moved": [], "keptOld": [], "skipped": ["已处理"]}
    _migrated.add(key)
    try:
        return migrate_legacy(ws)
    except Exception as exc:  # noqa: BLE001 —— 迁移永远不阻断主流程
        logger.warning(f"[atopia] 迁移异常（已忽略）：{exc}")
        return {"ok": False, "moved": [], "keptOld": [], "skipped": [str(exc)]}


def reset(ws, *, keep_extensions: bool = True) -> dict:
    """清空 `atopia/` 的运行状态（**L3：不开放给 AI**）。

    - 删 `limits.json`（回默认）、清空 `journal.jsonl`、删 `sessions/`（若有）；
    - `keep_extensions=True` 时**保留** `extensions/`（教师资产）。
    默认**不删 extensions**：它不是运行产物，是教师手工写的配置。
    """
    import shutil as _sh
    r = atopia_root(ws)
    if not r.is_dir():
        return {"ok": True, "removed": [], "kept": []}
    removed: list[str] = []
    kept: list[str] = []
    for p in sorted(r.iterdir()):
        if p.name == EXTENSIONS_DIR:
            if keep_extensions:
                kept.append(p.name)
                continue
        try:
            if p.is_dir():
                _sh.rmtree(p)
            else:
                p.unlink()
            removed.append(p.name)
        except OSError as exc:
            logger.warning(f"[atopia] reset 无法删除 {p.name}：{exc}")
    for p in (atopia_root(ws) / EXTENSIONS_DIR).glob("*.bak-*"):
        kept.append(p.name)
    try:
        _append_migration_journal(ws, {"ts": _now(), "moved": [],
                                       "keptOld": [f"reset 删除 {x}" for x in removed]})
    except OSError:
        pass
    return {"ok": True, "removed": removed, "kept": kept}


def _append_migration_journal(ws, rec: dict) -> None:
    p = journal_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": "atopia.migrate", "level": "L3", "status": "ok",
                            "confirmed_by": "engine:startup", **rec},
                           ensure_ascii=False) + "\n")
