#!/usr/bin/env bash
# D134-T3e：真实浏览器验证课堂资料页的「上传附件 / 文件列表 / 移除（二次确认 → 回收站）」。
#  - 挂载**真实组件** MaterialsView.vue
#  - 连**真实引擎**：POST /materials/upload、GET /materials/files、atopia/tools 的 materials.remove
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d134-upload：未找到 python（$PY）"; exit 0; fi

node "$APP_DIR/tests/_d130_sfc_build.mjs" \
  "$APP_DIR/src/views/MaterialsView.vue" "$APP_DIR/tests/.d134-materials.ts" || exit 1
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d134_upload_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d134-upload.bundle.js" \
  --log-level=error || exit 1

cat > "$APP_DIR/tests/_d134.upload.html" <<HTML
<!doctype html><meta charset="utf-8"><title>D134 upload</title>
<body><div id="app"></div>
<script src="./.d134-upload.bundle.js"></script>
</body>
HTML

D134_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, socket, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright

app = pathlib.Path(os.environ['D134_APP'])
sys.path.insert(0, str(app.parent / 'engine' / 'src'))

from assist import serve as S
from assist.files import materials as M

ws = pathlib.Path(tempfile.mkdtemp())
(ws / 'kb').mkdir()
M.ensure_chap(ws, 'chap04')

S.Handler.ws = ws
S.Handler.token = ''
s0 = socket.socket(); s0.bind(('127.0.0.1', 0)); port = s0.getsockname()[1]; s0.close()
httpd = S.ThreadingHTTPServer(('127.0.0.1', port), S.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.2)
addr = f'http://127.0.0.1:{port}'
print(f'[engine] {addr} ws={ws}')

exe = None
root = pathlib.Path.home() / '.cache' / 'ms-playwright'
if root.is_dir():
    for dd in sorted(root.iterdir()):
        cand = dd / 'chrome-linux64' / 'chrome'
        if dd.name.startswith('chromium-') and cand.exists():
            exe = str(cand)
if not exe:
    print('SKIP d134-upload：未找到 Chromium'); httpd.shutdown(); sys.exit(0)

out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page()
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(f'window.__ENGINE_ADDR__ = {json.dumps(addr)};')
        pg.goto((app / 'tests' / '_d134.upload.html').resolve().as_uri())
        pg.wait_for_function('window.__ready === true', timeout=15000)
        pg.wait_for_function(
            "() => document.body.innerText.includes('chap04')", timeout=20000)

        # ---- 上传两个文件（其中一个用危险扩展名，应被前端拒绝）----
        pg.set_input_files('input[type=file]', [
            {'name': 'plan.md', 'mimeType': 'text/markdown',
             'buffer': '第4章 动量守恒'.encode()},
            {'name': 'evil.exe', 'mimeType': 'application/octet-stream',
             'buffer': b'MZ'},
        ])
        pg.wait_for_function(
            "() => document.body.innerText.includes('已上传 1 个')", timeout=20000)
        pg.wait_for_function(
            "() => document.body.innerText.includes('plan.md')", timeout=20000)
        body = pg.inner_text('body')
        src = ws / 'materials' / 'chap04' / '_source'
        out['upload'] = {
            'saved': (src / 'plan.md').is_file(),
            'contentOk': (src / 'plan.md').read_text(encoding='utf-8') == '第4章 动量守恒',
            'exeRejected': not (src / 'evil.exe').exists(),
            'rejectShown': '已拒绝' in body,
            'listedInTable': 'plan.md' in body,
        }

        # ---- 同名再传一次：引擎自动改名 -2，不覆盖原件 ----
        pg.set_input_files('input[type=file]', [
            {'name': 'plan.md', 'mimeType': 'text/markdown', 'buffer': 'v2'.encode()},
        ])
        pg.wait_for_function(
            "() => document.body.innerText.includes('同名已自动改名')", timeout=20000)
        out['sameName'] = {
            'originalIntact': (src / 'plan.md').read_text(encoding='utf-8') == '第4章 动量守恒',
            'renamed': (src / 'plan-2.md').is_file(),
            'noticeShown': 'plan-2.md' in pg.inner_text('body'),
        }

        # ---- 移除：必须先二次确认，确认后才进回收站 ----
        pg.locator('button', has_text='移除').first.click()
        pg.wait_for_selector('text=确认移除原件？', timeout=10000)
        out['removeConfirm'] = {
            'dialogShown': True,
            'notYetMoved': (src / 'plan.md').is_file(),   # 未确认前不动
        }
        pg.locator('button', has_text='我确认移除').click()
        pg.wait_for_function(
            "() => document.body.innerText.includes('已移入回收站')", timeout=20000)
        trash = src / '_trash'
        trashed = sorted(x.name for x in trash.glob('*.md'))
        out['removeConfirm'].update({
            'trashedFiles': trashed,
            'inTrash': len(trashed) == 1,
            'contentPreserved': any((trash / n).read_text(encoding='utf-8')
                                    in ('第4章 动量守恒', 'v2') for n in trashed),
            'sourceOnlyOneLeft': len(list(src.glob('*.md'))) <= 1,
        })
        out['errors'] = errs
        b.close()
finally:
    httpd.shutdown()

print(json.dumps(out, ensure_ascii=False, indent=1))
u = out['upload']; s = out['sameName']; r = out['removeConfirm']
assert not out['errors'], f"资料页 JS 错误：{out['errors']}"
assert u['saved'] and u['contentOk'], f"上传未落盘：{u}"
assert u['exeRejected'] and u['rejectShown'], f"危险扩展名未被拒绝：{u}"
assert u['listedInTable'], f"上传后未出现在文件列表：{u}"
assert s['originalIntact'] and s['renamed'] and s['noticeShown'], f"同名未安全改名：{s}"
assert r['dialogShown'] and r['notYetMoved'], f"移除未经二次确认就执行：{r}"
assert r['inTrash'] and r['contentPreserved'], f"移除未进回收站或内容丢失：{r}"
print('OK d134-upload：扩展名白名单 · 同名不覆盖（自动 -2）· 移除二次确认 · 只进回收站不真删')
PY
RC=$?
rm -f "$APP_DIR/tests/_d134.upload.html" "$APP_DIR/tests/.d134-upload.bundle.js" \
      "$APP_DIR/tests/.d134-materials.ts"
exit $RC
