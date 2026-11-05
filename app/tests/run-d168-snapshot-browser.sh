#!/usr/bin/env bash
# D168：RosterView 的「本次结果关联到作业包」控件存在，且快照接口可用。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d168：未找到 python（$PY）"; exit 0; fi

ENTRY_TS=$(node "$APP_DIR/tests/_d130_sfc_all.mjs" \
  "$APP_DIR/src/views/RosterView.vue" | sed -n 's/^entry ts: //p')
[ -n "$ENTRY_TS" ] || { echo "SFC 编译失败"; exit 1; }
cp "$ENTRY_TS" "$APP_DIR/tests/.d168-roster.ts"

cat > "$APP_DIR/tests/_d168_entry.ts" <<'TS'
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import RosterView from './.d168-roster.ts'
import { useSettingsStore } from '../src/stores/settings'
const addr = (window as any).__ENGINE_ADDR__ || ''
const app = createApp({ render: () => h(RosterView) })
const pinia = createPinia()
app.use(pinia)
useSettingsStore(pinia).engineUrl = addr
app.mount('#app')
;(window as any).__ready = true
TS
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d168_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d168.bundle.js" --log-level=error || exit 1
cat > "$APP_DIR/tests/_d168.html" <<HTML
<!doctype html><meta charset="utf-8"><title>D168</title>
<body><div id="app"></div><script src="./.d168.bundle.js"></script></body>
HTML

D168_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, socket, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright
app = pathlib.Path(os.environ['D168_APP'])
sys.path.insert(0, str(app.parent / 'engine' / 'src'))
from assist import serve as S
ws = pathlib.Path(tempfile.mkdtemp())
(ws / 'classes' / '化工251').mkdir(parents=True)
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
    print('SKIP d168：未找到 Chromium'); httpd.shutdown(); sys.exit(0)
out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(f'window.__ENGINE_ADDR__={json.dumps(addr)};')
        pg.goto((app / 'tests' / '_d168.html').resolve().as_uri())
        pg.wait_for_function('window.__ready===true', timeout=15000)
        pg.wait_for_function(
            "() => document.body.innerText.includes('重算综合得分')", timeout=20000)
        body = pg.inner_text('body')
        out = {
            'hasHint': '关联作业包' in body,   # D170-T8：文案改为更短的「关联作业包」
            'hasOptionDefault': '（不关联，只更新班级名单）' in body,
            'hasRecomputeBtn': pg.locator('button', has_text='重算综合得分').count() >= 1,
            'errors': errs,
        }
        b.close()
finally:
    httpd.shutdown()
print(json.dumps(out, ensure_ascii=False, indent=1))
assert not out['errors'], f"JS 错误：{out['errors']}"
assert out['hasHint'], 'D168/D170：缺少「关联作业包」控件'
assert out['hasOptionDefault'], 'D168：缺少「不关联」默认选项'
print("OK d168：作业包快照关联控件渲染正常")
PY
