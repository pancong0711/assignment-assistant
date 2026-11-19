# D200：上传“批阅报告图 + 分数”即可，不因批语文本为空被判阻塞

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/139-D196-upload-submitted-only-and-per-student.md`、
> `docs/136-D193-upload-gbk-unicode-and-report-versioning.md`
>
> 隐私：测试只用合成数据（学生甲/学生乙）。

---

## 0. 现场

上传前对照提示：

```text
将上传 8 名已提交且批语齐全的学生；48 名已提交但批语为空，请先批阅/AI 批阅；
1 名已提交但没有本地草稿
批语为空：…（48 人名单）
```

但教师确认：**全部学生都有 AI 批语与批阅报告（含人工修改）**。

## 1. 结论：教师的判断正确

教师的工作流是：**上传“批阅报告图片” + 打分**。
报告图里已经是排版好的批语（人工修改也在里面），
**不需要再把原始批语文本重复写进平台批语框**。

## 2. 根因（两个）

### A. 就绪判定只看批语文本，完全忽略报告图

`grade_plan.upload_readiness()` 原实现：

```python
comment = text_of(p.get("comment") or "")
elif not comment:
    state = NO_COMMENT   # ← 有报告图也照样判“批语为空”
```

报告图（`images`）与分数（`score`）都没参与判断 → 48 人被误判。

### B. 草稿批语可能为空，而 AI 批语在 evaluations 里

草稿的 `ai.comment` 在某些落盘路径（只写转写/报告图，或旧版本缺字段）会为空，
而 AI 批语实际在 `grading/<taskId>/evaluations/<学生>.json` 的 `feedback_md` 中。
预览只读草稿 → 看到“空批语”。

## 3. 修复

### R1. 就绪判定 = 报告图 / 批语 / 分数 任一

| 状态 | 条件 | 提示 |
|---|---|---|
| `ready` | 有报告图 **或** 批语 **或** 分数 | “可上传（报告图 + 分数；批语文本不重复上传）” |
| `no-report` | 已提交但三者都没有 | “请先『📄 一键生成批阅报告』” |
| `no-draft` | 已提交但无本地草稿 | “请先『转写+评阅』” |
| `not-submitted` | 平台未提交 | 不上传 |

新增字段：`hasImage / hasComment / hasScore / imageCount / uploadMode`。
“批语文本为空但有报告图”单独归入 `emptyComment`（只提示，不阻断）。

### R2. 默认“只上传报告图 + 分数”

- CLI：`assist xxt grade-upload` 新增 `--report-only/--with-comment-text`（默认 `--report-only`）；
- 有报告图时**不写批语文本**，只上传图片 + 分数；
- `POST /xxt/grade/upload {reportOnly}` 透传；前端对照表新增勾选项
  **“☑ 只上传报告图 + 分数，不再重复上传原始批语文本”**（默认勾选）。

### R3. evaluations 兜底

新增 `enrich_payloads_from_evaluations()`：草稿缺批语/分数时，
用 `evaluations/<学生>.json` 的 `feedback_md` / `total_score` **补齐空字段**
（不覆盖已有内容），预览与 `--from-drafts` 上传都走这道兜底。

### R4. 顺带修复：上传清单从未写成功

`cli.py` 里 `write_upload_manifest(ws, _resolve_class_dir(), _task_id(), ...)` 调用的
两个函数**从来不存在**，`NameError` 被 `except` 吞掉 → 上传清单一直没落盘。
改为真实的 `_upload_scope()`（classmap + discover_draft_scopes 解析）。

## 4. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 有报告图、无批语文本、有分数 | `ready`，`uploadMode=report-only`，不再提示“批语为空” |
| 2 | 只有批语文本 | `ready`，`uploadMode=text` |
| 3 | 只有分数 | `ready` |
| 4 | 三者都没有 | `no-report`，提示先生成报告 |
| 5 | 草稿无批语但 evaluations 有 | 预览自动补齐，显示可上传 |
| 6 | `reportOnly=true` | 平台只收到报告图 + 分数，无批语文本 |
| 7 | 上传清单 | 正确落盘（旧实现 NameError 被吞） |
| 8 | 回归 | 全量 pytest 1836 passed；selfcheck:d188–d200 通过 |

## 5. 范围

允许：`engine/src/assist/xxt/grade_plan.py`、`engine/src/assist/xxt/grade_upload.py`、
`engine/src/assist/xxt/cli.py`、`engine/src/assist/serve.py`、
`app/src/lib/engineClient.ts`、`app/src/components/AiGradingPanel.vue`、
`app/package.json`、对应 tests、本文档与 README 索引。
不得改评分口径；不得读取真实学生数据。

## 6. 实施结果

- `grade_plan`：`NO_REPORT` 状态、`hasImage/hasScore/uploadMode`、新 hint 口径；
- `grade_upload`：`enrich_payloads_from_evaluations()`；
- `cli`：`--report-only`（默认）、evaluations 兜底、修复上传清单 helper；
- `serve`：预览走兜底、上传透传 `reportOnly`；
- 前端：报告图/批语/分数三态显示、`☑ 只上传报告图+分数`（默认勾选）、
  `no-report` 状态提示与按钮禁用；
- 测试：`engine/tests/test_d200_report_image_upload.py`（11 项）+ `selfcheck:d200`；
  同步更新 D196 两个测试到新口径（无内容才拦，有分数/报告图即放行）。
