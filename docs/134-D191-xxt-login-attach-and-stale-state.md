# D191 修复：409「已有扫码登录任务」把教师卡死 + 遗留登录态冒充当前扫码

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/133-D190-xxt-qr-before-avatar.md`、`docs/132-D189-xxt-relogin-success-detection.md`、
> `docs/131-D188-xxt-relogin-and-extract-error-detail.md`
>
> 隐私：需求单与测试只用合成数据；不记录 cookie 值、二维码票据、学生姓名/学号/作答内容。

---

## 0. 现场

点击「🔁 重新扫码登录」后，页面长期显示：

```text
已有扫码登录任务在进行中，请先完成扫码或稍后再试
已生成二维码，等待手机扫码（扫码后请勿关闭页面）；当前页：passport2.chaoxing.com

⚠ 最近一次发现/提取被跳转到学习通登录页：体检可能仍显示已登录，但课程工作台会话已失效。
  请点「🔁 重新扫码登录」后重试。
```

但**看不到二维码**，再点重新扫码还是同一条 409，红字也不会消失。

## 1. 根因

1. **409 被当作失败**：`/xxt/login/start` 发现已有 `xxt_login` 任务在跑就返回 409；
   前端 `startXxtLogin()` 直接抛错，页面只显示“已有任务在进行中”，**从不接管该任务**
   → 那个任务生成的二维码永远传不到页面。
2. **遗留状态冒充当前扫码**：没有任务在跑时，`/xxt/login/state` 仍无条件读
   `xxt-login-state.json` / `xxt-qr.png`；上一轮的 `stage=waiting_scan` 与旧二维码
   让页面一直“等待扫码”，实际引擎里根本没有在等的任务。
3. **旧的 loginRedirect 不肯消失**：D188 的 `loginRedirect` 来自“最近一次发现/提取产物”；
   扫码登录成功后到下一个人工发现/提取之间，红字会一直亮着。
4. **任务消失无收尾**：引擎重启后 `/jobs/<id>` 返回 404，前端只当作查询失败继续轮询。

## 2. 修复

### R1. 409 = 接管正在运行的任务（不再报死）

- `engineClient.startXxtLogin()` 改为返回 `{kind:'started'|'busy', ...}`；
- 409 `stage=busy` 时返回 `jobId / startedAt / ageSec / error / hint`；
- 引擎 409 hint 改为可执行建议（页面会自动接管；二维码约 2 分钟过期可重新出码），
  **不再要求关闭引擎重启**；
- 前端 `startScan()` 收到 `busy` 时：`loginJobId = jobId`、按 `ageSec` 回推等待起点、
  继续轮询 `/xxt/qr` 并把二维码显示出来，提示“已接上正在进行的扫码任务”。

### R2. 遗留状态/旧二维码不再冒充当前扫码

引擎 `_xxt_login_state(home, since=0, readonly_since=0)`：

- `since>0`（带 `job_id`）：只认该任务开始后写入的状态；
- `readonly_since>0`（**本进程当前没有登录任务在跑**）：状态文件更旧则不采信；
  没有状态文件且 `xxt-qr.png` 也不新鲜 → `qrExists=False`；
- `/xxt/login/state` 不带 `job_id` 且无运行中任务时，基准取
  「运行中任务起点」或「进程启动时间 `_STARTED_EPOCH`」。

前端轮询：`!loginJobId && !qrFiled` → 收掉等待态，显示“没有正在等待的扫码任务，
请点「🔁 重新扫码登录」”，并停止空转轮询；新增 `qrStale` 失效占位（⌛ 二维码已失效）。

### R3. 登录成功后旧的“被跳登录页”红字消失

- 新增 `_xxt_login_completed_after(ts)`：`ts` 之后若状态文件是 `logged_in`，返回其 mtime；
- `/xxt/status`：命中该情形时把 `loginRedirect` 置 false，并透传 `loginCompletedTs`；
- 前端除 `reloginAt` 外再用 `loginCompletedTs` 隐藏更早的跳转记录。

### R4. 任务消失有收尾 + 刷新后可接上

- `fetchXxtLoginJob()` 把 404 映射为 `status:'missing'`；
- 前端收到 `missing` → 停止轮询并提示“上一次扫码任务已结束，请重新出码”；
- `/xxt/status` 透传只读 `loginJob: {job_id, started_at, age}`，刷新页面后仍可判断
  是否有任务在跑（cookie 值/票据不外泄）；
- `/jobs/<id>` 透传 `started_at`。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 已有扫码任务在跑时点「重新扫码」 | 页面接管，二维码显示出来，不再只报 409 |
| 2 | 引擎无任务但残留旧 `waiting_scan`/旧二维码 | 不显示等待扫码，提示重新出码 |
| 3 | 扫码登录成功后 | 旧的“被跳登录页”红字消失 |
| 4 | 引擎重启后旧 job | 停止轮询，提示重新出码 |
| 5 | 刷新页面 | 可读取 `loginJob` 判断是否仍在扫码 |
| 6 | 隐私 | 状态接口仍不含 cookie 值/token/票据 |
| 7 | 回归 | 全量 pytest、前端 build/selfcheck 通过 |

## 4. 范围

允许：`engine/src/assist/serve.py`、`app/src/lib/engineClient.ts`、
`app/src/views/XxetongView.vue`、`app/package.json`、对应 tests、本文档与 `README.md` 索引。
不得改提取/批次/批阅逻辑；不得读取真实会话或学生数据。

## 5. 实施结果

- 引擎：`_xxt_login_job_running_info()`、`_xxt_login_state(readonly_since=)`、
  `_xxt_login_completed_after()`、409 可读 hint、`/xxt/status` 透传
  `loginCompletedTs`/`loginJob`、`/jobs` 透传 `started_at`、`_STARTED_EPOCH`。
- 前端：`startXxtLogin()` 返回结构化 busy；`startScan()` 接管任务；`qrStale` 失效态；
  `job missing` 收尾；旧 `loginRedirect` 按 `loginCompletedTs` 隐藏。
- 测试：`engine/tests/test_d191_xxt_login_attach_and_stale_state.py`（9 项）；
  `app/tests/selfcheck-d191-login-attach.mjs`，已接入 `npm run selfcheck`。
