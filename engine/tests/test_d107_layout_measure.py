"""D107：CLI 排版能力对等（sheet layout + 自动测量）。"""
import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner
from openpyxl import Workbook

from assist.cli import cli
from assist.files import solutions as sol


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    kb = ws / "kb"; kb.mkdir(parents=True)
    wb = Workbook(); sh = wb.active; sh.title = "chap04"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["c1", "求速度", "", 1, "", "计算", "", ""])
    wb.save(kb / "problems.xlsx")
    sol.add_version(ws, "c1", "解：$v=2t$ 得 20 m/s", source="ai")
    sol.pin_version(ws, "c1", "v1")
    task = {"id": "d107", "layout": {"orientation": "portrait", "per_page": 1},
            "items": [{"kb": "problems", "chap": "chap04", "ids": ["c1"], "tag": "t"}],
            "watermark": {"enabled": False}}
    (ws / "task.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    return ws


def test_sheet_layout_command_exists():
    assert "layout" in cli.commands["sheet"].commands


def test_measure_unavailable_degrades(monkeypatch, tmp_path):
    """Playwright/Chromium 不可用时：自动测量失败但**不阻断出图**（回退旧网格）。"""
    ws = _ws(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("chromium unavailable")

    import assist.paper.layout_measure as lm
    monkeypatch.setattr(lm, "measure_layout", _boom)
    r = CliRunner().invoke(cli, ["sheet", "html", "--task", str(ws / "task.json"),
                                 "-w", str(ws), "-o", str(ws / "o.html"), "--students", "blank"])
    assert r.exit_code == 0, r.output
    assert (ws / "o.html").exists()
    t = json.loads((ws / "task.json").read_text(encoding="utf-8"))
    assert "layout_result" not in t, "测量失败不应写入 layout_result"


def test_no_measure_flag_skips(tmp_path):
    ws = _ws(tmp_path)
    r = CliRunner().invoke(cli, ["sheet", "html", "--task", str(ws / "task.json"),
                                 "-w", str(ws), "-o", str(ws / "o.html"),
                                 "--students", "blank", "--no-measure"])
    assert r.exit_code == 0, r.output
    t = json.loads((ws / "task.json").read_text(encoding="utf-8"))
    assert "layout_result" not in t


def test_existing_layout_result_reused(monkeypatch, tmp_path):
    """已有 layout_result 时**不再测量**（避免重复开销）。"""
    ws = _ws(tmp_path)
    task = json.loads((ws / "task.json").read_text(encoding="utf-8"))
    task["layout_result"] = {"v": 1, "pages": [{"page": 1, "cells": [
        {"row": 0, "col": 0, "blocks": [{"qid": "c1", "no": "1.", "kind": "content",
                                         "text": "求速度", "cont": False}]}]}]}
    (ws / "task.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    called = {"n": 0}

    def _spy(*a, **k):
        called["n"] += 1
        raise RuntimeError("should not be called")

    import assist.paper.layout_measure as lm
    monkeypatch.setattr(lm, "measure_layout", _spy)
    r = CliRunner().invoke(cli, ["sheet", "html", "--task", str(ws / "task.json"),
                                 "-w", str(ws), "-o", str(ws / "o.html"), "--students", "blank"])
    assert r.exit_code == 0, r.output
    assert called["n"] == 0, "已有 layout_result 时不应触发测量"


def test_bundle_buildable():
    """前端算法 bundle 必须存在（构建期产物），否则 CLI 无法与 PWA 同源。"""
    from assist.paper.layout_measure import BUNDLE
    assert BUNDLE.exists(), f"缺少 {BUNDLE}；运行 node engine/tools/build-layout-bundle.mjs"


def test_bundle_exports_expected_symbols():
    from assist.paper.layout_measure import BUNDLE
    src = BUNDLE.read_text(encoding="utf-8")
    for fn in ["autoLayout", "cellGeometry", "solveGridForSolution"]:
        assert fn in src, f"bundle 缺少导出 {fn}"
