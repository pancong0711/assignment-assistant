# D217 需求单：疑似错卷「照常批阅 + 上传前默认拦截」

> 日期：2026-11-20
> 状态：**已完成（2026-11-20）**
> 关联：`docs/159-D216-align-implementation.md`、`docs/158-D215-align-before-grade-design.md`
>
> 隐私：测试只用合成数据。

---

## 0. 背景

D216 让程序在批阅前判断“学生做的是不是这份卷”，`mismatch` 时**仅警告、仍出分**。

问题：错分若被直接上传到平台，学生看到的是另一份卷的批语与分数——伤害发生在**上传**，
而不是“算出来”。

同时确认了一个事实：PWA 批阅完成只显示 `✅ 完成`，**不显示** `evaluate_skipped`。
因此“跳过批阅”会让漏批不可见，比错分更难发现。

## 1. 口径（教师 2026-11-20 拍板：方案 C）

| 阶段 | 行为 |
|---|---|
| 批阅 | **照常出分**（`align=mismatch` 标记，不阻断、不扣分） |
| 上传前对照 | 疑似错卷默认 **`align-mismatch`（暂不上传）**，不计入可上传名单 |
| 批量上传 | 默认**排除**；需教师显式勾选「包含疑似错卷」才传 |
| 逐生上传 | 允许，但**二次确认**“该生疑似错卷，仍要上传？” |
| 逐生审核 | 该生行内提示“改 tag 后点「转写+批阅」重批” |
| 引擎兜底 | `--from-drafts` 默认跳过 mismatch，需 `--allow-mismatch` 才传 |

> 不做：自动改 tag、自动换卷批阅、新增“一键改卷重批”按钮。

## 2. 需求

### R1. payload 携带对齐结论

`drafts_to_payloads()` 输出 `align`（来自草稿 `ai.align`），供上传就绪判定使用。

### R2. 新增就绪态 `align-mismatch`

`grade_plan.upload_readiness()` 判定优先级：

1. 未提交 → `not-submitted`
2. 无本地草稿 → `no-draft`
3. **疑似错卷（`align.verdict == mismatch`）→ `align-mismatch`**
4. 无报告图/批语/分数 → `no-report`
5. 其余 → `ready`

`align-mismatch` 的 `reason`：`题目疑似不匹配（建议 tag：X）；默认不上传`

### R3. 引擎兜底拦截

- CLI `grade-upload --from-drafts` 默认跳过 `align.verdict == mismatch` 的 payload，
  记入结果的 `skippedMismatch[]`；`--allow-mismatch` 可强制上传；
- serve 透传 `allowMismatch`。

### R4. 前端

- 对照表新增状态徽标「疑似错卷·暂不上传」；
- 顶部汇总显示 `疑似错卷 N 人（默认不上传）`；
- 新增勾选项「包含疑似错卷（N 人）」默认**不勾**；
- 「按对照表上传」默认排除；勾选后才包含；
- 逐生「上传」按钮对 mismatch 行二次确认；
- 逐生审核表该生行内提示“改 tag 后重批”。

### R5. 可见性

- 报告与 JSON 已由 D216 提供 `align`；
- 本单补：上传对照表 + 逐生审核行内指引。

---

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 疑似错卷学生 | 对照表显示「疑似错卷·暂不上传」，不计入可上传 |
| 2 | 按对照表上传 | 默认不传该生 |
| 3 | 勾选「包含疑似错卷」 | 才传该生 |
| 4 | 逐生上传疑似错卷 | 二次确认后才传 |
| 5 | 引擎 `--from-drafts` | 默认跳过并列出 `skippedMismatch` |
| 6 | 逐生审核 | 行内提示“改 tag 后重批” |
| 7 | 回归 | 全量 pytest、selfcheck 通过 |

---

## 4. 范围

允许：`grading/grade_plan.py`、`grading/grade_upload.py`、`xxt/cli.py`、`serve.py`、
`app/src/components/AiGradingPanel.vue`、`app/src/lib/engineClient.ts`、
`app/src/lib/engineClient.ts`、对应 tests、本文档与 README 索引。

不得：自动改 tag、自动换卷、增加新按钮（可加勾选项）。


---

## 5. 实施结果

### 5.1 引擎

| 变更 | 位置 |
|---|---|
| payload 携带 `align` | `grade_upload.drafts_to_payloads()` |
| 新增就绪态 `align-mismatch`（优先于 no-report/ready） | `grade_plan.upload_readiness()` |
| readiness 返回 `alignMismatch[]` + 汇总计数 + hint | 同上 |
| `--allow-mismatch`（默认跳过疑似错卷） | `xxt/cli.py` |
| 被跳过的学生记入 `skippedMismatch[]`；若全部被跳过则报错退出 | 同上 |
| serve 透传 `allowMismatch` | `serve.py` |

### 5.2 前端

- 对照表「提交/就绪」列新增红色徽标 **「疑似错卷·暂不上传」**；
- 顶部汇总新增 `疑似错卷（默认不上传）N`；
- 新增勾选项 **「包含疑似错卷（N 人）」**（默认不勾）；
- 「按对照表上传」默认排除，勾选后才包含；
- 逐生「上传」对疑似错卷**二次确认**后才传；
- 逐生审核「🧭 题目匹配」列在该生行内提示 **“改 tag 后点「转写+批阅」重批”**。

### 5.3 测试

`engine/tests/test_d217_mismatch_upload_guard.py`（8 项）：
状态优先级（未提交 > 疑似错卷）、match/unknown 仍 ready、汇总计数、
CLI/serve/payload、前端勾选与二次确认契约。

全量 pytest：`1976 passed`；`selfcheck:d217` 通过；前端 build 通过。

## 6. 效果

| 场景 | 现在 |
|---|---|
| 疑似错卷学生 | 照常出分（可参考），但对照表标红、默认不进入上传名单 |
| 批量上传 | 默认跳过；勾选「包含疑似错卷」才传 |
| 逐生上传 | 二次确认后才传 |
| 引擎直连 CLI | 默认跳过，`--allow-mismatch` 才传 |
| 教师处置 | 逐生审核有行内指引，改 tag 后重批 |
