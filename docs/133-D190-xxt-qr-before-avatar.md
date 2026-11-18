# D190 修复：「重新扫码登录」提示已生成二维码，却仍显示旧头像

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/132-D189-xxt-relogin-success-detection.md`、`docs/131-D188-xxt-relogin-and-extract-error-detail.md`、
> `docs/19-D68-xxt-scan-login-state.md`、`docs/16-xuexitong-integration.md`
>
> 隐私：需求单与测试只用合成数据；不记录 cookie 值、二维码票据、学生姓名/学号/作答内容。

---

## 0. 现场

点「🔁 重新扫码登录」后页面提示：

```text
已有扫码登录任务在进行中，请先完成扫码或稍后再试
已生成二维码，等待手机扫码（扫码后请勿关闭页面）；当前页：passport2.chaoxing.com
```

但**二维码位显示的是上一轮登录的头像**，教师找不到可扫的二维码。
期望：扫码期间显示二维码；**扫完并登录成功之后**才在该位置显示头像。

## 1. 根因

1. **头像与 QR 的优先级只在模板层按 `verdict` 判断**：
   `qrcode` 为空时只要 `verdict==='alive'` 且旧头像还在缓存里，就渲染头像。
   重新扫码期间旧 verdict 仍是 alive、头像 ref 未清 → 头像长期占位。
2. **每次 `/xxt/status` 都会触发引擎抓头像**（`_xxt_avatar_cached` 未命中时新开浏览器，
   最长 25s）；扫码轮询每 1.5–3s 调一次 → 引擎在二维码生成阶段被头像抓取拖住，
   `/xxt/login/state` 与 `/xxt/qr` 都可能迟到，前端只能停在“生成中/旧头像”。
3. **上一轮登录遗留的 `xxt-login-state.json`（`stage=logged_in`）** 会被当前任务的前端
   读到：失败分支拿它拼文案，可能把“本轮失败”包装成“已登录”。
4. 二维码就绪只看 `/xxt/qr` 是否可解码，未与登录阶段（`waiting_scan` + `qrExists`）对齐，
   浏览器刚启动时可能拿到上一轮残留字节或半张图。
5. 「📷 扫码登录（QR）」在 `verdict==='alive'` 时被禁用，教师无法从正常态主动出码。

## 2. 修复

### R1. 扫码期间头像位只让给二维码（前端）

`app/src/views/XxetongView.vue`：

- 新增 `loginFlowActive = computed(() => qrLoading || qrcode !== '')`；
- 模板顺序固定为 `二维码 → 头像 → 🎓 已登录占位 → 生成中占位 → 待扫码`，
  头像与 🎓 均加 `!loginFlowActive` 守卫；
- 发起扫码（`startScan`）与重新扫码（`relogin`）时立即 `avatar.value = null`；
- 扫码状态文案优先显示“等待出码 / 请扫码”，不被 `/xxt/status` 的“已登录”覆盖。

### R2. 头像只在登录成功后刷新

- 新增 `refreshAvatarAfterLogin()`：`finishLoginSuccess()` 里先清旧头像再异步取新头像；
- `refreshStatus()` 不再用 `null` 覆盖已有头像，只在 `verdict!=='alive'` 时清空；
- `onMounted` 已登录时用 `ensureAvatarLoaded()` 补一次（30s 节流）。

### R3. 引擎侧：登录开始即作废旧头像缓存

`engine/src/assist/serve.py`：

- `/xxt/login/start` 清理 QR/状态文件时同时 `_XXT_AVATAR = None`，
  避免扫码期间 `/xxt/status` 先跑一次 25s 抓头像；
- `_start_stream_job()` 记录 `started_at`；
- 新增 `_xxt_task_started_at(job_id)`；
- `_xxt_login_state(home, since=0)`：带 `job_id` 查询时，若状态文件 mtime 早于任务开始时间，
  视为**上一轮遗留**，返回空 `stage`（不把旧 `logged_in` 当本轮结果）；
- `GET /xxt/login/state?job_id=...` 透传 `since`。

### R4. 前端二维码就绪判定更稳

- 轮询时先取 `/xxt/login/state?job_id=`，要求 `qrExists !== false` 且阶段允许
  （`starting/waiting_scan/logged_in`），再探测 `/xxt/qr` 是否可解码；
- 图片可解码但状态仍停在 `starting` 时以图片为准放行（写入本地判定为 `waiting_scan`）；
- 阶段已 `failed/timeout` 时立即收尾并展示脱敏原因；
- 任务失败分支只采信本轮 `waiting_scan/failed/timeout` 的状态文本，避免旧 `logged_in` 混淆。

### R5. 按钮可用性

「📷 扫码登录（QR）」不再因 `verdict==='alive'` 禁用，仅出码过程中禁用。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 已登录态点「重新扫码登录」 | 头像立即消失，出现“二维码生成中” |
| 2 | 二维码落盘（waiting_scan） | 显示二维码，提示“请用学习通 App 扫码” |
| 3 | 扫码成功 | 收尾提示成功，随后头像出现在原二维码位 |
| 4 | 二维码阶段失败/超时 | 收掉二维码态，显示脱敏原因 |
| 5 | 上一轮遗留 `logged_in` | 不冒充当轮结果，不误报成功 |
| 6 | 隐私 | 状态接口仍不含 cookie 值/token/票据 |
| 7 | 回归 | 全量 pytest、前端 build/selfcheck 通过 |

## 4. 范围

允许：`app/src/views/XxetongView.vue`、`app/src/lib/engineClient.ts`、`app/package.json`、
`app/tests/selfcheck-d190-*.mjs`、`engine/src/assist/serve.py`、
`engine/tests/test_d190_*.py`、本文档与 `README.md` 索引。
不得改提取/批次/批阅逻辑；不得读取真实会话或学生数据。

## 5. 实施结果

- 前端：`loginFlowActive` 守卫 + 发起扫码即清头像 + 登录成功后才异步刷头像 +
  QR 就绪双确认（状态 + 图片）+ 失败不采信旧 `logged_in` + 扫码按钮不再被 alive 禁用。
- 引擎：登录开始清头像缓存；`_start_stream_job` 记录 `started_at`；
  `/xxt/login/state?job_id=` 按任务起点过滤上一轮状态。
- 测试：`engine/tests/test_d190_xxt_qr_after_relogin.py`（6 项）；
  `app/tests/selfcheck-d190-qr-before-avatar.mjs`，已接入 `npm run selfcheck`。
