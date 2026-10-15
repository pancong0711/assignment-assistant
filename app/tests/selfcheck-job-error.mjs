/** D83 修复回归：CLI job 输出 → 可读错误（PWA 只显示「}」的根因）。
 *  运行前置：esbuild 打包 src/lib/engineClient.ts（npm run selfcheck:job-error）。 */
import assert from 'node:assert'
const ec = await import('./engineClient.bundle.mjs')

// ① 失败 JSON：取 "error" 字段（含后端步骤名），而不是 indent JSON 的末行 "}"
{
  const out = ['{', ' "ok": false,',
    ' "error": "新建作业失败（步骤：选择题型（简答题））：TimeoutError",',
    ' "step": "选择题型（简答题）"', '}'].join('\n')
  assert.equal(ec.extractJobError(out),
    '新建作业失败（步骤：选择题型（简答题））：TimeoutError')
}
// ② 无 JSON（未捕获异常）：回退 traceback 末行
{
  const out = 'Traceback (most recent call last):\n  File "work.py", line 1\nplaywright.TimeoutError: Locator.click: Timeout 10000ms exceeded\n'
  assert.equal(ec.extractJobError(out), 'playwright.TimeoutError: Locator.click: Timeout 10000ms exceeded')
}
// ③ JSON 转义（\\ / \n）正确解码
{
  const out = '{\n "error": "附件被拒：a\\\\b.zip\\n见截图"\n}'
  const got = ec.extractJobError(out)
  assert.ok(got.includes('a\\b.zip') && got.includes('\n'), `转义解码失败: ${got}`)
}
// ④ 多个 error 字段取最后一个（本 job 结论 JSON）
{
  const out = '{"error": "旧的中间态"}\n{"error": "最终失败原因"}'
  assert.equal(ec.extractJobError(out), '最终失败原因')
}
// ⑤ 空输出
assert.equal(ec.extractJobError(''), '未知错误（无输出）')

console.log('selfcheck-job-error: ALL PASS（D83 ×5）')
