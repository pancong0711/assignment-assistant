# D204：提交报「未找到提交按钮」——先分辨会话过期；新增「演练」安全复测

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/146-D203-submit-confirmation-click.md`、`docs/145-D202-upload-verification.md`
>
> 隐私：测试只用合成数据。

---

## 0. 现场

```text
❌ 提交失败：{'ok': False, 'error': "未找到提交按钮：{'ok': False,
   'reason': 'no-markAction(1)'}"}；确认弹窗 0 个，点击 None
```

教师补充：学习通会话**应该已经过期**，并问“为什么之前在大学物理拾遗班级做的上传测试没有改成功”。

## 1. 结论：多半不是“按钮没了”，而是“页面已经不是批阅页”

会话过期后打开批阅页会被跳到 `passport2.chaoxing.com/login`，
那个页面上当然没有 `markAction(1)`。旧实现只报“未找到提交按钮”，
把人引向“平台改版”的错误方向；而实际要做的是重新扫码登录。

关于“之前测试为什么没成功”：同一原因——旧版本在**提交后没有核验**（D202 才补上），
会话失效或确认弹窗没点中时，界面仍显示成功，实际什么都没写。

## 2. 修复

### R1. 提交前先诊断页面状态

新增 `page_state(page)`（只读）返回：

```json
{"url": "...", "title": "...", "loginRedirect": true, "hasPassword": true,
 "hasCommentBox": false, "hasScoreInput": false,
 "candidates": [{"text": "提交", "onclick": "markAction(1)", "id": "", "cls": ""}]}
```

`submit()` 判定顺序：

1. `loginRedirect`（域名/路径含 passport/login/sso）**或** 有密码框但没有批语框
   → `status="session-expired"`，错误文案：
   > 学习通会话已失效（当前页跳到了登录页/出现登录框）：请点「🔁 重新扫码登录」后重试
2. 页面正常但 `markAction(1)` 不存在 → 走兜底策略；
3. 兜底也失败 → `status="no-submit-button"` 并**带回页面诊断与候选按钮**。

### R2. 打开批阅页后立即校验（写之前就拦住）

`upload_grade()` 打开批阅页后先取 `page_state`：

- 登录页 → `session-expired`，**不填任何内容**；
- 既无批语框也无分数框 → `not-mark-page`（作业/班级参数不对或平台改版）。

这样不会再把内容填到错误页面上。

### R3. 提交按钮多策略兜底

`_JS_CLICK_SUBMIT_FALLBACK`：按优先级点可见元素
`markAction(1)`(100) → `confirmPiyueWork`(90) → onclick 含 submit/save/publish(80)
→ 文案「提交」(70) → 文案「保存」(60) → 含“提交/保存”(50)，
并把 `tried[]` 一起返回便于排查。

### R4. 逐生「演练」按钮（安全复测）

对照表每行新增「演练」：`send=false`，只**填入批语/分数并读回**，不点提交。
- 成功：「✅ 演练通过（已填入并读回，未提交）」
- 会话过期/页面不对：立即报 `session-expired` / `not-mark-page`

建议复测顺序：**先「演练」1 人 → 通过后再「上传」**。

## 3. 关于“重新扫码登录后再测试”

推荐流程：

1. 点「🔁 重新扫码登录」，扫完确认头像出现、体检 alive；
2. 「🕘 报告版本」确认名单与报告齐全；
3. 「🔍 上传前对照」→ 找到目标学生 → 点**「演练」**（不写平台）；
4. 演练返回“已填入并读回” → 点**「上传」**（真提交 + 提交后核验）；
5. 学习通上确认该生变为已批阅且分数正确。

## 4. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 提交页跳 passport | `session-expired` + 提示重新扫码 |
| 2 | 有密码框无批语框 | `session-expired` |
| 3 | 页面正常但无 `markAction(1)` | 兜底按文案/onclick 点击 |
| 4 | 兜底也失败 | `no-submit-button` + 页面诊断/候选按钮 |
| 5 | 打开批阅页即登录页 | 不填任何内容，直接报会话过期 |
| 6 | 页面无批语框也无分数框 | `not-mark-page` |
| 7 | 演练 | 只填不提交，可安全验证 |
| 8 | 回归 | 全量 pytest 1865 passed；selfcheck:d188–d204 通过 |

## 5. 范围

允许：`engine/src/assist/xxt/marking.py`、`engine/src/assist/xxt/grade_upload.py`、
`app/src/components/AiGradingPanel.vue`、`app/package.json`、对应 tests、
本文档与 README 索引。不得改评分口径；不得读取真实学生数据。

## 6. 实施结果

- `marking.py`：`_JS_PAGE_STATE` / `page_state()`、`_JS_CLICK_SUBMIT_FALLBACK`、
  `submit()` 先判会话再兜底点击，返回 `page/candidates/fallback` 诊断；
- `grade_upload.py`：打开批阅页后校验 `pageState`；提交阶段遇 `session-expired`
  直接收尾并提示重新扫码；
- 前端：逐生「演练」按钮（`send=false`）、演练/上传两套结果文案；
- 测试：`engine/tests/test_d204_submit_button_and_session.py`（6 项）+ `selfcheck:d204`。
