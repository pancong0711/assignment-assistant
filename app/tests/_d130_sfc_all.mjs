/** 递归把入口 SFC 及其 import 到的所有 .vue 都编译成 .ts（esbuild 可打包）。 */
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, dirname, resolve } from 'node:path'

const seen = new Map()   // abs .vue path → 生成的 .ts path

function compileOne(vuePath) {
  vuePath = resolve(vuePath)
  if (seen.has(vuePath)) return seen.get(vuePath)
  // D142：产物写到 tests/ 下（此前落在 src/ 旁边，会被 tsc 扫进构建、
  // 且 .gitignore 只覆盖 components/ 导致 views/ 下的残留文件进版本库）
  const outTs = resolve(process.cwd(), 'tests',
                        basename(vuePath).replace(/\.vue$/, `.compiled-${hash(vuePath)}.ts`))
  seen.set(vuePath, outTs)

  const src = readFileSync(vuePath, 'utf-8')
  const id = basename(vuePath)
  const { descriptor, errors } = parse(src, { filename: id })
  if (errors.length) throw new Error(`SFC parse 失败 ${id}: ${errors[0].message}`)
  const script = compileScript(descriptor, { id, inlineTemplate: false })
  const tpl = compileTemplate({
    source: descriptor.template?.content || '',
    filename: id, id,
    compilerOptions: { bindingMetadata: script.bindings },
  })
  if (tpl.errors.length) throw new Error(`模板编译失败 ${id}: ${tpl.errors[0]}`)

  let code = script.content
  if (!/export\s+default\s+/.test(code)) throw new Error(`无 export default：${id}`)
  code = code.replace(/export\s+default\s+/, 'const __sfc_main = ')

  const dir = dirname(vuePath)
  // 递归编译此 SFC 里 import 的其它 .vue
  code = code.replace(/(from\s+['"])(\.[^'"]+\.vue)(['"])/g, (_m, a, p, b) => {
    const abs = resolve(dir, p)
    return `${a}${compileOne(abs)}${b}`
  })
  // 相对 .ts/.js 也改成绝对路径
  code = code.replace(/((?:from|import)\s*\(?\s*['"])(\.[^'"]+)(['"])/g, (m, a, p, b) => {
    if (p.endsWith('.vue')) return m
    return `${a}${resolve(dir, p).replace(/\\/g, '/')}${b}`
  })
  writeFileSync(outTs, `${code}\n${tpl.code}\n__sfc_main.render = render\nexport default __sfc_main\n`,
                'utf-8')
  return outTs
}

function hash(s) {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h).toString(36).slice(0, 6)
}

const entry = process.argv[2]
const out = compileOne(entry)
console.log('entry ts:', out)
for (const f of seen.values()) console.log('compiled:', f)
