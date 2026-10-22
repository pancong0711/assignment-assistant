# 批阅规程

## 输入（只吃文字）
- 该生的**转录 markdown** + 该 tag 的**题目** + **参考答案**；
- **不允许再看图**（看图是转录阶段的事，避免两段重复且不一致）。

## 输出（结构化，必须落文件）
按 `EVALUATION_SCHEMA` 输出 JSON，关键字段：
- 每题：`reasoning`（思路评价）、`correct_points`（做对之处）、`errors[]`、`confidence`、`has_diagram`；
- 每条错误：`step/description/guidance/deduct` + **`evidence`（引用学生原文）** + **`why`（为什么判错）** + `confidence`；
- `guidance`：苏格拉底式提问，**不直接给答案**。

## 硬规则
- **不得自行算分**：分数由程序 `score_from_analysis` 计算；
- `evidence` 找不到原文 → 不报这条错，或标 `confidence=low`；
- `confidence=low` 的错误**只提示、不计分**（程序处理）；
- 不得编造学生未写的内容。

## 用哪条路径
同 `transcribe.md`：command/API → `assist grade`；无则 plan/collect。
