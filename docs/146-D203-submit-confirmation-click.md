# D203：提交后平台仍停在「待批阅」——确认弹窗没点中

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/145-D202-upload-verification.md`、`docs/37-D84-grade-upload.md`、
> `docs/16-xuexitong-integration.md`（§「提交三态按钮」）
>
> 隐私：测试只用合成数据。

---

## 0. 现场

D202 的提交后核验生效后，报错变得具体：

```text
❌ 提交后核验失败：提交后平台状态仍为「待批阅」（未变成已批阅）
```

教师确认学习通上确实没有批阅。说明**提交动作被平台取消了**，而不是核验误判。

## 1. 根因：确认弹窗的“确定”按钮不是 `#popok`

点 `markAction(1)` 后，学习通会弹确认层，**必须再点“确定”才会真正保存**。
旧实现只找一个按钮：

```python
const el = document.querySelector('#popok, #popokTwice');
if (el && el.offsetParent !== null) { el.click(); return true; }
```

但新版学习通的确认入口是 **`confirmPiyueWork()`**（docs/16 早已记录该函数），
或只是文案为「确定/确认」的普通 `<a>`，**都没有 `popok` id**。
→ 确认层永远没被点掉 → 提交被取消 → 平台状态一直「待批阅」。

## 2. 修复

### R1. 确认弹窗识别与点击都放宽

`_JS_FIND_POPUP`：候选层 `#tabindexWorkpop / #tabindexWorkpopTwice / #confirmPiyueWin /
#popok / #popokTwice / .layui-layer / .popup / .dialog`，
且要求层内**存在可确认元素**或文案含“确定/确认/是否/未批阅/评分”。

`_JS_CLICK_POPUP_CONFIRM` 按优先级点：

1. `#popok` / `#popokTwice`（经典）；
2. `onclick` 含 **`confirmPiyueWork`** 的元素（新版）；
3. 可见元素文案为「确定/确认/继续/确定提交」。

返回 `{ok, how, text}`，`how` 记录命中方式，便于事后判断。

### R2. 支持多层确认

`handle_confirmation_dialog()` 现在循环处理：有弹窗就点确认 → 等待 → 再看；
连续 3 次（约 1.5s）无弹窗才认为结束。返回
`{ok, popups:[{id,text}], clicks:[{popup,clicked}]}`。

### R3. 记录平台自己的 confirm/alert

页面初始化注入：

```js
window.__assistDialogs = [];
window.confirm = (msg) => { __assistDialogs.push({type:'confirm', msg, accepted:true}); return true; };
window.alert = (msg) => { __assistDialogs.push({type:'alert', msg}); };
```

既保证平台 confirm 被接受，也能在失败时看到平台到底提示了什么
（例如“分数不能为空”“还有题目未批阅”）。

### R4. 未生效自动重试一次

提交 → 核验；若“点到了按钮但平台未保存”，等 2s 再提交一次并再次核验
（确认层点击有时序问题）。结果里记录 `submitAttempts[]`。

### R5. 失败信息带证据

```text
提交后核验失败：提交后平台状态仍为「待批阅」（未变成已批阅）
；确认弹窗 1 个，点击 [{'popup': '#tabindexWorkpop', 'clicked': {'ok': False,
 'reason': 'no-visible-confirm'}}]
；页面提示：分数不能为空
；候选按钮：提交(markAction(1))、保存(markAction(2))
```

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 确认按钮走 `confirmPiyueWork()` | 能点中，`clicks[0].how=onclick:confirmPiyueWork` |
| 2 | 两层确认弹窗 | 两层都被点掉 |
| 3 | 无弹窗 | 不报错，直接进入核验 |
| 4 | 弹窗存在但点不到 | 明确返回 `no-visible-confirm`（不静默成功） |
| 5 | 首次提交未生效 | 自动重试一次并再次核验 |
| 6 | 失败 | 错误含 confirm/alert 文案与候选按钮 |
| 7 | 回归 | 全量 pytest 1859 passed；selfcheck:d188–d203 通过 |

## 4. 范围

允许：`engine/src/assist/xxt/marking.py`、`engine/src/assist/xxt/grade_upload.py`、
`app/package.json`、对应 tests、本文档与 README 索引。
不得改评分口径；不得读取真实学生数据。

## 5. 实施结果

- `marking.py`：`_JS_FIND_POPUP`、`_JS_CLICK_POPUP_CONFIRM`（含 `confirmPiyueWork` 与文案兜底）、
  `handle_confirmation_dialog()` 返回详情并支持多层、`submit()` 带
  `confirmPopup/dialogs/submitCandidates`；
- `grade_upload.py`：注入 `__assistDialogs` + 接管 `window.confirm`；提交未生效重试一次；
  失败错误拼接弹窗/对话框/候选按钮证据；
- 测试：`engine/tests/test_d203_submit_confirmation.py`（7 项）+ `selfcheck:d203`。

## 6. 若仍失败，请把这段发我

`classes/<班级>/grading/<packId>/upload/<workId>.json` 里的 `result` 字段，
特别是 `submitAttempts` / `afterSubmit` / `submitCandidates`，
以及 `receipts/grade-upload-submitted*.png` 截图。
据此可判断是“确认按钮又变了”“平台校验拦截（如分数超范围）”，还是“分数没写进输入框”。
