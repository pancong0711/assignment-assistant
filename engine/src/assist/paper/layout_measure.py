"""layout_measure.py — D107：用 headless 浏览器测量并生成 `layout_result`。

为什么需要：`layout_result`（D103 预排版结果）原本只能由 PWA 浏览器生成，
导致**纯 CLI / AI 工作流无法出完整作业纸**（必须人工先打开 PWA）。

方案：把前端 `autoLayout.ts` + `measureLayout.ts` 打包成
`paper/layout_bundle.mjs`（`engine/tools/build-layout-bundle.mjs`），
用 Playwright 打开一个空白页导入该 bundle，在页面里用 **真实 DOM 测量**
（含 KaTeX）后调用 `autoLayout()` —— **PWA 与 CLI 跑同一份算法**，结果一致。

依赖：Playwright（optional-dependencies[playwright]）。缺失时抛清晰错误。
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

BUNDLE = Path(__file__).with_name("layout_bundle.mjs")

# 页面里挂载 KaTeX 的最小 HTML（同源自托管不适用：这里用 CDN 或已内联 css/js 均可，
# 公式高度对 KaTeX 版本不敏感；用与 PWA 相同的 0.16.4 保证一致）
KATEX_CSS = "https://cdn.jsdelivr.net/npm/katex@0.16.4/dist/katex.min.css"
KATEX_JS = "https://cdn.jsdelivr.net/npm/katex@0.16.4/dist/katex.min.js"
KATEX_AR = "https://cdn.jsdelivr.net/npm/katex@0.16.4/dist/contrib/auto-render.min.js"


class LayoutMeasureError(RuntimeError):
    pass


def ensure_bundle() -> Path:
    if not BUNDLE.exists():
        raise LayoutMeasureError(
            f"缺少测量 bundle：{BUNDLE}\n"
            "请运行 `node engine/tools/build-layout-bundle.mjs`（构建期已自动执行）")
    return BUNDLE


def measure_layout(items: list[dict], *, orientation: str = "portrait",
                   timeout_ms: int = 30000) -> dict:
    """测量并返回 `layout_result` dict。

    items: [{qid, no, content, solution}]
    orientation: 'portrait' | 'landscape'
    """
    ensure_bundle()
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise LayoutMeasureError(
            "需要 Playwright：`uv pip install -e engine[playwright]` + `playwright install chromium`"
        ) from exc

    payload = json.dumps(items, ensure_ascii=False)
    bundle_uri = BUNDLE.resolve().as_uri()

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="{KATEX_CSS}">
<script src="{KATEX_JS}"></script>
<script src="{KATEX_AR}"></script>
<style>
  .probe {{ position:absolute; left:-10000px; top:0; visibility:hidden;
            white-space:pre-wrap; word-break:break-word; line-height:1.5; }}
  .probe.content {{ font-size:11.5pt; }}
  .probe.solution {{ font-size:10pt; }}
  .probe img, .probe svg {{ max-width:100%; height:auto; }}
</style>
</head><body><div id="root"></div></body></html>"""

    import os
    with sync_playwright() as p:
        launch_kw: dict = {}
        # 允许显式指定浏览器（CI/无 `playwright install` 的环境）
        exe = os.environ.get("ASSIST_CHROMIUM_PATH") or ""
        if exe:
            launch_kw["executable_path"] = exe
        try:
            browser = p.chromium.launch(**launch_kw)
        except Exception as exc:  # noqa: BLE001
            raise LayoutMeasureError(
                f"无法启动 Chromium：{exc}\n"
                "提示：`playwright install chromium`，或设置环境变量 ASSIST_CHROMIUM_PATH 指向可执行文件"
            ) from exc
        try:
            page = browser.new_page(viewport={"width": 1200, "height": 1000})
            page.set_content(html, wait_until="load")
            # 把 bundle 源码注入页面（避免 file:// 动态 import 受限）：
            # 用 Blob + URL.createObjectURL 生成可 import 的模块 URL
            bundle_src = BUNDLE.read_text(encoding="utf-8")
            page.evaluate(
                """(src) => {
                    const blob = new Blob([src], { type: 'text/javascript' });
                    window.__D107_BUNDLE_URL = URL.createObjectURL(blob);
                }""", bundle_src)
            # 等 KaTeX 就绪（CDN 失败则公式按源码测高，仍可工作）
            try:
                page.wait_for_function(
                    "() => typeof window.renderMathInElement === 'function'", timeout=8000)
            except Exception:  # noqa: BLE001
                logger.warning("KaTeX 未就绪（离线？）：公式将按源码测高，可能略偏小")
            result = page.evaluate(
                """async ({ bundleUri, items, orientation }) => {
                    const mod = await import(window.__D107_BUNDLE_URL || bundleUri);
                    const geo = mod.cellGeometry(orientation);
                    const B = String.fromCharCode(92);
                    const makeProbe = (kind) => {
                        const el = document.createElement('div');
                        el.className = 'probe ' + kind;
                        el.style.width = geo.cellW + 'px';
                        document.body.appendChild(el);
                        return el;
                    };
                    const probes = { content: makeProbe('content'), solution: makeProbe('solution') };
                    const cache = new Map();
                    const measure = (text, kind) => {
                        const key = kind + '::' + text;
                        if (cache.has(key)) return cache.get(key);
                        const el = probes[kind];
                        el.textContent = text;
                        if (window.renderMathInElement) {
                            try {
                                window.renderMathInElement(el, { delimiters: [
                                    {left:'$$',right:'$$',display:true},
                                    {left:B+'[',right:B+']',display:true},
                                    {left:'$',right:'$',display:false},
                                    {left:B+'(',right:B+')',display:false},
                                ], throwOnError: false });
                            } catch (e) { /* 降级 */ }
                        }
                        const h = el.getBoundingClientRect().height;
                        el.textContent = '';
                        cache.set(key, h);
                        return h;
                    };
                    const layout = mod.autoLayout({
                        geometry: { cellW: geo.cellW, cellH: geo.cellH, rows: geo.rows, cols: geo.cols },
                        items: items.map(i => ({ qid: i.qid, no: i.no, content: i.content, solution: i.solution || '' })),
                        measure,
                    });
                    return layout;
                }""",
                {"bundleUri": bundle_uri, "items": json.loads(payload),
                 "orientation": orientation})
            return result
        finally:
            browser.close()
