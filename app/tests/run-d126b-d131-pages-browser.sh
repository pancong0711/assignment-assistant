#!/usr/bin/env bash
# D126-B / D131：真实浏览器验证「教师总结报告卡」与「课堂资料页」。
#  - 挂载**真实组件**（@vue/compiler-sfc 编译，非复刻）
#  - 连**真实引擎**（/grade/teacher-report、/materials/list、/materials/knowledge）
# 需要 python 已装 playwright（本仓库 .scratch/venv）。
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$APP_DIR/../.scratch/venv/bin/python}"
if [ ! -x "$PY" ]; then echo "SKIP d126b-d131-pages：未找到 python（$PY）"; exit 0; fi

node "$APP_DIR/tests/_d130_sfc_build.mjs" \
  "$APP_DIR/src/components/TeacherReportCard.vue" "$APP_DIR/tests/.d126b-teacher.ts" || exit 1
node "$APP_DIR/tests/_d130_sfc_build.mjs" \
  "$APP_DIR/src/views/MaterialsView.vue" "$APP_DIR/tests/.d131-materials.ts" || exit 1
"$APP_DIR/node_modules/.bin/esbuild" "$APP_DIR/tests/_d131_pages_entry.ts" \
  --bundle --format=iife --outfile="$APP_DIR/tests/.d131-pages.bundle.js" \
  --log-level=error || exit 1

for PAGE in teacher materials; do
cat > "$APP_DIR/tests/_d131.$PAGE.html" <<HTML
<!doctype html><meta charset="utf-8"><title>D126B/D131 $PAGE</title>
<body><div id="app"></div>
<script src="./.d131-pages.bundle.js"></script>
</body>
HTML
done

D131_APP="$APP_DIR" "$PY" - <<'PY'
import json, os, pathlib, socket, sys, tempfile, threading, time
from playwright.sync_api import sync_playwright

app = pathlib.Path(os.environ['D131_APP'])
sys.path.insert(0, str(app.parent / 'engine' / 'src'))

from assist import serve as S
from assist.files import materials as M
from assist.grading.flow import grading_dir

# ---- 真实 workspace：一条 evaluations + 一章已确认的课堂资料 ----
ws = pathlib.Path(tempfile.mkdtemp())
(ws / 'kb').mkdir()
task = {'id': 'pack1', 'class_dir': 'classes/化工25', 'items': []}
ev = grading_dir(ws, task) / 'evaluations'
ev.mkdir(parents=True, exist_ok=True)

def rec(stu, score, terms, missing=()):
    return {'student': stu, 'total_score': score,
            'analysis': {'questions': [{'id': 1, 'errors': [
                {'knowledge': [t], 'description': f'{t}出错', 'confidence': 'high'}
                for t in terms]}]},
            'per_question_scores': [score],
            'per_question_rules': [{'id': 1, 'kind': 'problems', 'deduct': 5}],
            'knowledge_missing': list(missing)}

(ev / '张三.json').write_text(json.dumps(rec('张三', 80, ['动量守恒', '完全弹性碰撞'],
                                             ['完全弹性碰撞']), ensure_ascii=False), encoding='utf-8')
(ev / '李四.json').write_text(json.dumps(rec('李四', 60, ['动量守恒']), ensure_ascii=False), encoding='utf-8')

d = M.ensure_chap(ws, 'chap04')
(d / '_source' / 'plan.md').write_text('第4章：动量守恒；完全弹性碰撞', encoding='utf-8')
M.extract_chap(ws, 'chap04')
(d / M.KNOW_AI).write_text(json.dumps({'chap': 'chap04', 'knowledge': [
    {'term': '动量守恒', 'aliases': [], 'importance': 'core', 'evidence': '第1页'},
    {'term': '完全弹性碰撞', 'aliases': [], 'importance': 'supporting', 'evidence': '第1页'},
], 'logic': [], 'generatedAt': '2026-10-30'}, ensure_ascii=False), encoding='utf-8')
M.confirm_knowledge(ws, 'chap04')

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
    print('SKIP d126b-d131-pages：未找到 Chromium'); httpd.shutdown(); sys.exit(0)

out = {}
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)

        # ---------- 教师总结报告卡 ----------
        pg = b.new_page()
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script(
            'window.__WHICH__ = "teacher";'
            f'window.__ENGINE_ADDR__ = {json.dumps(addr)};'
            'window.__PROPS__ = {classDir: "classes/化工25", taskId: "pack1"};')
        pg.goto((app / 'tests' / '_d131.teacher.html').resolve().as_uri())
        pg.wait_for_function('window.__ready === true', timeout=15000)
        pg.wait_for_selector('text=教师总结报告', timeout=15000)
        pg.wait_for_function(
            "() => document.body.innerText.includes('已汇总 2 名学生')", timeout=20000)
        body = pg.inner_text('body')
        out['teacher'] = {
            'students': '已评阅' in body,
            'topk': '动量守恒' in body and '完全弹性碰撞' in body,
            'matrixSvg': pg.locator('svg.mx').count() == 1,
            'bars': pg.locator('svg.bars rect').count(),
            'segments': '分数段分布' in body,
            'onlyTeacher': '不发给学生' in body or '不上传、不发学生' in body,
            'errors': errs,
        }

        # ---------- 课堂资料页 ----------
        pg2 = b.new_page()
        errs2 = []
        pg2.on('pageerror', lambda e: errs2.append(str(e)))
        pg2.add_init_script(f'window.__WHICH__ = "materials";'
                            f'window.__ENGINE_ADDR__ = {json.dumps(addr)};')
        pg2.goto((app / 'tests' / '_d131.materials.html').resolve().as_uri())
        pg2.wait_for_function('window.__ready === true', timeout=15000)
        pg2.wait_for_function(
            "() => document.body.innerText.includes('已生效')", timeout=20000)
        body2 = pg2.inner_text('body')
        out['materials'] = {
            'chapListed': 'chap04' in body2,
            'confirmed': '已生效' in body2,
            'terms': '动量守恒' in body2 and '完全弹性碰撞' in body2,
            'nextStepDone': '已完成' in body2,
            'errors': errs2,
        }
        b.close()
finally:
    httpd.shutdown()

print(json.dumps(out, ensure_ascii=False, indent=1))
t = out['teacher']; m = out['materials']
assert not t['errors'], f"教师报告页 JS 错误：{t['errors']}"
assert not m['errors'], f"资料页 JS 错误：{m['errors']}"
assert t['students'] and t['topk'], f"教师报告未渲染易错知识点：{t}"
assert t['matrixSvg'], '共现矩阵 SVG 未渲染'
assert t['bars'] >= 1, f"得分率柱状图未渲染：{t}"
assert t['segments'], '分数段未渲染'
assert t['onlyTeacher'], '缺少"只给教师"声明'
assert m['chapListed'] and m['confirmed'], f"资料页未显示已生效章节：{m}"
assert m['terms'], '资料页未显示知识点术语'
assert m['nextStepDone'], '资料页未提示"已完成"'
print('OK d126b-d131-pages：教师报告（易错点/共现矩阵/得分率/分数段，且声明只给教师）'
      ' · 资料页（章节状态/生效清单/下一步）全部通过')
PY
RC=$?
rm -f "$APP_DIR/tests/_d131.teacher.html" "$APP_DIR/tests/_d131.materials.html" \
      "$APP_DIR/tests/.d131-pages.bundle.js" "$APP_DIR/tests/.d126b-teacher.ts" \
      "$APP_DIR/tests/.d131-materials.ts"
exit $RC
