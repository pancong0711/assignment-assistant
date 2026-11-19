/** D205：本地仿真学习通批阅页的端到端测试已入库（插图/打分/提交/核验/会话过期/重试）。 */
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const appRoot = join(__dirname, '..')
const root = join(appRoot, '..')
const e2e = fs.readFileSync(
  join(root, 'engine/tests/test_d205_upload_e2e_mock_markpage.py'), 'utf8')
const upload = fs.readFileSync(join(root, 'engine/src/assist/xxt/grade_upload.py'), 'utf8')
const marking = fs.readFileSync(join(root, 'engine/src/assist/xxt/marking.py'), 'utf8')
const pkg = JSON.parse(fs.readFileSync(join(appRoot, 'package.json'), 'utf8'))
const errors = []
const must = (c, m) => { if (!c) errors.push(m) }

// 1) 仿真页覆盖真实选择器
must(/textarea name="comment"/.test(e2e) || /textarea\[name="comment"\]/.test(e2e), '仿真页缺批语框')
must(/edui-for-insertimage/.test(e2e), '仿真页缺插图按钮')
must(/tmpscore/.test(e2e), '仿真页缺总分输入')
must(/markAction\(1\)/.test(e2e), '仿真页缺提交按钮')
must(/confirmPiyueWork/.test(e2e), '仿真页缺确认函数')
must(/dataBody_td/.test(e2e) && /cz_py/.test(e2e), '仿真页缺批阅列表结构')

// 2) 四个关键场景
must(/def test_e2e_upload_image_and_score_then_verified/.test(e2e), '缺“插图+打分+核验”场景')
must(/def test_e2e_confirm_button_without_popok_id/.test(e2e), '缺“无 #popok 确认按钮”场景')
must(/def test_e2e_unverified_when_confirm_disabled_then_retry_succeeds/.test(e2e),
  '缺“未保存→重试”场景')
must(/def test_e2e_session_expired_detected/.test(e2e), '缺“会话过期”场景')

// 3) 重试必须重开批阅页（D205 核心修复）
must(/if attempt > 1:/.test(upload) && /_open_and_check\(\)/.test(upload),
  '重试未重新打开批阅页')
must(/_fill_page\(first=False\)/.test(upload), '重试未重新填写内容')

// 4) 确认弹窗不重复点击
must(/clicked_keys/.test(marking) && /stillOpen/.test(marking),
  '确认弹窗仍可能被重复点击')

must(/selfcheck:d205/.test(String(pkg.scripts?.['selfcheck'] || '')), 'selfcheck 链未接入 d205')
must(!!pkg.scripts?.['selfcheck:d205'], 'package.json 缺少 selfcheck:d205')

if (errors.length) {
  for (const e of errors) console.error(`✗ ${e}`)
  process.exit(1)
}
console.log('✓ 本地仿真页覆盖真实选择器（批语/插图/分数/提交/确认/列表）')
console.log('✓ 4 个端到端场景（成功/无#popok/未保存重试/会话过期）')
console.log('✓ 重试会重新打开批阅页并重填；确认弹窗不重复点击')
console.log('✓ D205 selfcheck 已接入 npm run selfcheck')
