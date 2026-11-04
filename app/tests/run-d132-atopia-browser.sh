#!/usr/bin/env bash
# D132：真实浏览器验证 Atopia 工作区（L3 不可执行 / L2 需二次确认 / 执行与审计）。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d132-atopia：未找到 python（$PY）"; exit 0; fi

node "$APP_DIR/tests/_d130_sfc_build.mjs" \
  "$APP_DIR/src/components/AtopiaPanel.vue" "$APP_DIR/tests/.d132-atopia.ts" || exit 1
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d132_atopia_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d132-asst.bundle.js" \
  --log-level=error || exit 1

cat > "$APP_DIR/tests/_d132.asst.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>D132 Atopia</title>
<body><div id="app"></div>
<script src="./.d132-asst.bundle.js"></script>
</body>
HTML

D132_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, socket, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright

app = pathlib.Path(os.environ['D132_APP'])
sys.path.insert(0, str(app.parent / 'engine' / 'src'))
from assist import serve as S

ws = pathlib.Path(tempfile.mkdtemp())
(ws / 'kb').mkdir()
S.Handler.ws = ws
S.Handler.token = ''
s0 = socket.socket(); s0.bind(('127.0.0.1', 0)); port = s0.getsockname()[1]; s0.close()
httpd = S.ThreadingHTTPServer(('127.0.0.1', port), S.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.2)
addr = f'http://127.0.0.1:{port}'
print(f'[engine] {addr}')

exe = None
root = pathlib.Path.home() / '.cache' / 'ms-playwright'
if root.is_dir():
    for d in sorted(root.iterdir()):
        cand = d / 'chrome-linux64' / 'chrome'
        if d.name.startswith('chromium-') and cand.exists():
            exe = str(cand)
if not exe:
    print('SKIP d132-atopia：未找到 Chromium'); httpd.shutdown(); sys.exit(0)

out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page()
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(f'window.__ENGINE_ADDR__ = {json.dumps(addr)};')
        pg.goto((app / 'tests' / '_d132.asst.html').resolve().as_uri())
        pg.wait_for_function('window.__ready === true', timeout=15000)
        pg.wait_for_selector('text=Atopia', timeout=15000)
        pg.wait_for_function(
            "() => document.body.innerText.includes('kb.stats')", timeout=20000)

        body = pg.inner_text('body')
        out['toolListed'] = 'kb.stats' in body
        out['l3ShownAsClosed'] = '不开放' in body

        # ---- L0 执行：rules.show ----
        pg.click('.tool:has-text("rules.show")')
        pg.click('button:has-text("▶ 执行")')
        pg.wait_for_function(
            "() => document.body.innerText.includes('执行成功')", timeout=25000)
        out['l0Ran'] = '执行成功' in pg.inner_text('body')

        # ---- L2：点执行后**不应立刻执行**，应出现确认框 ----
        pg.click('.tool:has-text("rules.reset")')
        pg.click('button:has-text("执行（需确认）")')
        pg.wait_for_selector('.confirm', timeout=10000)
        out['l2AsksConfirm'] = '我确认执行' in pg.inner_text('.confirm')

        # 未确认前不应写 journal 的 rules.reset
        j = json.loads(pg.request.get(f'{addr}/atopia/journal').text())
        out['notRunBeforeConfirm'] = not any(
            r.get('tool') == 'rules.reset' for r in j.get('records', []))

        # 确认后执行
        pg.click('button:has-text("我确认执行")')
        pg.wait_for_function(
            "() => document.body.innerText.includes('执行成功')", timeout=25000)
        j2 = json.loads(pg.request.get(f'{addr}/atopia/journal').text())
        rec = next((r for r in j2.get('records', []) if r.get('tool') == 'rules.reset'), None)
        out['l2RanAfterConfirm'] = rec is not None
        out['confirmedBy'] = (rec or {}).get('confirmed_by')
        out['journalShown'] = '最近调用' in pg.inner_text('body')
        out['errors'] = errs
        b.close()
finally:
    httpd.shutdown()

print(json.dumps(out, ensure_ascii=False, indent=1))
assert not out['errors'], f'JS 错误：{out["errors"]}'
assert out['toolListed'], '工具列表未渲染'
assert out['l3ShownAsClosed'], 'L3 未标明不开放'
assert out['l0Ran'], 'L0 工具未执行'
assert out['l2AsksConfirm'], 'L2 未要求二次确认'
assert out['notRunBeforeConfirm'], 'L2 在确认前就被执行了（严重）'
assert out['l2RanAfterConfirm'], '确认后 L2 未执行'
assert out['confirmedBy'] == 'teacher:pwa', f'确认来源未记录：{out["confirmedBy"]}'
assert out['journalShown'], '审计日志未显示'
print('OK d132-atopia：L3 不开放 · L0 直接执行 · L2 二次确认（确认前未执行，'
      '确认后执行且记 confirmed_by=teacher:pwa）· 审计日志可见')
PY
RC=$?
rm -f "$APP_DIR/tests/_d132.asst.html" "$APP_DIR/tests/.d132-asst.bundle.js" \
      "$APP_DIR/tests/.d132-atopia.ts"
exit $RC
