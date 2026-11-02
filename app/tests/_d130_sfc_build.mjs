/** 把 .vue SFC 编译成 esbuild 可打包的 .js（D130-T9 浏览器回归用）。
 *
 *  esbuild **不能**解析 .vue（`--loader:.vue=copy` 只是原样拷贝，组件根本不会挂载），
 *  这里用项目自带 @vue/compiler-sfc 真正编译 script + template：
 *    compileScript → 组件对象（含 setup）
 *    compileTemplate → render 函数
 *  然后把这个唯一的 export default 改名，补上 render，再导出一份。
 */
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import { readFileSync, writeFileSync } from 'node:fs'
import { basename, dirname, resolve } from 'node:path'

const entry = process.argv[2]
const out = process.argv[3]
const src = readFileSync(entry, 'utf-8')
const id = basename(entry)
const { descriptor, errors } = parse(src, { filename: id })
if (errors.length) throw new Error(`SFC parse 失败：${errors[0].message}`)

const script = compileScript(descriptor, { id, inlineTemplate: false })
const tpl = compileTemplate({
  source: descriptor.template.content,
  filename: id,
  id,
  compilerOptions: { bindingMetadata: script.bindings },
})
if (tpl.errors.length) throw new Error(`模板编译失败：${tpl.errors[0]}`)

let code = script.content
// compileScript 产出的组件就在 `export default <expr>` 里；改成具名，避免两个 default。
const EXPORT_RE = /export\s+default\s+/
if (!EXPORT_RE.test(code)) throw new Error('compileScript 输出里没有 export default')
code = code.replace(EXPORT_RE, 'const __sfc_main = ')

// 相对导入重写成绝对路径（产物在 tests/ 下，原相对路径会解析错）
const dir = dirname(resolve(entry))
const fixed = code.replace(/((?:from|import)\s*\(?\s*['"])(\.[^'"]+)(['"])/g,
  (_m, head, p, tail) => `${head}${resolve(dir, p).replace(/\\/g, '/')}${tail}`)

const body = [
  fixed,
  '',
  tpl.code,
  '',
  '__sfc_main.render = render',
  'export default __sfc_main',
  '',
].join('\n')
writeFileSync(out, body, 'utf-8')
console.log('sfc compiled:', out)
