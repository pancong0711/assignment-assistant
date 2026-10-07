"""作业纸网格布局解析（D61）。

语义：
- ``per_page`` = 每页题数 N；``grid_rows``/``grid_cols`` = 显式网格；
- 必须满足 rows*cols >= N，多出的格子留空（空位放在阅读顺序末尾）；
- 缺省无显式网格时保持旧任务兼容：竖版 2/3/4 = rowsN、横版 2/3 = colsN、横版 4 = 2x2；
- 新 UI 推荐默认 = ``rows=ceil(N/2), cols=2``（N=1 特例 1x1）；
- 阅读顺序：竖版行优先（左→右、上→下），横版列优先（上→下、左→右）。
"""

from __future__ import annotations

from math import ceil, floor, sqrt
from typing import Any

MAX_PER_PAGE = 12
MAX_GRID_DIM = 12


def normalize_per_page(v: Any, orientation: str) -> int:
    """把 per_page 归一化到 1..MAX_PER_PAGE；非法时回落到方向缺省（竖1横2）。"""
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = 0
    if 1 <= n <= MAX_PER_PAGE:
        return n
    return 2 if orientation == "landscape" else 1


def _positive_dim(v: Any) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= MAX_GRID_DIM else None


def legacy_grid(orientation: str, per_page: int) -> tuple[int, int]:
    """旧任务包（无 grid_rows/grid_cols）的兼容网格。"""
    if per_page <= 1:
        return 1, 1
    if orientation == "portrait":
        return per_page, 1
    if per_page == 4:
        return 2, 2
    return 1, per_page


def default_grid(per_page: int) -> tuple[int, int]:
    """新 UI 默认：N/2 x 2（N=1 特例 1x1）。"""
    if per_page <= 1:
        return 1, 1
    return max(1, ceil(per_page / 2)), 2


def auto_square_grid(per_page: int) -> tuple[int, int]:
    """均匀方阵：在因子对中选最接近平方的一对；质数回退 1xN。"""
    if per_page <= 1:
        return 1, 1
    best = (1, per_page)
    best_delta = abs(1 - per_page)
    for r in range(2, int(sqrt(per_page)) + 1):
        if per_page % r == 0:
            c = per_page // r
            delta = abs(r - c)
            if delta < best_delta or (delta == best_delta and r < best[0]):
                best, best_delta = (r, c), delta
    return best


def resolve_grid(orientation: str, per_page: int,
                 grid_rows: Any = None, grid_cols: Any = None) -> dict:
    """解析为实际网格。

    返回 ``{rows, cols, per_page, order, capacity, legacy, empty}``：
    - order: 'row' = 行优先；'col' = 列优先；
    - legacy=True 表示使用了旧兼容默认（未提供合法显式网格）。
    """
    n = normalize_per_page(per_page, orientation)
    rows = _positive_dim(grid_rows)
    cols = _positive_dim(grid_cols)
    legacy = False
    if rows is None or cols is None or rows * cols < n:
        legacy = True
        rows, cols = legacy_grid(orientation, n)
    order = "row" if orientation == "portrait" else "col"
    return {
        "rows": rows,
        "cols": cols,
        "per_page": n,
        "order": order,
        "capacity": rows * cols,
        "legacy": legacy,
        "empty": max(0, rows * cols - n),
    }


def grid_line_styles(rows: int, cols: int) -> list[dict]:
    """内部虚线位置（HTML：% 定位；PDF 由 layout.grid_lines 用实际坐标画）。"""
    out: list[dict] = []
    for i in range(1, max(0, cols)):
        out.append({"dir": "v", "style": f"left:{round(i * 100 / cols, 4)}%"})
    for j in range(1, max(0, rows)):
        out.append({"dir": "h", "style": f"top:{round(j * 100 / rows, 4)}%"})
    return out


def grid_body_style(rows: int, cols: int, order: str) -> str:
    """HTML .sheet-body 的内联 CSS Grid 样式（PWA/j2 同口径）。"""
    flow = "column" if order == "col" else "row"
    return (
        "display:grid;"
        f"grid-template-columns:repeat({cols}, minmax(0, 1fr));"
        f"grid-template-rows:repeat({rows}, minmax(0, 1fr));"
        f"grid-auto-flow:{flow};"
    )
