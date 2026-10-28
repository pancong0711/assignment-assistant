#!/usr/bin/env bash
# D117：在真实浏览器里断言 richdoc.renderRich 保留 SVG 几何属性。
# 需要 python 环境已装 playwright（本仓库：.scratch/venv）。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d117-svg-browser：未找到 python（$PY）"; exit 0; fi

# 1) 生成 IIFE 与静态页面
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/src/lib/richdoc.ts" \
  --bundle --format=iife --global-name=RD \
  --outfile="$APP_DIR/tests/.richdoc.d117.iife.js" --log-level=error || exit 1

cat > "$APP_DIR/tests/_d117.svg.html" <<'HTML'
<!doctype html><meta charset="utf-8"><body><div id="t"></div>
<script src=".richdoc.d117.iife.js"></script>
<script>
  window.__result = function () {
    const SRC = '示意图：\n\n<svg viewBox="0 0 200 150" xmlns="http://www.w3.org/2000/svg">\n'
      + '  <circle cx="100" cy="75" r="35" stroke="black" fill="none"/>\n'
      + '  <text x="112" y="70" font-size="10" fill="black">R1</text>\n</svg>\n'
      + '\n![img](data:image/png;base64,iVBORw0KGgo=)';
    const html = RD.renderRich(SRC);
    const d = document.getElementById('t');
    d.innerHTML = html;
    const svg = [...d.querySelectorAll('svg')].pop();
    return { html, hasSvg: !!svg,
      viewBox: svg ? svg.getAttribute('viewBox') : null,
      width: svg ? svg.getAttribute('width') : null,
      height: svg ? svg.getAttribute('height') : null,
      circles: svg ? svg.querySelectorAll('circle').length : 0,
      cx: svg && svg.querySelector('circle') ? svg.querySelector('circle').getAttribute('cx') : null,
      r: svg && svg.querySelector('circle') ? svg.querySelector('circle').getAttribute('r') : null,
      renderedW: svg ? Math.round(svg.getBoundingClientRect().width) : 0,
      imgCount: d.querySelectorAll('img').length };
  };
</script></body>
HTML

# 2) 用 python playwright 打开并断言
D117_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, sys
from playwright.sync_api import sync_playwright
app = pathlib.Path(os.environ['D117_APP'])
page = (app/'tests'/'_d117.svg.html').as_uri()
exe = None
for root in [pathlib.Path.home()/'.cache'/'ms-playwright']:
    if root.is_dir():
        for d in sorted(root.iterdir()):
            p = d/'chrome-linux64'/'chrome'
            if d.name.startswith('chromium-') and p.exists(): exe = str(p)
if not exe:
    print('SKIP d117-svg-browser：未找到 Chromium'); sys.exit(0)
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=exe)
    pg = b.new_page(); pg.goto(page); r = pg.evaluate('() => window.__result()'); b.close()
ok = True
def chk(cond, msg):
    global ok
    if not cond:
        ok = False; print('FAIL:', msg)
chk(r['hasSvg'], 'renderRich 输出中没有 <svg>')
chk(r['viewBox'], 'viewBox 被剥掉（ALLOWED_URI_REGEXP 全局生效的典型症状）')
chk(r['width'] and r['height'], 'width/height 被剥掉')
chk(r['circles'] >= 1, 'circle 被剥掉')
chk(r['cx'] and r['r'], 'cx/r 被剥掉')
chk(r['renderedW'] > 0, 'SVG 渲染宽度为 0（图不可见）')
chk(r['imgCount'] >= 1, 'data:image 被误删')
if not ok: print('HTML:', r['html'][:400]); sys.exit(1)
print(f"OK d117-svg-browser：真实 DOMPurify 下 viewBox/width/height/cx/r 全保留、SVG 可渲染({r['renderedW']}px)、data:image 放行")
PY
rc=$?
rm -f "$APP_DIR/tests/.richdoc.d117.iife.js" "$APP_DIR/tests/_d117.svg.html"
exit $rc
