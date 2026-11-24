#!/usr/bin/env bash
# D226：真实 Chromium 验证——题号在公式/列表/软换行题干旁都不独占一行。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d226-browser：未找到 python（$PY）"; exit 0; fi

"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/src/lib/sheetHtml.ts" \
  --bundle --format=esm --external:jszip \
  --outfile="$APP_DIR/tests/.d226.sheetHtml.mjs" --log-level=error
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/src/lib/taskpad.ts" \
  --bundle --format=esm \
  --outfile="$APP_DIR/tests/.d226.taskpad.mjs" --log-level=error
node "$APP_DIR/tests/_d226_browser_fixture.mjs" \
  "$APP_DIR/tests/.d226.sheetHtml.mjs" "$APP_DIR/tests/.d226.taskpad.mjs" \
  "$APP_DIR/tests/.d226.html"

D226_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, sys
from playwright.sync_api import sync_playwright
app = pathlib.Path(os.environ['D226_APP'])
url = (app / 'tests' / '.d226.html').resolve().as_uri()
exe = None
root = pathlib.Path.home() / '.cache' / 'ms-playwright'
if root.is_dir():
    for d in sorted(root.iterdir()):
        cand = d / 'chrome-linux64' / 'chrome'
        if d.name.startswith('chromium-') and cand.exists():
            exe = str(cand)
if not exe:
    print('SKIP d226-browser：未找到 Chromium'); sys.exit(0)
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=exe)
    pg = b.new_page(viewport={'width': 1200, 'height': 1800})
    pg.goto(url)
    pg.wait_for_function("() => document.querySelectorAll('.q-content[data-katex-done=\"1\"]').length >= 3", timeout=15000)
    data = pg.evaluate("""() => [...document.querySelectorAll('.q-content')].map(el => {
      const no = el.querySelector('.q-no')
      const body = el.querySelector('.q-content-body')
      const first = body && body.firstElementChild
      const rect = (e) => { const r = e.getBoundingClientRect(); return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,text:(e.textContent||'').trim()} }
      return {
        no: no ? rect(no) : null,
        body: body ? rect(body) : null,
        first: first ? rect(first) : null,
        bodyHtml: body ? body.innerHTML.slice(0, 180) : '',
      }
    })""")
    b.close()
assert len(data) == 3, f'应有 3 道题，实际 {len(data)}'
for i, q in enumerate(data, 1):
    assert q['no'] and q['body'], f'第 {i} 题缺少题号/正文容器'
    assert abs(q['no']['top'] - q['body']['top']) <= 2, f'第 {i} 题题号与正文顶部未对齐：{q}'
    assert q['bodyHtml'].strip(), f'第 {i} 题正文为空'
    assert not q['bodyHtml'].lstrip().startswith('<p'), f'第 {i} 题正文首块仍是块级 <p>：{q["bodyHtml"]}'
# 第 1 题行间公式是正文首块：消除 margin-top 后应与正文顶部对齐
assert abs(data[0]['first']['top'] - data[0]['body']['top']) <= 2, f'行间公式首块上边距未清零：{data[0]}'
# 第 2 题松散列表必须已经行内化，不能残留 <li><p>
assert '<p>' not in data[1]['bodyHtml'], f'松散列表未行内化：{data[1]["bodyHtml"]}'
assert data[1]['bodyHtml'].startswith('Sentence one.'), f'松散列表首项未与题号同排：{data[1]["bodyHtml"]}'
# 第 3 题软换行保留 <br>，首行文字直接开始
assert '<br>' in data[2]['bodyHtml'], f'软换行丢失：{data[2]["bodyHtml"]}'
print(json.dumps(data, ensure_ascii=False))
print('OK d226-browser：公式/松散列表/软换行题干均未把题号挤成独立一行')
PY
rc=$?
rm -f "$APP_DIR/tests/.d226.sheetHtml.mjs" "$APP_DIR/tests/.d226.taskpad.mjs" \
      "$APP_DIR/tests/.d226.html"
exit $rc
