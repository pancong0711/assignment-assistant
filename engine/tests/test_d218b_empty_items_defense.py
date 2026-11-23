"""D218-FIX2：任何入口都不应把“空 items”变成崩溃；并能确认引擎版本。

教师反馈“相同操作仍报 items 必须是非空数组”——仓库代码已无该路径，
说明运行中的引擎可能仍是旧发布包。为此：
1) batchrun / transcribe_batch 对空 items 返回空报告（不崩）；
2) flow 把 ItemsError 转成可读 GradingInputError；
3) 每个后台任务第一行打印 `[engine] version=… commit=…`，便于核对是否加载了修复。
"""
from __future__ import annotations

from pathlib import Path

from assist.grading.batchrun import run_items
from assist.grading.transcribe import transcribe_batch


def test_batchrun_empty_no_raise(tmp_path: Path):
    rep = run_items([], lambda it: {"ok": True}, kind="transcribe", out_dir=tmp_path)
    assert rep["total"] == 0 and rep.get("empty") is True
    assert "没有需要处理的条目" in rep.get("note", "")


def test_transcribe_batch_empty_no_raise(tmp_path: Path):
    rep = transcribe_batch(None, [], tmp_path / "t")
    assert rep["total"] == 0 and rep.get("empty") is True


def test_flow_has_readable_wrapper():
    src = (Path(__file__).resolve().parents[1] / "src/assist/grading/flow.py").read_text(
        encoding="utf-8")
    assert "转录阶段没有可处理的学生" in src
    assert "except _ItemsError as exc" in src


def test_serve_prints_engine_banner():
    src = (Path(__file__).resolve().parents[1] / "src/assist/serve.py").read_text(
        encoding="utf-8")
    assert "[engine] version=" in src
    assert "get_commit" in src


def test_start_bat_forces_update_when_version_file_missing():
    """删除 _engine/engine-version.json 会触发重新下载（教师现场可用来强制更新）。"""
    repo = Path(__file__).resolve().parents[2]
    src = (repo / "tools/start.bat").read_text(encoding="utf-8", errors="replace")
    assert 'IF NOT EXIST "%VERSION_LOCAL%" goto ENGINE_DOWNLOAD' in src
