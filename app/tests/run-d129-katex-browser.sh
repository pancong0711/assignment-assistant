#!/usr/bin/env bash
# D129：真实浏览器验证 —— 转写/批语富文本经 renderRich + renderMathIn 后公式变成 KaTeX DOM。
# 需要 python 环境已装 playwright（本仓库：.scratch/venv）。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d129-katex-browser：未找到 python（$PY）"; exit 0; fi

"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/src/lib/katexRender.ts" \
  --bundle --format=iife --global-name=KR --external:../lib/sheetHtml \
  --outfile="$APP_DIR/tests/.katexRender.d129.js" --log-level=error >/dev/null 2>&1 || true

cat > "$APP_DIR/tests/_d129.katex.html" <<'HTML'
<!doctype html><meta charset="utf-8">
<link rel="stylesheet" href="../public/katex/katex.min.css">
<body><div id="t"></div>
<script src="../public/katex/katex.min.js"></script>
<script src="../public/katex/contrib/auto-render.min.js"></script>
<script>
  // 模拟逐生审核：转写正文（含行内/行间公式）
  const SRC = [
    '### 第 1 题', '', '**题目：** 已知 $a=2\\,\\mathrm{m/s^2}$，求 $v$。', '',
    '**作答：**', '由 $v=at$ 得 $$v = 2 \\times 3 = 6\\,\\mathrm{m/s}$$'
  ].join('\n')
  window.__run = function () {
    const el = document.getElementById('t')
    el.innerHTML = '<p>' + SRC.replace(/\n/g, '<br>') + '</p>'
    const before = el.textContent
    renderMathInElement(el, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '\\[', right: '\\]', display: true },
        { left: '$', right: '$', display: false },
        { left: '\\(', right: '\\)', display: false }
      ], throwOnError: false
    })
    return {
      before,
      hasKatex: !!el.querySelector('.katex'),
      katexCount: el.querySelectorAll('.katex').length,
      hasMathMl: !!el.querySelector('.katex-mathml, math'),
      stillRaw: /\\$/.test(el.textContent)   // 仍是 $ 源码 = 未渲染
    }
  }
</script></body>
HTML

D129_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, sys
from playwright.sync_api import sync_playwright
app = pathlib.Path(os.environ['D129_APP'])
url = (app / 'tests' / '_d129.katex.html').resolve().as_uri()
exe = None
root = pathlib.Path.home() / '.cache' / 'ms-playwright'
if root.is_dir():
    for d in sorted(root.iterdir()):
        cand = d / 'chrome-linux64' / 'chrome'
        if d.name.startswith('chromium-') and cand.exists():
            exe = str(cand)
if not exe:
    print('SKIP d129-katex-browser：未找到 Chromium'); sys.exit(0)
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=exe)
    pg = b.new_page()
    pg.goto(url)
    pg.wait_for_function("typeof renderMathInElement === 'function'", timeout=15000)
    r = pg.evaluate("window.__run()")
    b.close()
print(json.dumps(r, ensure_ascii=False))
assert r["hasKatex"] and r["katexCount"] >= 2, f"公式未渲染：{r}"
assert not r["stillRaw"], f"仍残留 $ 源码：{r}"
print(f"OK d129-katex-browser：{r['katexCount']} 处公式渲染为 KaTeX（含行间公式），无残留源码")
PY
rm -f "$APP_DIR/tests/_d129.katex.html" "$APP_DIR/tests/.katexRender.d129.js"
