/**
 * D145：provider 请求头 UI 重做后的**数据语义**。
 *
 * 这些是 UI 的纯函数，抽出来直接跑（避免"只有真浏览器才能验证"）。
 * 断言：
 *  1. 勾选「需要会话头」→ 存的是 {"x-opencode-session": "{session}"}（占位符由前端代填）
 *  2. 取消勾选 → 该项被移除
 *  3. 其他自定义头与勾选头**合并**，且勾选头优先（重名时）
 *  4. 编辑已有 provider 时能正确拆出勾选状态（不把 {session} 显示给教师）
 */
function parseHeaders(text) {
  const out = {}
  for (const raw of String(text || '').split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const i = line.indexOf('=')
    if (i <= 0) return { error: `格式应为 name=value：${line}` }
    out[line.slice(0, i).trim()] = line.slice(i + 1).trim()
  }
  return out
}
function collectHeaders({ hdrText, sessionOn, sessionName }) {
  const parsed = parseHeaders(hdrText)
  if (parsed.error) return parsed
  const out = { ...parsed }
  if (sessionOn) {
    const name = (sessionName || '').trim() || 'x-opencode-session'
    if (!/^x-[\w-]+$/i.test(name)) return { error: `头名非法：${name}` }
    out[name] = '{session}'
  }
  return out
}
function splitForEdit(headers) {
  const hdrs = headers || {}
  const sess = Object.entries(hdrs).find(([, v]) => String(v).includes('{session}'))
  return {
    sessionOn: !!sess,
    sessionName: sess ? sess[0] : 'x-opencode-session',
    otherText: Object.entries(hdrs).filter(([k]) => !sess || k !== sess[0])
      .map(([k, v]) => `${k}=${v}`).join('\n'),
  }
}

let bad = 0
function ok(name, cond, detail = '') {
  if (cond) console.log(`✓ ${name}`)
  else { console.error(`✘ ${name}${detail ? '：' + detail : ''}`); bad = 1 }
}

const a = collectHeaders({ hdrText: '', sessionOn: true, sessionName: 'x-opencode-session' })
ok('勾选会话头 → 存占位符', a['x-opencode-session'] === '{session}', JSON.stringify(a))

const b = collectHeaders({ hdrText: '', sessionOn: false, sessionName: '' })
ok('未勾选 → 没有任何头', Object.keys(b).length === 0, JSON.stringify(b))

const c = collectHeaders({ hdrText: 'x-trace=abc', sessionOn: true,
                            sessionName: 'x-opencode-session' })
ok('与其他自定义头合并', c['x-trace'] === 'abc' && c['x-opencode-session'] === '{session}',
   JSON.stringify(c))

// 重名：勾选头优先（自定义里也写了同名，但没写 {session}）
const d = collectHeaders({ hdrText: 'x-opencode-session=WRONG', sessionOn: true,
                            sessionName: 'x-opencode-session' })
ok('重名时勾选头优先（不会被写死值覆盖）',
   d['x-opencode-session'] === '{session}', JSON.stringify(d))

const e = collectHeaders({ hdrText: 'badline', sessionOn: true })
ok('非法自定义头报错', !!e.error)

const f = collectHeaders({ hdrText: '', sessionOn: true, sessionName: 'not-x' })
ok('会话头名必须以 x- 开头', !!f.error)

const g = splitForEdit({ 'x-opencode-session': '{session}', 'x-trace': 'abc' })
ok('编辑回填：拆出勾选状态', g.sessionOn === true && g.sessionName === 'x-opencode-session',
   JSON.stringify(g))
ok('编辑回填：其他头保留、不含 {session}', g.otherText === 'x-trace=abc', g.otherText)

const h = splitForEdit({ 'x-trace': 'abc' })
ok('编辑回填：无会话头时勾选为 false', h.sessionOn === false && h.sessionName === 'x-opencode-session')

if (!bad) console.log('OK d145-header-ux：会话头勾选式（占位符前端代填）· 合并/重名优先 · 回填拆分')
process.exit(bad)
