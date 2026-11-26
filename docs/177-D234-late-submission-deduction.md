# D234：补交状态校验与自动扣 5 分

> 日期：2026-11-26
> 状态：已完成
> 关联：D130（程序算分）、D149（AI 批阅成绩源）、D175（草稿版报告）

## 0. 教师诉求

学生作答情况里有一类“补交”。希望程序直接校验平台提交状态，补交扣 5 分，
并把“提交状态 + 补交扣分”整合进批阅报告；同时需要确认分数到底由 AI 给还是程序算。

## 1. 结论：分数由程序计算，不是 AI 给

现行评分链路是：

```
AI 输出 analysis JSON（逐题发现/证据/扣分建议）
        ↓
score_from_analysis()（Python 按题库 kind + grading-rules.json 算分）
        ↓
evaluations/<学生>.json 的 total_score
        ↓
草稿 / 上传 / 成绩源 / 报告统一读取这个 total_score
```

因此补交扣分**不能写进 AI prompt 让它自己算**，否则会出现同一状态被重复扣、
不同模型结果不一致、旧产物无法审计的问题。正确位置是在 Python 算完学术分之后，
按平台提交状态做一次独立的程序调整。

## 2. 实现

### 2.1 提交状态从平台落盘到 plan

- `read_review_students()` 保留 `students.json` 里的 `status`；
- `build_plan()` 为每名学生写入 `submissionStatus` 与只读标记 `lateSubmission`；
- `flow._run_evaluate()` 把该生状态透传给 `evaluate_student(..., submission_status=...)`。

状态判定集中在 `evaluate.is_late_submission()`：识别“补交/迟交/逾期/late”。
没有状态时**不扣分，也不猜测**。

### 2.2 程序扣分

`score_from_analysis()`：

1. 先完成所有学术扣分并应用 `floor`，得到 `academic_score`；
2. 如果状态为补交/迟交，再扣全局规则 `lateSubmissionDeduct`（默认 5）；
3. 最终分最低为 0；
4. 结果 JSON 增加：

```json
{
  "academic_score": 100,
  "total_score": 95,
  "submission": {"status": "补交", "late": true},
  "score_adjustments": [
    {"kind": "late-submission", "deduct": 5, "status": "补交",
     "reason": "平台提交状态为补交/迟交"}
  ]
}
```

补交扣分在学术分之后执行，避免被 `floor`（默认 40）吞掉。

### 2.3 报告与成绩源

- `evaluations/*.json` 的最终 `total_score` 已含补交扣分；
- 报告总分下方显示“平台状态”和“程序已按提交状态自动扣分（−5 分）”；
- 草稿 AI 套同步保存 `submission/score_adjustments/academic_score`，
  PWA 预览与实际生成报告走同一套 `_mode_report_md`，不会出现预览与上传不一致；
- `D149` 批阅成绩源读取的仍是最终 `total_score`，并额外返回
  `submissionStatus/lateSubmission/academicScore/scoreAdjustments` 供核对。

### 2.4 配置

`grading-rules.json → global.lateSubmissionDeduct` 默认 5，
可在评阅规则卡中调整（0~50）。修改只影响后续新批阅；旧报告不复算。

## 3. 验收

| # | 验收 | 测试 |
|---|---|---|
| 1 | “补交/迟交”识别为 late，“已批阅/待批阅”不误判 | `test_is_late_submission_only_uses_explicit_status` |
| 2 | 学术分 100 → 最终 95，调整记录只出现一次 | `test_score_from_analysis_applies_five_point_penalty_once` |
| 3 | floor 40 时仍额外扣到 35 | `test_late_penalty_is_applied_after_academic_floor` |
| 4 | 下载清单状态进入 plan | `test_read_review_students_keeps_platform_status` / `test_build_plan_propagates_submission_status` |
| 5 | 评阅产物与两种报告都显示提交状态和扣分 | `test_evaluate_student_writes_adjustment_and_report_mentions_it` |
| 6 | 成绩源使用调整后的总分并可审计 | `test_grading_score_source_uses_adjusted_score_and_exposes_status` |

## 4. 边界

- 人工改分仍以人工分为准；补交状态只作为报告中的事实说明，不再对人工分二次扣减。
- 已生成的旧 `evaluations/*.json` 不会自动重算；需要重新评阅才会写入新的提交状态与调整。
- 平台状态缺失或文案不含“补交/迟交/逾期/late”时不扣分，避免误伤。
