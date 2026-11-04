#!/usr/bin/env bash
# D135：真实浏览器验证「跨作业知识点趋势」卡片。
#  - 挂载**真实组件** TrendCard.vue（@vue/compiler-sfc 编译）
#  - 连**真实引擎** /grade/trend（真实 workspace：3 次作业，同一知识点反复出错）
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d135-trend：未找到 python（$PY）"; exit 0; fi

node "$APP_DIR/tests/_d130_sfc_build.mjs" \
  "$APP_DIR/src/components/TrendCard.vue" "$APP_DIR/tests/.d135-trend.ts" || exit 1
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d135_trend_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d135-trend.bundle.js" \
  --log-level=error || exit 1

cat > "$APP_DIR/tests/_d135.trend.html" <<HTML
<!doctype html><meta charset="utf-8"><title>D135 trend</title>
<body><div id="app"></div>
<script src="./.d135-trend.bundle.js"></script>
</body>
HTML

D135_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, socket, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright

app = pathlib.Path(os.environ['D135_APP'])
sys.path.insert(0, str(app.parent / 'engine' / 'src'))

from assist import serve as S

ws = pathlib.Path(tempfile.mkdtemp())
(ws / 'kb').mkdir()
CLASS = 'classes/化工25'


def put(pack, name, students, ts):
    d = ws / CLASS / 'grading' / pack / 'evaluations'
    d.mkdir(parents=True, exist_ok=True)
    for stu, terms in students:
        rec = {'student': stu, 'timestamp': ts,
               'analysis': {'questions': [{'id': 1, 'errors': [
                   {'knowledge': [t], 'description': f'{t}出错', 'confidence': 'high'}
                   for t in terms]}]}}
        (d / f'{stu}.json').write_text(json.dumps(rec, ensure_ascii=False), encoding='utf-8')


# 动量守恒：三次都出现（持续）／角动量守恒：只在后两次（持续）／单次错点（one-off）
put('pack1', '作业1', [('张三', ['动量守恒']), ('李四', ['动量守恒'])], '2026-10-01 10:00')
put('pack2', '作业2', [('张三', ['动量守恒', '角动量守恒']),
                       ('李四', ['角动量守恒'])], '2026-10-10 10:00')
put('pack3', '作业3', [('张三', ['动量守恒', '角动量守恒', '单次错点'])], '2026-10-20 10:00')

# 作业包名（让报告显示"作业1/2/3"）
from assist.packs import save_pack
for pid, nm in (('pack1', '作业1'), ('pack2', '作业2'), ('pack3', '作业3')):
    save_pack(ws, pid, {'name': nm, 'class_dir': CLASS})

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
    print('SKIP d135-trend：未找到 Chromium'); httpd.shutdown(); sys.exit(0)

out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page()
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(
            f'window.__ENGINE_ADDR__ = {json.dumps(addr)};'
            f'window.__CLASS_DIR__ = {json.dumps(CLASS)};')
        pg.goto((app / 'tests' / '_d135.trend.html').resolve().as_uri())
        pg.wait_for_function('window.__ready === true', timeout=15000)
        # 注意：静态文案里本来就有"反复出错"四个字，必须等**数据**出现
        pg.wait_for_function(
            "() => document.body.innerText.includes('动量守恒')", timeout=20000)
        body = pg.inner_text('body')
        out = {
            'title': '知识点趋势' in body,
            'sequence': all(x in body for x in ('作业1', '作业2', '作业3')),
            'recurringShown': '动量守恒' in body and '角动量守恒' in body,
            'persisting': '仍在持续' in body,
            'sparklines': pg.locator('svg polyline').count(),
            'rows': pg.locator('table.tbl tbody tr').count(),
            'onlyTeacher': '只给教师' in body,
            'errors': errs,
        }
        b.close()
finally:
    httpd.shutdown()

print(json.dumps(out, ensure_ascii=False, indent=1))
assert not out['errors'], f"趋势卡 JS 错误：{out['errors']}"
assert out['title'] and out['onlyTeacher'], f"缺少标题/只给教师声明：{out}"
assert out['sequence'], f"作业序列未渲染：{out}"
assert out['recurringShown'], f"反复出错知识点未渲染：{out}"
assert out['persisting'], f"未标出「仍在持续」：{out}"
assert out['sparklines'] >= 2, f"走势折线未渲染：{out}"
assert out['rows'] >= 2, f"反复出错表格行数不足：{out}"
print('OK d135-trend：作业序列（按评阅时间）· 反复出错知识点 · 走势折线 · 持续/改善判定 · 只给教师')
PY
RC=$?
rm -f "$APP_DIR/tests/_d135.trend.html" "$APP_DIR/tests/.d135-trend.bundle.js" \
      "$APP_DIR/tests/.d135-trend.ts"
exit $RC
