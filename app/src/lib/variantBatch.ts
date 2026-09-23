/** D23 变体编排（B3.5）：一键生成"整班分层作业纸"batch 交付包（纯前端，
 *  无引擎/无 LLM/无学习通依赖——只是把 engine `assist sheet batch` 需要的
 *  文件与命令打包好，教师本机执行即可出整班分层作业纸）。
 *
 *  zip 内容（解压到 workspace 根即为对齐 docs/04 §1 的目录结构）：
 *  - classes/<班级>/roster/roster.xlsx  （带 tag 名单，RosterView 产出）
 *  - tasks/<id>.taskpad.json ×N        （已保存任务包，含 target_tag 绑定）
 *  - batch.json                        （roster/pads/mapping 元数据清单）
 *  - README-变体编排.md                 （整条 engine 命令 + --default 说明）
 *
 *  引擎侧（已实现，engine/src/assist/paper/batch.py）：
 *  `assist sheet batch --roster <tagged.xlsx> --pads <taskpad.json...> --class-dir <dir>`
 *  —— 一个任务包对应一个 tag（包内 target_tag 字段或 items 唯一 tag 自动
 *  绑定）；混合 tag 包需映射（本包 README 提示用 target_tag 或 --map）。 */
import JSZip from 'jszip'
import { writeRosterXlsx } from './rosterXlsx'
import type { RosterStudent } from './roster'
import { parseTaskpad } from './taskpad'
import { STUDENT_TAG_LABELS } from './kb'
import { PRINT_GUIDE_SUMMARY } from './printGuide'

export interface BatchZipPad { id: string; json: string }

/** VB-5：可注入的 HTML 生成器（12-H1/14-§VB-5）。
 *
 *  父代理的 `stringifySheetHtml`（H2 同模板 TS 实现）就绪后，由调用方在
 *  export 前注册：`setSheetHtmlProvider((id, json, students) => Promise<string>)`；
 *  未注册/生成失败时降级——只写 `tasks/<id>.html-preview.txt` 说明 +
 *  README 提示教师先用引擎 `assist sheet html`（docs/14 §VB-3）补 HTML。
 */
export type SheetHtmlProvider = (id: string, json: string, students: RosterStudent[]) => Promise<string> | string
let sheetHtmlProvider: SheetHtmlProvider | null = null
export function setSheetHtmlProvider(fn: SheetHtmlProvider | null) { sheetHtmlProvider = fn }
async function trySheetHtml(id: string, json: string, students: RosterStudent[]): Promise<string | null> {
  if (!sheetHtmlProvider) return null
  try { return await sheetHtmlProvider(id, json, students) } catch { return null }
}

/** 单包 HTML 预览说明文件内容（VB-5：`tasks/<id>.html-preview.txt`）。 */
function htmlPreviewText(id: string, tag: string, hasHtml: boolean, padPath: string): string {
  return [
    `${id}.html — 变体编排 batch：浏览器打印版（HTML 主通道）预览说明`,
    '',
    `任务包：${padPath}`,
    `绑定 tag：${tag || '（无显式绑定，待 --map / target_tag）'}`,
    '',
    hasHtml
      ? '本包预览：sheets/' + id + '.html（batch 内已内嵌，双击本地打开 → Ctrl+P）'
      : '本包预览：本 batch 未内嵌 HTML（引擎或前端未启用生成）。',
    '',
    '流程（docs/14 §VB-5 / 05-D30）：',
    '1. 解压 batch zip 到引擎 workspace 根目录；',
    hasHtml
      ? '2. 直接用浏览器打开 sheets/' + id + '.html，按打印教程（A4/边距=无/页眉页脚=关/背景图形=开）打印整班 HTML；'
      : '2. 若引擎/前端已具备 sheet html 能力，用下面 CLI 生成自包含整班 HTML 后浏览器打印；',
    '3. CLI 通道：assist sheet html --task ' + padPath + ' [--roster ' + 'classes/<班级>/roster/roster.xlsx]',
    '   （该命令为 docs/14 §VB-3 双实现之一；与 PWA「打印浏览器版」共用同模板，D1 超集铁律。）',
    '4. 需要每生独立 PDF（信纸/精修水印）时：README 中的 `assist sheet batch` 命令。',
    '',
    '打印对话框设置与浏览器差异（Chrome 首选 / Edge / Firefox / Safari）：见「作业纸版式」页教程弹层或 docs/14 §VB-6。',
  ].join('\n')
}

/** engine batch 命令示例（整条、可直接粘贴教师本机 terminal）。 */
export function batchCommand(row: string, padFiles: string[], classDir: string, missing?: string[]): string {
  const pads = padFiles.map((f) => ` --pads ${f}`).join(' \\')
  const def = missing?.length ? ` --default <兜底任务包.taskpad.json>` : ''
  return `uv run assist sheet batch \\${pads} \\
  --roster ${row} \\
  --class-dir ${classDir}${def}`
}

/** 计算 batch 交付包路径（roster 放班级 roster/、tasks 平级 workspace/tasks/）。 */
export function batchPaths(cd: string) {
  return {
    classDir: `classes/${cd}`,
    roster: `classes/${cd}/roster/roster.xlsx`,
    task: (id: string) => `tasks/${id}.taskpad.json`,
  }
}

/** 生成 batch 交付包 zip（D23/B3.5）。pads = 任务包清单（stored 原样 JSON）。
 *  返回生成说明文案，blob 通过 caller 下载（保持 fsAccess 下载出口统一）。 */
export async function buildVariantBatchZip(
  students: RosterStudent[],
  pads: BatchZipPad[],
): Promise<{ blob: Blob; cd: string; padCount: number }> {
  const cd = students[0]?.class || 'classA'
  const p = batchPaths(cd)
  const zip = new JSZip()
  zip.file(p.roster, writeRosterXlsx(students))

  // mapping：显式 target_tag / items 唯一 tag → 任务包路径（与 engine --map 同口径）
  const mapping: Record<string, string> = {}
  const mixed: string[] = []
  for (const { id, json } of pads) {
    try {
      const parsed = parseTaskpad(JSON.parse(json))
      const tags = [...new Set(parsed.items.map((i) => String(i.tag ?? '')).filter(Boolean))]
      const tag = parsed.target_tag ?? (tags.length === 1 ? tags[0] : tags.length === 0 ? 'default' : '')
      if (tag) mapping[tag] = `${id}.taskpad.json`
      else mixed.push(id)
    } catch {
      mixed.push(id)
    }
  }

  // VB-5：每个已绑定 tag 的任务包 → tasks/<id>.html-preview.txt（预览地址与流程），
  // 且若 sheetHtmlProvider 可用（父代理 stringifySheetHtml），再落 sheets/<id>.html。
  const padFiles = pads.map((pd) => ({ id: pd.id, path: p.task(pd.id) }))
  const htmlOf: Record<string, string | null> = {}
  for (const { id, json } of pads) {
    zip.file(`tasks/${id}.taskpad.json`, json)
    const tag = Object.entries(mapping).find(([, v]) => v === `${id}.taskpad.json`)?.[0] ?? ''
    htmlOf[id] = tag ? await trySheetHtml(id, json, students) : null
    zip.file(`tasks/${id}.html-preview.txt`,
      htmlPreviewText(id, tag, Boolean(htmlOf[id]), `tasks/${id}.taskpad.json`))
    if (htmlOf[id]) zip.file(`sheets/${id}.html`, htmlOf[id] as string)
  }

  if (!sheetHtmlProvider) {
    zip.file('sheets/README-html.txt', [
      'sheets/ — VB-5 HTML 主通道产物位（docs/14 §VB-5 / 05-D30）。', '',
      '本包导出时前端暂未启用「浏览器打印版」生成（H2 stringifySheetHtml 未就绪或未注册）。', '',
      '教师可先走引擎 CLI 通道（VB-3 双实现，同模板语义）：',
      ...pads.map(({ id }) => `  assist sheet html --task tasks/${id}.taskpad.json [--roster ${p.roster}]`),
      '',
      '若当前引擎尚未实现 `assist sheet html`（docs/14 §VB-3 属后续会话），可先用',
      'README 的 `assist sheet batch`（reportlab PDF 线，每生独立 PDF）出整班作业纸。',
    ].join('\n'))
  }

  zip.file('batch.json', JSON.stringify({
    task: 'variants-batch',
    generated_at: new Date().toISOString(),
    note: '元数据清单（engine CLI 参数快照）；执行以 README 命令为准。',
    class_dir: p.classDir,
    roster: p.roster,
    pads: padFiles.map((f) => f.path),
    mapping,
  }, null, 2))

  const tagOf: Record<string, string> = {} // <id> -> tag（前向展示用）
  for (const [tag, v] of Object.entries(mapping)) tagOf[v.replace('.taskpad.json', '')] = tag
  const padLines = pads.map(({ id }, i) =>
    `  ${i + 1}. tasks/${id}.taskpad.json` +
    (tagOf[id]
      ? `（tag: ${tagOf[id]}）`
      : '⚠ 混合 tag：请先在任务包标注 target_tag 或 CLI 加 --map'))
  const tagLines = Object.entries(mapping).map(([tag, v]) =>
    `  - ${STUDENT_TAG_LABELS[tag] ?? tag} → ${v}`)

  const readme = [
    '# 变体编排 batch 交付包（D23 · 一键生成整班分层作业纸）',
    '',
    '> 本包由 PWA「作业纸内容 → 变体编排」面板导出，全部为合成/本地数据；',
    '> 不含任何引擎在线调用：教师把 zip 解压到引擎 workspace 根目录（保持包内目录结构），',
    '> 在本机 terminal 执行下述命令即可出整班分层作业纸 PDF。',
    '',
    '## 命令（copy 即用）',
    '',
    '```bash',
    batchCommand(p.roster, padFiles.map((f) => f.path), p.classDir),
    '```',
    '',
    '- 产出：`' + `${p.classDir}/sheets/batch/<tag>/*.pdf` + '`（每生一份，按 roster 的 tag 自动选变体）。',
    '',
    '## HTML 浏览器打印通道（VB-5 · docs/14）',
    '',
    sheetHtmlProvider
      ? '本包已内嵌浏览器打印版 HTML：' + pads.filter((x) => htmlOf[x.id]).map((x) => `sheets/${x.id}.html`).join('、')
      : '本包未内嵌 HTML（前端生成器未启用）——教师可先用引擎 `assist sheet html --task <任务包> [--roster 名单.xlsx]`' + '\n  自行生成（见 sheets/README-html.txt 与各 tasks/<id>.html-preview.txt）；它尚未上线时，上面 batch PDF 命令为主通道。',
    '',
    `打印教程一句话：${PRINT_GUIDE_SUMMARY}`,
    '',
    missingNote(Object.keys(mapping)),
    '',
    '## 包内容',
    '',
    `- \`${p.roster}\` —— 带 tag 名单（名单页「导出 tag 名单」同款口径）。`,
    ...padLines.map((l) => `- ${l}`),
    `- \`batch.json\` —— roster/pads/mapping 元数据（引擎 batch 校对用，非必读）。`,
    `- \`tasks/<id>.html-preview.txt\` —— 每个已绑定 tag 包的 HTML 打印版说明（VB-5）。`,
    sheetHtmlProvider ? '- `sheets/<id>.html` —— 浏览器打印版作业纸（全部已内嵌）。' : '- `sheets/README-html.txt` —— HTML 主通道与 CLI 生成指引（前端生成器未启用时的占位注记）。',
    '',
    '## tag → 任务包 绑定',
    '',
    ...(tagLines.length ? tagLines : ['-（无任何显式绑定；引擎将按 items 唯一 tag 推断或报错）']),
    '',
    mixed.length ? `## 需要注意：${mixed.length} 份任务包为混合 tag 且未绑定 target_tag\n\n引擎会拒绝执行（提示加 --map）：请在 PWA「作业纸设计 → 任务包头」为该包绑定 target_tag 后重新导出本包。\n` : '',
    '全部学生/题目数据均为合成占位风格（学生A、2026xxxx01 等），不含真实信息。',
    '',
    `导出时间：${new Date().toISOString()}`,
    `参与变体任务包：${pads.length} 份`,
  ].join('\n')
  zip.file('README-变体编排.md', readme)

  const blob = await zip.generateAsync({ type: 'blob' })
  return { blob, cd, padCount: pads.length }
}

function missingNote(tags: string[]): string {
  if (!tags.length) return '- ⚠ 当前没有任何显式 tag 绑定：请在名单页「变体编排」面板逐条绑定后再导出。'
  const mention = tags.map((t) => STUDENT_TAG_LABELS[t] ?? t).join('、')
  return `- 已绑定的 tag 覆盖：${mention}。未覆盖的 tag 会被人跳过（引擎 log warning）；\n  如需兜底：把某份任务包通过 --default 指定为其兜底变体。`
}
