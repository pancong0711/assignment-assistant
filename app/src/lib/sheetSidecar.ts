/** sheetSidecar.ts — D168-T13：整班作业纸输出（打印/下载）的**追溯 sidecar**。
 *
 *  教师使用习惯（docs/112-D168 §3.3）：
 *  > 预览整班的作业纸之后打印 PDF 保存了，而不是生成 batch 或 json 文件，
 *  > 这样一些信息就有可能丢失。
 *
 *  问题：打印出来的 PDF 是**零元数据**的——事后无法回答
 *  "这份 PDF 对应哪个作业包 / 发给哪些学生 / 谁什么 tag"。
 *
 *  解决：打印或下载时，同目录/同批产出一个 `*.json`（sidecar），记录：
 *    - 哪个作业包、哪些作业纸（padId + tag）
 *    - 学生名单与其 tag（与 D168 roster-tags 快照同口径）
 *    - 输出开关（含答案/水印/页码大字）
 *    - 生成时间
 *
 *  注意：sidecar **只描述**"这次输出了什么"，不改任何生效数据。
 */

export interface SidecarStudent {
  name: string
  number?: string
  tag?: string
  padId?: string
}

export interface SheetSidecar {
  version: 1
  kind: 'class-sheet-output'
  generatedAt: string
  /** 作业包 id（有当前包时） */
  packId: string
  packName?: string
  /** 输出用途：print = 浏览器打印；download = 下载 HTML */
  purpose: 'print' | 'download'
  /** 涉及哪些作业纸：padId → tag */
  pads: Array<{ padId: string; tag: string }>
  /** 学生 → tag（+ 命中的作业纸） */
  students: SidecarStudent[]
  /** 打印/导出开关（便于事后复现同一版式） */
  options: {
    includeAnswers: boolean
    includeWatermark: boolean
    includePageText: boolean
  }
  /** 未绑定 tag 的学生（预览会跳过他们） */
  unboundTags: string[]
  counts: { students: number; pads: number }
}

/** 生成 sidecar 内容（纯函数，便于单测）。 */
export function buildSheetSidecar(input: {
  packId?: string
  packName?: string
  purpose: 'print' | 'download'
  pads: Array<{ padId: string; tag: string }>
  students: Array<{ name: string; number?: string; tag?: string }>
  /** 学生名 → 命中的 padId（由 tag→pad 绑定推出；无绑定时可缺省） */
  padByStudent?: Record<string, string>
  options: { includeAnswers: boolean; includeWatermark: boolean; includePageText: boolean }
  now?: Date
}): SheetSidecar {
  const now = input.now || new Date()
  const tagToPad = new Map<string, string>()
  for (const p of input.pads) {
    if (p.tag) tagToPad.set(p.tag, p.padId)
  }
  const students: SidecarStudent[] = input.students.map((s) => ({
    name: s.name,
    ...(s.number ? { number: s.number } : {}),
    ...(s.tag ? { tag: s.tag } : {}),
    ...(input.padByStudent?.[s.name]
      ? { padId: input.padByStudent[s.name] }
      : (s.tag && tagToPad.has(s.tag) ? { padId: tagToPad.get(s.tag) } : {})),
  }))
  const boundTags = new Set(input.pads.map((p) => p.tag).filter(Boolean))
  const unbound = [...new Set(
    input.students.map((s) => s.tag || '').filter((t) => t && !boundTags.has(t)),
  )].sort()
  return {
    version: 1,
    kind: 'class-sheet-output',
    generatedAt: now.toISOString(),
    packId: input.packId || '',
    ...(input.packName ? { packName: input.packName } : {}),
    purpose: input.purpose,
    pads: input.pads.map((p) => ({ padId: p.padId, tag: p.tag })),
    students,
    options: { ...input.options },
    unboundTags: unbound,
    counts: { students: students.length, pads: input.pads.length },
  }
}

/** 文件名：与 HTML 同名、换 .json 后缀（便于配对查找）。 */
export function sidecarFileName(htmlName: string): string {
  return htmlName.replace(/\.html?$/i, '') + '.json'
}
