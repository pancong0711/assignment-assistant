"""D53-G2/D58：reportlab PDF 网格与 HTML/PWA 的竖版 per_page=4 对齐。"""

from assist.paper.layout import grid_frames, grid_lines


def test_portrait_four_rows_not_cross():
    frames = grid_frames("portrait", 4)
    assert len(frames) == 4
    ys = sorted(round(f.y1, 2) for f in frames)
    xs = sorted(set(round(f.x1, 2) for f in frames))
    # 四帧纵向一列（x 相同），不是 2×2 十字
    assert len(xs) == 1
    assert len(ys) == 4

    lines = grid_lines("portrait", 4)
    assert len(lines) == 3
    # 三条横线：y 不同、x 跨度相同
    assert all(abs(l[0] - lines[0][0]) < 0.01 and abs(l[2] - lines[0][2]) < 0.01 for l in lines)
    assert len({round(l[1], 2) for l in lines}) == 3


def test_landscape_four_still_cross():
    frames = grid_frames("landscape", 4)
    assert len(frames) == 4
    assert len({round(f.x1, 2) for f in frames}) == 2
    assert len({round(f.y1, 2) for f in frames}) == 2
    assert len(grid_lines("landscape", 4)) == 2
