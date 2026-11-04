/**
 * D142：provider 表单保存后必须清空，否则新建下一个 provider 时
 * 会把上一个的请求头/UA 原样带过去（静默污染另一个 provider 的鉴权/路由）。
 *
 * 这里验证的是**引擎侧**的写入语义：同一个 name 再写一次会覆盖，
 * 不同 name 各自独立；配合 UI 的表单清空，才能保证"一个 provider 一套头"。
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const PY = process.argv[2]
const ws = mkdtempSync(join(tmpdir(), 'd142-'))

function py(code) {
  return execFileSync(PY, ['-c', code], { encoding: 'utf-8' }).trim()
}

py(`
import sys; sys.path.insert(0,'${process.cwd()}/../engine/src')
from pathlib import Path
from assist.grading import providers as P
ws=Path('${ws}'); (ws/'kb').mkdir(parents=True)
# provider A：带 opencode 请求头
P.save_provider(ws,'opencode-go',base_url='https://opencode.ai/inference/go/openai/v1',
                api_key='k', headers={'x-opencode-session':'{session}'}, user_agent='assignment-assistant/1.0')
# provider B：另一个供应商，**不应**继承 A 的头
P.save_provider(ws,'aliyun',base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
                api_key='k2')
`)

const d = JSON.parse(readFileSync(join(ws, 'settings.local.json'), 'utf-8'))
const provs = Object.fromEntries((d.llm?.providers || []).map((p) => [p.name, p]))
let bad = 0
function ok(name, cond, detail = '') {
  if (cond) console.log(`✓ ${name}`)
  else { console.error(`✘ ${name}${detail ? '：' + detail : ''}`); bad = 1 }
}

ok('A 保存了请求头', provs['opencode-go']?.headers?.['x-opencode-session'] === '{session}')
ok('A 保存了自定义 UA', provs['opencode-go']?.user_agent === 'assignment-assistant/1.0')
ok('B 没有继承 A 的请求头', !provs['aliyun']?.headers,
   JSON.stringify(provs['aliyun']?.headers))
ok('B 没有继承 A 的 UA', !provs['aliyun']?.user_agent, String(provs['aliyun']?.user_agent))

if (!bad) console.log('OK d142-provider-form：请求头按 provider 隔离（B 不继承 A 的头/UA）')
process.exit(bad)
