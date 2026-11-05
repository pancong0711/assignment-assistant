#!/usr/bin/env bash
# D168-B4：Atopia 工作区「一键解析」两段式控件存在（工步0抽取 / 工步1 AI 解析）。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d168-atopia：未找到 python"; exit 0; fi
ENTRY_TS=$(node "$APP_DIR/tests/_d130_sfc_all.mjs" \
  "$APP_DIR/src/views/AtopiaView.vue" | sed -n 's/^entry ts: //p')
[ -n "$ENTRY_TS" ] || { echo "SFC 编译失败"; exit 1; }
cp "$ENTRY_TS" "$APP_DIR/tests/.d168-atopia.ts"
cat > "$APP_DIR/tests/_d168_atopia_entry.ts" <<'TS'
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import AtopiaView from './.d168-atopia.ts'
import { useSettingsStore } from '../src/stores/settings'
const addr = (window as any).__ENGINE_ADDR__ || ''
const app = createApp({ render: () => h(AtopiaView) })
const pinia = createPinia()
app.use(pinia)
useSettingsStore(pinia).engineUrl = addr
app.mount('#app')
;(window as any).__ready = true
TS
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d168_atopia_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d168-atopia.bundle.js" --log-level=error || exit 1
cat > "$APP_DIR/tests/_d168_atopia.html" <<HTML
<!doctype html><meta charset="utf-8"><title>D168 atopia</title>
<body><div id="app"></div><script src="./.d168-atopia.bundle.js"></script></body>
HTML
D168_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, socket, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright
app = pathlib.Path(os.environ['D168_APP'])
sys.path.insert(0, str(app.parent / 'engine' / 'src'))
from assist import serve as S
ws = pathlib.Path(tempfile.mkdtemp()); (ws / 'kb').mkdir()
S.Handler.ws = ws; S.Handler.token = ''
s0 = socket.socket(); s0.bind(('127.0.0.1', 0)); port = s0.getsockname()[1]; s0.close()
httpd = S.ThreadingHTTPServer(('127.0.0.1', port), S.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.2)
addr = f'http://127.0.0.1:{port}'
exe = None
root = pathlib.Path.home() / '.cache' / 'ms-playwright'
if root.is_dir():
    for dd in sorted(root.iterdir()):
        cand = dd / 'chrome-linux64' / 'chrome'
        if dd.name.startswith('chromium-') and cand.exists():
            exe = str(cand)
if not exe:
    print('SKIP d168-atopia：未找到 Chromium'); httpd.shutdown(); sys.exit(0)
out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(f'window.__ENGINE_ADDR__={json.dumps(addr)};')
        pg.goto((app / 'tests' / '_d168_atopia.html').resolve().as_uri())
        pg.wait_for_function('window.__ready===true', timeout=15000)
        pg.wait_for_function("() => document.body.innerText.includes('工作区')", timeout=15000)
        pg.locator('button', has_text='工作区').first.click()
        pg.wait_for_timeout(800)
        body = pg.inner_text('body')
        out = {
            'hasOneClick': '一键解析' in body,
            'hasExtractBtn': pg.locator('button', has_text='① 抽取（免费）').count() >= 1,
            'hasParseBtn': pg.locator('button', has_text='② AI 解析（会花钱）').count() >= 1,
            'hasTaskSelect': pg.locator('select').count() >= 1,
            'errors': errs,
        }
        b.close()
finally:
    httpd.shutdown()
print(json.dumps(out, ensure_ascii=False, indent=1))
assert not out['errors'], f"JS 错误：{out['errors']}"
assert out['hasOneClick'], 'D168-B4：缺少「一键解析」区块'
assert out['hasExtractBtn'], 'D168-B4：缺少「① 抽取（免费）」按钮'
assert out['hasParseBtn'], 'D168-B4：缺少「② AI 解析（会花钱）」按钮'
print("OK d168-atopia：一键解析两段式控件渲染正常")
PY
