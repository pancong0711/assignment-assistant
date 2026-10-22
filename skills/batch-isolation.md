# 批量隔离与路径选择（必读）

## 为什么需要隔离

LLM API 无状态；**是否串味只取决于该次请求的 messages**。但 agent 是长会话全量重放，
同一会话里连续处理两名学生，后一名必然"看到"前一名。所以要保证：

- 每名学生的转录/批阅在**独立请求**中完成；
- 主会话**不累积**学生正文。

## 路径优先级（严格按顺序）

### 1. type=command / 本地 OpenAI 兼容端点（首选）
程序 `assist` 每次调用**起新子进程**或新 HTTP 请求 → 天然隔离、可复现、可审计。
配置见 `provider-setup.md`。验证：`assist doctor --json` 的 `capabilities.command.available=true`。

### 2. subagent（次选，仅当框架支持）
每名学生一个 subagent，输入**只含**该生图片路径 + 指令，输出写 `transcripts/<id>.json`。
前提：你的 agent 框架提供 subagent/新 run 原语。**没有就别假装有。**

### 3. plan/collect（兜底，非默认）
`assist grade-plan xxt-plan` 生成任务清单 → agent 自己做 → `assist grade-plan collect` 校验。
程序**不调模型**，会明确打印"正文由 agent 完成"。

### 4. 逐条在主会话亲自做 —— **禁止**
不可控、不可复现、token 累积、难审计。除非用户显式要求并理解风险。

## 首选路径失败怎么办

**不要自动降级**（会让质量悄悄变化）。停止，向用户报告，并提示可手动切到下一路径。

## 执行报告

无论哪条路径，都看 `<grading>/batch-report.json`：
- `total/ok/failed`；`items[].status`、`error`、`images`；
- 失败项可重跑；**主会话只读报告摘要，不读正文**。
