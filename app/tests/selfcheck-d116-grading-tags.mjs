/** D116 自检：AI 辅助批阅的 tags 下拉数据源。
 *
 *  背景 bug：tagOptions 从 `students`（学习通批阅列表）里取 `tag`，
 *  但学习通**不提供**分层 tag（xxt/preview.py / xxt/review.py 里没有 tag 概念）
 *  → 下拉恒为空。分层是本机信息：学生在「班级与标签」打 tag，作业纸用 target_tag 绑定。
 *
 *  运行：node tests/selfcheck-d116-grading-tags.mjs */
import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const src = readFileSync(resolve(appDir, 'src/components/AiGradingPanel.vue'), 'utf-8')
const code = src.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !/^\s*\/\//.test(l)).join('\n')

/* 1) tagOptions 不得再只依赖学习通 students */
assert.ok(!/tagOptions[\s\S]{0,200}for \(const s of students\.value\)/.test(code),
  'tagOptions 不得只从学习通 students 取 tag（学习通没有 tag）')
assert.ok(/const rosterTags = computed/.test(code), '应有 rosterTags（本地 roster 的 tag）')
assert.ok(/const padTags = computed/.test(code), '应有 padTags（作业纸 target_tag）')
assert.ok(/for \(const t of rosterTags\.value\)[\s\S]{0,120}for \(const t of padTags\.value\)/.test(code),
  'tagOptions 应 = rosterTags ∪ padTags')

/* 2) C 方案：空 tag 时必须给出可操作提示（不能静默空着） */
assert.ok(/const tagHint = computed/.test(code), '应有 tagHint')
assert.ok(/班级与标签/.test(code), '提示应指引去「班级与标签」打 tag')
assert.ok(/v-if="tagHint"/.test(src), '模板应展示 tagHint')

/* 3) 未选 tag 的语义必须说清楚（批全部，但只有打 tag 才能关联题目） */
assert.ok(/批阅全部学生/.test(src), '应提示"不选 = 批阅全部学生"')
assert.ok(/只有打了 tag 的学生才能关联/.test(src), '应提示"未打 tag 无法关联题目"')

/* 4) 引擎侧确认：学习通链路确实没有 tag（防止未来误判为"后端该给 tag"） */
{
  const prev = readFileSync(resolve(appDir, '..', 'engine/src/assist/xxt/preview.py'), 'utf-8')
  assert.ok(!/\btag\b/.test(prev), 'xxt/preview.py 不应有 tag 概念（分层来自本机 roster）')
}

/* 5) 默认全选 watch 必须在相关 computed 之后（否则 immediate 触发 TDZ） */
{
  const idxWatch = code.indexOf('watch(tagOptions')
  const idxTagOptions = code.indexOf('const tagOptions = computed')
  assert.ok(idxWatch > idxTagOptions, 'watch(tagOptions) 必须在 tagOptions 定义之后')
  const idxCurWork = code.indexOf('const curWork = computed')
  assert.ok(idxWatch > idxCurWork, 'watch(tagOptions) 必须在 curWork 之后（immediate 会立刻求值）')
}

console.log('OK d116-grading-tags：tags 来自 roster∪作业纸 · 空 tag 有可操作提示 · '
  + '未选语义明确 · 学习通无 tag 已确认 · watch 顺序防 TDZ')
