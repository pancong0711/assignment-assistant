"""D106：转录图片分段压缩 + SVG 重绘开关。"""
from pathlib import Path

import pytest
from PIL import Image

from assist.grading.imageprep import (BIG_BYTES, FREE_BYTES, MAX_SIDE_FREE,
                                      compress_for_model)


def _mk(path: Path, size, *, quality=92, fmt="JPEG") -> Path:
    Image.new("RGB", size, (200, 200, 200)).save(path, format=fmt, quality=quality)
    return path


def test_small_image_passthrough(tmp_path):
    p = _mk(tmp_path / "small.jpg", (800, 600))
    data, mime, meta = compress_for_model(p)
    assert meta["strategy"] == "passthrough"
    assert data == p.read_bytes(), "小图必须原样发送"
    assert meta["orig_bytes"] == meta["sent_bytes"]


def test_oversize_long_side_resized(tmp_path):
    p = _mk(tmp_path / "big.jpg", (4000, 3000), quality=95)
    data, mime, meta = compress_for_model(p)
    assert meta["strategy"] != "passthrough"
    assert meta["sent_side"] <= MAX_SIDE_FREE, "长边应缩到 2000 以内"
    assert len(data) < meta["orig_bytes"]


def test_original_mode_keeps_raw(tmp_path):
    p = _mk(tmp_path / "big.jpg", (4000, 3000), quality=95)
    raw = p.read_bytes()
    data, mime, meta = compress_for_model(p, mode="original")
    assert data == raw
    assert meta["strategy"] == "original"
    assert meta["sent_bytes"] == meta["orig_bytes"]


def test_original_file_not_modified(tmp_path):
    p = _mk(tmp_path / "big.jpg", (3000, 2000), quality=95)
    before = p.read_bytes()
    compress_for_model(p)
    assert p.read_bytes() == before, "压缩不得修改原图"


def test_png_lineart_stays_png(tmp_path):
    p = tmp_path / "line.png"
    Image.new("RGB", (2400, 1800), (255, 255, 255)).save(p, format="PNG")
    data, mime, meta = compress_for_model(p)
    if meta["strategy"] != "passthrough":
        assert mime == "image/png", "PNG 线稿应保持 PNG"


def test_meta_fields(tmp_path):
    p = _mk(tmp_path / "big.jpg", (4000, 3000), quality=95)
    _, _, meta = compress_for_model(p)
    for k in ("strategy", "orig_bytes", "sent_bytes"):
        assert k in meta


def test_undecodable_falls_back(tmp_path):
    p = tmp_path / "broken.jpg"
    p.write_bytes(b"not-an-image")
    data, mime, meta = compress_for_model(p)
    assert meta["strategy"] == "decode-failed"
    assert data == b"not-an-image", "无法解码时原样发送（不报错）"


# ---------------- SVG 重绘开关 ----------------

def test_transcription_prompt_svg_toggle():
    from assist.grading.prompts import transcription_prompt
    off = transcription_prompt(False)
    on = transcription_prompt(True)
    assert "内联 SVG" not in off, "默认关：不得含 SVG 重绘指令"
    assert "内联 SVG" in on
    assert "<svg viewBox" in on


def test_system_prompt_respects_env(monkeypatch):
    from assist.grading import transcribe
    monkeypatch.delenv("ASSIST_SVG_REDRAW", raising=False)
    assert "内联 SVG" not in transcribe._system_prompt()
    monkeypatch.setenv("ASSIST_SVG_REDRAW", "1")
    assert "内联 SVG" in transcribe._system_prompt()
