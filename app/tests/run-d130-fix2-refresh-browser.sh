#!/usr/bin/env bash
# D130-FIX2：复现「刷新后逐生审核 AI 状态 / tag 不显示」并验证已修复。
#  挂载**真实** AiGradingPanel（不选作业包，等于刷新后的状态），
#  连**真实引擎**（有 roster + 已有批阅草稿），断言：
#   - tag 列显示（来自本校名单 join）
#   - AI 状态列显示「已评阅」（引擎从磁盘反查批阅目录）
#   - 「🔄 读取状态」按钮存在且可点
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d130-fix2：未找到 python（$PY）"; exit 0; fi

# 递归编译面板及其 import 的所有 .vue（含弹窗/规则卡/教师报告/Assistopia）
ENTRY_TS=$("$APP_DIR/node_modules/.bin/../.." 2>/dev/null; node "$APP_DIR/tests/_d130_sfc_all.mjs" \
  "$APP_DIR/src/components/AiGradingPanel.vue" | sed -n 's/^entry ts: //p')
[ -n "$ENTRY_TS" ] || { echo "SFC 编译失败"; exit 1; }
cp "$ENTRY_TS" "$APP_DIR/tests/.d130fix2-panel.ts"

cat > "$APP_DIR/tests/_d130fix2_entry.ts" <<'TS'
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import AiGradingPanel from './.d130fix2-panel.ts'
import { useSettingsStore } from '../src/stores/settings'
const addr = (window as any).__ENGINE_ADDR__ || ''
const app = createApp({ render: () => h(AiGradingPanel, { engineAddr: addr, token: '' }) })
const pinia = createPinia()
app.use(pinia)
useSettingsStore(pinia).engineUrl = addr
app.mount('#app')
;(window as any).__ready = true
TS

"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d130fix2_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d130fix2.bundle.js" \
  --log-level=error || exit 1

cat > "$APP_DIR/tests/_d130fix2.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>D130-FIX2</title>
<body><div id="app"></div>
<script src="./.d130fix2.bundle.js"></script>
</body>
HTML

D130F2_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, socket, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright

app = pathlib.Path(os.environ['D130F2_APP'])
sys.path.insert(0, str(app.parent / 'engine' / 'src'))
from assist import serve as S
from assist.files import roster_io

ws = pathlib.Path(tempfile.mkdtemp())
(ws / 'kb').mkdir()
roster_io.write_roster(ws, 'classes/化工25',
                       [{'name': '张三', 'number': '1', 'tag': 'q1'},
                        {'name': '李四', 'number': '2', 'tag': 'q2'}])
# 已有批阅草稿（AI 已评阅）——模拟"升级/刷新前跑过批阅"
d = ws / 'classes' / '化工25' / 'grading' / 'pack1' / 'drafts'
d.mkdir(parents=True)
(d / 'wid1.json').write_text(json.dumps({
    '张三': {'ai': {'transcript': '转写内容', 'comment': 'AI 批语', 'score': 88}},
}, ensure_ascii=False), encoding='utf-8')
# 学习通批阅目录：让 ③ 区「作业」下拉有内容（否则不会自动选作业 → 不触发读学生）
review = ws / 'xxt' / 'pages' / 'review' / 'cid1' / 'wid1'
review.mkdir(parents=True)
(review / 'list.html').write_text(
    '<ul class="dataBody_td"><div class="py_name">张三</div></ul>'
    '<ul class="dataBody_td"><div class="py_name">李四</div></ul>', encoding='utf-8')
(review / 'students.json').write_text(json.dumps({
    'courseId': 'course1', 'className': '化工25',
    'students': [{'name': '张三', 'workAnswerId': 'wa1'},
                 {'name': '李四', 'workAnswerId': 'wa2'}],
}, ensure_ascii=False), encoding='utf-8')
(review / 'zhangsan_1.jpg').write_bytes(b'\xff\xd8\xff\xd9')
# 类映射：学习通班级 → 本地班级目录（否则 classDir 为空，反查不到目录）
(ws / 'settings.local.json').write_text(json.dumps({
    'xxt': {'class_map': {'course1:cid1': 'classes/化工25'}},
}, ensure_ascii=False), encoding='utf-8')

# xxt 工件根要指向本测试 workspace（否则会去找真实 workspace 的 .runtime/xxt）
os.environ['XXT_HOME'] = str(ws / 'xxt')
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
    print('SKIP d130-fix2：未找到 Chromium'); httpd.shutdown(); sys.exit(0)

out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page()
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(f'window.__ENGINE_ADDR__ = {json.dumps(addr)};')
        pg.goto((app / 'tests' / '_d130fix2.html').resolve().as_uri())
        pg.wait_for_function('window.__ready === true', timeout=20000)
        pg.wait_for_selector('text=AI 辅助批阅', timeout=20000)
        try:
            pg.wait_for_selector('text=读取状态', timeout=20000)
        except Exception:
            print('[DEBUG] body >>>')
            print(pg.inner_text('body')[:1500])
            print('[DEBUG] errors:', errs)
            raise
        # 等学生表出现（引擎反查目录后应能读到）
        try:
            pg.wait_for_selector('.review-list-table', timeout=20000)
        except Exception:
            print('[DEBUG] body:', pg.inner_text('body')[:900])
            raise
        body = pg.inner_text('.review-list-table')
        out['hasButton'] = True
        out['tagShown'] = 'q1' in body or 'q2' in body
        out['aiStateShown'] = '已评阅' in body
        out['scoreShown'] = '88' in body
        out['errors'] = errs
        b.close()
finally:
    httpd.shutdown()

print(json.dumps(out, ensure_ascii=False, indent=1))
assert not out['errors'], f'JS 错误：{out["errors"]}'
assert out['tagShown'], 'tag 列仍为空（应来自名单 join）'
assert out['aiStateShown'], 'AI 状态仍显示未跑（引擎未反查到批阅目录）'
assert out['scoreShown'], 'AI 分未显示'
print('OK d130-fix2：刷新后（未选作业包）tag 与 AI 状态正常显示，「读取状态」按钮可用')
PY
RC=$?
rm -f "$APP_DIR/tests/_d130fix2.html" "$APP_DIR/tests/.d130fix2.bundle.js" \
      "$APP_DIR/tests/_d130fix2_entry.ts" "$APP_DIR/tests/.d130fix2-panel.ts" \
      "$APP_DIR"/src/components/*.compiled-*.ts
exit $RC
