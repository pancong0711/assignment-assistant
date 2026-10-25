"""richdoc.py — D105：参考答案 md+html 的安全渲染与纯文本派生。

背景：答案由「纯文本」升级为「Markdown + HTML 白名单」，以支持
- 示意图（内联 SVG 或 base64 图片）
- 表格/列表等富结构
- KaTeX 公式（$..$ / $$..$$ / \\(..\\) / \\[..\\]）

安全边界（与 PWA `app/src/lib/richdoc.ts` **同一份白名单**）：
- 允许：p/br/strong/em/del/code/pre/blockquote/ul/ol/li/table 系列/hr/h1-h6
  + img（**仅 data:image**）+ svg 白名单元素
- 禁止：script/iframe/object/embed/form/input/link/meta/base/style
- 禁止：任何 on* 事件属性、javascript: URL、外链 src/href
- svg 禁 foreignObject / use[href] / image[href]

用法：
    html = render_rich(text)          # 安全 HTML（可直接插入模板）
    plain = strip_markup(text)        # 纯文本摘要（检索/Excel/xlsx 摘要列）
"""
from __future__ import annotations

import html as _html
import re

# ---------------- 白名单（单一事实源；PWA 侧逐项对齐） ----------------

ALLOWED_TAGS = {
    # 排版
    "p", "br", "hr", "div", "span", "blockquote", "pre", "code",
    "strong", "b", "em", "i", "del", "s", "sub", "sup", "u",
    "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
    "h1", "h2", "h3", "h4", "h5", "h6",
    # 图片（仅 data:image）
    "img",
    # SVG 白名单
    "svg", "g", "path", "line", "rect", "circle", "ellipse", "polygon",
    "polyline", "text", "tspan", "defs", "marker", "title", "desc",
}

ALLOWED_ATTRS = {
    "class", "title", "alt", "src", "width", "height", "colspan", "rowspan",
    "align", "valign", "scope",
    # SVG 常用属性
    "viewBox", "viewbox", "xmlns", "d", "fill", "stroke", "stroke-width",
    "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "x", "y", "x1",
    "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "points", "transform",
    "font-size", "font-family", "text-anchor", "dominant-baseline",
    "marker-end", "marker-start", "marker-mid", "id", "opacity",
    "fill-opacity", "stroke-opacity",
}

# 明确禁止的标签（即使 bleach 白名单遗漏也二次兜底）
FORBIDDEN_TAGS = {
    "script", "iframe", "object", "embed", "form", "input", "button",
    "textarea", "select", "link", "meta", "base", "style",
    "foreignobject", "use", "image", "audio", "video", "source",
}

# 允许的 data:image MIME（禁外链图片）
_DATA_IMG_RE = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp|svg\+xml);base64,[A-Za-z0-9+/=\s]+$")


def _filter_attr(tag: str, name: str, value: str) -> bool:
    """逐属性二次校验（补 bleach 的 protocol 限制不足处）。"""
    n = str(name or "").lower()
    v = str(value or "")
    if n.startswith("on"):                      # 事件属性一律禁
        return False
    if n in ("href", "xlink:href"):             # 外链/引用一律禁（含 javascript:）
        return False
    if n == "src":
        # 仅允许 data:image/*;base64
        return bool(_DATA_IMG_RE.match(v.strip()))
    if "javascript:" in v.lower():
        return False
    return True


def _sanitize(html_text: str) -> str:
    """用 bleach 白名单净化；bleach 缺失时退回「全转义」（最安全降级）。"""
    try:
        import bleach
    except Exception:  # noqa: BLE001 —— 无依赖时安全降级
        return _html.escape(html_text)
    cleaner = bleach.Cleaner(
        tags=ALLOWED_TAGS,
        attributes=_filter_attr,
        protocols=["data"],
        strip=True,
        strip_comments=True,
    )
    out = cleaner.clean(html_text)
    # 二次兜底：把漏网的禁标签整段删掉（正则不是解析器，但作为第二道闸足够）
    for tag in FORBIDDEN_TAGS:
        out = re.sub(rf"<\s*/?\s*{tag}\b[^>]*>", "", out, flags=re.IGNORECASE)
    return out


# ---------------- 渲染 ----------------

_MATH_PLACEHOLDER = "D105MATHPLACEHOLDER"
_MATH_END = "END"

_MATH_PATTERNS = [
    re.compile(r"\$\$[\s\S]*?\$\$"),
    re.compile(r"\\\[[\s\S]*?\\\]"),
    re.compile(r"\\\([\s\S]*?\\\)"),
    re.compile(r"\$(?:\\.|[^$\\])+\$"),
]


def _protect_math(src: str) -> tuple[str, list[str]]:
    """把公式片段抽出占位，避免 Markdown 把 \\( \\[ 当转义吃掉（D105 修复）。"""
    math: list[str] = []

    def _sub(m: "re.Match[str]") -> str:
        math.append(m.group(0))
        return f"{_MATH_PLACEHOLDER}{len(math) - 1}{_MATH_END}"

    out = src
    for pat in _MATH_PATTERNS:
        out = pat.sub(_sub, out)
    return out, math


def _restore_math(html_text: str, math: list[str]) -> str:
    def _sub(m: "re.Match[str]") -> str:
        idx = int(m.group(1))
        return math[idx] if 0 <= idx < len(math) else m.group(0)

    return re.sub(rf"{_MATH_PLACEHOLDER}(\d+){_MATH_END}", _sub, html_text)


def _md_to_html(md_text: str) -> str:
    """Markdown → HTML（表格/围栏代码/换行），失败则按段落转义降级。"""
    try:
        import markdown as _md
        return _md.markdown(md_text, extensions=["tables", "fenced_code", "nl2br"])
    except Exception:  # noqa: BLE001
        out = []
        for line in str(md_text or "").splitlines():
            out.append(f"<p>{_html.escape(line)}</p>" if line.strip() else "")
        return "\n".join(out)


# 这些标签要**连内容一起**丢弃（否则 script/style 的正文会变成可见乱码）
_DROP_WITH_CONTENT = ("script", "style", "iframe", "object", "embed", "noscript",
                      "foreignObject", "form", "textarea", "select", "audio", "video")


def _drop_dangerous_blocks(src: str) -> str:
    out = src
    for tag in _DROP_WITH_CONTENT:
        out = re.sub(rf"<\s*{tag}\b[\s\S]*?<\s*/\s*{tag}\s*>", "", out, flags=re.IGNORECASE)
        out = re.sub(rf"<\s*{tag}\b[^>]*/>", "", out, flags=re.IGNORECASE)
        out = re.sub(rf"<\s*{tag}\b[^>]*>", "", out, flags=re.IGNORECASE)
    return out


def render_rich(text: str) -> str:
    """参考答案/题干 → 安全 HTML（可安全插入模板）。

    - 先**整段删除**危险标签（script/style/iframe/... 含其内容，避免 JS/CSS 文本泄漏）；
    - 再按 Markdown 解析（保留内联 HTML）；
    - 最后走白名单净化（含 SVG / data:image 限制）；
    - 输出为空时返回空串，调用方自行降级（显示 text_plain 或源码）。
    """
    src = str(text or "")
    if not src.strip():
        return ""
    guarded, math = _protect_math(_drop_dangerous_blocks(src))
    return _sanitize(_restore_math(_md_to_html(guarded), math))


def render_rich_inline(text: str) -> str:
    """行内渲染：去掉最外层 `<p>`，让「题号 + 正文」排在同一行（D105 修复）。

    仅当整体就是单个 `<p>…</p>`（内部无块级标签）时去包裹。
    """
    html = render_rich(text)
    if not html:
        return ""
    trimmed = html.strip()
    m = re.fullmatch(r"<p>((?:(?!</p>)[\s\S])*)</p>", trimmed)
    if not m:
        return html
    inner = m.group(1)
    if re.search(r"<(table|ul|ol|li|h[1-6]|blockquote|pre|svg|div|p|br/?)[\s>]", inner, re.I):
        return html
    return inner


# ---------------- 纯文本派生 ----------------

_TAG_RE = re.compile(r"<[^>]+>")
_MD_MARKS = re.compile(r"(\*\*|__|`|~~|^#{1,6}\s+|^\s*[-*+]\s+|^\s*\d+\.\s+)", re.MULTILINE)


def strip_markup(text: str, limit: int = 0) -> str:
    """md+html → 纯文本（供检索 / Excel 摘要 / xlsx solution 列）。

    - 去 HTML 标签；SVG 整段丢弃（图无法文本化）；
    - 去 Markdown 记号（粗体/代码/标题/列表前缀）；
    - 公式保留源码（$..$ 原样），便于教师识别；
    - limit > 0 时截断并加省略号。
    """
    src = str(text or "")
    if not src.strip():
        return ""
    # SVG / 图片整段丢弃（含自闭合）
    src = re.sub(r"<svg\b[\s\S]*?</svg\s*>", " [图] ", src, flags=re.IGNORECASE)
    src = re.sub(r"<img\b[^>]*>", " [图] ", src, flags=re.IGNORECASE)
    src = _TAG_RE.sub("", src)
    src = _html.unescape(src)
    src = _MD_MARKS.sub("", src)
    # 压缩空白（保留换行语义为空格，便于摘要）
    src = re.sub(r"[ \t]+", " ", src)
    src = re.sub(r"\n{2,}", "\n", src).strip()
    if limit and len(src) > limit:
        src = src[: max(0, limit - 1)].rstrip() + "…"
    return src
