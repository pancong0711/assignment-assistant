"""D98-B1：items 统一契约 + 结构性隔离（每条请求不含他条的题干/图片）。"""
import json
from pathlib import Path

import pytest

from assist.grading.items import (ItemsError, build_messages, image_files, load_items_file,
                                  normalize_items)


def test_normalize_keeps_items_separate(tmp_path):
    raw = [
        {"id": "s1", "question": "转录学生甲", "images": ["a1.png", "a2.png"]},
        {"id": "s2", "question": "转录学生乙", "images": ["b1.png"]},
    ]
    items = normalize_items(raw, base_dir=tmp_path)
    assert items[0]["images"] == [str(tmp_path / "a1.png"), str(tmp_path / "a2.png")]
    assert items[1]["images"] == [str(tmp_path / "b1.png")]
    # 同生多页在一条里（裁决 1）
    assert len(items[0]["images"]) == 2


def test_rejects_duplicate_or_bad_id():
    with pytest.raises(ItemsError):
        normalize_items([{"id": "x"}, {"id": "x"}])
    with pytest.raises(ItemsError):
        normalize_items([{"id": "a/b"}])
    with pytest.raises(ItemsError):
        normalize_items([{}])
    with pytest.raises(ItemsError):
        normalize_items([])


def test_build_messages_isolated_by_signature():
    """build_messages 只接受**单条** item —— 结构上无法把别的条拼进来。"""
    items = normalize_items([
        {"id": "s1", "question": "学生甲的作答内容AAA", "images": ["a.png"]},
        {"id": "s2", "question": "学生乙的作答内容BBB", "images": ["b.png"]},
    ])
    m1 = build_messages(items[0], default_system="sys", user_text=items[0]["question"],
                        image_data_urls=["data:image/png;base64,AAAA"])
    m2 = build_messages(items[1], default_system="sys", user_text=items[1]["question"],
                        image_data_urls=["data:image/png;base64,BBBB"])
    dump1 = json.dumps(m1, ensure_ascii=False)
    dump2 = json.dumps(m2, ensure_ascii=False)
    assert "AAA" in dump1 and "BBB" not in dump1
    assert "BBB" in dump2 and "AAA" not in dump2
    assert "AAAA" in dump1 and "BBBB" not in dump1
    assert "BBBB" in dump2 and "AAAA" not in dump2


def test_load_items_file_resolves_relative_to_file(tmp_path):
    f = tmp_path / "batch.json"
    f.write_text(json.dumps({"items": [{"id": "s1", "question": "q", "images": ["x.png"]}]}),
                 encoding="utf-8")
    items = load_items_file(f)
    assert items[0]["images"] == [str(tmp_path / "x.png")]


def test_image_files_filters_missing(tmp_path):
    (tmp_path / "ok.png").write_bytes(b"x")
    items = normalize_items([{"id": "s1", "images": ["ok.png", "missing.png"]}], base_dir=tmp_path)
    assert [p.name for p in image_files(items[0])] == ["ok.png"]
