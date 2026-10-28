/** D117 自检（浏览器行为）：richdoc.renderRich 在**真实 DOMPurify** 下必须保留 SVG 几何属性。
 *
 *  为什么必须跑浏览器：richdoc 在无 DOM 时走 sanitizeWithoutDom 兜底，
 *  那段会剥属性的 DOMPurify 配置**根本不会被执行** —— 所以 Node 里永远测不出这个 bug。
 *
 *  需要 Playwright（与其它浏览器自检同前提）。找不到浏览器时**跳过**而不是失败。
 *
 *  运行：node tests/selfcheck-d117-svg-browser.mjs */
import { execFileSync } from 'node:child_process'
import { existsSync, readdirSync, writeFileSync, rmSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/* 说明：本仓库前端没装 playwright（是 Python 侧依赖）。
   这里生成 HTML 产物 + 供 Python 侧调用的断言脚本；
   若无 PY 驱动环境则跳过（自检不因缺浏览器而失败）。 */
const RUN_PY = process.env.D117_RUN_PY === '1'
if (!RUN_PY) {
  console.log('SKIP d117-svg-browser：需 D117_RUN_PY=1 由 python 侧驱动（见 tests/run-d117-browser.sh）')
  process.exit(0)
}
const exe = findChrome()
if (!exe) {
  console.log('SKIP d117-svg-browser：未找到 Chromium 可执行文件')
  process.exit(0)
}

function findChrome() {
  const home = process.env.HOME || ''
  const roots = [join(home, '.cache', 'ms-playwright'), process.env.PLAYWRIGHT_BROWSERS_PATH || '']
  for (const root of roots) {
    if (!root || !existsSync(root)) continue
    for (const d of readdirSync(root)) {
      if (!d.startsWith('chromium-')) continue
      const p = join(root, d, 'chrome-linux64', 'chrome')
      if (existsSync(p)) return p
    }
  }
  return ''
}

/* 1) 把 richdoc 打成 IIFE（含 DOMPurify + markdown-it） */
const iife = join(appDir, 'tests', '.richdoc.d117.iife.js')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/richdoc.ts'), '--bundle', '--format=iife', '--global-name=RD',
  `--outfile=${iife}`, '--log-level=error',
], { stdio: 'inherit' })

const page = join(appDir, 'tests', '_d117.svg.html')
writeFileSync(page, `<!doctype html><meta charset="utf-8"><body><div id="t"></div>
<script src=".richdoc.d117.iife.js"></script>
<script>
  window.__result = function () {
    const SRC = '示意图：\\n\\n<svg viewBox="0 0 200 150" xmlns="http://www.w3.org/2000/svg">\\n'
      + '  <circle cx="100" cy="75" r="35" stroke="black" fill="none"/>\\n'
      + '  <text x="112" y="70" font-size="10" fill="black">R1</text>\\n</svg>\\n'
      + '\\n![img](data:image/png;base64,iVBORw0KGgo=)';
    const html = RD.renderRich(SRC);
    const d = document.getElementById('t');
    d.innerHTML = html;
    const svg = [...d.querySelectorAll('svg')].pop();
    return {
      html,
      hasSvg: !!svg,
      viewBox: svg ? svg.getAttribute('viewBox') : null,
      width: svg ? svg.getAttribute('width') : null,
      height: svg ? svg.getAttribute('height') : null,
      circles: svg ? svg.querySelectorAll('circle').length : 0,
      cx: svg && svg.querySelector('circle') ? svg.querySelector('circle').getAttribute('cx') : null,
      r: svg && svg.querySelector('circle') ? svg.querySelector('circle').getAttribute('r') : null,
      renderedW: svg ? Math.round(svg.getBoundingClientRect().width) : 0,
      imgCount: d.querySelectorAll('img').length,
    };
  };
</script></body>`)

const browser = await playwright.chromium.launch({ executablePath: exe })
try {
  const pg = await browser.newPage()
  await pg.goto(pathToFileURL(page).href)
  const r = await pg.evaluate(() => window.__result())
  const fail = (m) => { throw new Error(m + '\nHTML: ' + r.html) }
  if (!r.hasSvg) fail('renderRich 输出中没有 <svg>')
  if (!r.viewBox) fail('viewBox 被剥掉（ALLOWED_URI_REGEXP 全局生效的典型症状）')
  if (!r.width || !r.height) fail('width/height 被剥掉')
  if (r.circles < 1) fail('circle 被剥掉')
  if (!r.cx || !r.r) fail('cx/r 被剥掉')
  if (r.renderedW <= 0) fail('SVG 渲染宽度为 0（图不可见）')
  if (r.imgCount < 1) fail('data:image 被误删（hook 应放行）')
  console.log('OK d117-svg-browser：真实 DOMPurify 下 viewBox/width/height/cx/r 全部保留、'
    + `SVG 可渲染(${r.renderedW}px)、data:image 放行`)
} finally {
  await browser.close()
  rmSync(iife, { force: true })
  rmSync(page, { force: true })
}
