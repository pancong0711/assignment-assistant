#!/usr/bin/env bash
# D148：真实浏览器验证「知识点」选项卡（标注 / 要点 / 词表）+ 逐生补批按钮存在。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d148：未找到 python（$PY）"; exit 0; fi

ENTRY_TS=$(node "$APP_DIR/tests/_d130_sfc_all.mjs" \
  "$APP_DIR/src/views/KnowledgeView.vue" | sed -n 's/^entry ts: //p')
[ -n "$ENTRY_TS" ] || { echo "SFC 编译失败"; exit 1; }
cp "$ENTRY_TS" "$APP_DIR/tests/.d148-knowledge.ts"

cat > "$APP_DIR/tests/_d148_entry.ts" <<'TS'
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import KnowledgeView from './.d148-knowledge.ts'
import { useSettingsStore } from '../src/stores/settings'
const addr = (window as any).__ENGINE_ADDR__ || ''
const app = createApp({ render: () => h(KnowledgeView) })
const pinia = createPinia()
app.use(pinia)
useSettingsStore(pinia).engineUrl = addr
app.mount('#app')
;(window as any).__ready = true
TS
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d148_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d148.bundle.js" --log-level=error || exit 1
cat > "$APP_DIR/tests/_d148.html" <<HTML
<!doctype html><meta charset="utf-8"><title>D148</title>
<body><div id="app"></div><script src="./.d148.bundle.js"></script></body>
HTML

D148_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, socket, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright
app = pathlib.Path(os.environ['D148_APP'])
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
    print('SKIP d148：未找到 Chromium'); httpd.shutdown(); sys.exit(0)
out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(f'window.__ENGINE_ADDR__={json.dumps(addr)};')
        pg.goto((app / 'tests' / '_d148.html').resolve().as_uri())
        pg.wait_for_function('window.__ready===true', timeout=15000)
        pg.wait_for_function(
            "() => document.body.innerText.includes('AI 知识点标注')", timeout=20000)
        body = pg.inner_text('body')
        out = {
            'hasTag': 'AI 知识点标注' in body,
            'hasRubric': '参考解答 + 评阅要点' in body,
            'hasVocab': '受控知识点词表' in body,
            'hasPreviewBtn': pg.locator('button', has_text='预览（dry-run）').count() >= 1,
            # D166：AI 再整理 + 知识点预览
            'hasTidy': 'AI 再整理知识点' in body,
            'hasTidyBtn': pg.locator('button', has_text='生成整理建议').count() >= 1,
            'errors': errs,
        }
        b.close()
finally:
    httpd.shutdown()
print(json.dumps(out, ensure_ascii=False, indent=1))
assert not out['errors'], f"JS 错误：{out['errors']}"
assert out['hasTag'] and out['hasRubric'] and out['hasVocab'], f"三块缺失：{out}"
assert out['hasPreviewBtn'], '缺少 dry-run 预览按钮'
assert out['hasTidy'], 'D166：缺少「AI 再整理知识点」区块'
assert out['hasTidyBtn'], 'D166：缺少「生成整理建议」按钮'
print('OK d148：知识点选项卡（标注 dry-run / 要点生成 / 词表）渲染正常')
PY
RC=$?
rm -f "$APP_DIR/tests/_d148.html" "$APP_DIR/tests/.d148.bundle.js" "$APP_DIR/tests/.d148-knowledge.ts" "$APP_DIR/tests/_d148_entry.ts"
exit $RC
