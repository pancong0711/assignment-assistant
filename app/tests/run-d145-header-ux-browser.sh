#!/usr/bin/env bash
# D145：真实浏览器验证 provider 请求头 UI —— 勾选式会话头 / 高级块在保存键上方 /
#       保存后反馈"是否已分配段"。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d145-ux：未找到 python（$PY）"; exit 0; fi

ENTRY_TS=$(node "$APP_DIR/tests/_d130_sfc_all.mjs" \
  "$APP_DIR/src/components/AiGradingPanel.vue" | sed -n 's/^entry ts: //p')
[ -n "$ENTRY_TS" ] || { echo "SFC 编译失败"; exit 1; }
cp "$ENTRY_TS" "$APP_DIR/tests/.d145-panel.ts"

cat > "$APP_DIR/tests/_d145_entry.ts" <<'TS'
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import AiGradingPanel from './.d145-panel.ts'
import { useSettingsStore } from '../src/stores/settings'
const addr = (window as any).__ENGINE_ADDR__ || ''
const app = createApp({ render: () => h(AiGradingPanel, { engineAddr: addr, token: '' }) })
const pinia = createPinia()
app.use(pinia)
useSettingsStore(pinia).engineUrl = addr
app.mount('#app')
;(window as any).__ready = true
TS
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d145_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d145.bundle.js" \
  --log-level=error || exit 1

cat > "$APP_DIR/tests/_d145.html" <<HTML
<!doctype html><meta charset="utf-8"><title>D145</title>
<body><div id="app"></div><script src="./.d145.bundle.js"></script></body>
HTML

D145_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, socket, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright

app = pathlib.Path(os.environ['D145_APP'])
sys.path.insert(0, str(app.parent / 'engine' / 'src'))
from assist import serve as S
from assist.grading import providers as P

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
    print('SKIP d145-ux：未找到 Chromium'); httpd.shutdown(); sys.exit(0)

out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(f'window.__ENGINE_ADDR__={json.dumps(addr)};')
        pg.goto((app / 'tests' / '_d145.html').resolve().as_uri())
        pg.wait_for_function('window.__ready===true', timeout=15000)
        pg.wait_for_selector('text=LLM 设置', timeout=20000)

        # 1) 高级块必须在「保存 provider」**上方**（同一时刻比较，避免布局变化干扰）
        adv_y = pg.locator('summary', has_text='高级：请求头').bounding_box()['y']
        save_y = pg.locator('button', has_text='保存 provider').bounding_box()['y']
        out['order'] = adv_y < save_y
        out['orderDetail'] = {'advY': round(adv_y), 'saveY': round(save_y)}

        # 2) 界面不应出现 {session} 字样
        body = pg.inner_text('body')
        out['noPlaceholderVisible'] = '{session}' not in body

        # 3) 填 provider + 勾选会话头 → 保存 → 二次确认 → 落盘
        pg.fill('input[placeholder="Aliyun"]', 'opencode-go')
        pg.fill('input[placeholder*="compatible-mode"]',
                'https://opencode.ai/inference/go/openai/v1')
        pg.fill('input[placeholder*="留空=不修改"]', 'sk-test')
        pg.locator('summary', has_text='高级：请求头').click()
        pg.wait_for_selector('text=需要会话头', timeout=10000)
        pg.locator('input[type=checkbox]').first.check()   # 第一个是 batch？用文案定位更稳
        pg.uncheck('input[type=checkbox]', force=True) if False else None
        # 精确定位"需要会话头"那一行的 checkbox
        pg.locator('label.adv-row input[type=checkbox]').check()
        pg.locator('button', has_text='保存 provider').click()
        pg.wait_for_selector('text=确认保存这些请求头', timeout=15000)
        out['confirmShowsHeader'] = 'x-opencode-session' in pg.inner_text('.dlg')
        pg.locator('button', has_text='我确认保存').click()
        pg.wait_for_function(
            "() => document.body.innerText.includes('已保存')", timeout=20000)
        saved = P.get_provider(ws, 'opencode-go') or {}
        out['savedHeaders'] = saved.get('headers')
        out['warnUnassigned'] = '还没分配到' in pg.inner_text('body')

        # 4) 编辑回填：勾选状态应为 true、文本框不应出现 {session}
        pg.locator('a', has_text='编辑').first.click()
        pg.wait_for_timeout(300)
        out['editChecked'] = pg.locator('label.adv-row input[type=checkbox]').is_checked()
        out['editNoPlaceholder'] = '{session}' not in pg.locator('.adv-box').inner_text()

        out['errors'] = errs
        b.close()
finally:
    httpd.shutdown()

print(json.dumps(out, ensure_ascii=False, indent=1))
assert not out['errors'], f"JS 错误：{out['errors']}"
assert out['order'], '高级块不在保存键上方'
assert out['noPlaceholderVisible'], '界面仍显示 {session} 占位符'
assert out['confirmShowsHeader'], '二次确认未列出请求头'
assert (out['savedHeaders'] or {}).get('x-opencode-session') == '{session}', \
    f"会话头未落盘：{out['savedHeaders']}"
assert out['warnUnassigned'], '未提示"还没分配到段"'
assert out['editChecked'], '编辑时勾选状态未回填'
assert out['editNoPlaceholder'], '编辑区仍显示 {session}'
print('OK d145-ux：高级块在保存键上方 · 勾选式会话头 · 不暴露占位符 · 保存反馈含未分配警告 · 编辑可回填')
PY
RC=$?
rm -f "$APP_DIR/tests/_d145.html" "$APP_DIR/tests/.d145.bundle.js" \
      "$APP_DIR/tests/.d145-panel.ts" "$APP_DIR/tests/_d145_entry.ts"
exit $RC
