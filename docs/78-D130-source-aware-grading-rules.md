# D130 需求单：按题目来源分型的评阅规则 + AI 生成评阅要点 + 知识点体系 + Assistopia（项目游乐城）

> 日期：2026-10-30
> 状态：**已定稿；P1 拆三批执行（P1a → P1b → P1c），见 §4.1**
> 关联：`docs/69-D119`、`docs/74-D125`、`docs/75-D126`、`docs/76-D127`、`docs/77-D129`、`docs/12`（D126-B 教师总结报告）

## 0. 一句话

把「**题目来源（题库哪张表）**」作为评阅范式的第一驱动，产出
**来源分型的评分规则**（三层）＋ **AI 生成的评阅要点**＋ **知识点体系**，
并规划一个可让 AI 安全调用本机工具的 **Assistopia**。

## 1. 用户诉求（原话要点）

- 批阅提示词教师看不到也改不了；评分口径不透明；
- 非计算题（qa / distinguish / innovation / translation / summary / copy）需要不同的评阅标准；
- 批阅报告目前**没有预览入口**；
- 希望 AI 能辅助「打知识点标签」，并做**全标注检查 + 术语归一**；
- 希望课堂资料（PPT / 授课计划）参与 `summary` 类批阅，并让启发式提问更贴切；
- 希望有一个可视化的 AI 工作区，能让 AI 调用本项目自己的工具，且**升级不覆盖用户改动**。

## 2. 现状审查（已核实）

| # | 事实 | 证据 |
|---|---|---|
| P1 | **题目来源已存在但未透传**：`expand_items` 有 `kind = spec.get("kb")`，但未写入输出 | `grading/flow.py:53`；`inputs._questions_of` 同样缺 |
| P2 | 评阅系统提示词 `ANALYSIS_PROMPT` **硬编码** | `evaluate.py:25` |
| P3 | 分型指令仅 5 种且硬编码 | `prompts.TAG_INSTRUCTIONS` |
| P4 | 计分规则硬编码（每错 −5、单题上限 −20、缺图 −5、无签名 −5、底线 40） | `evaluate.score_from_analysis` |
| P5 | 题库已有 `related`（关联知识点）列，前后端均可读写 | `kb_io.COLUMNS`、`kbXlsx.ts`、`KbEditorView` |
| P6 | AI 作答能力已有且可置顶（成为生效答案） | `grading/solve.solve_targets(pin=True)`、`files/solutions.effective_solution` |
| P7 | 提示词模板库仅 `prompts/ai-solve/`（作答风格），**无评阅规则概念** | `files/prompts.py` |
| P8 | **报告无任何预览入口**（只有「有报告」状态） | `AiGradingPanel.vue` |
| P9 | LLM 客户端**无 function calling** 能力；Playground 仅单次/批量问答 | `grading/llm.py`、`playground/ask.py` |
| P10 | 本机具备 `officecli`（AI-friendly、支持 .pptx）与 LibreOffice | 实测 `officecli view x.pptx text` 可提取文本 |
| P11 | 评测产物已含 `errors[].knowledge[]`、`audit{pad_id,question_numbers}` | D127 实施 |

## 3. 决策（已拍板）

### 3.1 题目来源 → 评阅范式

| 来源（kind） | 评阅重点 | 是否生成 AI 评阅要点 |
|---|---|---|
| `problems` | 计算/推导，逐处找错 | ✅ |
| `qa` | 回答要点是否完整 + 示意图 | ✅ |
| `copy`（含 copyonly/copysp 别名） | 抄写完整性：题目 / 解答过程 / 示意图 | ❌（以原文为唯一依据） |
| `distinguish` | 辨析角度与依据（较宽） | ✅ |
| `innovation` | 思考过程（宽松，超纲允许） | ✅ |
| `translation` | 译文准确性（较宽） | ✅ |
| `summary` | 知识点与概念 / 重要模型公式（含推导）/ 示意图 | ❌（未来接课堂资料） |

> `copy` 未来会补全题目；`summary` 未来接课堂讲义/PPT —— 记入 §7 扩展点。

### 3.2 三层评分规则（避免把规则与要点混成一团）

```
第 1 层 全局规则（跨题/跨作业，长期稳定）      → <ws>/grading-rules.json : global
第 2 层 题型规则（按来源分型）                  → <ws>/grading-rules.json : types.<kind>
第 3 层 单题评阅要点（随题走）                  → 答案版本库（AI 生成 + 教师确认置顶）
```

**规则与要点解耦**：要点只描述“该答什么”，规则只描述“缺了怎么扣”。
生成要点的提示词 = 题目 + **该题型的规则摘要** + 输出格式要求（保证要点粒度与扣分方式匹配）。

### 3.3 评分细则（用户给定）

- **全局**：解题过程过于简略、缺关键步骤 → **−5**（即便答案正确）；
- **全局惩戒**：若 **≥80% 的题**都被判为“过程简略” → **总分额外 −5**（一次性，非逐题）；
- **problems**：每错一处 −5（沿用现有，单题上限 20）；
- **qa**：每缺一个评阅要点 −5；缺示意图 −5；
- **copy**：未抄题目 / 未抄解题过程 / 未抄示意图 → 各 −5（题本身有图才要求抄图）；
- **distinguish / innovation / translation**：
  - 作答长度以**题目字数的 3 倍**为基准（下限保护 `max(3×题长, 60字)`）；
  - 达不到 **80%** → −5；达不到 **50%** → −10；**与题目完全无关** → −20；
  - **逻辑错误豁免扣分**，但**必须生成启发式提问**；
- **summary**：知识点与概念 / 重要模型公式（含推导）/ 示意图，每项不佳 −5；示意图项**题干要求画图才计**。

### 3.4 评阅规则卡（可视化页）

**分级开放**（解决“教师看不到批阅提示词”）：

| 级别 | 内容 | 可改 |
|---|---|---|
| 🔒 只读 | 题型 → 评阅侧重的提示词正文、评分算法名 | ❌（但完全可见） |
| ✏️ 可改数值 | 扣分分值、上限、长度倍率、阈值、豁免开关（带范围校验） | ✅ |
| ➕ 可改扩展 | 题型 checklist 的检查项名称（如 copy 的“题目/过程/示意图”） | ✅ |

配套：改动记 journal（旧值/新值/时间）、一键「恢复默认」、页面明示“影响后续批阅，不改已生成报告”。

### 3.5 知识点标注体系

- **生成要点时顺带打标签**：模型同时输出「参考解答 / 评阅要点 / 知识点 / 示意图要求」；
- `related` 采用**轻量两层**（不做完整版本库）：
  ```json
  related: "动量守恒, 弹性碰撞"
  related_meta: { "source": "ai|human|merged", "ai_suggested": "...",
                  "pinned_by": "human", "updatedAt": "..." }
  ```
  - 为空 → AI 可直接写入；已有内容 → **不覆盖**，作为 `ai_suggested` 建议；
  - `pinned_by: human` 后 AI 不再改动；教师可在题库表格逐项编辑。
- **批量标注四种粒度**：全部 / 某类型 / 某些类型 / 具体题目（以及按章节）；
- **默认只处理未标注**（`--only-empty`），覆盖需显式 `--force`。

### 3.6 术语归一（全标注检查）

- AI **提议**等价组 + 置信度；**默认不全选**；语义不同者（如「动量守恒」vs「动量定理」）显式警示且默认不勾；
- 教师在 PWA **勾选**确认后执行；执行前展示影响面；执行后写变更日志（可回滚）；
- 归一前先做分隔符标准化（`，`/`;`/`、`/`；` → `,`）。

### 3.7 受控词表

`<ws>/knowledge-terms.json`：由题库 `related` 自动汇总 + 人工维护。标注时**优先选词表内术语**，新词入库标注来源（human/ai）。同时作为 `summary` 未来接入课堂资料的中间层。

### 3.8 报告预览

- 逐生审核弹窗新增「📄 报告」页（复用 `reports/<学生>.html`，iframe 预览）；
- 点「一键生成批阅报告」后**自动切到报告页**；
- 报告中标注：本题来源、适用规则、扣分明细。

### 3.9 Assistopia（原 Agent Playground 升级）

命名：**Assistopia = assist + utopia**（用户提议，采纳）。定位：AI 调用本项目工具的**可视化工作区**。

- **工具白名单分级**：
  | 级别 | 示例 | AI 权限 |
  |---|---|---|
  | L0 只读 | `kb stats`、`packs list`、`grade drafts`、`doctor --json` | 直接执行 |
  | L1 预览 | `kb tag-knowledge --dry-run`、`kb check-knowledge` | 直接执行（dry-run） |
  | L2 写入 | `kb write`、`tag-knowledge --apply`、术语归一执行 | **教师二次确认** |
  | L3 危险 | 迁移 `--apply`、删除、引擎更新 | **不开放** |
- **护栏**：调用次数上限、超时、预算；每次调用记 journal（参数/结果/耗时）；
- **用户扩展隔离**（核心）：
  ```
  <ws>/extensions/        ← 升级永不触碰
      tools/  rules/  knowledge-terms.json  …
  ```
  加载优先级：内置默认 → `extensions/` 覆盖 → 生效。
- 需新增 LLM function calling 能力（现状 P9 无）。

### 3.10 课堂资料 → summary 批阅

- 教师把 PPT / 授课计划放入 `<ws>/materials/<chap>/`；
- 优先支持 **PDF / PNG/JPG**（走多模态，与转写同路）；`.pptx` 视 `officecli` 可用性接入（本机实测可提文本）；
- 抽取「本章知识点 + 逻辑关系」→ 与受控词表比对 → 教师确认 → 生成「本章知识点清单」；
- `summary` 批阅以此为参考依据，启发式提问可指向“本堂课漏掉的知识点”。

## 4. 实施清单与阶段

### P1（本轮，独立可交付）

| # | 任务 |
|---|---|
| T0 | `expand_items` / `_questions_of` 透传 `kb`（来源）；kind 别名归一（copys/copyonly/copysp→copy） |
| T1 | `grading-rules.json`：`global` + `types` 结构与默认值；加载器（缺失即写默认） |
| T2 | 评阅 prompt 按来源注入题型指令与**规则摘要**；生成要点提示词共用同一规则摘要 |
| T3 | 计分算法按 `mode` 分派：`errorCount` / `missingPoints` / `checklist` / `lengthBased` |
| T4 | 全局规则：`briefProcessDeduct`、`allBriefDeduct`（≥80% 触发，总分一次性） |
| T5 | AI 生成「参考解答 + 评阅要点 + 知识点 + 示意图要求」，写入答案版本库（**默认不置顶**，教师确认） |
| T6 | `assist kb tag-knowledge`（四种粒度 + `--only-empty`/`--dry-run`/`--force`），顺带在要点生成时写入 |
| T7 | `assist kb check-knowledge`（提议等价组 + 置信度；`--apply --mapping` 执行；变更日志） |
| T8 | `knowledge-terms.json` 受控词表（自动汇总 + 人工维护；标注优先选词表） |
| T9 | PWA「评阅规则」卡（只读全量 + 数值可改 + 校验 + journal + 恢复默认） |
| T10 | PWA 逐生审核「📄 报告」页 + 生成后自动切换 |
| T11 | 评阅 prompt 显式给出题库知识点标注，要求模型**优先使用同术语** |

#### 4.1 P1 拆批（已确认）

> 依据「耦合度优先」：强耦合的规则/计分主干由主 agent 连贯完成，旁支（词表/归一/前端卡片/报告预览）可独立验证，单独成批。
> 顺序上把**独立的显示 bug 修复**提到最前，记为 **T12**（已在 P1c 完成）。
> 该编号原先在 P2 清单里指材料导入，现已顺延为 **T19**（见 §4 P2 表），编号不重复使用。

| 批次 | 范围 | 任务 | 验收要点 |
|---|---|---|---|
| **P1a 主干**（强耦合，必须一起做） | 来源透传 → 规则结构 → prompt 分型 → 计分分派 → 全局规则 | T0 T1 T2 T3 T4 T11 | 验收 1/3/4；pytest 覆盖默认规则不变（历史 749 例不回归） |
| **P1b 知识体系** | AI 生成要点（不置顶）+ 知识点标注 + 术语归一 + 受控词表 | T5 T6 T7 T8 | 验收 5/6/7 |
| **P1c 前端** | 评阅规则卡 + 报告预览 + 显示 bug 修复 | T9 T10 T12 | 验收 2/8 |

每批完成即跑「pytest / app build / selfcheck / 脱敏」四项，并单独提交推送（便于回滚）。

### P2（下一轮）

> 编号说明：P2 原清单的 `T12`（材料导入）**与 P1c 已完成的 T12（显示 bug 修复）撞号**，
> 现顺延为 T19/T20/T21，避免"同一个编号指两件事"。

| # | 任务（括号内为原编号） |
|---|---|
| T19 | `<ws>/materials/` 导入 PDF/图片 → AI 抽取知识点与逻辑关系 → 教师确认（原 T12） |
| T20 | `.pptx` 支持（优先 `officecli`，回退 LibreOffice 转 PDF）（原 T13） |
| T21 | summary 批阅接入「本章知识点清单」；启发式提问指向遗漏知识点（原 T14） |

### P3（高阶，另行立项）

| # | 任务 |
|---|---|
| T15 | Assistopia 基础版：L0/L1 工具白名单 + journal 审计 |
| T16 | LLM function calling 能力（`tools` 协议） |
| T17 | L2 写操作二次确认；调用次数/超时/预算护栏 |
| T18 | `<ws>/extensions/` 覆盖机制 + 加载优先级 |

## 5. 验收标准（P1）

1. 同一份作业中，`qas` 与 `problems` 题目按**各自规则**扣分，报告中标明来源与规则；
2. 任一题型规则参数修改后，**新批阅**生效、**已生成报告**不变；
3. `qa` 题缺要点按 `missingPoints` 扣分；`distinguish` 按长度档扣分且逻辑错误不扣但产生提问；
4. 「整体简略」仅在 ≥80% 题目触发时对**总分**一次性 −5；
5. AI 生成要点**不自动置顶**；教师确认后批阅才使用；
6. `related` 为空可被 AI 写入、非空不被覆盖；`pinned_by: human` 后 AI 不触碰；
7. 术语归一必须**教师勾选确认**后执行，且有变更日志；
8. 逐生审核内可预览报告，生成后自动切换；
9. engine pytest / PWA build / selfcheck / 脱敏 全绿。

## 6. 风险

| 风险 | 缓解 |
|---|---|
| 规则开放后教师改坏 | 范围校验 + journal + 恢复默认 + 只读展示提示词正文 |
| AI 生成要点质量不稳 | 默认不置顶、教师确认；报告标注“依据 AI 要点” |
| 长度规则误伤（题干过短） | `max(3×题长, 60字)` 下限保护 |
| 术语归一误合并 | 默认不勾选 + 显式警示 + 影响面预览 + 可回滚 |
| 知识点标注口径漂移 | 受控词表 + 评阅 prompt 复用同术语 |
| Assistopia 工具误用 | 分级白名单 + 二次确认 + 审计 + extensions 隔离 |

## 7. 未来扩展（已记录）

- `copy` 题目补全后，可支持“原文比对”式要点；
- `summary` 接入课堂讲义/PPT/授课计划（P2）；
- `related` 若出现“大面积标错需回滚”，再升级为版本库；
- 知识点层级（上位/下位）暂不做，数据结构预留可扩展；
- Assistopia 的“AI 参与修改工具代码”需额外沙箱与版本管理设计（P3 之后）。

## 8. 实施记录

### 8.1 P1a（T0/T1/T2/T3/T4/T11）— 2026-10-30 完成

| 任务 | 落地 | 关键决定 |
|---|---|---|
| T0 | `flow.expand_items` / `inputs._questions_of` 输出 `kb`/`kind`/`chap` | `kind` 用 `rules.normalize_kind` 归一（copys/copyonly/copysp/punish→copy；未知→problems） |
| T1 | **新增** `grading/rules.py`：`<ws>/grading-rules.json` + 缺失即写默认 + 损坏不覆盖 + 缺字段补默认 + 范围校验 + journal + reset | 规则文件不入库（`.gitignore`） |
| T2 | `prompts.kind_instruction` / `kind_output_hint`；`evaluate.build_user_prompt(ws=)` 按**去重后的每种 kind** 注入"范式 + 规则摘要 + 输出要求" | 规则摘要与要点生成共用 `rules.rule_summary`；旧"整份只用第一个 tag 指令"改为逐 kind（混合来源不再串规则） |
| T3 | `score_from_analysis(items=, ws=)` 按 `mode` 分派 `errorCount`/`missingPoints`/`checklist`/`lengthBased`；返回 `per_question_rules` | 扣分数值由 Python 统一算，**不信模型自报 deduct**（否则规则卡改数值对模型无效） |
| T4 | 全局 `briefProcessDeduct` 逐题 + `≥allBriefRatio → 总分一次性 −allBriefDeduct` | 一次性规则不逐题累计（测试断言只出现 1 次） |
| T11 | `prompts.knowledge_instruction`：题库 `related` + 受控词表 → 要求**优先沿用同术语** | 全份作业汇总一次（避免每题重复烧 token） |
| 附带 | `report.build_report_md` 增「评分依据（按题目来源）」；CLI `assist rules show/defaults/summary/set/reset`；`grading/vocab.py`（T8 底座） | — |

**实施中修正的两个真实缺陷**（测试先暴露，非拍脑袋改）：
1. 长度档阈值原先**降序**遍历并 `break`，导致 <50% 也只得 −5 —— 改为**升序**取最严档（<50% → −10）；
2. 模型自报 `answer_chars` 会覆盖 `Python 实算字数`（模型报 500、原文仅 5 字 → 不扣分）—— 改为**有转写原文时一律以原文重算**。

**验证**：engine pytest **792 passed**（新增 `tests/test_d130_source_aware_rules.py` 43 例，含端到端"混合题型各按自身规则扣分 + 报告标注来源/规则"）；脱敏检查通过。

**已知口径变更**：`problems` 缺示意图**不再**按"题数×5（上限 10）"另扣 —— 缺图在 `qa/copy/summary` 的题型规则内计，`problems` 视为提示不扣分（docs/78 §3.1 未要求计算题缺图扣分）。

### 8.2 P1b（T5/T6/T7/T8）— 2026-10-30 完成

| 任务 | 落地 | 关键决定 |
|---|---|---|
| T5 | **新增** `grading/rubric.py`：`build_rubric_prompt`（带**该题型规则摘要**）+ `generate_rubric` + `save_rubric_version` | 写入答案版本库 `source=ai`、**默认 pin=False**；教师 `kb solution pin` 后才成为生效答案（生效答案会被 `expand_items` 实时取用 → 自动进入后续批阅 prompt） |
| T6 | `assist kb tag-knowledge`：四种粒度（全部/类型/章节/具体题目）+ `--only-empty`（默认）/`--force`/`--dry-run`；`rubric.plan_tagging` 集中判定三条口径 | 「为空可写 / 非空不覆盖 / `pinned_by:human` 后 AI 不碰」三态在 `plan_tagging` 一处判定，CLI 与未来 PWA 共用 |
| T7 | **新增** `grading/termnorm.py` + `assist kb check-knowledge`：AI 只提议 → 教师勾选 → `--apply --mapping` → 变更日志 → `--rollback` | 默认**不全选**（置信 <0.9 或带 warning 的组不勾）；执行前 `impact()` 展示影响面；归一前先做分隔符标准化 |
| T8 | **新增** `grading/vocab.py` + `assist kb vocab harvest/list/add`：`<ws>/knowledge-terms.json` | 汇总**保留**人工词条的别名与 source；标注时术语经 `canonical()` 归到词表正名 |

**实施中修正的真实缺陷**：教师手写 mapping 文件（无 `selected` 字段）会让 `build_mapping` 静默产出空映射 → 改为"无任何 selected 字段时视为全部勾选"，但**显式 `selected:false` 仍不执行**（两者都有测试锁定）。

**验证**：engine pytest **820 passed**（新增 `tests/test_d130_knowledge_rubric.py` 28 例）。

**口径说明**：`related_meta` 不新增 xlsx 列，存 `<ws>/kb/knowledge-meta.json`（sidecar，`kb__chap__qid` 为键），避免改动题库表结构；写题库一律走 `write_chapters_preserving`（保样式）+ 写前 `snapshot`（可回滚）。

### 8.3 P1c（T9/T10/T12）— 2026-10-30 完成

| 任务 | 落地 | 关键决定 |
|---|---|---|
| **T12**（原 P2 清单里的显示 bug，按用户确认提前） | 根因**已复现**：草稿键可能是 `workAnswerId`，也可能是**姓名**（批阅清单未解析到 id 时回落）；前端列表固定用 `workAnswerId \|\| name` 取 → 表里"未跑"、弹窗却能读到 | ① 引擎新增 `grade_store.resolve_draft_key()`；② `/xxt/preview/students` 返回**统一 `students[].key`**（带 taskId/classDir/altTaskId 参数）；③ 前端新增 `draftOf()`，**表格与弹窗同源**；④ 新增契约测试锁死"不得再直接 `drafts[s.key]`" |
| T9 | **新增** `GradingRulesCard.vue` + serve `GET /rules`、`POST /rules/save`、`POST /rules/reset` | 三级开放：🔒 只读（实际进 prompt 的规则摘要 + 算法名）/ ✏️ 数值（引擎下发范围，前端即时提示，**权威校验在引擎**）/ ➕ checklist 项名；页面明示"只影响后续批阅，不改已生成报告" |
| T10 | **新增** serve `GET /grade/report/<classDir>?taskId=&student=`；`StudentReviewModal` 加「✏ 批阅 / 📄 报告」页签 + iframe；生成报告后**自动切页** | 报告接口**故意不放在 `/xxt/` 分支下**（纯本地产物，不应因学习通模块不可用被 503）；取文件限定在 `<ws>/classes/**/grading/<taskId>/reports/` 内并做 resolve 校验防穿越 |

**验证**：engine pytest **834 passed**；app build 0 error；selfcheck 全绿（新增 `selfcheck-d130-rule-cards.mjs`）；脱敏通过。
新增 `tests/test_d130_serve_rules_report.py`（5 例，**起真实 HTTP 服务**验证读写/校验/journal/报告 200/404/**路径穿越被拒**）；新增 `tests/test_d130_t12_draft_key_contract.py`（9 例）。

### 8.4 P1 完成度对照（验收标准 §5）

| # | 验收项 | 状态 | 依据 |
|---|---|---|---|
| 1 | 同一份作业 qa 与 problems 各按自身规则扣分，报告标明来源与规则 | ✅ | 端到端测试 `test_end_to_end_mixed_kinds` |
| 2 | 规则参数修改后**新批阅**生效、**已生成报告**不变 | ✅ | `test_prompt_follows_modified_rules`；报告是纯组装产物（D127） |
| 3 | qa 缺要点按 missingPoints 扣；distinguish 按长度档且逻辑错误不扣但产生提问 | ✅ | `test_qa_missing_points_deduct` / `test_length_based_tiers` / `test_length_based_logic_errors_exempt` |
| 4 | 「整体简略」仅 ≥80% 触发时对总分一次性 −5 | ✅ | `test_all_brief_only_fires_at_80_percent` / `test_all_brief_not_double_counted_per_question` |
| 5 | AI 要点不自动置顶，教师确认后才使用 | ✅ | `test_save_rubric_version_not_pinned_by_default` / `test_pinned_rubric_becomes_effective_solution` |
| 6 | related 为空可写、非空不覆盖、pinned_by:human 后不动 | ✅ | `test_plan_tagging_*` 三例 |
| 7 | 术语归一须教师勾选确认后执行且有变更日志 | ✅ | `test_propose_groups_defaults_not_all_selected` / `test_impact_and_apply_mapping` / `test_rollback_restores_previous_terms` |
| 8 | 逐生审核内可预览报告，生成后自动切换 | ✅ | 页签 + iframe + `showReportTab()`；`test_report_preview_serves_generated_html` |
| 9 | pytest / build / selfcheck / 脱敏 全绿 | ✅ | 834 passed / 0 error / 全绿 / 通过 |

### 8.5 P1 遗留（不在本轮范围，已记录）

- ~~规则卡的 PWA 端到端点击回归~~ → **已补**（见 §8.6）。
- `SheetContentView.vue` 整班 zip 变体编排仍用全库 `pad.savedJsons()`（与整班预览口径未统一，D127 已登记）。
- 教师总结报告（D126-B）未实施；`evaluations/*.json` 已带 `knowledge[]`。
- P2（课堂资料 → summary）与 P3（Assistopia）未开始。

### 8.6 P1 补强（真实浏览器回归 + 编号冲突修正）— 2026-10-30

**1. T9 规则卡真实浏览器回归**（补上 §8.5 的第一条遗留）

`app/tests/run-d130-rules-browser.sh`：用**真实 Chromium** 挂载**真实 `GradingRulesCard.vue`**，
连**真实引擎 HTTP 服务**（`/rules`、`/rules/save`、`/rules/reset`），逐项验证：

| 验证项 | 结果 |
|---|---|
| 🔒 只读规则摘要可见（教师能看到进 prompt 的正文） | ✅ |
| 题型页签齐备（7 种） | ✅ |
| ✏️ 越界数值被前端拦截，且**引擎未被写入** | ✅ |
| ✏️ 合法修改保存后**引擎落盘**，且只读摘要同步变化 | ✅ |
| ➕ checklist 项名可改并落盘（copy → 题目/解题过程/受力图） | ✅ |
| 「恢复默认」两个题型均回到内置默认 | ✅ |
| 页面 JS 无报错 | ✅ |

> 实现要点：esbuild **不能**编译 `.vue`（`--loader:.vue=copy` 只是原样拷贝，组件根本不会挂载——
> 第一版就是这样"通过"了却什么都没测到）。因此新增 `tests/_d130_sfc_build.mjs`，
> 用项目自带 `@vue/compiler-sfc` 真正编译 `script` + `template`，再交给 esbuild 打包。

**2. 修文档编号冲突**：P2 原清单的 `T12`（材料导入）与 P1c 已完成的 `T12`（显示 bug）撞号，
P2 顺延为 **T19/T20/T21**（见 §4 表内注明原编号）。同一编号不指两件事。

**3. 顺手清理**：`serve.py` 三处 `workspace\_engine` 字符串转义告警（`SyntaxWarning`）修为 `workspace/_engine`；
`.gitignore` 增加浏览器回归临时产物规则（SFC 编译/打包/落地页，脚本自行清理）。

**验证**：engine pytest **834 passed**；app build 0 error；selfcheck **21 项全绿**；脱敏通过。
