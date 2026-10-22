# 全流程编排（两段式）

```
0. assist doctor --json          # 先探测能力，决定路径
1. 转录（只图 → markdown）        # transcribe.md
2. 批阅（markdown+题+答案 → 发现） # evaluate.md
3. 报告（人工在前 / AI 附件 / 修订标红） # assist grade-drafts / grade-render / render
4. 上传（默认 dry-run）           # assist xxt grade-upload --confirm-send 才真发
```

## 执行报告怎么看
- `<grading>/batch-report.json`：`total/ok/failed`、每条 `status/error/images/ms`；
- 失败项：修正输入后重跑该条（不要整批重来）；
- 主会话**只读报告**，正文留在文件里。

## 停止条件（必须报告给用户）
- 首选路径（command/API）失败 → 停止，不自动降级；
- 转录失败率过高（如 >20%）→ 停止并检查图片质量/模型；
- 批阅出现大量 `confidence=low` → 提示教师复核，不要直接上传分数。
