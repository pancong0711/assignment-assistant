---
name: assignment-grading
description: 大学物理作业的“两段式”AI 辅助批阅（先转录、只吃文字再评阅），通过本机 assist CLI 完成，避免同会话串上下文。当用户提到“批阅作业 / 转录学生作答 / AI 批改 / 生成批阅报告”时使用。
---

# 作业两段式批阅（转录 → 评阅）

## 适用场景
- 用户有一批学生手写作业照片，要转录 + 批阅 + 生成报告；
- 用户本机已安装 `assist`（assignment-assistant 引擎）。

## 第一原则：正文落文件，会话只读报告
- 转录/评阅的**正文**一律写入文件（`transcripts/`、`evaluations/`）；
- 你（agent）在主会话里**只读 `batch-report.json`** 摘要，不要把学生正文复述进对话——
  否则长会话会累积上下文、浪费 token 并把不同学生内容混在一起。

## 第 0 步：探测能力（必须先做）
```bash
assist doctor --json
```
读 `capabilities.recommendedPath`：
- `api` → 有 API key，直接进入第 1 步；
- `command` → 本机有 agent CLI 或已配置 `type=command`，同样进入第 1 步；
- `subagent-or-manual` → 没有可用 LLM 后端，**停止并告知用户**如何配置：
  `assist llm provider --action set --name local --type command --cmd <CLI>`，
  或为转录配置一个视觉模型 API。**不要逐条亲自读图**（不可控、不可复现、token 浪费）。

同时查看 `capabilities.warnings`：
- 若提示 `transcription_command_no_images`：说明转录段用的 CLI 不能读图 →
  告知用户把转录段换成 `type=api` 的视觉模型：
  `assist llm provider --action stage --stage transcription --name <api-provider>`；
  评阅段仍可用 command。

## 第 1 步：转录（读图 → Markdown）
```bash
assist grade --task <任务包.json> --xxt-class <courseId>:<classId> --work <workId>
```
程序会**按学生逐人独立请求**（同一学生多页放同一次），互不串上下文。

## 第 2 步：评阅（文字 + 题目 + 参考答案 → 结构化发现）
同上命令会继续执行评阅；或单独重跑：
```bash
assist grade --task <任务包.json> --rerun evaluate
```
评阅只吃文字，**不得再看图**；分数由程序计算，你不需要（也不应该）自行打分。

## 第 3 步：看执行报告
```bash
# 报告位置：<classDir>/grading/<taskId>/batch-report.json
```
字段：`total / ok / failed / items[].status,error,images,ms`。
- 有失败项 → 只重跑失败的学生，不要整批重来；
- 失败率过高（>20%）→ 停止并让用户检查图片质量/模型配置。

## 第 3.5 步：失败时先出自检报告（定位根因）
```bash
assist doctor --report          # 写 <workspace>/selfcheck-report.json
assist doctor --report --json   # 机器可读（含 issues[].code/layer/fix）
```
按 `layer` 定位：`environment`（依赖）→ `config`（provider/stage/key）→
`capability`（能力/图片）→ `data`（题库/班级）→ `artifact`（上次运行失败）。
把 `issues[].fix` 转述给用户，不要凭猜测修改。

## 第 4 步：生成报告 / 上传（默认 dry-run）
```bash
assist grade-drafts --task <任务包.json> --class <classId> --work <workId>
assist xxt grade-upload --course <courseId> --class <classId> --work <workId> --from-drafts
# 真正提交再加 --confirm-send（务必先向用户确认）
```

## 禁止
- ❌ 在同一会话里连续亲自读多个学生的图（会串上下文）；
- ❌ 把上一位学生的转录内容拼进下一位学生的请求；
- ❌ 自行编造分数或结论；一切以程序产物与 `batch-report.json` 为准。
