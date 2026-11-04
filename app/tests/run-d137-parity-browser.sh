#!/usr/bin/env bash
# D137：真实浏览器验证 PWA 对齐 —— 资料页三动作（抽取/AI建议/确认生效）+ Atopia 护栏可改。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d137-parity：未找到 python（$PY）"; exit 0; fi

node "$APP_DIR/tests/_d130_sfc_build.mjs" "$APP_DIR/src/views/MaterialsView.vue" \
  "$APP_DIR/tests/.d137-materials.ts" || exit 1
node "$APP_DIR/tests/_d130_sfc_build.mjs" "$APP_DIR/src/components/AtopiaPanel.vue" \
  "$APP_DIR/tests/.d137-atopia.ts" || exit 1
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d137_parity_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d137-parity.bundle.js" \
  --log-level=error || exit 1

for PAGE in materials atopia; do
cat > "$APP_DIR/tests/_d137.$PAGE.html" <<HTML
<!doctype html><meta charset="utf-8"><title>D137 $PAGE</title>
<body><div id="app"></div>
<script src="./.d137-parity.bundle.js"></script>
</body>
HTML
done

D137_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, socket, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright

app = pathlib.Path(os.environ['D137_APP'])
sys.path.insert(0, str(app.parent / 'engine' / 'src'))
from assist import serve as S
from assist.files import materials as M
from assist.atopia import limits as L

ws = pathlib.Path(tempfile.mkdtemp()); (ws / 'kb').mkdir()
d = M.ensure_chap(ws, 'chap04')
(d / '_source' / 'plan.md').write_text('第4章 动量守恒；完全弹性碰撞', encoding='utf-8')
# 预置一份 AI 建议（模拟已点过「AI 建议知识点」），用于验证确认弹窗展示全文
(d / M.KNOW_AI).write_text(json.dumps({
    'chap': 'chap04',
    'knowledge': [{'term': '动量守恒', 'aliases': [], 'importance': 'core',
                   'evidence': '第1页'},
                  {'term': '完全弹性碰撞', 'aliases': [], 'importance': 'supporting',
                   'evidence': '第1页'}],
    'logic': [], 'generatedAt': '2026-10-31'}, ensure_ascii=False), encoding='utf-8')

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
    print('SKIP d137-parity：未找到 Chromium'); httpd.shutdown(); sys.exit(0)

out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)

        # ---- 资料页：抽取 → 确认弹窗展示全文 → 确认生效 ----
        pg = b.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(f'window.__ENGINE_ADDR__={json.dumps(addr)};'
                           f'window.__WHICH__="materials";')
        pg.goto((app / 'tests' / '_d137.materials.html').resolve().as_uri())
        pg.wait_for_function('window.__ready===true', timeout=15000)
        pg.wait_for_function("() => document.body.innerText.includes('chap04')", timeout=20000)

        # ① 抽取
        pg.locator('button', has_text='① 抽取').click()
        pg.wait_for_function("() => document.body.innerText.includes('已抽取')", timeout=30000)
        out_extract = (M.chap_dir(ws, 'chap04') / M.INDEX).is_file()

        # ③ 确认生效（必须展示全文）
        pg.locator('button', has_text='③ 确认生效').click()
        pg.wait_for_selector('text=确认让这份清单成为批阅依据？', timeout=20000)
        dlg_text = pg.inner_text('.dlg.wide')
        out_confirm_dialog = {'showsTerms': '动量守恒' in dlg_text
                              and '完全弹性碰撞' in dlg_text,
                              'count': '共 2 个知识点' in dlg_text}
        pg.locator('button', has_text='我确认生效').click()
        pg.wait_for_function(
            "() => document.body.innerText.includes('已确认生效')", timeout=30000)
        out_confirm = {'mdCreated': (M.chap_dir(ws, 'chap04') / M.KNOW_MD).is_file(),
                       'statusShown': '✅ 已生效' in pg.inner_text('body')}

        # ---- Atopia 护栏可改 ----
        pg2 = b.new_page(); errs2 = []
        pg2.on('pageerror', lambda e: errs2.append(str(e)))
        pg2.add_init_script(f'window.__ENGINE_ADDR__={json.dumps(addr)};'
                            f'window.__WHICH__="atopia";')
        pg2.goto((app / 'tests' / '_d137.atopia.html').resolve().as_uri())
        pg2.wait_for_function('window.__ready===true', timeout=15000)
        pg2.wait_for_function("() => document.body.innerText.includes('护栏')", timeout=20000)
        inp = pg2.locator('.lim-item input').first
        inp.fill('66')
        pg2.locator('button', has_text='保存护栏').click()
        pg2.wait_for_selector('text=将修改护栏', timeout=15000)
        pg2.locator('button', has_text='我确认修改').click()
        pg2.wait_for_function(
            "() => document.body.innerText.includes('护栏已保存')", timeout=20000)
        out_limits = {'saved': L.read_limits(ws)['maxCallsPerSession'] == 66}

        # ---- A1：provider 请求头经 HTTP 写入（白名单在引擎侧） ----
        import urllib.request
        def post(path, payload):
            req = urllib.request.Request(
                f'{addr}{path}', data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json'}, method='POST')
            try:
                return json.loads(urllib.request.urlopen(req).read().decode())
            except urllib.error.HTTPError as e:
                return json.loads(e.read().decode())

        ok_rep = post('/llm/provider', {
            'action': 'set', 'name': 'oc',
            'base_url': 'https://opencode.ai/inference/go/openai/v1',
            'headers': {'x-opencode-session': '{session}'},
            'user_agent': 'assignment-assistant/test'})
        bad_rep = post('/llm/provider', {
            'action': 'set', 'name': 'evil',
            'headers': {'Authorization': 'Bearer x'}})
        from assist.grading import providers as PR
        out_hdr = {
            'saved': ok_rep.get('ok') is True
                     and (PR.get_provider(ws, 'oc') or {}).get('headers', {})
                         .get('x-opencode-session') == '{session}',
            'rejected': bad_rep.get('ok') is False
                        and 'Authorization' in str(bad_rep.get('error') or ''),
        }

        out = {'extract': out_extract, 'confirmDialog': out_confirm_dialog,
               'confirm': out_confirm, 'limits': out_limits, 'headers': out_hdr,
               'errors': errs + errs2}
        b.close()
finally:
    httpd.shutdown()

print(json.dumps(out, ensure_ascii=False, indent=1))
assert not out['errors'], f"JS 错误：{out['errors']}"
assert out['extract'], '抽取未产出 索引.json'
assert out['confirmDialog']['showsTerms'], f"确认弹窗未展示清单全文：{out['confirmDialog']}"
assert out['confirm']['mdCreated'] and out['confirm']['statusShown'], f"确认未生效：{out['confirm']}"
assert out['limits']['saved'], f"护栏未保存：{out['limits']}"
assert out['headers']['saved'], f"provider 请求头未写入：{out['headers']}"
assert out['headers']['rejected'], f"Authorization 头未被拒绝：{out['headers']}"
print('OK d137-parity：资料页①抽取 · ③确认弹窗展示全文并生效 · Atopia 护栏可改（二次确认）· provider 请求头可写且拒敏感头')
PY
RC=$?
rm -f "$APP_DIR/tests/_d137.materials.html" "$APP_DIR/tests/_d137.atopia.html" \
      "$APP_DIR/tests/.d137-parity.bundle.js" "$APP_DIR/tests/.d137-materials.ts" \
      "$APP_DIR/tests/.d137-atopia.ts"
exit $RC
