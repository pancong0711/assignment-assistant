"""D72：学习通 run/pages/shots 统一 artifact 路径契约。

CLI `xxt extract` 与 serve `/xxt/*` 必须共用这里，避免再次出现
“CLI 写到 runs/，PWA 只扫根目录”的漂移。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

_EXCLUDE_NAMES = {
    "xxt-extract-targets.json",   # D74-6：旧 targets spec，误被当成 run
    "xxt-readonly.json",
    "xxt-notices.json",
    "xxt-session-check.json",
    "xxt-storage.json",
    "xxt-login-state.json",
}


def _home(home: "Path | str | None" = None) -> Path:
    if home is not None:
        return Path(home)
    from .session import xxt_home
    return xxt_home()


def runs_dir(home: "Path | str | None" = None) -> Path:
    return _home(home) / "runs"

def targets_json(home: "Path | str | None" = None) -> Path:
    """D72 targets 模式：最近一次只读发现（课程/班级清单）的落盘位置。"""
    return _home(home) / "targets.json"


def targets_spec_json(home: "Path | str | None" = None) -> Path:
    """D74-6：提取勾选清单落到非 run 扫描目录，避免被当成 run。"""
    return _home(home) / "targets" / "extract-spec.json"


def targets_history_dir(home: "Path | str | None" = None) -> Path:
    """D74-3：发现结果历史快照目录（默认保留最近 5 份）。"""
    return _home(home) / "targets-history"


def is_run_shape(data) -> bool:
    """D74-6：run JSON 形状白名单（纯函数）。

    必须：dict、`courses` 是 list、`run_id` 以 `xxt-` 开头。
    不满足者（如 targets spec）不得进入 run 列表/详情。
    """
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("courses"), list):
        return False
    rid = str(data.get("run_id") or "")
    return rid.startswith("xxt-")


def pages_dir(home: "Path | str | None" = None) -> Path:
    return _home(home) / "pages"


def shots_dir(home: "Path | str | None" = None) -> Path:
    return pages_dir(home) / "shots"


def _legacy_shots_dir(home: "Path | str | None" = None) -> Path:
    return _home(home) / "xxt-pages" / "shots"


def run_pages_dir(run_id: str, home: "Path | str | None" = None) -> Path:
    """D73-11：单条 run 的 HTML 存档目录（pages/runs/<run_id>/）。

    新契约：每个 run 的 HTML 存档独立归档，删除 run 时可一并删除；
    旧版平铺在 pages/ 根目录的存档仍兼容读取，但不随单 run 删除（跨 run 共享）。
    """
    return pages_dir(home) / "runs" / run_id


def _read_run_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def run_json_files(home: "Path | str | None" = None, validate: bool = True) -> list[Path]:
    """返回 run JSON 列表（新 runs/ 优先；兼容旧 home 根目录）。

    D74-6：默认按 is_run_shape 校验内容，targets spec 等非 run 文件不再混入。
    """
    home = _home(home)
    found: dict[str, Path] = {}
    for d in (runs_dir(home), home):
        if not d.is_dir():
            continue
        for f in d.glob("xxt-*.json"):
            if f.name in _EXCLUDE_NAMES or "login-state" in f.name:
                continue
            if validate and not is_run_shape(_read_run_json(f)):
                continue
            # runs/ 优先；若已存在同名，不用 home 根目录覆盖
            found.setdefault(f.name, f)
    return sorted(found.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def find_run_json(run_id: str, home: "Path | str | None" = None) -> "Path | None":
    home = _home(home)
    for d in (runs_dir(home), home):
        p = d / f"{run_id}.json"
        if p.is_file() and is_run_shape(_read_run_json(p)):
            return p
    return None


def shot_candidates(run_id: str, fname: str,
                    home: "Path | str | None" = None) -> list[Path]:
    """返回可能的截图路径；新 pages/shots 优先，兼容旧 xxt-pages/shots。"""
    home = _home(home)
    names = [f"{run_id}-step{fname}", fname]
    out: list[Path] = []
    for d in (shots_dir(home), _legacy_shots_dir(home)):
        for name in names:
            p = d / name
            if p.is_file() and p.suffix.lower() == ".png":
                out.append(p)
    return out

def delete_run_artifacts(run_id: str, home: "Path | str | None" = None) -> list[str]:
    """D73：删除单条 run 的 JSON 与 run 级截图；返回已删路径（字符串）。

    HTML 存档当前按 class/work 命名、跨 run 共享，不在这里删除，避免误删其他 run。
    """
    home = _home(home)
    removed: list[str] = []
    for d in (runs_dir(home), home):
        p = d / f"{run_id}.json"
        if p.is_file():
            p.unlink()
            removed.append(str(p))
    for d in (shots_dir(home), _legacy_shots_dir(home)):
        if not d.is_dir():
            continue
        for p in d.glob(f"{run_id}-*.png"):
            if p.is_file():
                p.unlink()
                removed.append(str(p))
    # D73-11：run 级 HTML 存档目录
    rp = run_pages_dir(run_id, home)
    if rp.is_dir():
        removed.extend(str(p) for p in rp.rglob("*") if p.is_file())
        shutil.rmtree(rp, ignore_errors=True)
    return removed


def clear_runs(home: "Path | str | None" = None) -> dict:
    """D73-11：清空全部 run（JSON + run 级截图 + run 级 HTML 存档）。

    只处理 run_json_files() 识别出的 run；会话文件（xxt-storage 等）永不触碰。
    """
    home = _home(home)
    run_ids: list[str] = []
    seen: set[str] = set()
    for f in run_json_files(home):
        stem = f.stem
        if stem in seen:
            continue
        seen.add(stem)
        run_ids.append(stem)
    removed: list[str] = []
    for rid in run_ids:
        removed.extend(delete_run_artifacts(rid, home))
    return {"runs": run_ids, "removed": removed}
