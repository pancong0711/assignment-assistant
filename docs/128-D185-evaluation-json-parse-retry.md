# D185 需求单：评阅 JSON 偶发格式错误导致单生批阅直接失败

> 日期：2026-11-17
> 状态：**已完成**
> 关联：`docs/103-D156-D160-grading-quality.md`（D158/D160 评阅 JSON/schema）、
> `docs/109-D166-escape-and-related-json.md`（LaTeX/JSON 修复）
>
> 隐私：只使用合成学生与合成评阅 JSON；不得使用真实学生姓名、转写、图片或成绩。

---

## 0. 现场报错

逐生点击「转写+批阅」后失败：

```text
转写+批阅失败：
[评阅] FAIL 学生A:
评阅JSON解析失败: Expecting ',' delimiter: line 22 column 59 (char 765)
Error: 学生「学生A」评阅失败：
评阅JSON解析失败: Expecting ',' delimiter: line 22 column 59 (char 765)
```

该错误发生在**模型返回内容解析阶段**，不是转写失败，也不是评分规则失败。

---

## 1. 初步定位方向

当前链路：

```text
evaluate_student()
→ analyze()
→ client.chat(response_format=json_schema/json_object)
→ parse_llm_json(raw)
→ score_from_analysis()
```

已知现状：

- `parse_llm_json()` 会清洗 ```json 围栏、修复部分 LaTeX 反斜杠、裸换行/制表符；
- `analyze()` 只对 `Unterminated string` 类截断错误做 `max_tokens` 翻倍重试；
- 对 `Expecting ',' delimiter`、尾逗号、缺字段、字符串内未转义引号等
  **非截断型 JSON 错误没有重试/二次修复**，会直接让该生评阅失败。

需要确认本次错误具体属于哪一类：

1. 模型输出字符串中含未转义双引号；
2. LaTeX 反斜杠导致 JSON 转义错位；
3. 尾逗号；
4. 单引号/注释等非标准 JSON；
5. JSON 上下文被额外文本/代码围栏污染；
6. 截断虽未报 `Unterminated string`，但实际仍被截断；
7. provider 的 `json_schema` 返回了不规范但近似 JSON 的文本。

---

## 2. 修复目标

不能因为一次 JSON 格式漂移就让整名学生评阅失败。要求在 `analyze()` / JSON
解析层增加可控的失败恢复，同时保留最终失败时的可读错误。

### R1. 增强解析

- 抽成可测试的纯函数；
- 在现有 `parse_llm_json()` 基础上支持至少以下常见近 JSON：
  - 对象前后的解释文字/多个代码围栏；
  - 尾逗号；
  - 未转义双引号（谨慎，不能破坏合法 JSON）；
  - 字符串内裸换行/制表符；
  - 单引号（仅在明确判定为非标准 JSON 时）；
  - 截断后能补齐的简单缺失括号/大括号。
- 所有修复必须**保留 JSON 内容语义**，不得把 evidence/学生原文改写成错误内容；
- 无法恢复时必须抛出可读错误，并保留原始错误类别。

### R2. 重试策略

`analyze()` 中：

1. 首次解析失败 → 先尝试更强的本地修复；
2. 仍失败 → 用同一 prompt 再请求一次模型，明确要求“只返回合法 JSON，不要解释”；
3. 截断类错误沿用现有 max_tokens 翻倍；
4. 重试次数必须有上限，避免无限消耗；
5. 最终失败时错误信息包含：阶段、学生、错误类型/位置、建议（如“请重试/检查模型输出”），
   但**不得把完整 raw 学生内容写入日志**。

### R3. 可诊断性

- 解析修复成功时记录 warning（只记修复类别/位置，不记原文）；
- 不建议默认将完整 raw 响应落盘（含学生作业内容）；
- 可增加最小 `_parse_repairs` 诊断字段，如 `["trailing-comma", "fence-strip"]`；
- 对批阅结果不得因诊断字段变化而影响评分。

---

## 3. 测试要求

使用合成 JSON，不调用真实模型：

1. 正常 JSON 不回归；
2. 代码围栏 + 前后解释文字；
3. `Expecting ',' delimiter` 的最小复现输入；
4. 尾逗号；
5. 字符串内裸换行 / 未转义反斜杠；
6. 未转义双引号；
7. 截断 + 可补齐括号；
8. 本地修复失败时，`analyze()` 只重试有限次数并最终报可读错误；
9. 修复后仍能正常进入 `score_from_analysis()` / 写出批语；
10. 全量 pytest、相关 D158/D166/E2E 测试通过。

---

## 4. 允许修改范围

- `engine/src/assist/grading/transcribe.py`（`parse_llm_json`/修复纯函数）
- `engine/src/assist/grading/evaluate.py`（`analyze()` 重试策略）
- 新增/修改对应 tests
- 本任务需求单

不得修改评分规则、提示词业务语义、前端、题库、快照；不新增必须联网的依赖。
如确实要引入零依赖以外的 JSON 修复库，必须先说明理由并停下等待人工确认。

---

## 5. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | `Expecting ',' delimiter` 的合成响应 | 能修复或有限重试后成功 |
| 2 | 合法 JSON | 行为完全不变 |
| 3 | 无法修复的响应 | 可读失败，不刷屏、不写完整学生原文 |
| 4 | 截断响应 | 仍按原逻辑翻倍 max_tokens |
| 5 | 单生批阅 E2E | 不再因一次格式漂移导致整生失败 |
| 6 | 回归 | 全量 pytest 通过；脱敏检查通过 |

完成后停在 worktree 等待人工 review；禁止 commit/push。

---

## 6. 实现摘要

- `engine/src/assist/grading/transcribe.py`：
  - 新增 `_strip_fences_and_preamble`、`_remove_trailing_commas`、`_balance_brackets`、`_fix_unescaped_quotes_in_text` 等纯函数；
  - `parse_llm_json` 增加 `repairs_out` 参数，解析失败时依次尝试：剥离围栏/说明 → 修复尾逗号 → 转义裸控制字符/反斜杠 → LaTeX 修复 → 修复字符串内未转义双引号 → 补齐截断括号；
  - 所有修复均尽量保留原文语义，不修改 evidence 等字段内容。

- `engine/src/assist/grading/evaluate.py`：
  - `analyze()` 首次解析失败先走增强本地修复；
  - 截断类错误仍按 `max_tokens` 翻倍逻辑处理；
  - 非截断类错误本地修复失败后，最多 2 次模型重试，明确要求"只返回合法 JSON"；
  - 最终失败信息可读、脱敏，不泄露学生原文；
  - 修复成功时返回 `_parse_repairs` 诊断字段（仅修复类型标签）。

- `engine/tests/test_d185_evaluation_json_parse.py`：覆盖正常 JSON、围栏/说明、尾逗号、裸换行/反斜杠、未转义双引号、截断补齐、analyze 重试边界、诊断字段、score/feedback 流程及相关回归。

## 7. 验收结果

- D185 目标测试：`21 passed`；
- 相关 JSON/LaTeX/评阅/归一化回归：`107 passed`；
- 全量 pytest（deselect 一个既有 Playwright 报告渲染超时用例）：
  `1682 passed, 2 skipped`；
- `engine/tests/test_grading.py::test_rerun_report_only` 在当前环境单独/全量均因
  Playwright `Page.set_content` 30s 超时失败，与本次 JSON 解析改动无关；
- `tools/check-secrets.sh`、`tools/lint_bat.py`、`git diff --check` 通过。
