# 转录规程

## 输入
- 每名学生一条 item：`{id, question, images:[该生所有页]}`；
- **同一学生多页放在同一次转录请求**（不要逐页独立再合并）；
- **不同学生绝不共享图片**。

## 输出（必须落文件）
`<grading>/transcripts/<id>.json`：
```json
{"student": "<id>", "markdown": "转录正文（LaTeX 行内 $...$）", "quality": {"handwriting": "...", "clarity": "...", "organization": "..."}, "page_map": {"p1": "..."}}
```
- 严格保留学生原写内容，**不要纠正**（纠正是批阅阶段的事）；
- 看不清标 `[无法辨认]`，手绘图写 `[此处有手绘图表：...]`。

## 用哪条路径
- 有 `type=command`/API key：`assist grade --task ... --xxt-class ...`（程序逐生独立+并发）；
- 只有 subagent：每生一个 subagent，输入只给该生图片；
- 都没有：`assist grade-plan ...` 生成清单，自己做，再 `collect`。

## 禁止
- 在同一会话/同一次请求里转录第二名学生的图；
- 把上一名学生的 markdown 拼进下一条请求。
