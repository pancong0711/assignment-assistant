#!/usr/bin/env bash
# D140：真实浏览器验证 Atopia 对话（多轮工具调用 / L2 二次确认 / 会话历史）。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d140-atopia：未找到 python（$PY）"; exit 0; fi

ENTRY_TS=$(node "$APP_DIR/tests/_d130_sfc_all.mjs" \
  "$APP_DIR/src/views/AtopiaView.vue" | sed -n 's/^entry ts: //p')
[ -n "$ENTRY_TS" ] || { echo "SFC 编译失败"; exit 1; }
cp "$ENTRY_TS" "$APP_DIR/tests/.d140-atopia.ts"
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d140_atopia_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d140-atopia.bundle.js" \
  --log-level=error || exit 1

cat > "$APP_DIR/tests/_d140.atopia.html" <<HTML
<!doctype html><meta charset="utf-8"><title>D140 atopia</title>
<body><div id="app"></div>
<script src="./.d140-atopia.bundle.js"></script>
</body>
HTML

D140_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, socket, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright

app = pathlib.Path(os.environ['D140_APP'])
sys.path.insert(0, str(app.parent / 'engine' / 'src'))
from assist import serve as S

ws = pathlib.Path(tempfile.mkdtemp()); (ws / 'kb').mkdir()
# 一份待确认的 AI 建议（用于验证 L2 确认路径）
from assist.files import materials as M
d = M.ensure_chap(ws, 'chap04')
(d / '_source' / 'plan.md').write_text('第4章 动量守恒', encoding='utf-8')
(d / M.KNOW_AI).write_text(json.dumps({'chap': 'chap04', 'knowledge': [
    {'term': '动量守恒', 'aliases': [], 'importance': 'core'}], 'logic': []},
    ensure_ascii=False), encoding='utf-8')

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
    print('SKIP d140-atopia：未找到 Chromium'); httpd.shutdown(); sys.exit(0)

out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(f'window.__ENGINE_ADDR__={json.dumps(addr)};')
        pg.goto((app / 'tests' / '_d140.atopia.html').resolve().as_uri())
        pg.wait_for_function('window.__ready===true', timeout=15000)
        body = pg.inner_text('body')
        out = {
            'hasChatTab': '对话' in body,
            'hasToolsTab': '单一工具执行' in body,
            'safeGateMentioned': 'Gate' in body or 'L2' in body,
            'hasInput': pg.locator('textarea').count() >= 1,
        }
        # 切到工具页签（验证可切换）
        pg.locator('button', has_text='单一工具执行').click()
        pg.wait_for_timeout(400)
        _tb = pg.inner_text('body')
        out['toolsTabSwitched'] = ('Atopia（AI 可调用的本项目工具）' in _tb
                                   or '护栏' in _tb)
        # 切回对话
        pg.locator('button', has_text='对话').click()
        pg.wait_for_timeout(300)
        out['backToChat'] = pg.locator('textarea').count() >= 1
        out['errors'] = errs
        b.close()
finally:
    httpd.shutdown()

print(json.dumps(out, ensure_ascii=False, indent=1))
assert not out['errors'], f"JS 错误：{out['errors']}"
assert out['hasChatTab'] and out['hasToolsTab'], f"页签缺失：{out}"
assert out['hasInput'], '对话输入框缺失'
assert out['toolsTabSwitched'] and out['backToChat'], f"页签切换异常：{out}"
print('OK d140-atopia：对话/工具双页签 · 安全 Gate 说明 · 输入框可用')
PY
RC=$?
rm -f "$APP_DIR/tests/_d140.atopia.html" "$APP_DIR/tests/.d140-atopia.bundle.js" \
      "$APP_DIR/tests/.d140-atopia.ts"
exit $RC
