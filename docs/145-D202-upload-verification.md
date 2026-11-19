# D202：上传显示“成功”但学习通实际未批阅、未打分

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/144-D201-upload-draft-scope.md`、`docs/143-D200-report-image-upload-default.md`
>
> 隐私：测试只用合成数据（学生甲/学生乙/韩冰月为现场姓名，仅用于复述现象，不含真实作答内容）。

---

## 0. 现场

逐生上传后界面显示「✅ 已上传」，重新读取平台状态也显示已上传，
但学习通上该学生**仍是未批阅，也没有分数**。

## 1. 根因：“点了按钮”被当成“写成功了”

`upload_grade()` 的提交段原实现：

```python
result["submitResult"] = submit(page)
result["ok"] = bool(result["submitResult"].get("ok"))   # ← 只表示点到了 markAction(1)
```

两个缺口：

1. **提交后没有任何核验**：不重新读列表，不知道平台是否真的变成「已批阅」、分数是否写入；
2. **提交前没有校验分数是否真的进了输入框**：学习通的分数输入框需要 `blur`（失焦）
   才会被框架确认；只派发 `change/input` 时值可能被回滚 → 点提交等于空提交，
   平台自然停在「待批阅」。

## 2. 修复

### R1. 提交后核验（决定成败）

新增 `verify_submission()`：提交后**重新打开批阅列表**，按 `workAnswerId`（回落姓名）
定位该生，检查：

- 状态包含「已批阅」；
- 若指定了期望分数，列表回读分数需一致（容差 0.005）。

```python
clicked = bool(result["submitResult"].get("ok"))
ver = verify_submission(page, course_id, class_id, wid,
                        student=..., work_answer_id=wa, expect_score=total_score)
result["ok"] = bool(clicked and ver.get("ok"))
```

失败时给出可读原因：

- `提交后平台状态仍为「待批阅」（未变成已批阅）`
- `提交后平台分数为「空」，与期望 90 不一致`
- `提交后未在批阅列表找到学生：…`

并标记 `status = "unverified"`（点了按钮但没保存）+ `hint` 提示人工确认。

### R2. 提交前分数校验

`read_back(page)` 之后先比对期望分数；没写进去就**中止提交**：

```json
{"ok": false, "status": "score-not-filled",
 "error": "分数未成功写入页面（页面读到「空」，期望 90），已中止提交"}
```

避免“空提交”污染平台状态。

### R3. 分数填写更可靠

`marking.fill_scores()`：写值后依次触发 `input` → `change` → `keyup(Enter)` → `blur()`。
学习通需要失焦才确认分数，这是“填了但没生效”的直接原因之一。

### R4. 列表回读分数

`JS_REVIEW` 增加 `score` 字段（`input.scoreInput` 或「得分：N」文本），
`_students_from_mark_list()` 保留该字段供核验使用。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 提交后状态仍「待批阅」 | `ok=false`，错误明确写“仍为待批阅” |
| 2 | 提交后分数与期望不符 | `ok=false`，列出平台值与期望值 |
| 3 | 提交后成功 | `ok=true`，`afterSubmit.status/score` 记录证据 |
| 4 | 分数没写进页面 | **中止提交**，不误报成功 |
| 5 | 列表读不到该生 | `ok=false`，提示核对名单 |
| 6 | 核验读取异常 | `ok=false`，不吞错 |
| 7 | 回归 | 全量 pytest 1852 passed；selfcheck:d188–d202 通过 |

## 4. 范围

允许：`engine/src/assist/xxt/grade_upload.py`、`engine/src/assist/xxt/marking.py`、
`engine/src/assist/xxt/extractor.py`、`app/src/components/AiGradingPanel.vue`、
`app/package.json`、对应 tests、本文档与 README 索引。
不得改评分口径；不得读取真实学生数据。

## 5. 实施结果

- `grade_upload.py`：`verify_submission()`、提交前分数校验、`ok` 与核验绑定、
  `unverified` 状态与 hint、列表行 `score` 字段；
- `marking.py`：填分触发 `blur`/回车；
- `extractor.py`：`JS_REVIEW` 回读分数；
- 前端：成功文案改为「✅ 已上传（已核验平台状态）」，失败展示引擎可读原因；
- 测试：`engine/tests/test_d202_upload_verification.py`（10 项）+ `selfcheck:d202`。

## 6. 现场排查建议

若修复后仍失败，`result.afterSubmit` 与截图会给出证据：

```
classes/<班级>/grading/<packId>/upload/<workId>.json     ← 上传清单（含 decision/platformBefore）
receipts/grade-upload-*.json                              ← 每次上传的 before/after/afterSubmit
receipts/grade-upload-submitted.png                       ← 提交后截图
```
