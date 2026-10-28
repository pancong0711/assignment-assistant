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
    """把公式占位还原成原文（D112 修复）。

    坑：公式里的 `<`（如 `$R_1<R_2$`）还原时若不转义，会被后续 bleach/DOMPurify
    当成标签开头，`<R_2$),单位长度…` 整段被丢弃 → **答案在 `$R_1` 后被截断**。
    因此还原前先做 HTML 转义（KaTeX 读文本节点时会自动 unescape，公式不受影响）。
    """
    def _sub(m: "re.Match[str]") -> str:
        idx = int(m.group(1))
        if not 0 <= idx < len(math):
            return m.group(0)
        return _html.escape(math[idx], quote=False)

    return re.sub(rf"{_MATH_PLACEHOLDER}(\d+){_MATH_END}", _sub, html_text)


_BLOCK_PLACEHOLDER = "D109HTMLBLOCKPLACEHOLDER"
_BLOCK_END = "END"

# D109：多行内联 HTML/SVG 必须先整体抽出占位，否则 nl2br 会往 <svg> 内部塞 <br>，
# 浏览器解析出的 <svg> 就变成 0 个图元（空白框），后面的图元文本反而漏到正文外面。
_BLOCK_PATTERNS = [
    re.compile(r"<svg\b[\s\S]*?</svg\s*>", re.IGNORECASE),
    re.compile(r"<table\b[\s\S]*?</table\s*>", re.IGNORECASE),
    re.compile(r"<pre\b[\s\S]*?</pre\s*>", re.IGNORECASE),
    re.compile(r"<blockquote\b[\s\S]*?</blockquote\s*>", re.IGNORECASE),
]


def _protect_html_blocks(src: str) -> tuple[str, list[str]]:
    """把跨行 HTML 块（svg/table/pre/blockquote）抽出占位，免受 nl2br 破坏（D109）。

    单行块不处理（不含换行时 nl2br 不会插入 `<br>`，且保留原文更利于 Markdown 判定块级）。
    """
    blocks: list[str] = []

    def _sub(m: "re.Match[str]") -> str:
        text = m.group(0)
        if "\n" not in text:
            return text
        blocks.append(text)
        return f"{_BLOCK_PLACEHOLDER}{len(blocks) - 1}{_BLOCK_END}"

    out = src
    for pat in _BLOCK_PATTERNS:
        out = pat.sub(_sub, out)
    return out, blocks


_SVG_TAG_RE = re.compile(r"<svg\b([^>]*)>", re.IGNORECASE)


def _normalize_svg_size(html_text: str) -> str:
    """给无 width/height 的 `<svg>` 补上按 viewBox 比例的内联尺寸（D109）。

    没有 width/height 时，浏览器会让 `<svg>` 撑满容器（实测 684×513px 的巨型图），
    示意图因此被放大到变形、并挤占整格。这里按 viewBox 宽高比算出「最大宽 100%、
    最大高 60mm」的等价尺寸，保持原比例且不溢出。
    """
    def _sub(m: "re.Match[str]") -> str:
        attrs = m.group(1)
        if re.search(r"\bwidth\s*=", attrs, re.I) and re.search(r"\bheight\s*=", attrs, re.I):
            return m.group(0)
        vb = re.search(r"\bviewbox\s*=\s*[\"']\s*[\d.+-]+[\s,]+[\d.+-]+[\s,]+([\d.+-]+)[\s,]+([\d.+-]+)",
                       attrs, re.I)
        if not vb:
            return m.group(0)
        try:
            w, h = float(vb.group(1)), float(vb.group(2))
        except ValueError:
            return m.group(0)
        if w <= 0 or h <= 0:
            return m.group(0)
        # 以「高不超过 45mm」为主约束，宽按比例推，并限制在格宽内
        max_h = 45.0
        width_mm = min(80.0, max_h * w / h)
        height_mm = width_mm * h / w
        # 注意：bleach 白名单不含 style，这里只用 width/height 属性；
        # 溢出由模板里的 `.q-solution svg { max-width:100%; height:auto }` 兜底。
        return f'<svg{attrs} width="{width_mm:.1f}mm" height="{height_mm:.1f}mm">'

    return _SVG_TAG_RE.sub(_sub, html_text)


def _restore_html_blocks(html_text: str, blocks: list[str]) -> str:
    """占位还原。

    注意：Markdown 可能把独占一行的占位包成 `<p>…</p>`；块级元素（svg/table/pre/
    blockquote）不能待在 `<p>` 里（浏览器会自动闭合 `<p>`，造成图元跑到框外），
    所以还原时把「整段就是一个占位的 `<p>`」替换成块本身。
    """
    def _sub(m: "re.Match[str]") -> str:
        idx = int(m.group(1))
        return blocks[idx] if 0 <= idx < len(blocks) else m.group(0)

    out = re.sub(rf"<p>\s*{_BLOCK_PLACEHOLDER}(\d+){_BLOCK_END}\s*</p>",
                 _sub, html_text)
    return re.sub(rf"{_BLOCK_PLACEHOLDER}(\d+){_BLOCK_END}", _sub, out)


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
    guarded = _drop_dangerous_blocks(src)
    # 顺序：先抽 HTML 块（含 svg），再抽公式占位（公式可能在 svg/text 里，但两者互不嵌套于换行场景）
    guarded, blocks = _protect_html_blocks(guarded)
    guarded, math = _protect_math(guarded)
    html = _md_to_html(guarded)
    html = _restore_math(html, math)
    html = _restore_html_blocks(html, blocks)
    return _sanitize(_normalize_svg_size(html))


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
