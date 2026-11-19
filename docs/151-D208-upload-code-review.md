# D208：上传/打分代码审核报告（4 个真实问题，含 2 个高危）

> 日期：2026-11-19
> 状态：**已完成（2026-11-19）**
> 关联：`docs/149-D206-real-platform-validation.md`、`docs/150-D207-completed-status.md`
>
> 隐私：测试与文档只用合成数据；真实平台仅做只读核验。

---

## 审核范围

| 文件 | 内容 |
|---|---|
| `engine/src/assist/xxt/grade_upload.py` | `upload_grade` / `verify_submission` / 学生匹配 / payload |
| `engine/src/assist/xxt/marking.py` | 填分 / 插图片 / 提交 / 确认弹窗 / 页面诊断 |
| `engine/src/assist/xxt/grade_plan.py` | 三态决策 / 上传就绪判定 |
| `engine/src/assist/xxt/cli.py` | `grade-upload` 命令 |
| `engine/src/assist/serve.py` | `POST /xxt/grade/upload` |
| `app/src/components/AiGradingPanel.vue` | 对照表 / 逐生上传 / 批量上传 |

---

## 1. 【高危】姓名子串兜底可能写到**另一个学生**

`find_student_row()` / `find_payload()` 原实现：精确不中就用**子串包含**兜底。

```python
if fuzzy is None and key and key in name:   # "王伟" in "王伟伟" → 命中
    fuzzy = r
```

复现：

```python
rows = [{"name": "王伟伟", "workAnswerId": "wa2"}]
find_student_row(rows, "王伟")   # → {'name': '王伟伟'}  ❌
```

**后果**：给「王伟」上传，批语/分数写到了「王伟伟」身上——错人且不可逆。

**修复**：
- 新增 `name_suffix_match(key, name)`：仅当 key 是 name 前缀且后面是**备注后缀**
  （`(`、`（`、空格、`-`、`_`、`#` 等）时才算模糊命中。
  - `张三` vs `张三(补交)` → ✅
  - `王伟` vs `王伟伟` → ❌
- 模糊命中仍要求**唯一**；
- `match_students()` 额外返回 `similar`（仅用于报错展示“有相似姓名，已中止”）。

---

## 2. 【高危】前端「按对照表上传」的确认名单被忽略

`AiGradingPanel.uploadAll(force, only)` 里：

```ts
const n = only?.length ?? Object.keys(drafts.value).length   // 只用于计数
...
await startXxtGradeUpload({ ... })                            // ← 没有传 only
```

**后果**：教师在对照表里只确认了 8 人，实际会把**全部草稿**都上传
（含未确认、未提交、批语缺失者），与“按对照表”语义不符，也可能覆盖不该动的学生。

**修复**（端到端打通）：
- CLI `grade-upload` 新增 `--students`（可重复）；
- serve 透传 `students[]` → `--students`；
- 前端 `uploadAll` 传 `students: only`；
- 若指定名单在草稿中不存在 → 明确报错退出（不静默全传）。

---

## 3. 【中】提交按钮兜底可能点到「提交并进入下一份」

`_JS_CLICK_SUBMIT_FALLBACK` 排序里有一条：

```js
if (/提交|保存|submit|save/i.test(text)) return 50;
```

「Submit and proceed to the next」也会命中 → 一旦主路径失败，兜底可能点它，
把批阅带**到下一个学生**。

**修复**：命中 `next|下一|下一位|下份` 的候选**直接跳过**并记
`skipped: 'next-student'`。

---

## 4. 【中】重试前不复验 → 可能重复提交

D205 的重试逻辑：核验失败 → 等 2s → 重新打开页面 → 重新提交。
但若核验失败只是**平台列表延迟**，就会重复提交。

**修复**：重试前先再核验一次（`afterSubmitRecheck`），已保存则不再提交。

---

## 5. 真实平台复验（只读）

| 检查 | 结果 |
|---|---|
| 精确姓名匹配 | ✅ 命中 |
| 前缀相似名（少一个字） | ✅ 被拒绝（防错人） |
| 提交后核验 | ✅ `ok=true`，`status=Completed（教师提交）`，`score=100`，`note=null` |

平台状态未改变（只读核验）。

---

## 6. 其余观察到但**未改**的点（说明）

| 项 | 说明 |
|---|---|
| `fill_scores` 每题分不足时用最后一题分补齐 | 既有行为；当前上传链路只传总分，暂不影响 |
| receipts / upload manifest 含批语正文 | 仅存本地 `.runtime/xxt/`，未上传、未入库；如需彻底脱敏可另开需求 |
| `handle_confirmation_dialog` 的 `stillOpen` 未直接置失败 | 由提交后核验兜底判定，失败会体现在 `error` |
| `_JS_CLICK_SUBMIT_FALLBACK` 会点 `div/span` | 已排除“下一份/next”，其余按文案排序 |

---

## 7. 测试

新增 `engine/tests/test_d208_upload_code_review_fixes.py`（13 项）：

- 相似名不得命中；精确仍命中；唯一备注后缀仍可用；歧义拒绝；候选诊断；
- workAnswerId 精确匹配；
- CLI/serve/前端确认名单端到端契约；
- 兜底不得点“next”；
- 重试前复验。

全量 pytest：`1896 passed`。

---

## 8. 结论

- 上传/打分主链路（插图、打分、提交、核验）在真实平台已验证可用；
- 本次审核修掉 **2 个高危**（错人上传、名单被忽略）与 **2 个中危**（误点下一份、重复提交）；
- 建议：**优先用逐生上传**做关键学生；批量上传前务必走「上传前对照」并核对名单。
