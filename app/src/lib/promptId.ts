/** D108-FIX：提示词模板 id 规则（PWA 侧），与引擎 files/prompts.py 的 _ID_RE 保持一致。
 *
 *  id 同时是 `<ws>/prompts/ai-solve/<id>.json` 的文件名，所以：
 *  - 允许中文（与 grading/items.py 的 id 规则一致，教师直接用中文命名不会被拒）；
 *  - 不允许空格 / 路径分隔符 / 其它标点，且不能以 `.` 或 `-` 开头。
 *
 *  背景：旧版直接把 window.prompt 的原始输入提交给引擎，用户填中文名或带空格
 *  就会整串报「模板 id 非法」，且弹窗对合法字符毫无提示。
 */

export const PROMPT_ID_RE = /^[0-9A-Za-z_\u4e00-\u9fff][0-9A-Za-z_\-\u4e00-\u9fff.]{0,63}$/

export const PROMPT_ID_HINT =
  '需 1..64 位，以字母/数字/中文/下划线开头，可含 _ . -（不能有空格）'

/** 归一化用户输入：去首尾空白、空白转 `-`、丢弃非法字符、去开头 `.`、截断到 64。
 *  返回 '' 表示无法自动修复（交给调用方提示）。 */
export function normalizePromptId(raw: string): string {
  const s = String(raw ?? '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/[^0-9A-Za-z_\u4e00-\u9fff.\-]/g, '')
    .replace(/^[.\-]+/, '')
    .slice(0, 64)
  return PROMPT_ID_RE.test(s) ? s : ''
}

/** 根据模板名称生成一个未被占用的建议 id（用户直接回车即可）。 */
export function suggestPromptId(name: string, usedIds: Iterable<string> = []): string {
  const base = normalizePromptId(name) || 'template'
  const used = new Set(usedIds)
  let id = base
  let n = 2
  while (used.has(id)) id = `${base}-${n++}`
  return id
}
