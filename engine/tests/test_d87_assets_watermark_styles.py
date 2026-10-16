"""D87 §1/§2 自测：素材目录解析 + 水印样式库（命名/默认/style_ref/旧路径兼容）。

对应 docs/40-D87-assets-watermark-styles.md §2（目录解析顺序）与 §3（样式库 + 优先级）。
不依赖 reportlab 出 PDF，仅验证解析/读写/优先级与路径兼容（generation 由既有 pdf 单测覆盖）。
"""

from pathlib import Path

from assist import ASSETS_DIR
from assist.paper.assets import (
    has_workspace_assets, resolve_assets_dir, styles_dir, watermark_dir,
)
from assist.paper.watermark_styles import (
    DEFAULT_STYLE_NAME, default_style, delete_style, list_styles,
    normalize_image_ref, read_style, rename_style, resolve_pad_watermark,
    save_style, set_default,
)


# ---------------- §1 素材目录解析 ----------------

def test_resolve_engine_by_default(tmp_path):
    """无 explicit、无 workspace assets → 引擎内置 assets。"""
    d, src = resolve_assets_dir(ws=None)
    assert src == "engine"
    assert Path(d) == Path(ASSETS_DIR)


def test_resolve_workspace_when_assets_present(tmp_path):
    """workspace 下存在 assets/watermark 或 assets/fonts → workspace 优先。"""
    ws = tmp_path / "ws"
    (ws / "assets" / "watermark").mkdir(parents=True)
    assert has_workspace_assets(ws) is True
    d, src = resolve_assets_dir(ws=ws)
    assert src == "workspace"
    assert Path(d) == (ws / "assets").resolve()


def test_resolve_fonts_only_also_triggers_workspace(tmp_path):
    ws = tmp_path / "ws"
    (ws / "assets" / "fonts").mkdir(parents=True)
    _, src = resolve_assets_dir(ws=ws)
    assert src == "workspace"


def test_resolve_explicit_wins(tmp_path):
    ws = tmp_path / "ws"
    (ws / "assets" / "watermark").mkdir(parents=True)
    explicit = tmp_path / "custom-assets"
    d, src = resolve_assets_dir(ws=ws, explicit=explicit)
    assert src == "explicit"
    assert Path(d) == explicit.resolve()


def test_resolve_explicit_relative_to_ws(tmp_path):
    ws = tmp_path / "ws"
    d, src = resolve_assets_dir(ws=ws, explicit="assets")
    assert src == "explicit"
    assert Path(d) == (ws / "assets").resolve()


# ---------------- §2 样式库读写 ----------------

def test_style_save_read_list(tmp_path):
    ad = tmp_path / "assets"
    res = save_style(ad, "期末版", {"enabled": True, "pageText": False,
                                   "items": [{"image": "watermark/a.png", "pos": "rb",
                                              "ratio": 0.3, "alpha": 0.6}]})
    assert res["ok"] is True
    st = read_style(ad, "期末版")
    assert st["name"] == "期末版"
    assert st["pageText"] is False
    assert st["items"][0]["image"] == "watermark/a.png"
    names = [s["name"] for s in list_styles(ad)]
    assert names == ["期末版"]


def test_style_illegal_name_rejected(tmp_path):
    ad = tmp_path / "assets"
    for bad in ["", "  ", "a/b", "a\\b", "..", "x" * 41]:
        assert save_style(ad, bad, {})["ok"] is False


def test_set_default_is_single(tmp_path):
    ad = tmp_path / "assets"
    save_style(ad, "A", {"default": True})
    save_style(ad, "B", {})
    set_default(ad, "B")
    assert read_style(ad, "A")["default"] is False
    assert read_style(ad, "B")["default"] is True
    assert default_style(ad)["name"] == "B"


def test_delete_and_rename(tmp_path):
    ad = tmp_path / "assets"
    save_style(ad, "A", {"default": True, "items": [{"image": "watermark/a.png"}]})
    rename_style(ad, "A", "A2")
    assert read_style(ad, "A") is None
    assert read_style(ad, "A2")["name"] == "A2"
    assert default_style(ad)["name"] == "A2"  # rename 后默认跟随
    delete_style(ad, "A2")
    assert list_styles(ad) == []


def test_default_style_falls_back_to__default(tmp_path):
    ad = tmp_path / "assets"
    save_style(ad, DEFAULT_STYLE_NAME, {"items": [{"image": "watermark/d.png"}]})
    assert default_style(ad)["name"] == DEFAULT_STYLE_NAME


# ---------------- §3.1 旧路径兼容 ----------------

def test_normalize_image_ref():
    assert normalize_image_ref("assets/watermark/x.png") == "watermark/x.png"
    assert normalize_image_ref("watermark/x.png") == "watermark/x.png"
    assert normalize_image_ref("x.png") == "watermark/x.png"
    assert normalize_image_ref("assets\\watermark\\y.png") == "watermark/y.png"
    assert normalize_image_ref("") == ""


# ---------------- §3.2 解析优先级 ----------------

def _mk(ad, name, items, **kw):
    save_style(ad, name, {"items": items, **kw})


def test_resolve_priority_pad_items_first(tmp_path):
    ad = tmp_path / "assets"
    _mk(ad, "default1", [{"image": "watermark/d.png"}], default=True)
    pad = {"items": [{"image": "watermark/pad.png"}], "style_ref": "default1"}
    r = resolve_pad_watermark(ad, pad)
    assert r["source"] == "pad-items"
    assert r["items"][0]["image"] == "watermark/pad.png"


def test_resolve_priority_style_ref_over_default(tmp_path):
    ad = tmp_path / "assets"
    _mk(ad, "default1", [{"image": "watermark/d.png"}], default=True)
    _mk(ad, "期末版", [{"image": "watermark/final.png"}], pageText=False)
    r = resolve_pad_watermark(ad, {"style_ref": "期末版"})
    assert r["source"] == "style:期末版"
    assert r["items"][0]["image"] == "watermark/final.png"
    assert r["pageText"] is False


def test_resolve_falls_to_default_style(tmp_path):
    ad = tmp_path / "assets"
    _mk(ad, "d", [{"image": "watermark/d.png"}], default=True)
    r = resolve_pad_watermark(ad, {})
    assert r["source"] == "default:d"
    assert r["items"][0]["image"] == "watermark/d.png"


def test_resolve_builtin_when_nothing(tmp_path):
    ad = tmp_path / "assets"
    r = resolve_pad_watermark(ad, None)
    assert r["source"] == "builtin"
    assert r["items"] == []
    assert r["enabled"] is True


def test_resolve_missing_style_ref_falls_back(tmp_path):
    ad = tmp_path / "assets"
    _mk(ad, "d", [{"image": "watermark/d.png"}], default=True)
    r = resolve_pad_watermark(ad, {"style_ref": "不存在"})
    assert r["source"] == "default:d"


def test_styles_dir_created(tmp_path):
    ad = tmp_path / "assets"
    d = styles_dir(ad)
    assert d.is_dir() and d.name == "styles"
    assert watermark_dir(ad).name == "watermark"


# ---------------- §1/§5 集成：workspace 素材目录 + 样式落到 PDF/HTML ----------------

def _custom_asset_ws(tmp_path):
    ws = tmp_path / "ws"
    ad = ws / "assets" / "watermark"
    (ad / "styles").mkdir(parents=True)
    from PIL import Image
    Image.new("RGBA", (200, 200), (255, 0, 0, 180)).save(ad / "logo-custom.png")
    return ws, ad


def test_make_pdf_resolves_workspace_assets_and_embeds_custom(tmp_path):
    """workspace 优先：<ws>/assets/watermark 下的自定义图能被 make_pdf 找到并出水印。"""
    ws, ad = _custom_asset_ws(tmp_path)
    from assist.paper.layout import make_pdf
    files = make_pdf(
        [{"name": "张三", "number": "1", "class": "化工25"}],
        lambda i: [("题目", "", "copy", "1.")],
        ws / "out", assets_dir=None, workspace=ws,
        watermark_spec={"enabled": True,
                        "items": [{"image": "watermark/logo-custom.png",
                                   "pos": "rb", "ratio": 0.3, "alpha": 0.5}]})
    assert files and all(f.exists() for f in files)
    # 出水印 PDF（合并后文件名含 watermark-combine）
    assert any("watermark-combine" in f.name for f in files)


def test_make_pdf_tolerates_legacy_assets_prefix_path(tmp_path):
    """旧值 'assets/watermark/x.png' 不应导致图层被跳过（兼容只告警不崩溃，仍出水印）。"""
    ws, ad = _custom_asset_ws(tmp_path)
    from assist.paper.layout import make_pdf
    files = make_pdf(
        [{"name": "李四", "number": "2", "class": "化工25"}],
        lambda i: [("题目", "", "copy", "1.")],
        ws / "out", assets_dir=None, workspace=ws,
        watermark_spec={"enabled": True,
                        "items": [{"image": "assets/watermark/logo-custom.png",
                                   "pos": "rb", "ratio": 0.3, "alpha": 0.5}]})
    assert files and files[0].exists()


def test_html_style_ref_resolves_to_items(tmp_path):
    """HTML 通道：作业纸仅写 style_ref → 从样式库解析出 items（D87 §5）。"""
    ws, ad = _custom_asset_ws(tmp_path)
    (ws / "kb").mkdir(parents=True)
    save_style(ad, "期末版", {"items": [{"image": "watermark/logo-custom.png",
                                        "pos": "rb", "ratio": 0.3, "alpha": 0.5}]})
    from assist.paper.htmlfile import _watermark_items
    task = {"watermark": {"style_ref": "期末版"}}
    items = _watermark_items(task, ws, ad, "portrait")
    assert items and items[0]["b64"], "style_ref 应解析出内嵌图层的 b64"
    assert items[0]["pos"] == "rb"


def test_html_missing_style_ref_falls_back(tmp_path):
    """style_ref 指向不存在样式 → 回落默认样式（不崩）。"""
    ws, ad = _custom_asset_ws(tmp_path)
    (ws / "kb").mkdir(parents=True)
    save_style(ad, "d", {"default": True,
                         "items": [{"image": "watermark/logo-custom.png"}]})
    from assist.paper.htmlfile import _watermark_items
    items = _watermark_items({"watermark": {"style_ref": "不存在"}}, ws, ad, "portrait")
    assert items and items[0]["b64"]
