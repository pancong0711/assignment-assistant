"""D61 回归：rows×cols 显式网格内核（grid.py）——与 PWA taskpad.ts resolveGrid 同口径。"""

from assist.paper.grid import grid_body_style, grid_line_styles, normalize_per_page, resolve_grid


def test_normalize_per_page():
    assert normalize_per_page(2, "landscape") == 2
    assert normalize_per_page("4", "portrait") == 4
    assert normalize_per_page(None, "landscape") == 2   # 缺省 竖1横2
    assert normalize_per_page(9, "portrait") == 9   # 1..12 均合法（D61）
    assert normalize_per_page(13, "portrait") == 1  # 超上限回落
    assert normalize_per_page(0, "landscape") == 2


def test_resolve_grid_legacy_compat():
    # 旧任务（无 grid_rows/grid_cols）：竖版 2/3/4=rowsN；横版 2/3=colsN、4=2x2
    g = resolve_grid("portrait", 4, None, None)
    assert (g["rows"], g["cols"], g["order"]) == (4, 1, "row")
    g = resolve_grid("landscape", 4, None, None)
    assert (g["rows"], g["cols"], g["order"]) == (2, 2, "col")   # 横版=列优先
    g = resolve_grid("landscape", 3, None, None)
    assert (g["rows"], g["cols"]) == (1, 3)


def test_resolve_grid_explicit():
    g = resolve_grid("portrait", 6, 3, 2)
    assert (g["rows"], g["cols"], g["per_page"]) == (3, 2, 6)
    g = resolve_grid("landscape", 4, 2, 2)
    assert (g["rows"], g["cols"], g["order"]) == (2, 2, "col")   # order 由方向决定


def test_grid_line_styles_and_body():
    # 网格解析本身（rows/cols/order）保留：data-* 属性仍输出，供排查与旧测试兼容
    ls = grid_line_styles(4, 1)
    assert len(ls) == 3 and all(x["dir"] == "h" for x in ls)
    ls = grid_line_styles(2, 2)
    assert {x["dir"] for x in ls} == {"v", "h"}
    # D102：.sheet-body 改流式纵向排布 —— 不再输出等分行高（会裁切超长参考答案）
    st = grid_body_style(2, 2, "row")
    assert "grid-template-rows" not in st, "D102：不得再等分行高（会裁切答案）"
    assert "grid-template-columns" not in st
    assert "display:flex" in st and "flex-direction:column" in st
    assert "overflow:visible" in st
    # 行/列数不再影响排版结果（幂等）
    assert grid_body_style(1, 2, "col") == st
