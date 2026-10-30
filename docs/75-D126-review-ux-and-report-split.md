# D126 缺陷修复：逐生审核看不到原图/转写 + 分步文案 + 报告拆「转写 / 批阅」

> 日期：2026-10-29
> 状态：**已执行完成**（2026-10-30 补漏，见 §6）
> 关联：`docs/74-D125`（分阶段 endpoint / 分步批阅）、`docs/32-D80`（批阅）

## 1. 现象（用户反馈）

1. 点「① 仅转录」后，进度条仍显示 **「AI 批阅中」**；
2. 转录 / 批阅跑完后，**逐生审核里看不到该生的作答原图、转写、批阅内容**；
3. 报告结构与期望不符：希望分成**「转写」「批阅」两部分**（要上传学习通给学生看，
   便于对照"AI 如何识别我的作答"与"原图"的差异）。

## 2. 根因

| # | 问题 | 根因 |
|---|---|---|
| P1 | 文案写死「AI 批阅」 | `AiGradingPanel.vue` 里三处 `progress.value` 硬编码，未按 `steps` 区分 |
| P2 | 看不到**作答原图** | `StudentReviewModal` 的 `answerImages` 只读 `draft.images`，而草稿里没有该字段（只有 `reportImages`）；**作答原件文件名从未传到前端** |
| P3 | 看不到**AI 转写** | 转录产物在 `classes/<班级>/grading/<task>/transcripts/<学生>.json`，但 ①前端从未读取；②「仅转录」时**根本不写草稿**（草稿只在全部 steps 跑完后写） |
| P4 | 报告不分「转写/批阅」 | `build_report_md` 顺序为「评分 → 转写 → 评阅」，转写被夹在中间 |

## 3. 修复

### 3.1 P1 文案按步骤区分

`startAi()` 内按 `steps` 计算 `jobName`：

| steps | 文案 |
|---|---|
| `['transcribe']` | 「AI 转写中…」/「✅ AI 转写完成」 |
| `['evaluate']` | 「AI 评阅中…」/「✅ AI 评阅完成」 |
| `['transcribe','evaluate']` | 「✅ 转写 + 评阅完成（尚未生成报告…）」 |
| 缺省（完整） | 「AI 批阅中…」/「✅ AI 批阅完成」 |

### 3.2 P2 作答原图接通

- **引擎**：`GET /xxt/preview/students/<classId>/<workId>` 现在会把
  `read_review_students()` 拿到的**作答原件文件名**合并进 `students[].images`
  （`Path(p).name`，与 `/xxt/review/file/...` 端点同口径）；
- **前端**：`loadStudents()` 保留 `images`；`students[]` 类型加 `images?: string[]`；
- **弹窗**：`answerImages` **优先 `students[].images`**，老数据回落 `draft.images`；
  空态提示改为"该生没有已下载的作答图，请先下载"。

### 3.3 P3 AI 转写可见

- 新增 `drafts.save_transcripts_to_drafts()`：把 `transcripts/<学生>.json` 的
  `markdown` 写入草稿 `ai.transcript`（附 `ai.transcriptModel`），
  **只填空缺字段，不影响已有分数/批语**；
- `flow.run_task` 在 `transcribe` 步骤完成后即调用它 →
  **「仅转录」也能在逐生审核中看到转写**；
- 弹窗新增「AI 转写」区（默认展开，可收起），与左侧原图并列便于对照。

### 3.4 P4 报告结构

```
# 作业批阅报告
**学生 / 转录模型 | 评阅模型 / 批阅时间**

## 一、AI 转写（你写的原文）
> 下面是 AI 从你的作答图片中识别出的文字。若与你的原图有出入，
> 说明是识别偏差，不影响对思路的判断。
<转录 markdown>

## 二、AI 批阅
**总分：xx / 100**
**扣分明细**
逐题：✅ 做对 / ❌ 问题 + **为什么** + **你的原文** + **想一想**（启发式提问）
```

批语本身已含「错误在哪（为什么/你的原文）」与「启发式提问（想一想）」，无需改动评阅 prompt。

### 3.5 顺带修复

`report.md_to_html()` 引用了**从未定义**的 `A4_CSS` / `MATHJAX_CDN`（早期遗留，一调用就
`NameError`）。改为复用 `report_html()` 同一套 `REPORT_CSS` + `_katex_head()`。

## 4. 验收

| 项 | 结果 |
|---|---|
| 「仅转录」文案 | 显示「AI 转写中/完成」✅ |
| 作答原图 | `students[].images` 文件名 → `/xxt/review/file/...` 加载 ✅ |
| AI 转写 | 仅转录也写 `ai.transcript`，弹窗可见 ✅ |
| 写转写不清空已有分数/批语 | ✅（有回归用例） |
| 报告 | 「一、AI 转写」在前、「二、AI 批阅」在后，含启发式提问 ✅ |
| `md_to_html` | 修复 NameError，可正常输出 HTML（含 KaTeX）✅ |
| engine pytest | **724 passed**（新增 `test_d126_review_modal_and_report.py` 6 例） |
| app `vue-tsc` / `build` | 0 error |
| app `npm run selfcheck` | **34 项全绿**（新增 `selfcheck-d126-review-ux.mjs`） |

## 6. 补漏（2026-10-30 · 复审 D126 同批工作）

> 背景：D126 实施过程中发生过 context window exceed，导致同批部分收尾未完成。
> 本次逐条核对 D126 需求单与实际代码，确认 §3.1–§3.5 **均已落地**，但发现 **P3 只修了一半**。

### 6.1 P3 的两处缺口（已修）

| # | 缺口 | 后果 |
|---|---|---|
| G1 | `save_transcripts_to_drafts` 写在 step 循环**之后** | `_run_transcribe` 在"部分失败且未加 `--allow-partial`"时直接 `raise`（D125 定的默认中止），**永远走不到写草稿** → 已成功学生的转写全部丢失。而"仅转录"正是最需要看转写的场景，"个别学生限流/读图失败"又是最常见情形。 |
| G2 | 写草稿的 key 依赖 `load_plan()` 从磁盘读 | `run_task(plan=...)` 的 plan 不一定落盘 → `wa_by_name` 为空 → 退化成**用姓名当 key**；前端 `drafts[students[].key]` 按 `workAnswerId` 取 → 写了草稿但逐生审核**依旧空白**（静默失败）。 |

修复：

- 抽出 `flow._persist_transcripts()`；在 transcribe 分支用 **`try/finally`** 调用——
  无论成功、部分失败中止还是 0 名学生有图，已产生的转写都会落草稿；
  循环后的调用保留为幂等兜底（覆盖"只重跑转录"等不走该分支的路径）。
- `save_transcripts_to_drafts(..., plan=)` 新增参数，由调用方**直接传入 plan**；
  仅在未传时才回落 `load_plan()`。
- PWA：`allowPartial` 此前在 `engineClient`/serve/CLI 三层都已支持却**没有任何界面入口**，
  等于形同虚设。现加「有学生转录失败时仍继续（默认中止）」勾选框，默认仍保持 D125 的中止语义。

### 6.2 顺带发现（未改，已登记）

- `build_report_md` 页脚、`evaluate.py`/`transcribe.py` 产物 `version` 字段仍写着
  `assist-engine 0.1.0`（实际 `__version__ = 0.4.0`）。属历史元数据，改动会影响
  既有产物版本比对语义，**不在本轮范围**，记入 `docs/12-backlog.md`。

### 6.3 验证（补漏后）

| 项 | 结果 |
|---|---|
| 新增回归 `test_partial_failure_still_persists_successful_transcripts` | 修复前**复现失败**（drafts = `{}`），修复后通过 ✅ |
| 新增回归 `test_md_to_html_no_nameerror_and_has_katex` | 通过 ✅ |
| engine pytest | **726 passed** |
| app `vue-tsc` / `build` | 0 error |
| app `npm run selfcheck` | 34 项全绿 |

## 7. 补漏二（2026-10-30 用户现场反馈：已批阅学生看不到转写/批语）

> 现象：AI 辅助批阅 → 逐生审核里**能看到作答原图，但 AI 转写与 AI 批语都是空的**；
> 且学生在列表里显示为已批阅（AI 列有 ✓）。

### 7.1 根因：`read_drafts` 不做归一化（H1）

| 层 | 事实 |
|---|---|
| D85 时代的旧草稿 | 磁盘上是**单套**结构 `{score, comment, comment_text, images}` |
| 新结构（D92-R2 起） | 双套 `{ai:{...}, human:{...}, humanMode, revision}` |
| `normalize_draft()` | 负责把单套转成双套 —— 但只有**写路径**（`save_draft_sets`）和 `grading/drafts.py` 调用它 |
| `grade_store.read_drafts()` | **直接回原始 JSON**，而 serve 的 `/xxt/grade/drafts` 正是用它 |

于是前端 `draft.ai.comment` / `draft.ai.transcript` 取到的都是 `undefined` →
弹窗显示「无 AI 批语 / 暂无转写」。**列表页却显示正常**，因为它有兜底：

```vue
{{ drafts[s.key]?.ai ? (drafts[s.key].ai.score ?? '✓') : (drafts[s.key]?.score ?? '—') }}
```

这就是"看起来已批阅、点进去却什么都没有"的直接原因。

### 7.2 修复

| # | 改动 | 说明 |
|---|---|---|
| F1 | 新增 `grade_store.read_drafts_normalized()` | 逐条 `normalize_draft`；**`read_drafts()` 契约保持不变**（既有 3 个调用方与测试不受影响） |
| F2 | serve `/xxt/grade/drafts` 改用 `read_drafts_normalized` | 逐生审核拿到的永远是正确的双套结构 |
| F3 | `save_drafts_from_grading` 写入 `ai.transcript` / `transcriptModel` | 「生成报告 → 回读落草稿」这条路径此前只写 score/comment，逐生审核会只剩批语没有转写（合并写入，不覆盖已有值） |
| F4 | 弹窗空态文案区分「老数据无转写」与「确实没跑转录」 | 避免教师误判为故障 |

### 7.3 关于"历史已批阅学生"

D126 之前（含 D85/D86 的批阅）**从未保存过转写**，只有评阅产物。
所以对老数据，补文案之后仍会显示「暂无转写内容」——这**不是 bug**；
重跑一次「① 仅转录」即可补齐（F1/F2 修好后写入即可见）。

### 7.4 验证

| 项 | 结果 |
|---|---|
| 回归 `test_read_drafts_normalizes_legacy_single_set` | 旧单套 `{score, comment}` → `ai.comment` 有值 ✅ |
| 回归 `test_read_drafts_normalizes_new_two_set` | 双套 `ai.transcript` / `humanMode` 原样保留 ✅ |
| 回归 `test_save_drafts_from_grading_includes_transcript` | 落草稿带转写 ✅ |
| 既有 `test_xxt_grade_store` 3 例 | 保持通过（证明 `read_drafts` 契约未破坏）✅ |
| engine pytest | **729 passed** |
| app `vue-tsc` / build | 0 error |
| app selfcheck | 34 项全绿（d126 自检新增"读草稿归一化"断言）|

## 5. 后续（已记录，本轮不做）

### 5.1 教师总结报告（用户提出）

> 「应该准备一份总结报告给教师查看，主要是全部作业的易错知识点（指出易错点之间的关联），
> 这部分我们后面会和知识点共现+得分率图结合（另一个教学工具项目）。先记着，不用着急做。」

需求要点（待与"知识点共现 + 得分率图"项目合并时细化）：

- **面向教师**（学生报告已分离，见 §3.4）；
- 汇总**全班/全部作业**的易错知识点，并指出**易错点之间的关联**；
- 计划与「知识点共现矩阵 + 得分率图」结合展示；
- 数据来源：`evaluations/<学生>.json` 的 `questions[].errors[]`（含 `knowledge` /
  `description` / `evidence`）+ `per_question_scores`。

> 已在 `docs/12-backlog.md` 记一条待办，避免遗漏。
