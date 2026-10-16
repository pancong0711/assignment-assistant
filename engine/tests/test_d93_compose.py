"""D93-S1：summary/copy-page/translation 合成题（resolve_items）。"""
from pathlib import Path

from assist.paper.compose import seed_index, copy_content, pick_translation, SUMMARY_CONTENT
from assist.paper.task import resolve_items


def _kb(translation_entries=None):
    return {
        "problems": {"chap10": [{"id": "c1", "content": "计算题1", "img_path": None}]},
        "copy": {"chap10": [
            {"id": "k1", "content": "抄写内容A", "page": 42, "img_path": None},
            {"id": "k2", "content": "抄写内容B", "img_path": None},   # 无 page
        ]},
        "translation": {"translation": translation_entries or []},
    }


def test_summary_auto_added(tmp_path):
    items = resolve_items(_kb(), [{"kb": "problems", "chap": "chap10", "ids": ["c1"], "tag": "summary"}],
                          tmp_path, "auto", seed=1)
    contents = [c for c, *_ in items]
    assert any("请总结课堂内容" in c for c in contents)
    assert SUMMARY_CONTENT in contents
    # 1 道计算题 + 1 道总结题
    assert len(items) == 2


def test_summary_not_added_for_other_tag(tmp_path):
    items = resolve_items(_kb(), [{"kb": "problems", "chap": "chap10", "ids": ["c1"], "tag": "qa"}],
                          tmp_path, "auto", seed=1)
    assert not any("请总结" in c for c, *_ in items)
    assert len(items) == 1


def test_summary_no_duplicate_if_manual(tmp_path):
    kb = _kb()
    kb["summary"] = {"s": [{"id": "summary", "content": "手写总结", "img_path": None}]}
    items = resolve_items(kb, [{"kb": "summary", "chap": "s", "ids": ["summary"], "tag": "summary"}],
                          tmp_path, "auto", seed=1)
    # 手写 summary 已存在 → 不重复追加
    assert sum(1 for c, *_ in items if "总结" in c) == 1


def test_copy_page_rewrites_content(tmp_path):
    kb = _kb()
    items = resolve_items(kb, [{"kb": "copy", "chap": "chap10", "ids": ["k1", "k2"], "tag": "copy"}],
                          tmp_path, "auto")
    c1 = next(c for c, *_ in items if "抄写内容A" in c)
    assert c1.startswith("请抄写：42页") and "画出示意图" in c1 and "（k1）" in c1
    c2 = next(c for c, *_ in items if "抄写内容B" in c)
    assert c2 == "抄写内容B"   # 无 page → 不改写


def test_translation_deterministic_by_seed(tmp_path):
    entries = [{"id": "translation", "content": f"翻译{i}", "img_path": None} for i in range(5)]
    kb = _kb(entries)
    spec = [{"kb": "problems", "chap": "chap10", "ids": ["c1"], "tag": "translation"}]
    a = resolve_items(kb, spec, tmp_path, "auto", seed=123)
    b = resolve_items(kb, spec, tmp_path, "auto", seed=123)
    ta = [c for c, *_ in a if c.startswith("翻译")]
    tb = [c for c, *_ in b if c.startswith("翻译")]
    assert len(ta) == 1 and ta == tb, "同 seed 应抽同一道"


def test_translation_different_seeds_may_differ(tmp_path):
    entries = [{"id": "translation", "content": f"翻译{i}", "img_path": None} for i in range(8)]
    kb = _kb(entries)
    spec = [{"kb": "problems", "chap": "chap10", "ids": ["c1"], "tag": "translation"}]
    picks = {resolve_items(kb, spec, tmp_path, "auto", seed=s)[-1][0] for s in range(8)}
    assert len(picks) >= 2, "不同 seed 应有不同抽题（可移植 LCG）"


def test_translation_not_added_when_no_entries(tmp_path):
    items = resolve_items(_kb([]), [{"kb": "problems", "chap": "chap10", "ids": ["c1"], "tag": "translation"}],
                          tmp_path, "auto", seed=1)
    assert len(items) == 1   # 无 translation 表 → 只 1 道


# ---- compose 纯函数 ----

def test_seed_index_portable_range():
    for s in [0, 1, 12345, 2**31 - 1]:
        for n in [1, 3, 7]:
            v = seed_index(s, n)
            assert 0 <= v < n


def test_copy_content_template():
    assert copy_content(42, "X", "k1") == "请抄写：42页 X，并画出示意图。（k1）"


def test_pick_translation_none_when_empty():
    assert pick_translation([], 1) is None


def test_summary_by_target_tag_only_empty_items(tmp_path):
    """实机反馈回归：仅设 target_tag=summary、items 为空 → 仍追加总结题。"""
    items = resolve_items(_kb(), [], tmp_path, "auto", seed=1, target_tag="summary")
    assert any(c == SUMMARY_CONTENT for c, *_ in items)


def test_translation_by_target_tag_only_empty_items(tmp_path):
    entries = [{"id": "translation", "content": "翻译X", "img_path": None}]
    items = resolve_items(_kb(entries), [], tmp_path, "auto", seed=1, target_tag="translation")
    assert any(c == "翻译X" for c, *_ in items)
