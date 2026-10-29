# D126 缺陷修复：逐生审核看不到原图/转写 + 分步文案 + 报告拆「转写 / 批阅」

> 日期：2026-10-29
> 状态：**已执行完成**
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
