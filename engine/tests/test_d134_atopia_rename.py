"""D134-T1：`assistopia` → `atopia` 更名的兼容性回归。

改名是纯机械的，唯一风险是**漏改导致静默失效**。本文件锁三件事：
1. 新包可导入，旧包名不再存在（避免"两套并存"的幽灵模块）；
2. CLI 旧名 `assist assistopia` 仍可用（argv 别名）；
3. HTTP 旧路由 `/assistopia/*` 仍能转发到 `/atopia/*`。
"""
from __future__ import annotations

import importlib


def test_atopia_package_importable():
    for mod in ("assist.atopia", "assist.atopia.registry", "assist.atopia.runner",
                "assist.atopia.limits", "assist.atopia.extensions",
                "assist.atopia.agent"):
        assert importlib.import_module(mod) is not None


def test_old_package_name_gone():
    """旧包名必须**不能**导入：两套并存会让修复只改到一套。"""
    try:
        importlib.import_module("assist.assistopia")
    except ModuleNotFoundError:
        return
    raise AssertionError("assist.assistopia 仍然存在（改名未彻底）")


def test_cli_alias_rewrites_first_subcommand():
    from assist.cli import _alias_assistopia_argv
    assert _alias_assistopia_argv(["assistopia", "tools"]) == ["atopia", "tools"]
    assert _alias_assistopia_argv(["assistopia", "run", "--tool", "x"]) == \
        ["atopia", "run", "--tool", "x"]
    # 新名不动
    assert _alias_assistopia_argv(["atopia", "tools"]) == ["atopia", "tools"]
    # 其他命令不动（`materials` 等不受影响）
    assert _alias_assistopia_argv(["materials", "list"]) == ["materials", "list"]
    # 空 argv 安全
    assert _alias_assistopia_argv([]) == []


def test_legacy_http_path_rewritten():
    from assist.serve import _rewrite_legacy_atopia
    assert _rewrite_legacy_atopia("/assistopia/tools") == ("/atopia/tools", True)
    assert _rewrite_legacy_atopia("/assistopia/journal") == ("/atopia/journal", True)
    assert _rewrite_legacy_atopia("/assistopia") == ("/atopia", True)
    # 新路径原样
    assert _rewrite_legacy_atopia("/atopia/tools") == ("/atopia/tools", False)
    # 不含该前缀的路径不被误伤
    assert _rewrite_legacy_atopia("/materials/list") == ("/materials/list", False)
    assert _rewrite_legacy_atopia("/x/assistopia/tools") == ("/x/assistopia/tools", False)


def test_tool_registry_still_intact():
    """改名不能动工具清单（D148 新增 fs.ls/fs.read/fs.search → 34 个）。

    L3 仍为 5 个且写死拒绝——新增工具不得引入新的危险入口。
    """
    from assist.atopia.registry import BUILTIN_TOOLS, L3
    assert len(BUILTIN_TOOLS) == 34
    assert len([t for t in BUILTIN_TOOLS if t.level == L3]) == 5
