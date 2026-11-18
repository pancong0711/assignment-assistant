# D192 审核与修复：扫码任务卡住无法重新出码（是否需要退出账号？）

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/134-D191-xxt-login-attach-and-stale-state.md`、`docs/133-D190-xxt-qr-before-avatar.md`、
> `docs/132-D189-xxt-relogin-success-detection.md`、`docs/19-D68-xxt-scan-login-state.md`
>
> 隐私：需求单与测试只用合成数据；不记录 cookie 值、二维码票据、学生姓名/学号/作答内容。

---

## 0. 结论先行

**不需要退出学习通账号。**

扫码登录只在**本机新建一个干净的浏览器上下文**里拿 `passport2.chaoxing.com` 的登录票据，
与教师手机 App / 网页端是否已登录无关；也不复用 `xxt-storage.json` 里的旧 cookie。
真正导致“重扫二维码不显示”的是**服务端单实例锁 + 旧任务无法取消 + 只读状态误判**。

## 1. 审核发现的问题（D189–D191 后续回归）

| # | 问题 | 触发场景 | 影响 |
|---|---|---|---|
| A | 旧扫码任务无法取消，单实例锁要占满 CLI 等待窗口（`--timeout 1800` = 30 分钟） | 上一次扫码未扫/浏览器卡住 | 重新出码永远 409，只能关引擎 |
| B | `_xxt_login_state` 只按 mtime 判断“状态是否新鲜” | 旧任务持续刷新状态文件 | 没有任务在跑时仍显示“已生成二维码，等待扫码” |
| C | 前端 `refreshStatus()` 无超时，轮询可能被单个请求拖住 | 引擎侧 `/xxt/status` 触发体检/抓头像 | 二维码出来后页面迟迟不刷新 |
| D | 任务长时间 running 但无二维码时没有退出路径 | 浏览器启动失败/页面卡在 passport | 无限“二维码生成中” |
| E | `/jobs/<id>` 404 未区分“任务不存在” | 引擎重启 | 旧实现只当作查询失败继续轮询 |

## 2. 修复

### R1. 可取消的登录任务（核心）

`engine/src/assist/serve.py`：

- `_start_stream_job()` 登记子进程句柄 `_JOBS[id]["proc"]`；
- 新增 `cancel_job(job_id, reason)`：`terminate()` → 3 秒后 `kill()` 兜底；
- 新增 `cancel_xxt_login_job(reason)`：取消当前运行的扫码任务；
- 新增 `POST /jobs/<id>/cancel`；
- `_xxt_login_job_running_info()` 增加 `pid` / `stale`（超过 `_XXT_LOGIN_MAX_AGE=1900s` 视为卡死）。

### R2. 重新扫码 = 先取消旧任务再出新码

- `POST /xxt/login/start?replace=1`：先 `cancel_xxt_login_job()`，等旧进程退出（≤8s）再启动新任务；
- 响应带 `replacedJob`，前端提示“已取消上一次扫码任务，正在生成新二维码”；
- 「🔁 重新扫码登录」与「⚡ 强制重新出码」都走 `replace=1`；
- 普通「📷 扫码登录」仍为接管语义（409 → 接管正在跑的二维码）。

### R3. 只读状态不再误判“等待扫码”

- `_xxt_login_state(..., job_running: bool | None)`：
  - `job_running=False`（本进程确无扫码任务）：状态文件与二维码**一律不采信**，`qrExists=False`；
  - `job_running=True`：仍按任务起点（`since`）过滤上一轮 `logged_in`；
  - `None`：保留纯函数/诊断调用的旧行为。
- `/xxt/login/state` 显式传 `jobRunning`，并回显任务摘要 `job{job_id,started_at,age,stale}`。

### R4. 前端卡住出口

- 任务 running 但 45s 或 `stale` 仍无二维码 → 显示原因 + 出现「⚡ 强制重新出码」按钮；
- 文案明确：不需要退出学习通账号、无需关闭引擎；
- 刷新页面后若引擎仍有任务在跑，自动接上该任务（`jobRunning` + `job.job_id`）；
- 任务 404 → 停止轮询并提示重新出码。

## 3. 是否需要“退出账号”？

不需要，且**不建议**：

1. `qr_login()` 每次都 `browser.new_context()`（全新上下文，不加载 storage），
   旧 cookie 不存在，因此与账号当前登录态无关；
2. 学习通扫码是“在手机已登录的前提下授权新设备”，重新扫码即新增/刷新本机会话；
3. 退出账号反而会让手机端也要重登，风险与成本更高；
4. 真正会挡住重新扫码的是**服务端遗留任务**，已由 R1/R2 解决。

## 4. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 旧扫码任务卡住（>45s 无二维码） | 出现「⚡ 强制重新出码」，点了能取消旧任务并出新码 |
| 2 | 重新扫码时已有任务在跑 | 引擎取消旧任务后启动新任务（`replacedJob` 非空） |
| 3 | 无任务在跑但有遗留 `waiting_scan`/旧二维码 | 不再显示等待扫码 |
| 4 | 刷新页面且引擎有任务在跑 | 自动接上该任务并显示其二维码 |
| 5 | 引擎重启后旧 job | 停止轮询并提示重新出码 |
| 6 | 隐私 | 状态接口仍不含 cookie 值/token/票据 |
| 7 | 回归 | 全量 pytest、前端 build/selfcheck 通过 |

## 5. 范围

允许：`engine/src/assist/serve.py`、`app/src/lib/engineClient.ts`、
`app/src/views/XxetongView.vue`、`app/package.json`、对应 tests、本文档与 `README.md` 索引。
不得改提取/批次/批阅逻辑；不得读取真实会话或学生数据。

## 6. 实施结果

- 引擎：子进程句柄登记、`cancel_job`/`cancel_xxt_login_job`、`/jobs/<id>/cancel`、
  `replace=1`、`_XXT_LOGIN_MAX_AGE`/`stale`、`job_running` 只读过滤、`jobRunning`/`job` 回显。
- 前端：`cancelXxtJob()`、`startXxtLogin(..., {replace})`、`forceReissueQr()`、
  `qrBlocked` 卡住提示、`startScan()` 签名统一。
- 测试：`engine/tests/test_d192_xxt_cancel_stuck_login.py`（11 项）；
  `app/tests/selfcheck-d192-cancel-stuck-login.mjs`，已接入 `npm run selfcheck`；
  D188/D189/D190/D191 既有 selfcheck 断言随函数签名更新（非放宽口径）。
