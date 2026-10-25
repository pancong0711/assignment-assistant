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
    # D103：恢复 MxN 等分网格 —— 版式控制权是作业纸样式的重要组成部分
    ls = grid_line_styles(4, 1)
    assert len(ls) == 3 and all(x["dir"] == "h" for x in ls)
    ls = grid_line_styles(2, 2)
    assert {x["dir"] for x in ls} == {"v", "h"}
    # 横版 1x2：中间一条竖线（用户明确要求保留）
    assert grid_line_styles(1, 2) == [{"dir": "v", "style": "left:50.0%"}]
    st = grid_body_style(2, 2, "row")
    assert "display:grid" in st
    assert "grid-template-columns:repeat(2, minmax(0, 1fr))" in st
    assert "grid-template-rows:repeat(2, minmax(0, 1fr))" in st
    assert "grid-auto-flow:row" in st
    assert "grid-auto-flow:column" in grid_body_style(1, 2, "col")
    # 行列数确实影响排版（非幂等）—— 这是版式控制权的体现
    assert grid_body_style(1, 2, "col") != grid_body_style(2, 1, "row")
