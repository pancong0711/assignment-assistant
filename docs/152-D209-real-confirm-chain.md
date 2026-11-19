# D209：真实学习通提交确认链（Continue/checkPass）——真机实测与修复

> 日期：2026-11-19
> 状态：**已完成（2026-11-19）**
> 关联：`docs/149-D206-real-platform-validation.md`、`docs/150-D207-completed-status.md`、
> `docs/151-D208-upload-code-review.md`
>
> 隐私：不记录学生姓名、批语正文、作答内容；测试图为合成图。

---

## 0. 本次测试对象

| 项 | 值 |
|---|---|
| 课程 | 大学物理知识点拾遗（by pc）`217801417` |
| 班级 | 新建班级2 `157567052` |
| 作业 | 「手动测试作业发布」`57107990` |
| 作答 | 1 份，初始状态 `To be reviewed`、分数 `0`、无批语、无图片 |

此前测试用的是另一份作业（「大学物理作业纸提交（测试）」），**这份确实没测过**。

## 1. 现象

点「上传」后：提交按钮点到了（`<a class="btnBlue fr fs14">提交</a>`），
但**确认弹窗 0 个**、平台状态与分数都不变。

## 2. 真机定位（读页面 JS 源码）

```js
function markAction(type) { setTimeout(function () { pigai(type); }, 500); }

function pigai(n) {
  if (window.itemScoreCheck) { window.itemScoreCheck = false; return; }   // ← 守卫
  ...
  if (score.length == 0) { toast("Please enter score"); return; }
  if (Number(score) > Number(fullScore)) { toast("The score cannot exceed the full score: " + fullScore); return; }
  ...
  showConfirmV1(markTip, "Continue", "Cancel", "checkPass()");            // ← 关键
}

function checkPass() {
  ...
  comfirmMark();      // 分数达标
}
function comfirmMark() {
  setRecordTarget(); setCompoundSubjectQuesScore(); ...
  $("#confirmPop2").fullFadeOut();
  formSubmit();       // ← 真正提交
}
```

真实确认层实测按钮：

```html
<a class="jb_btn jb_btn_92 fr fs14 confirmHref" onclick="checkPass()">保存并继续</a>
<a class="btnBlue btn_92_cancel fr fs14" onclick="hidePop()">Cancel</a>
```

**根因**：旧确认逻辑只匹配 `#popok` 与「确定/确认/继续」，
而真实按钮是 **`保存并继续` + `onclick=checkPass()`**（也不是 `#confirmPop2` 常见选择器），
于是从来没点中 → 提交被静默取消。

另外 `pigai()` 首行有 `window.itemScoreCheck` 守卫，残留为真会让提交直接 return。

## 3. 修复

### R1. 确认链（多轮）

新增 `click_confirm_chain()` + `_JS_CLICK_CONFIRM_STEP`：

- 按 **onclick 关键字**优先匹配：`checkPass | comfirmMark | formSubmit | confirmPiyueWork`（rank 100）；
- 其次文案精确匹配：`continue|confirm|ok|yes|确定|确认|继续|提交`（rank 80/70）；
- **排除** `cancel|取消|关闭|next|下一|下一位|下份`；
- 循环最多 5 轮（Continue → 可能再来一次「提交」），直到没有可点确认按钮。

### R2. 清 `itemScoreCheck` 守卫

提交前执行 `window.itemScoreCheck = false`，避免上一次交互残留导致静默失败。

### R3. 捕获平台 toast

`submit()` 现在采集 `[class*=toast], .layui-layer-msg` 等可见提示，
并写入错误信息（例如“分数不能超过满分”“Please enter score”），便于当场定位。

### R4. 弹层选择器补充 `#confirmPop2`

`_JS_FIND_POPUP` 增加 `#confirmPop2`（真实确认层 id）。

## 4. 真机实测结果

```
ok: true | status: submitted
submit: {text: "提交", tag: "A", cls: "btnBlue fr fs14"}
confirm steps: [
  {"how": "onclick:checkPass()", "text": "保存并继续"},
  {"how": "text:提交", "text": "提交"}
]
toasts: []
afterSubmit: {"ok": true, "status": "已完成", "score": "88", "expectScore": 88}
attempts: 1
```

提交后只读复查：

| 项 | 值 |
|---|---|
| 列表状态 | `Completed` |
| 列表分数 | `88` |
| 批阅页分数 | `88` |
| 批语长度 | 134 字符 |
| 批语图片 | 1 张（测试图确实上传成功） |

→ **图片上传 + 打分 + 提交 + 核验 全链路在真实平台成功。**

## 5. 测试

新增 `engine/tests/test_d209_real_confirm_chain.py`（4 项）：

- 必须点中 `onclick=checkPass()` 的「保存并继续」，再点「提交」，最终保存；
- 绝不点 `Cancel`；
- 核验识别 `Completed`；
- 源码契约（确认链 / itemScoreCheck / toast / confirmPop2）。

全量 pytest：`1900 passed`。

## 6. 已知边界

- 平台文案/结构仍可能再变；一旦变化，`toasts` + `submitCandidates` 会给出证据；
- 确认链最多 5 轮，若平台未来增加更多确认步骤需调整；
- 本次测试作业为「手动测试作业发布」，已留下测试批语与图片（教师可自行清除）。

## 7. 建议使用方式

1. 「🔍 上传前对照」→ 选中学生 → 先「演练」；
2. 演练通过 → 「上传」；
3. 若失败，优先看错误里的 **平台 toast**（通常是分数超满分/未填分）。 
