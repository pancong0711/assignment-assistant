/** classOverlay.ts — VC-3 整班预览的「tag→作业纸」映射与 batch manifest（docs/14 §VC-3）。
 *
 *  D43-3/D43-6 收口（docs/13）：_Fallback 静态页块模板已删除_（与 lib/sheetHtml.ts
 *  stringifySheetHtml 的双实现收敛）——整班预览改由视图层用 partitionStudentsByTag
 *  拿到「每包一段学生子集」，再调 stringifySheetHtml（与 CLI assignment.html.j2 同一模板）
 *  拼装，公式/水印/页眉页脚与打印产物同源。本文件保留：
 *  - partitionStudentsByTag：名单按 tag（显式 target_tag / items 唯一 tag 推断）分段，
 *    未匹配学生回到 unmatched（引擎 batch 同口径跳过，--default 语义 = fallbackPadId）；
 *  - buildBatchManifest：README/manifest 文本（教师核对 tag→包绑定，无引擎可用）。
 */

import type { RosterStudent } from './roster'
import { STUDENT_TAG_LABELS } from './kb'
import { parseTaskpad, padInferredTag, type Taskpad } from './taskpad'

/** tag→作业纸分段结果（pad 顺序 = 清单顺序） */
export interface PadStudentGroup {
  pad: Taskpad
  /** padInferredTag 推断结果（显式 target_tag / items 唯一 tag；mixed 未定 = null） */
  tag: string | null
  students: RosterStudent[]
}

/** 名单按 tag 分段到各作业纸（fallbackPadId = --default 兜底语义）。
 *  未匹配（tag 未绑定且无兜底）的学生进 unmatched——视图层负责提示，
 *  引擎 batch 对这部分学生同样跳过。 */
export function partitionStudentsByTag(
  students: RosterStudent[],
  padJsons: Array<{ id: string; json: string }>,
  fallbackPadId = '',
): { groups: PadStudentGroup[]; unmatched: RosterStudent[] } {
  const pads: Array<{ id: string; pad: Taskpad; tag: string | null }> = []
  for (const { id, json } of padJsons) {
    try {
      const pad = parseTaskpad(JSON.parse(json))
      pads.push({ id, pad, tag: padInferredTag(pad.items, pad.target_tag) })
    } catch { /* JSON 损坏包跳过（与 batch 引擎"拒收后进"口径一致） */ }
  }
  const byTag = new Map<string, Taskpad>()
  for (const p of pads) if (p.tag) byTag.set(p.tag, p.pad)
  const fallback: Taskpad | undefined = fallbackPadId
    ? pads.find((p) => p.id === fallbackPadId)?.pad
    : undefined

  const groups: PadStudentGroup[] = pads.map((p) => ({ pad: p.pad, tag: p.tag, students: [] }))
  const unmatched: RosterStudent[] = []
  for (const stu of students) {
    const pad = (stu.tag && byTag.get(stu.tag)) || fallback
    const g = pad ? groups.find((x) => x.pad === pad) : undefined
    if (g) g.students.push(stu)
    else unmatched.push(stu)
  }
  return { groups, unmatched }
}

/** fallback 口径（docs/14 §VC-3）：无引擎也不空转——
 *  生成 batch zip 同款 README/manifest 的文本展示（教师核对 tag→包绑定）。 */
export function buildBatchManifest(
  students: RosterStudent[],
  padJsons: Array<{ id: string; json: string }>,
): string {
  const tagCounts: Record<string, number> = {}
  for (const s of students) if (s.tag) tagCounts[s.tag] = (s.tag ? tagCounts[s.tag] ?? 0 : 0) + 1
  const lines: string[] = ['# 整班预览 manifest（tag→包绑定核对，无引擎可用）', '']
  lines.push(`- 名单：${students.length} 人；tag 分布：${
    Object.entries(tagCounts).map(([t, n]) => `${STUDENT_TAG_LABELS[t] ?? t}×${n}`).join('、') || '（无）'}`)
  lines.push('')
  lines.push('## tag → 作业纸 绑定（引擎 batch 同口径）')
  for (const { id, json } of padJsons) {
    try {
      const pad = parseTaskpad(JSON.parse(json))
      const tag = padInferredTag(pad.items, pad.target_tag)
      lines.push(`- ${id} → ${tag ?? '⚠ 混合 tag 未绑定'}（${pad.items.length} 组 / ${
        pad.items.reduce((n, i) => n + i.ids.length, 0)} 题 · ${pad.layout.orientation === 'landscape' ? '横版' : '竖版'}${pad.layout.per_page}题页）`)
    } catch {
      lines.push(`- ${id} → ⚠ JSON 损坏，引擎 batch 将拒收`)
    }
  }
  return lines.join('\n')
}
