# D196：只上传已提交学生的批阅报告 + 批语缺失提醒 + 逐生上传

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/136-D193-upload-gbk-unicode-and-report-versioning.md`、
> `docs/138-D195-report-scope-and-duplicate-students.md`
>
> 隐私：测试只用合成数据。

---

## 0. 教师诉求

1. **只上传已提交学生**的批阅报告；未提交的学生不需要上传；
2. 已提交但**批语/报告没生成**的，要提醒去批阅 / AI 批阅；
3. 考虑**逐生上传**——测试更可控，单人也更好定位问题。

## 1. 现状核查（结论：诉求成立）

- 学习通批阅清单 `JS_REVIEW` **只抓有作答的行**（行内 `a.cz_py` → `workAnswerId`）；
  “未交/未提交”的学生在另一个「未交列表」里（`_unsubmitted_rows`，无 `cz_py`）；
- 但上传链路此前**没有显式按“已提交”过滤**：只要本地有草稿就会尝试上传，
  未提交者最终靠“没有 workAnswerId”偶然被挡，提示也不清楚；
- 批语为空时，旧代码会继续走到 `decide()`：
  - 若平台未批阅 → 判定 `new` → **可能把空批语写进平台**；
  - 若平台已批阅 → 判定 `conflict`，提示“内容不同”，而不是“你还没批阅”。

## 2. 修复

### R1. 上传范围 = 已提交学生（引擎强制，不只是提示）

`engine/src/assist/xxt/grade_plan.py` 新增：

- `is_submitted(row)`：有 `workAnswerId`/`review_path` 或状态含“已批阅/待批阅/已交/补交”才算已提交；
  状态含“未交/未提交”一律否；
- `upload_readiness(platform_rows, payloads)` 四态：
  | 状态 | 含义 | 动作 |
  |---|---|---|
  | `ready` | 已提交 + 批语齐全 | 可上传 |
  | `no-comment` | 已提交但批语为空 | **提醒先批阅 / AI 批阅** |
  | `no-draft` | 已提交但无本地草稿 | 提醒先批阅 |
  | `not-submitted` | 未提交（或平台名单无此人） | **不上传** |

`engine/src/assist/xxt/grade_upload.py` 在 `upload_grade()` 中**硬拦截**：

- 平台状态含“未交/未提交” → 返回 `not-submitted`，不写任何内容；
- 批语/分数/图片全为空 → 返回 `no-comment` + `needsReview: true`，
  提示“该学生批语为空，请先批阅（AI 批阅或人工批语）后再上传”，
  **不再把空批语写进平台**。

### R2. 对照表显示“提交/就绪”

`POST /xxt/grade/upload-preview` 返回新增 `readiness`，前端对照表增加一列：

- `已提交·可传` / `已提交·批语空` / `已提交·无草稿` / `未提交`；
- 顶部黄框提示：`将上传 N 名已提交且批语齐全的学生；M 名已提交但批语为空…；K 名未提交（不上传）`，
  并列出批语为空的学生名单，指引「转写+评阅」或人工批语；
- 仅本地核对（`platform=false`）也能提示 `needComment` / `noReport`。

### R3. 逐生上传

对照表每行新增「上传」按钮：

- 复用现有 `POST /xxt/grade/upload {student}`（引擎本就支持单人）；
- 单人独立 job + 独立结果（`✅ 已上传` / `❌ 原因`），**一人失败不影响其他人**；
- `not-submitted` / `no-comment` / `no-draft` 行的按钮禁用并给出原因 tooltip；
- 批量「按对照表上传」也改为只取 `readyState === 'ready'`（未提交/批语空自动排除）。

## 3. 为什么逐生上传更合理

| 维度 | 批量上传 | 逐生上传 |
|---|---|---|
| 故障定位 | 一个失败，需翻长日志找是谁 | 按钮旁直接显示该生命令结果 |
| 重试成本 | 重跑整批 | 只重试那一人 |
| 误覆盖风险 | 批量 `force` 影响全班 | 只在确认那一人后覆盖 |
| 限流/超时 | 一次长任务 | 每生独立任务，互不拖累 |
| 教师心理负担 | “要么全传要么不敢传” | 可先传 1 人验证，再传其余 |

代价是逐生会多次启动浏览器（较慢），因此**保留批量**作为默认，逐生作为“验证/补传”手段：
建议流程「先逐生传 1 人确认效果 → 再按对照表批量上传其余」。

## 4. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 学生未提交 | 对照表标 `未提交`，按钮禁用；批量上传不含该生 |
| 2 | 已提交但批语为空 | 标 `已提交·批语空` + 顶部提醒“请先批阅”；引擎返回 `no-comment` |
| 3 | 已提交、批语齐全 | 标 `已提交·可传`，可批量或逐生上传 |
| 4 | 逐生上传某人失败 | 只有该行显示失败原因，其他行不受影响 |
| 5 | 本地有草稿但平台名单没有 | 视为未提交，不上传 |
| 6 | 仅本地核对 | 也能提示批语为空/未生成报告 |
| 7 | 回归 | 全量 pytest 1801 passed；selfcheck:d188–d196 通过 |

## 5. 范围

允许：`engine/src/assist/xxt/grade_plan.py`、`engine/src/assist/xxt/grade_upload.py`、
`engine/src/assist/xxt/upload_preview.py`、`app/src/lib/engineClient.ts`、
`app/src/components/AiGradingPanel.vue`、`app/package.json`、对应 tests、本文档与 README 索引。
不得改评分口径；不得读取真实学生数据。
