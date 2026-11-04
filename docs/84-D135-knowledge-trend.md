# D135 需求单：跨多次作业的知识点趋势（同一知识点是否反复出错）

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/80-D126B-teacher-report`（§8 明确留待后续的那一项）、`docs/12`

## 0. 一句话

把同一班级的**多次作业**串成序列，看同一知识点是否**反复出错**、
以及是在**改善**还是**仍在持续**。纯统计，不调 LLM，只给教师。

## 1. 为什么单独成模块

`teacher_report` 的口径是「**一次作业**内全班分析」；趋势的口径是
「**同一班级多次作业**串成序列」。输入、聚合维度、阅读场景都不同，
混进去会把"单次报告"的语义搅浑。故新增 `grading/trend.py`，与 D126-B 并列。

## 2. 作业序列口径（定稿，不引入新概念）

```
同一 class_dir 下、按【评阅时间】升序排列的作业包序列
```

- 评阅时间取 `evaluations/*.json` 的 `timestamp` **最大值**（批阅可能跨分钟）；
  全部缺失时回落到目录内文件的 `mtime`；
- 时间相同按包名稳定排序（避免报告每次顺序抖动）；
- **没有评阅结果的包不进入序列**（否则趋势里出现断档空节点）。

不做"按章节串"：需要额外的章节↔作业映射，目前没有可靠依据。

## 3. 判定口径

| 概念 | 定义 |
|---|---|
| 反复出错（`recurring`） | 同一知识点在 **≥ `minRecur`（默认 2）次**作业中出现 |
| 仍在持续（`persisting`） | 末次出错率 **≥** 首次出错率 |
| 有改善（`improving`） | 末次出错率 **<** 首次出错率 |
| 仅出现一次（`oneOff`） | 只出现 1 次（可能是当次内容难点，折叠展示） |

统计只算 `errors[].knowledge[]` 且**排除低置信度**（与计分口径一致）。

用**出错率**而不是人数判定改善，是因为班额在多次作业间可能变化。

## 4. 实施

| 位置 | 内容 |
|---|---|
| `engine/src/assist/grading/trend.py` | `discover_sequence` / `analyze` / `render_md` / `generate` |
| CLI | `assist trend --class-dir classes/化工25 [--min-recur 2] [--out ...]` |
| serve | `GET /grade/trend?classDir=...&minRecur=2` |
| PWA | `TrendCard.vue`（作业序列 / 反复出错表 / SVG 迷你走势 / 持续·改善判定） |
| 挂载 | `AiGradingPanel` 中位于教师报告卡之后 |

产物：`<ws>/<class_dir>/grading/_trend/trend.md` 与 `trend.json`。

## 5. 验收

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 序列按**评阅时间**而非包名排序 | ✅ | `test_sequence_sorted_by_timestamp_not_name` |
| 2 | 无评阅结果的包不进入序列 | ✅ | `test_sequence_skips_packs_without_evaluations` |
| 3 | 同一知识点跨 2 次出现 → `recurring` | ✅ | `test_recurring_term_across_two_packs` |
| 4 | 改善 / 持续判定按出错率 | ✅ | `test_improving_vs_persisting` |
| 5 | 低置信度不计（与计分口径一致） | ✅ | `test_low_confidence_excluded` |
| 6 | 报告声明"只给教师/不发给学生" | ✅ | `test_render_md_contains_trail_and_disclaimer` |
| 7 | PWA 真实浏览器渲染序列/表格/折线 | ✅ | `run-d135-trend-browser.sh`（已接入 selfcheck） |

验证：pytest **1043 passed** · build 0 error · selfcheck **26/26** · 脱敏通过。

## 6. 已知限制

- 只按 `class_dir` 聚合；**跨班级**对比未做（需要先定"同一次作业跨班"的口径）。
- 知识点匹配是**字符串精确匹配**；同义术语需先用 `kb check-knowledge` 归一，
  否则会分散成多个知识点（这是刻意的：不静默合并，避免误归）。
- 不读 `knowledge_missing[]`（`summary` 漏点）：那是"应会未会"，
  与"做错"语义不同，混在一起会让趋势失真；如需可后续单独列一栏。
