# D80 计划：LLM 两步批阅 + 上传协作测试（白名单模式）

> 日期：2026-10-14
> 状态：计划稿；晚间与用户协作执行。
> 测试范围：**仅** `大学物理知识点拾遗（by pc） / 默认班级`（白名单）。
> 关联：`docs/30-D78...`、`docs/31-D79...`、`docs/16-xuexitong-integration.md`。

## 1. 目标

用户提供学生作答图片目录后，engine 完成：

1. **转录**（图片 → 转录 JSON）；
2. **评阅**（转录 + 作业题 JSON → 评分/评语 JSON）；
3. **生成报告**；
4. （后续实现）**上传**到学习通：评语 + 图片 + 自动打分。

所有写操作（上传/打分）沿用同一份
`workspace/settings.local.json → xxt.write_allowlist` 白名单。

## 2. 协作分工

- 用户：
  - 在学习通侧上传/准备作答图片；
  - 提供作业题 JSON（taskpad）与图片目录；
  - 晚间一起看平台结果。
- engine/我方：
  - 跑 `assist grade` 两步；
  - 检查转录/评阅质量；
  - 实现并执行上传步骤（若当晚可完成）；
  - 仅对白名单班级操作。

## 3. 执行顺序（建议）

### 3.1 准备

1. 确认 engine workspace 已配置 LLM key（`settings.local.json` 的 `llm` 段）；
2. 确认 `xxt.write_allowlist` 已包含目标班；
3. 准备：
   - `task.json`（作业纸 JSON，含题目 content/solution）；
   - `images/`（学生作业图片，文件名=学生名或学号-题号）。

### 3.2 两步批阅

现状：`assist grade` 已支持 transcribe / evaluate / report。

```bash
assist grade --task task.json --images images/
```

- 模型配置来自 task JSON 的 `grade.models.transcription / evaluation`；
- 产物结构：

```text
classes/<class>/grading/<task>/
  transcripts/
  evaluations/
  reports/
  journal.jsonl
```

### 3.3 检查

- 转录是否正确；
- 评阅是否按题目 solution/评分口径；
- 报告版式是否可读；
- 记录问题（选择器/提示词/评分口径）。

### 3.4 上传（待实现）

计划新增：

```text
assist xxt grade-upload --task <task.json> --run <run_id> --class <classId> --dry-run|--send
```

- 从 evaluations/reports 读取分数与评语；
- 上传评语文本、评语图片（如 LaTeX/PNG）、自动打分；
- 写操作前校验白名单；
- 默认 dry-run，二次确认，receipt 落盘。

## 4. 白名单边界

- 上传/打分/发布类写操作：必须校验 `xxt.write_allowlist`；
- 只读下载/预览：不限制；
- 默认白名单为空，用户按课程折叠勾选；
- 当前测试班：用户手动勾选后可用。

## 5. 验收

- 同班同作业不重复发布；
- 上传只落在白名单班级；
- 评语 + 分数与本地报告一致；
- journal/receipt 可回查；
- 其他班级零写入。
