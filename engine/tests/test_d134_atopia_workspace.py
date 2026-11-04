"""D134-T2：`<ws>/atopia/` 专用工作区 + 幂等迁移 + 「删除即回默认」硬性质。

核心断言（docs/83 §1、§5-3/5/5）：
1. 护栏/journal/扩展全部落在 `<ws>/atopia/`；
2. 旧位置（`<ws>/assistopia/`、`<ws>/extensions/`）自动迁入，幂等；
3. 冲突时**新目录优先**、旧的留 `.bak-<ts>`（不静默合并）；
4. **删掉 `<ws>/atopia/` 后**：护栏回默认、工具回内置、扩展不生效，
   且 `<ws>/materials/` 与 `<ws>/grading-rules.json` **不受影响**；
5. `rules` / `materials` **不在** `atopia/` 内（防「删 Atopia 连规则/原件一起没」）。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from assist.atopia import limits as L
from assist.atopia import paths as P
from assist.atopia import registry as R
from assist.atopia import runner as RN


@pytest.fixture()
def ws(tmp_path):
    d = tmp_path / "ws"
    d.mkdir()
    P._migrated.clear()
    return d


# ---------------- 路径归属 ----------------
def test_paths_all_under_atopia(ws):
    root = P.atopia_root(ws)
    assert root == ws / "atopia"
    assert P.limits_path(ws).parent == root
    assert P.journal_path(ws).parent == root
    assert P.extensions_dir(ws).parent == root
    assert L.limits_path(ws) == root / "limits.json"
    assert RN.journal_path(ws) == root / "journal.jsonl"
    assert R.extensions_dir(ws) == root / "extensions"


def test_rules_and_materials_not_inside_atopia(ws):
    """规则本体与教师原件**必须**在 atopia/ 之外（否则删 Atopia 会连累它们）。"""
    assert (ws / "atopia") not in (ws / "grading-rules.json").parents
    assert (ws / "atopia") not in (ws / "materials").parents


def test_limits_read_write_roundtrip(ws):
    rep = L.write_limits(ws, {"maxCallsPerSession": 12})
    assert rep.get("ok") is not False
    assert L.read_limits(ws)["maxCallsPerSession"] == 12
    assert (ws / "atopia" / "limits.json").is_file()


# ---------------- 迁移 ----------------
def test_migrate_legacy_limits_and_journal(ws):
    legacy = ws / "assistopia"
    legacy.mkdir()
    (legacy / "limits.json").write_text(json.dumps({"maxCallsPerSession": 7}), encoding="utf-8")
    (legacy / "journal.jsonl").write_text('{"tool": "x"}\n', encoding="utf-8")

    rep = P.migrate_legacy(ws)
    assert rep["ok"] is True
    assert (ws / "atopia" / "limits.json").is_file()
    assert L.read_limits(ws)["maxCallsPerSession"] == 7
    _j = (ws / "atopia" / "journal.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert _j[0] == '{"tool": "x"}'            # 旧记录原样保留
    assert any("atopia.migrate" in ln for ln in _j)   # 迁移本身也留痕
    # 旧根目录搬空后应清掉；旧文件不残留
    assert not legacy.exists()


def test_migrate_legacy_extensions(ws):
    (ws / "extensions" / "tools").mkdir(parents=True)
    (ws / "extensions" / "tools" / "a.json").write_text(
        json.dumps({"name": "kb.stats", "level": "L2"}), encoding="utf-8")

    rep = P.migrate_legacy(ws)
    assert rep["ok"] is True
    assert (ws / "atopia" / "extensions" / "tools" / "a.json").is_file()
    assert not (ws / "extensions").exists()
    # 迁移后覆盖仍生效（L0 → L2）
    ov = R.load_overrides(ws)
    assert ov.get("kb.stats") == "L2"


def test_migrate_idempotent(ws):
    (ws / "assistopia").mkdir()
    (ws / "assistopia" / "limits.json").write_text("{}", encoding="utf-8")
    P.migrate_legacy(ws)
    rep2 = P.migrate_legacy(ws)                       # 第二次：无旧目录 → 直接 done
    assert rep2["ok"] is True
    assert rep2["skipped"] == ["无旧目录"]


def test_migrate_conflict_new_wins_old_kept_as_bak(ws):
    """两边都有 limits.json：**新目录优先**，旧的留 .bak（不静默合并）。"""
    P.ensure_root(ws)
    (ws / "atopia" / "limits.json").write_text(
        json.dumps({"maxCallsPerSession": 11}), encoding="utf-8")
    (ws / "assistopia").mkdir()
    (ws / "assistopia" / "limits.json").write_text(
        json.dumps({"maxCallsPerSession": 99}), encoding="utf-8")

    rep = P.migrate_legacy(ws)
    assert rep["ok"] is True
    assert rep["keptOld"], "冲突时旧文件必须留 .bak"
    assert L.read_limits(ws)["maxCallsPerSession"] == 11   # 新目录优先
    baks = list((ws / "assistopia").glob("limits.json.bak-*"))
    assert baks, "旧版本应以 .bak-<ts> 保留（可追溯）"


def test_migrate_conflicting_extensions_not_silently_merged(ws):
    P.extensions_dir(ws).mkdir(parents=True)
    (ws / "atopia" / "extensions" / "tools").mkdir(parents=True)
    (ws / "atopia" / "extensions" / "tools" / "new.json").write_text(
        json.dumps({"name": "kb.stats", "level": "L1"}), encoding="utf-8")
    (ws / "extensions" / "tools").mkdir(parents=True)
    (ws / "extensions" / "tools" / "old.json").write_text(
        json.dumps({"name": "kb.stats", "level": "L3"}), encoding="utf-8")

    rep = P.migrate_legacy(ws)
    assert rep["ok"] is True
    assert rep["keptOld"], "两边都有 extensions/ 时不允许静默合并"
    # 旧目录整体改名保留，内容没被混进新目录
    assert not (ws / "atopia" / "extensions" / "tools" / "old.json").exists()


def test_ensure_migrated_runs_once(ws):
    (ws / "assistopia").mkdir()
    (ws / "assistopia" / "limits.json").write_text("{}", encoding="utf-8")
    a = P.ensure_migrated(ws)
    b = P.ensure_migrated(ws)
    assert a["moved"]
    assert b["skipped"] == ["已处理"]


# ---------------- 「删除即回默认」硬性质 ----------------
def test_delete_atopia_restores_defaults(ws):
    # 先造出非默认状态
    L.write_limits(ws, {"maxCallsPerSession": 15})
    P.extensions_dir(ws, ).mkdir(parents=True, exist_ok=True)
    (ws / "atopia" / "extensions" / "tools").mkdir(parents=True, exist_ok=True)
    (ws / "atopia" / "extensions" / "tools" / "a.json").write_text(
        json.dumps({"name": "kb.stats", "level": "L2"}), encoding="utf-8")
    assert L.read_limits(ws)["maxCallsPerSession"] == 15
    assert R.load_overrides(ws).get("kb.stats") == "L2"

    # 教师原件 + 规则本体（必须与 atopia/ 无关）
    (ws / "materials" / "chap04" / "_source").mkdir(parents=True)
    (ws / "materials" / "chap04" / "_source" / "a.pptx").write_bytes(b"PK\x03\x04")
    (ws / "grading-rules.json").write_text(json.dumps({"version": 1}), encoding="utf-8")

    shutil.rmtree(ws / "atopia")            # 整个删掉

    # 1) 护栏回默认，且**不报错**
    assert L.read_limits(ws)["maxCallsPerSession"] == L.DEFAULTS["maxCallsPerSession"]
    # 2) 工具回内置级别
    assert R.load_overrides(ws) == {}
    assert len(R.effective_tools(ws)) == len(R.BUILTIN_TOOLS)
    # 3) journal 读取不崩（空）
    assert RN.read_journal(ws) == []
    # 4) 教师原件与规则本体**不受影响**
    assert (ws / "materials" / "chap04" / "_source" / "a.pptx").is_file()
    assert json.loads((ws / "grading-rules.json").read_text(encoding="utf-8"))["version"] == 1


def test_delete_atopia_grading_rules_still_work(ws):
    """删掉 atopia/ 后评阅规则仍可读（规则本体不在 atopia/ 内）。"""
    from assist.grading import rules as GR
    P.ensure_root(ws)
    (ws / "atopia" / "extensions" / "rules").mkdir(parents=True, exist_ok=True)
    (ws / "atopia" / "extensions" / "rules" / "grading-rules.json").write_text(
        json.dumps({"global": {"briefProcessDeduct": 9}}), encoding="utf-8")
    assert GR.global_rules(ws)["briefProcessDeduct"] == 9     # 扩展生效

    shutil.rmtree(ws / "atopia")
    assert GR.global_rules(ws)["briefProcessDeduct"] == \
        GR.DEFAULT_RULES["global"]["briefProcessDeduct"]      # 回内置默认


# ---------------- reset（L3，不开放给 AI） ----------------
def test_reset_keeps_extensions_by_default(ws):
    L.write_limits(ws, {"maxCallsPerSession": 13})
    (ws / "atopia" / "extensions").mkdir(parents=True, exist_ok=True)
    (ws / "atopia" / "extensions" / "knowledge-terms.json").write_text("{}", encoding="utf-8")

    rep = P.reset(ws)
    assert rep["ok"] is True
    assert "limits.json" in rep["removed"]
    assert "extensions" in rep["kept"]
    assert L.read_limits(ws)["maxCallsPerSession"] == L.DEFAULTS["maxCallsPerSession"]
    assert (ws / "atopia" / "extensions" / "knowledge-terms.json").is_file()


def test_reset_can_drop_extensions(ws):
    (ws / "atopia" / "extensions").mkdir(parents=True, exist_ok=True)
    (ws / "atopia" / "extensions" / "x.json").write_text("{}", encoding="utf-8")
    rep = P.reset(ws, keep_extensions=False)
    assert "extensions" in rep["removed"]
    assert not (ws / "atopia" / "extensions").exists()


def test_reset_not_registered_as_ai_tool():
    """`atopia reset`（删除）不注册为 AI 工具（docs/81 §2 L3 口径）。

    注意 `rules.reset` 是**评阅规则**恢复默认，与本命令不是一回事。
    """
    names = {t.name for t in R.BUILTIN_TOOLS}
    assert not any(n.startswith("atopia.") for n in names)
    assert "atopia.reset" not in names
