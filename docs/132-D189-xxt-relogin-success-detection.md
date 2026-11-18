# D189 修复：「重新扫码登录」扫了没反应 / 不跳转

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/131-D188-xxt-relogin-and-extract-error-detail.md`、`docs/16-xuexitong-integration.md`

## 0. 现场

D188 增加「🔁 重新扫码登录」后，扫码仍然无效，页面不跳转，也没有可读的失败原因。

## 1. 根因

1. **登录成功判定过宽**：`session._is_logged_in()` 只要 cookie 里有 `_uid/uid`
   就判成功。教师以前登录过，浏览器里可能残留旧 `_uid`，于是新生成的二维码尚未被扫描，
   就被误判为“已登录”，循环提前退出；随后 `check_session()` 又拿到半有效会话，
   表现为“扫了没反应、不跳转”。
2. **登录失败无可读原因**：`startQrPolling()` 只显示任务最后一行，二维码阶段失败 /
   等待超时 / 浏览器被关 / 二次体检 dead 无法区分。
3. **并发登录任务**：重新扫码不会终止上一个登录任务，两个任务抢写同一张
   `xxt-qr.png`，可能扫到上一张票据。

## 2. 修复

### R1. 登录判定改为“基线 + 新会话”

`engine/src/assist/xxt/session.py`：

- 新增纯函数 `cookie_fingerprint()`：只取 cookie 名与值的哈希，供内存比较；
- `_is_logged_in(page, baseline)`：
  - 先按原 cookie/URL 信号判断“已具备会话形态”；
  - 再要求**相对 baseline 有变化**（新增/变更关键 cookie），否则不算登录成功；
  - 仍保留 `check_session()` 二次确认。

### R2. 登录任务单实例 + 可读状态

`engine/src/assist/serve.py`：

- `/xxt/login/start` 若已有 `xxt_login` 任务在跑，返回 409 + 可读提示，不并发写 QR；
- 启动前清掉旧 `xxt-qr.png` 与 `xxt-login-state.json`；
- 新增只读 `GET /xxt/login/state`：返回
  `{stage, error, urlHost, cookies(只名字), updatedAt}`，**不含** cookie 值/token/票据。

### R3. 前端展示真实原因

`app/src/views/XxetongView.vue`：

- 扫码期间轮询 `/xxt/login/state`；
- 失败/超时时显示阶段与错误（脱敏），并给出下一步建议；
- “已有登录任务在跑”时明确提示，不再静默。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 旧 `_uid` 仍在、新二维码未扫码 | 不判登录成功 |
| 2 | 新会话 cookie 变化 + 工作台可达 | 判成功并二次确认 |
| 3 | 二维码阶段失败 | 前端显示阶段 + 错误 |
| 4 | 等待超时 | 显示 timeout 与建议 |
| 5 | 并发重新扫码 | 返回可读 409，不抢写 QR |
| 6 | 隐私 | 状态接口不含 cookie 值/token |
| 7 | 回归 | 全量 pytest、前端 selfcheck/build 通过 |

## 4. 范围

允许：`engine/src/assist/xxt/session.py`、`engine/src/assist/serve.py`、
`app/src/views/XxetongView.vue`、`app/src/lib/engineClient.ts`、对应 tests、本文档。
不得改提取/批次/批阅逻辑，不得读取真实会话或学生数据，不得 commit/push。

## 5. 实施结果

- `session.py`
  - 新增 `cookie_fingerprint()`（值只存 8 位短哈希，不落盘）与
    `session_cookie_changed()`；
  - `_is_logged_in(page, baseline)` 改为“必须相对扫码前基线出现新的/变化的会话 cookie”，
    教学域无 cookie 的保底仅在首次扫码（baseline 为空）时保留；
  - `qr_login()` 在生成二维码后记录 baseline，并写入 `xxt-login-state.json`。
- `serve.py`
  - `/xxt/login/start` 单实例：已有登录任务在跑返回 409 `stage=busy` 与可读 hint；
  - 启动前清理旧 `xxt-qr.png` / `xxt-qr.tmp.png` / `xxt-login-state.json`；
  - 新增只读 `GET /xxt/login/state`（stage/error/urlHost/cookie 名/qrExists），
    `error` 先脱敏，不含 cookie 值或 token。
- `XxetongView.vue` / `engineClient.ts`
  - `fetchXxtLoginState()` 只读状态；
  - 登录阶段→可读原因映射（starting/waiting_scan/failed/timeout/logged_in）；
  - 失败/超时/409 均显示脱敏后的真实原因。
- 测试
  - `engine/tests/test_d189_xxt_login_success_detection.py`（13 项）；
  - `app/tests/selfcheck-d189-relogin-success.mjs`，已接入 `npm run selfcheck`。

## 6. 验收结果

- D189 目标 + 会话/登录状态回归：`43 passed`；
- 全量 pytest（deselect 既有 Playwright 报告渲染超时用例）：`1713 passed`；
- 前端 `selfcheck:d189`：通过；前端 build：通过；
- 脱敏检查、启动脚本 lint、`git diff --check`：通过。
