#!/usr/bin/env bash
# D130-T9：真实浏览器验证「评阅规则卡」—— 挂载**真实** GradingRulesCard.vue，
# 连**真实**引擎 HTTP 服务（/rules、/rules/save、/rules/reset），
# 验证：只读摘要可见 / 数值可改且越界拦截 / 保存后引擎落盘 / 恢复默认 / 扩展项可改名。
# 需要 python 环境已装 playwright（本仓库：.scratch/venv）。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d130-rules-browser：未找到 python（$PY）"; exit 0; fi

# 1) 编译真实 SFC（esbuild 不会编译 .vue，必须先用 @vue/compiler-sfc）
node "$APP_DIR/tests/_d130_sfc_build.mjs" \
  "$APP_DIR/src/components/GradingRulesCard.vue" "$APP_DIR/tests/.d130-card.ts" || exit 1
# 2) 打包入口（含案头组件 + vue runtime）
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d130_rules_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d130-rules.bundle.js" \
  --log-level=error || exit 1

cat > "$APP_DIR/tests/_d130.rules.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>D130 rules card</title>
<body><div id="app"></div>
<script src="./.d130-rules.bundle.js"></script>
</body>
HTML

D130_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, sys, tempfile, threading, time, socket

from playwright.sync_api import sync_playwright

app = pathlib.Path(os.environ['D130_APP'])
sys.path.insert(0, str(app.parent / 'engine' / 'src'))

# ---- 真实引擎 HTTP 服务（只用规则读写，不碰学习通） ----
from assist import serve as S
from assist.grading import rules as R

ws = pathlib.Path(tempfile.mkdtemp())
(ws / 'kb').mkdir()
S.Handler.ws = ws
S.Handler.token = ''
s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
httpd = S.ThreadingHTTPServer(('127.0.0.1', port), S.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.2)
addr = f'http://127.0.0.1:{port}'
print(f'[engine] {addr} ws={ws}')

exe = None
root = pathlib.Path.home() / '.cache' / 'ms-playwright'
if root.is_dir():
    for d in sorted(root.iterdir()):
        cand = d / 'chrome-linux64' / 'chrome'
        if d.name.startswith('chromium-') and cand.exists():
            exe = str(cand)
if not exe:
    print('SKIP d130-rules-browser：未找到 Chromium'); httpd.shutdown(); sys.exit(0)

url = (app / 'tests' / '_d130.rules.html').resolve().as_uri()
out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page()
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(f'window.__ENGINE_ADDR__ = {json.dumps(addr)};')
        pg.goto(url)
        pg.wait_for_function('window.__ready === true', timeout=15000)
        # 等卡片读到规则（只读摘要出现）
        pg.wait_for_selector('text=评阅规则卡', timeout=15000)
        pg.wait_for_function(
            "() => document.body.innerText.includes('【评阅范式')", timeout=15000)

        out['hasReadonlySummary'] = '【评阅范式' in pg.inner_text('body')
        out['kindTabs'] = pg.locator('.kind-tabs button').count()

        # ---- 越界拦截：把全局比例改成 9 → 前端应拦住（不请求保存） ----
        pg.click('text=全局规则')
        # 全局区在 <details> 内；限定作用域，避免与题型区同名输入框撞车
        ratio = pg.locator('details', has_text='全局规则') \
                  .locator('.num-item', has_text='整体简略触发比例').locator('input').first
        ratio.fill('9')
        pg.click('button:has-text("保存")')
        pg.wait_for_timeout(400)
        out['rangeBlockedMsg'] = '超出范围' in pg.inner_text('body')
        out['engineUnchangedAfterBad'] = (R.global_rules(ws)['allBriefRatio'] == 0.8)
        # 复位越界值（否则后续任何保存都会被前端拦下——这正是拦截生效的证据）
        ratio.fill('0.8')

        # ---- 合法修改：qa 每缺要点扣分 5 → 8，保存后引擎落盘 ----
        pg.click('.kind-tabs button:has-text("qa")')
        pg.wait_for_timeout(150)
        # 全局区也有「每个缺失要点扣分」之外的同名项；用 first（题型区在全局 details 之前）
        miss = pg.locator('.num-item', has_text='每个缺失要点扣分').locator('input').first
        miss.fill('8')
        pg.click('button:has-text("保存")')
        # 保存后组件会重新 load()（按设计：以引擎返回为准刷新草稿），
        # 所以这里断言**引擎落盘 + 只读摘要同步**，而不是会一闪而过的提示文案。
        pg.wait_for_function(
            "() => document.body.innerText.includes('扣 8 分')", timeout=15000)
        out['enginePerMissingPoint'] = R.type_rules(ws, 'qa')['perMissingPointDeduct']
        out['summaryUpdated'] = '扣 8 分' in pg.inner_text('body')

        # ---- 扩展项改名：qa/problems 无 checklist ----
        # D170-T9：copy 已改为 topicMatch（不再有"抄全三项"），
        # 现在**唯一**保留 checklist 的类型是 summary → 用它测该扩展项。
        pg.click('.kind-tabs button:has-text("summary")')
        pg.wait_for_timeout(150)
        chk = pg.locator('.chk-input')
        out['hasChecklistInput'] = chk.count() == 1
        chk.fill('知识点与概念，重要公式及推导，受力图')
        chk.dispatch_event('change')
        pg.click('button:has-text("保存")')
        pg.wait_for_timeout(800)
        out['engineChecklist'] = R.type_rules(ws, 'summary')['checklist']

        # ---- 恢复默认（有 confirm） ----
        pg.once('dialog', lambda d: d.accept())
        pg.click('button:has-text("恢复默认")')
        pg.wait_for_timeout(1200)
        out['afterResetPerMissingPoint'] = R.type_rules(ws, 'qa')['perMissingPointDeduct']
        out['afterResetChecklist'] = R.type_rules(ws, 'summary')['checklist']
        out['pageErrors'] = errs
        b.close()
finally:
    httpd.shutdown()

print(json.dumps(out, ensure_ascii=False, indent=1))
assert not out['pageErrors'], f'页面有 JS 错误：{out["pageErrors"]}'
assert out['hasReadonlySummary'], '未显示只读规则摘要（教师看不到规则正文）'
assert out['kindTabs'] >= 7, f'题型页签不足：{out["kindTabs"]}'
assert out['rangeBlockedMsg'], '越界数值未被前端拦截'
assert out['engineUnchangedAfterBad'], '越界数值竟然写进了引擎'
assert out['enginePerMissingPoint'] == 8, f'保存未生效：{out}'
assert out['summaryUpdated'], '只读摘要未随规则同步（改了数值但提示词没变）'
assert out['hasChecklistInput'], 'copy 题型缺少「检查项名称」可改扩展'
assert out['engineChecklist'] == ['知识点与概念', '重要公式及推导', '受力图'], f'检查项改名未落盘：{out}'
assert out['afterResetPerMissingPoint'] == 5 and \
       out['afterResetChecklist'] == ['知识点与概念', '重要公式及推导', '示意图'], f'恢复默认失败：{out}'
print('OK d130-rules-browser：真实组件+真实引擎 —— 只读摘要/越界拦截/保存落盘/摘要同步/'
      '扩展项改名/恢复默认 全部通过')
PY
RC=$?
rm -f "$APP_DIR/tests/_d130.rules.html" "$APP_DIR/tests/.d130-rules.bundle.js" \
      "$APP_DIR/tests/.d130-card.ts"
exit $RC
