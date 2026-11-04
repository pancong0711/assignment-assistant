# D156–D160 需求单：批阅正确性与质量（逐生补批落错人 / 结果不变 / 批阅太简略 / 转写无 schema）

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/78-D130`（分型评阅）、`docs/95-D148`（逐生补批）、`docs/12`

## 0. 教师反馈（三个现象）

1. 点「完整批阅」给张紫涵，日志却出现 **「张松」没有可用的作业纸题目**；
2. **两次完整批阅分数与批语完全一样**（同一模型同输入本应略有差异）；
3. **批阅结果太简略**，几乎没有有价值的信息 —— 批阅提示词是什么？

## 1. 根因

### 1.1 落错人（D156）

`--students` **只过滤了转写，没过滤评阅**：

```python
# 转写：用 plan.students（已按 students 过滤）✅
# 评阅（flow.py）：for tf in ctx["transcripts_dir"].glob("[!_]*.json")  ← 扫全部 ❌
```

张松之前被转写过（文件还在），于是每次评阅都把他扫进去。
**放大器**：前端 `runOne` 还传了 `tags: [该生 tag]`，让 plan 装配把该 tag 下所有人都装进来。

### 1.2 结果不变（D157）

不是"默认只做一次"，而是**已有的被跳过**：
- 转写/评阅都是覆盖写，但**没有跳过逻辑**；
- 评阅在拿不到 items 时会 `continue`，**不覆盖旧文件** → 看到的是上次的结果；
- 加上 LLM 本身非确定性，本应不同，但前提是**真的调用了**。

### 1.3 批阅太简略（D158）

`ANALYSIS_PROMPT` 是旧项目迁移的**简化版**（约 40 行），只说"逐题分析、输出 JSON"，
没有"什么是好的评阅"的规范。模型于是写"思路清晰/有计算错误"这类空话。

### 1.4 转写没有结构化约束（D160）

| | response_format |
|---|---|
| 评阅 | ✅ json_schema（带降级） |
| **转写** | ❌ **完全没有**，纯靠提示词 |

## 2. 修复

| # | 内容 |
|---|---|
| D156 | 评阅按 `only_students` 过滤；**前端去掉多余的 `tags`**（`students` 已精确到人） |
| D157 | 新增 `--force-rerun`；转写/评阅在**未强制时跳过已有**并记日志；**逐生补批固定 `force: true`** |
| D158 | 重写 `ANALYSIS_PROMPT`：evidence 逐字引用 / why 写物理依据 / 必须给 `correct_points` / guidance 苏格拉底式 / 按题型给评阅视角 / 输出前质量自查；`max_tokens` 8192 → **12288**；schema 里 `deduct` 改为**可选**（分数由系统算） |
| D159 | `thin_questions()`：某题既无 `correct_points` 也无 `errors` 且 note 过短 → 标记"评阅信息量不足"，报告里提示教师复核 |
| D160 | 转写加 `TRANSCRIPTION_SCHEMA`；`chat_with_images(response_format=)`；`validate_transcription()` 结构校验；**三档降级**（json_schema → json_object → 纯提示词）+ 校验失败重试 |

## 3. 验收

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 评阅只处理指定学生（不再出现张松） | ✅ | `test_evaluate_skips_students_outside_list` |
| 2 | 未强制时跳过已有；强制时重跑 | ✅ | `test_evaluate_skips_existing_without_force` / `test_evaluate_reruns_with_force` |
| 3 | 批阅提示词要求 evidence/why/correct_points | ✅ | `test_analysis_prompt_requires_evidence_and_why` |
| 4 | `deduct` 不再是必填 | ✅ | `test_deduct_no_longer_required_in_schema` |
| 5 | `max_tokens` ≥ 12288 | ✅ | `test_analyze_default_max_tokens_raised` |
| 6 | 信息量不足可检测 | ✅ | `test_thin_questions_detects_empty_review` |
| 7 | 转写有 schema + 校验 + 兼容旧格式 | ✅ | `test_validate_transcription_*`（4 项） |
| 8 | pytest / build / selfcheck / 脱敏 | ✅ | **1256 passed** · 0 error · 33/33 |

## 4. 已知限制

- 转写 schema 的**严格模式**要求 provider 支持 `json_schema`；不支持时降级为
  `json_object`，再不行回退纯提示词（此时只靠 `parse_llm_json` 兜底）；
- `thin_questions` 的阈值（note < 12 字）是经验值，可通过模板/参数调整；
- 逐生补批固定 `force: true`：**每次都会重新花额度**（这是教师明确要求的"强制"）。
