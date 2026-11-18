# D188 需求单：学习通会话失效的「重新扫码」按钮 + 提取失败详细原因

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/16-xuexitong-integration.md`、`docs/20-D69`（会话体检）、
> `docs/24-D73`（提取/run）、`docs/130-D187`（追加批次）
>
> 隐私：需求单与测试只用合成数据；不得记录或回显真实 cookie、二维码票据、
> 学生姓名/学号/作答内容。

---

## 0. 现场问题

1. 学习通扫码会话过期后，PWA 没有任何提示；
2. 点「提取所选 / 追加到当前批次」后只看到“提取完成”或空列表，
   不知道真正原因是**被重定向回登录页**；
3. PWA 只有「📷 扫码登录（QR）」，且 `verdict==='alive'` 时被禁用，
   教师无法主动重新扫码；
4. 提取结果 0 课程/0 班级时，界面没有把 `steps` 里的登录页 URL、
   失败原因、hint 展示出来。

现场实证（2026-11-18）：

```text
xxt check        → verdict=alive（个人空间可开）
xxt discover     → courses=0 classes=0
                   steps: title=用户登录
                   url=https://passport2.chaoxing.com/login?...
```

说明“体检 alive”只覆盖个人空间，**不代表课程工作台会话仍有效**。

---

## 1. 需求

### R1. 新增「重新扫码登录」按钮

`app/src/views/XxetongView.vue`：

- 保留现有「📷 扫码登录（QR）」；
- 新增「🔁 重新扫码登录」，**任何 verdict 下都可用**（alive 也可用）；
- 点击后调用现有 `startXxtLogin` 流程，先清掉旧 QR/旧 job 状态；
- 点击时前端提示：将重新生成二维码，旧会话可能立即失效；
- 登录成功后自动刷新 `verdict`/头像，并可选自动重新 discover。

### R2. 会话失效要“说出来”

`GET /xxt/status` 已经返回 `reasons`；需要前端：

- `verdict==='dead'` 或用 `reasons` 命中登录重定向时，登录卡显示醒目红色提示；
- 提示包含：`会话已失效`、`原因`、`请点「重新扫码登录」`；
- 不显示 cookie/token 等敏感值。

### R3. 提取失败详细原因

前端 `pollExtractJob()` 目前只取最后一行，需要：

- 任务失败或 `courses=0/classes=0` 时，展示：
  - 最后 5–10 行任务输出；
  - run JSON 中的 `steps[]`（action/detail/title/url/ts）；
  - `failures[]`（scope/ref/kind/detail/hint）；
  - 若任何 step 的 `url` 命中 `passport` / `login`，显示：
    `检测到学习通登录页跳转 → 会话已失效，请点「重新扫码登录」`；
- 展示可折叠（默认展开摘要，详情可展开），避免刷屏；
- 提取 0 课程/0 班级时把 run 置为“失败/需登录”态，不要显示“提取完成”。

### R4. 后端补充最小信息（如需要）

`engine/src/assist/serve.py` 的 `GET /xxt/status` 或新增只读端点：

- 可返回 `loginRedirect` 布尔（最近一次 status/steps 是否命中 passport）；
- 可返回 `lastExtractError`（最近 run 的 `failures` + 首个登录页 step），
  只含 URL 主机与原因，不含 cookie；
- 不得新增写操作。

---

## 2. 允许修改范围

- `app/src/views/XxetongView.vue`
- `app/src/lib/engineClient.ts`（仅类型/只读调用）
- `engine/src/assist/serve.py`（仅只读状态信息）
- `engine/src/assist/xxt/session.py`（仅如需要补 `loginRedirect` 判定）
- 对应 engine/app tests
- 本文档

不得修改提取写流程、批次合并逻辑、批阅产物、评分规则；不得读取/回显真实学生数据。

---

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | verdict=alive 时点「重新扫码登录」 | 可发起、旧 QR 清除、出现新二维码 |
| 2 | 会话过期，提取被重定向登录页 | 明确红字提示 + 指向重新扫码 |
| 3 | 提取 0 课程/0 班级 | 不显示“完成”，显示失败原因与 steps |
| 4 | 提取失败带 failures[] | 显示 scope/kind/detail/hint |
| 5 | 正常提取 | 行为不变，详情不打扰 |
| 6 | 隐私 | 页面/日志不含 cookie、token、学生 PII |
| 7 | 回归 | 前端 build、selfcheck、engine pytest 通过 |

完成后停在 worktree 等待人工 review；禁止 commit/push。

---

## 4. 实施记录

- 前端 `XxetongView.vue`：
  - 新增「🔁 重新扫码登录」，任何 verdict 可用；确认后清旧 QR/job 前端状态并重新
    `startScan`。alive 下重新扫码时不再被旧 verdict 立即判成功，改为等待登录任务
    `done + returncode=0` 收尾。
  - `verdict=dead` 或 `reasons` 命中登录/会话时，登录卡显示红色「会话已失效」提示；
    reasons / steps URL 统一经 `maskSensitive` 脱敏（token/cookie/ticket/query）。
  - `pollExtractJob()` 失败或 run 为 0 课程/0 班级时，显示可折叠详情：最后 10 行任务输出、
    `steps[]`（action/detail/title/url/ts）、`failures[]`（scope/ref/kind/detail/hint）；
    steps URL 命中 `passport`/`login` 时明确提示登录页跳转。0 结果不再显示“提取完成”。
- 引擎只读补充：
  - `xxt/session.py` 新增纯函数 `is_login_redirect_url` / `steps_have_login_redirect`。
  - `GET /xxt/status` 的 `xxt` 增加 `loginRedirect` 布尔与 `loginRedirectTs`（epoch 秒）。
    只取体检 `final_url` + 最新一份 targets/run 的 steps，只返回布尔与时间戳，
    不回显 URL/cookie/token；无新增写操作。前端用 `reloginAt` 忽略本次重新登录前的旧记录。
- 测试：
  - `engine/tests/test_d188_xxt_login_redirect.py`（纯函数 + 只读状态，合成数据）。
  - `app/tests/selfcheck-d188-xxt-relogin-extract-error.mjs`（静态断言，已接入
    `npm run selfcheck`）。

## 4. 验收结果

- D188 目标 + 会话相关回归：`30 passed`；
- 全量 pytest（deselect 既有 Playwright 报告渲染超时用例）：`1698 passed, 2 skipped`；
- 前端 `selfcheck:d188`：通过；
- 前端 build：通过；
- 脱敏检查、启动脚本 lint、`git diff --check`：通过。
