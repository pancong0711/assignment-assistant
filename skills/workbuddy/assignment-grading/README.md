# assignment-grading（WorkBuddy skill）

两段式 AI 批阅：**转录（读图）→ 评阅（只吃文字）**，由本机 `assist` CLI 执行。

## 为什么这样设计

- **隔离**：每名学生一次独立请求（同一学生多页放同一次），不会把上一位学生的内容带进下一位；
- **可复现**：流程在 CLI 里，不依赖会话记忆；
- **省 token**：正文只落文件，会话里只读执行报告。

## 使用前

1. 安装并初始化 assignment-assistant（`assist --version` 可用）；
2. 配置 LLM 能力：
   - 有 API key：`assist llm provider --action set --name <p> --base-url ... --api-key ...`，
     然后 `assist llm provider --action stage --stage transcription/evaluation --name <p>`；
   - 无 API key 但有 agent CLI：`assist llm provider --action set --name local --type command --cmd <CLI>`。

## 运行

```bash
assist doctor --json          # 先看 capabilities.recommendedPath 与 warnings
python run.py --task <任务包.json> --xxt-class <courseId>:<classId> --work <workId>
```

## 重要提醒

- 若 `doctor` 报 `transcription_command_no_images`，说明当前 CLI 不能读图：
  把**转录段**换成 `type=api` 的视觉模型，评阅段仍可用 command；
- 有学生失败时只重跑失败项，不要整批重来；
- 上传批阅默认 dry-run，真正提交需用户确认后加 `--confirm-send`。
