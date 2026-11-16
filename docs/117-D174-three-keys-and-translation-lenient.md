# D174 需求单：逐生批阅三键语义确认 + 翻译题批阅放宽

> 日期：2026-11-16
> 状态：**已完成**
> 关联：`docs/116-D171`（三键改名 + 评阅落草稿）、`docs/115-D170`（抄写题 topicMatch）

## 0. 教师原话（第 19 轮反馈）

> 在 ai 辅助批阅里的逐生批阅部分，
> 1、转写、批阅、完整键的含义都是什么，是否都是针对当前行学生的转写、批阅、完整（撰写+批阅）？
> 2、批阅键似乎只批阅，不打分，也没有出批语，这里的批阅应该加上批语和打分，
> 完整键应就是转写+批阅，我们将批语/打分融入进批阅键，这在整体的转写、批阅、完整键里
> 也应该是这样设计的吧，我们好像改过这个地方，以前好像全局的批阅键也是不带批语和打分，确认一下。
>
> 另，translation 的批阅提示词可能有些过于严格了，这部分我们主要看学生有没有翻译和回答基本问题，
> 如果翻译完全不对则扣 5 分，如果没有回答问题则扣 5 分，如果字数少于题目描述，则扣 10 分。
> 这样会不会宽一点？

---

## 1. 结论一：三键语义（已定版，行内 = 全局）

**逐生行内的三个键确实只作用于「当前这一行学生」**（`runOne` 传 `students:[姓名]`）。
语义与「③ 任务」区的全局三键**完全一致**：

| 键 | steps | 做什么 | 产出 |
|---|---|---|---|
| **转写** | `[transcribe]` | 作答图 → 结构化转写 | `transcripts/<学生>.json` + 草稿 `ai.transcript`；**不出批语、不打分** |
| **批阅** | `[evaluate]` | 基于已有转写评阅 | `evaluations/<学生>.json` + **草稿 `ai.score` + `ai.comment`**（批语+打分） |
| **转写+批阅** | `[transcribe, evaluate]` | ① + ② 一起做 | 上述两者；**不含报告**（报告用 ⑤「📄 一键生成批阅报告」） |

### 1.1 「完整」改名
行内第三个键原叫「完整」，与全局 D171 改名后的「转写+批阅」不一致 →
**改为「转写+批阅」**，并在 tooltip 写明三键各做什么。

### 1.2 「批阅只批阅、不打分不出批语」——是**显示层**问题，不是设计如此
- 评阅步 `_run_evaluate` → `evaluate_student()` 的产出就是 `total_score` + `feedback_md`，
  D171-T2 起由 `_persist_evaluations_to_drafts()` **写入草稿** `ai.{score, comment}`。
- 因此「批阅」**本来就是批语+打分**；教师感觉"只批阅"是因为**草稿里没有新结果**：
  - **D171 之前**：`runOne` 不传 `force`，命中 `if _ev.is_file() and not ctx.get("force"): 跳过`
    → 提示完成但什么都没变（**教师记忆中的"以前批阅键不带批语和打分"就是这件事**）；
  - **D171 之后**：`runOne` 固定 `force: true`（逐生补批必重跑），并修复了落草稿静默失败。
- 本轮把语义写进 **UI tooltip** 与**自检**（`app/tests/selfcheck-d174-three-keys.mjs`），防止回退。

> 版本沿革（供追溯）：D125 引入四键「① 仅转录 / ② 仅评阅 / ③ 转录+评阅 / ④ 完整批阅」；
> D171 去掉「④ 完整批阅」（它不传 force，名不副实），定版为三键；
> D174 把行内第三键「完整」同步为「转写+批阅」。

---

## 2. 结论二：translation 批阅放宽（是，会宽很多）

### 2.1 旧口径（过于严格）
`translation` 走通用 `lengthBased`：

| 判据 | 扣分 |
|---|---|
| 与题目无关 | −20（单题封顶 20） |
| 字数 < 题长×3（下限 60 字）的 80% | −5 |
| 字数 < 50% | −10 |

且提示词要求「检查翻译是否准确、术语使用是否正确」——文学作品翻译**没有唯一标准答案**，
转录又来自照片识别，逐词比对准确性会冤枉学生。

### 2.2 新口径：`mode="translation"`（专用算法，D174）

| 判据 | 扣分 | 说明 |
|---|---|---|
| 翻译完全不对（`relevance="irrelevant"`） | **−5** | 通篇乱译/根本没翻译 |
| 没有回答题目所问（`question_answered=false`） | **−5** | 题目只要求翻译时恒为 true，不扣 |
| 字数少于题目描述（`answer_chars < required_chars`） | **−10** | 只扣一次，**不再分档**；未规定字数则不扣 |

- **不读 `errors`**：术语/文采/个别句子理解偏差**不扣分**，只转成启发式提问（`guidance`）；
- 三项可叠加，仍受全局 `perQuestionCap`（默认 20）封顶；
- 字数以**转写原文重算**（不信模型自报），与抄写题同口径；
- 规则卡可调 `questionAnsweredDeduct` / `translationWrongDeduct` / `shortAnswerDeduct`。

### 2.3 提示词改动
- `kind_output_hint("translation")`：要求回 `answer_chars` / `relevance` / `question_answered`，
  明确"个别错误不要判 irrelevant"与"不扣分的事"；
- schema 增 `question_answered`（boolean）；
- `TAG_INSTRUCTIONS["translation"]` 与 `evaluate.py` 内旧副本同步改为宽松口径；
- `ANALYSIS_PROMPT` 的「逐题评阅视角」翻译题一条同步改写。

---

## 3. 验收

| # | 标准 | 验证 |
|---|---|---|
| 1 | 行内三键 = 转写 / 批阅 / 转写+批阅，且与全局同口径 | `tests/selfcheck-d174-three-keys.mjs` |
| 2 | 不再出现「完整批阅」/「完整」按钮 | 同上 |
| 3 | 翻译正确但用词有小错 → 100 分 | `test_good_translation_gets_full_marks` |
| 4 | 完全不对 → −5；未答题 → −5；字数不足 → −10（一次） | `test_d174_translation_lenient.py` |
| 5 | 三项叠加受全局单题封顶 | `test_three_penalties_can_coexist_capped` |
| 6 | 规则卡可读地展示新口径 | `test_rule_summary_mentions_lenient_deductions` |
| 7 | 四道门 | pytest 1579 · build 0 error · selfcheck · 脱敏 |
