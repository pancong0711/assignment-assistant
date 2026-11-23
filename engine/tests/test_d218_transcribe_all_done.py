"""D218：全班都已有转写时，点「转写+批阅」必须跳过转录而不是报错。

现场：`❌ AI 转写+批阅失败：assist.grading.items.ItemsError: items 必须是非空数组。`

根因：`_run_transcribe()` 在非 force 模式下会过滤“已有转写”的学生；
当**全班都已有转写**时过滤后 groups 为空，旧实现直接 `normalize_items([])`
→ ItemsError。正确行为是跳过转录，继续后续步骤（评阅/报告）。
"""
from __future__ import annotations

import json
from pathlib import Path

from assist.grading.flow import _run_transcribe


def _ctx(tmp_path: Path, *, names, force=False):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    return {
        "task": {},
        "plan": {"students": [{"name": n, "images": [str(img)]} for n in names]},
        "force": force,
        "concurrency": 1,
        "allow_partial": True,   # 测试里只验证“有没有尝试”，失败不中断

    }


def _transcripts(tmp_path: Path, names):
    d = tmp_path / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / f"{n}.json").write_text(
            json.dumps({"student": n, "items": []}, ensure_ascii=False), encoding="utf-8")
    return d


def test_all_have_transcripts_skips_instead_of_raising(tmp_path: Path):
    """核心回归：全班已有转写 → 返回 []，不抛 ItemsError。"""
    names = ["学生甲", "学生乙"]
    tdir = _transcripts(tmp_path, names)
    out = _run_transcribe(_ctx(tmp_path, names=names), client=None, transcripts_dir=tdir)
    assert out == []


def test_partial_missing_transcript_still_attempts(tmp_path: Path):
    """部分学生缺转写时不能整体跳过（会交给 transcribe_batch）。"""
    names = ["学生甲", "学生乙"]
    tdir = _transcripts(tmp_path, ["学生甲"])

    class _Client:
        evaluation_model = "fake"
        transcription_model = "fake"
        calls = 0

        def chat_with_images(self, **kw):  # 只验证“有没有尝试”
            _Client.calls += 1
            raise RuntimeError("fake client")

    # 不应因为“有一人已有转写”就整体跳过；会尝试转录学生乙（并记录失败）
    _run_transcribe(_ctx(tmp_path, names=names), client=_Client(), transcripts_dir=tdir)
    assert _Client.calls >= 1


def test_force_rerun_does_not_skip(tmp_path: Path):
    names = ["学生甲"]
    tdir = _transcripts(tmp_path, names)

    class _Client:
        evaluation_model = "fake"
        transcription_model = "fake"
        calls = 0

        def chat_with_images(self, **kw):
            _Client.calls += 1
            raise RuntimeError("fake client")

    _run_transcribe(_ctx(tmp_path, names=names, force=True), client=_Client(),
                    transcripts_dir=tdir)
    assert _Client.calls >= 1     # 强制重做时不应被“已有转写”跳过


def test_source_contract_for_d218():
    src = (Path(__file__).resolve().parents[1] / "src/assist/grading/flow.py").read_text(
        encoding="utf-8")
    assert "全部学生都已有转写" in src
    assert "return []" in src
