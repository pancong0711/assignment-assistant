# D130 需求单：按题目来源分型的评阅规则 + AI 生成评阅要点 + 知识点体系 + Assistopia（项目游乐城）

> 日期：2026-10-30
> 状态：**需求已定稿，分阶段实施（P1 先行）**
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

### P2（下一轮）

| # | 任务 |
|---|---|
| T12 | `<ws>/materials/` 导入 PDF/图片 → AI 抽取知识点与逻辑关系 → 教师确认 |
| T13 | `.pptx` 支持（优先 `officecli`，回退 LibreOffice 转 PDF） |
| T14 | summary 批阅接入「本章知识点清单」；启发式提问指向遗漏知识点 |

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

（执行时逐项回填）
