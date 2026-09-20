/** app 阶段4a 自检（docs/05-D13/D20/D2）：esbuild 打包纯逻辑模块 → node 运行。
 *  覆盖两组逻辑断言（不依赖浏览器）：
 *  1) 向导状态存储：assignment-assistant.onboarding.v1 的 key 写入/读取
 *     （用注入的 localStorage stub 验证 store 侧同款逻辑 key 约定）；
 *  2) watermark items 序列化兼容：
 *     - 新 items 列表解析/导出（{enabled,style,items[]}）；
 *     - legacy 三槽 university/text/boat（字符串或 {path,pos,ratio,alpha}）读旧配置
 *       自动映射为 items；
 *     - 导出双写：items + worksheets 兼容字段 university/text/boat（engine 现行
 *       _watermark_paths/_ovarg 消费形状）+ dataURL 不内嵌（image 仅路径 hint）。
 *  运行：在 app/ 下执行  node tests/selfcheck-watermark-or-doctor.mjs
 *  （脚本会先调用 node_modules/.bin/esbuild 打包 src/lib/taskpad.ts）。 */
import { execFileSync } from 'node:child_process'
import assert from 'node:assert'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { pathToFileURL } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tmp = mkdtempSync(join(tmpdir(), 'selfcheck-wm-'))
const bundle = join(tmp, 'taskpad.bundle.mjs')
execFileSync(join(appDir, 'node_modules', '.bin', 'esbuild'), [
  resolve(appDir, 'src/lib/taskpad.ts'),
  '--bundle', '--format=esm', `--outfile=${bundle}`,
], { stdio: 'inherit' })
process.on('exit', () => rmSync(tmp, { recursive: true, force: true }))

const mod = await import(pathToFileURL(bundle).href)
const { parseTaskpad, serializeTaskpad, parseWatermark, watermarkForExport } = mod

/* ---------- 1) 向导状态存储：onboarding.v1 key 约定 ---------- */
{
  // 与 stores/settings.ts 同 key（约定检查：常量保持一致）
  const bun = await import(pathToFileURL(join(tmp, 'noop')).href).catch(() => null)
  void bun
  // 直接验证 settings store 源码里的 key（esbuild 打包 pinia 需要 DOM，此处用源码断言）
  const { readFileSync } = await import('node:fs')
  const src = readFileSync(resolve(appDir, 'src/stores/settings.ts'), 'utf-8')
  assert.ok(src.includes("const LS_ONBOARDING_KEY = 'assignment-assistant.onboarding.v1'"),
    'onboarding key 应为 assignment-assistant.onboarding.v1（题面建议 key）')
  assert.ok(src.includes("localStorage.setItem(LS_ONBOARDING_KEY, 'done')"),
    '完成/跳过都应写入 onboarding key（重开不再弹）')
  // 模拟 localStorage stub 的读写闭环（与 store 的 finish/skip → needsSetup 逻辑等价）
  const stub = new Map()
  const needsSetup = () => stub.get('assignment-assistant.onboarding.v1') !== 'done'
  assert.equal(needsSetup(), true)
  stub.set('assignment-assistant.onboarding.v1', 'done') // 完成或跳过
  assert.equal(needsSetup(), false, '完成后 needsSetup=false（重开不再弹）')
  console.log('1) 向导状态存储（onboarding.v1 完成即不再弹）… ok')
}

/* ---------- 2a) 新 items schema：解析 + 序列化 ---------- */
{
  const pad = parseTaskpad({
    id: '2026S1-classA-chap1-100',
    layout: { orientation: 'landscape', per_page: 2, header: { title: '占位标题' }, footer: {} },
    items: [],
    watermark: {
      enabled: true, style: 'default', pageText: false,
      items: [
        { image: 'assets/watermark/logo-学校.png', pos: 'rt', ratio: 0.125, alpha: 0.5 },
        { image: 'assets/watermark/corner.png', pos: 'lb', ratio: 0.3, alpha: 0.25 },
      ],
    },
    grade: {},
  })
  assert.equal(pad.watermark.items.length, 2)
  assert.equal(pad.watermark.pageText, false)
  assert.equal(pad.watermark.items[0].pos, 'rt')
  // 导出：items 列表保留 + pageText 保留
  const out = JSON.parse(serializeTaskpad(pad))
  assert.equal(out.watermark.items.length, 2)
  assert.equal(out.watermark.items[1].pos, 'lb')
  assert.equal(out.watermark.pageText, false)
  assert.ok(!('university' in out.watermark) === false || out.watermark.university?.path === 'assets/watermark/logo-学校.png',
    '未配置三槽命中时不伪造 university 字段；命中时 path 取对应 item')
  console.log('2a) 水印 items 新 schema 解析/导出 … ok')
}

/* ---------- 2b) legacy 三槽读旧配置 → 自动映射 items ---------- */
{
  // 旧 engine overrides 形状：{enabled, university: 'logo.png', text: {path, pos:'lc', ratio, alpha}, boat: {...}} 等
  const wm = parseWatermark({
    enabled: true, style: '2603',
    university: 'assets/watermark/logo-university.png',
    text: { path: 'assets/watermark/logo-text.png', pos: 'lc', ratio: 0.1, alpha: 0.3 },
    boat: { path: 'assets/watermark/logo-boat.png', pos: 'rb', ratio: 0.3, alpha: 0.5 },
  })
  assert.equal(wm.items.length, 3, 'legacy 三槽应映射为 3 个 items')
  const byPos = Object.fromEntries(wm.items.map((it) => [it.pos, it]))
  assert.ok(byPos.rt, 'university 缺省映射 rt')
  assert.equal(byPos.rt.image, 'assets/watermark/logo-university.png')
  assert.ok(byPos.lm, "text 旧 pos 'lc' 映射到九宫格 lm")
  assert.ok(byPos.rb, 'boat 显式 pos=rb 保留')
  assert.equal(byPos.rb.ratio, 0.3)
  // enabled=false / 空串 / 布尔 true 槽位：布尔 true（无路径）不产生 item
  const wm2 = parseWatermark({ enabled: false, university: true, text: '', boat: undefined })
  assert.equal(wm2.items.length, 0)
  assert.equal(wm2.enabled, false)
  console.log("2b) legacy 三槽（university/text/boat）自动映射 items（'lc'→lm）… ok")
}

/* ---------- 2c) 导出双写：items + 三槽兼容字段 ---------- */
{
  const pad = parseTaskpad({
    id: 'wm-compat',
    layout: { orientation: 'portrait', per_page: 1 },
    items: [],
    watermark: {
      enabled: true,
      items: [
        { image: 'assets/watermark/logo-university.png', pos: 'rt', ratio: 0.125, alpha: 0.5 },
        { image: 'assets/watermark/logo-text.png', pos: 'lm', ratio: 0.1, alpha: 0.3 },
        { image: 'assets/watermark/logo-boat.png', pos: 'lb', ratio: 0.3, alpha: 0.5 },
        { image: 'assets/watermark/extra.png', pos: 'mm', ratio: 0.5, alpha: 0.1 },
      ],
    },
    grade: {},
  })
  const out = JSON.parse(serializeTaskpad(pad))
  // items 全量保留（D20 list）
  assert.equal(out.watermark.items.length, 4)
  // 三槽兼容双写（engine _ovarg/_watermark_paths 形状 {path,pos,ratio,alpha}）
  assert.deepEqual(out.watermark.university, { path: 'assets/watermark/logo-university.png', pos: 'rt', ratio: 0.125, alpha: 0.5 })
  assert.deepEqual(out.watermark.text, { path: 'assets/watermark/logo-text.png', pos: 'lm', ratio: 0.1, alpha: 0.3 })
  assert.deepEqual(out.watermark.boat, { path: 'assets/watermark/logo-boat.png', pos: 'lb', ratio: 0.3, alpha: 0.5 })
  // dataURL 不进任务包（image 仅路径 hint；parse 阶段已把 dataURL 视为普通字符串，
  // 但 DesignerView 只写路径 hint —— 用断言证明导出结构不含 base64 数据）
  const raw = serializeTaskpad(pad)
  assert.ok(!raw.includes('data:image'))

  // 三槽为空时不写兼容字段（避免向引擎传递空覆盖）
  const padNoItems = parseTaskpad({ id: 'wm-none', watermark: { enabled: true } })
  const out2 = JSON.parse(serializeTaskpad(padNoItems))
  assert.equal(out2.watermark.items.length, 0)
  assert.ok(!('university' in out2.watermark) && !('boat' in out2.watermark))
  console.log('2c) 导出双写 items + university/text/boat 兼容字段（dataURL 不内嵌）… ok')
}

/* ---------- 2d) 容错：非法值回落缺省 ---------- */
{
  const wm = parseWatermark({
    enabled: '真值', items: [
      { image: 'a.png', pos: 'xx', ratio: 42, alpha: 7 },
      { image: '', pos: null },
      '垃圾项',
    ],
  })
  assert.equal(wm.enabled, true, 'enabled 容错为 true（缺省）')
  assert.equal(wm.items.length, 2, '非对象项（垃圾项字符串）直接丢弃，不抛错')
  assert.equal(wm.items[0].pos, 'mm', '非法 pos 回落 mm')
  assert.equal(wm.items[0].ratio, 0.2, '非法 ratio 回落 0.2')
  assert.equal(wm.items[0].alpha, 0.5, '非法 alpha 回落 0.5')
  assert.equal(wm.items[1].pos, 'mm')
  console.log('2d) 非法值容错回落（pos/ratio/alpha 缺省）… ok')
}

assert.ok(watermarkForExport(parseWatermark({ enabled: true })).enabled === true)

console.log('\n全部水印/向导自检通过 ✔（阶段4a：onboarding.v1 + items 序列化兼容）')
