# D98 任务需求单：两段式转录/批阅的批量隔离 + 执行报告 + skill 规程

> 日期：2026-10-18（讨论稿，边讨论边补）
> 状态：**讨论定稿（2026-10-18），按 §8 执行顺序开工**；每批完成即更新进度表。
> 关联：`docs/39-D86-ai-grading-tab.md`（两段式/批阅）、`docs/43-D90-llm-playground.md`（Playground batch）、
> `docs/45-D92-grading-report-modes.md`（报告）、`_legacy/2601playwright/src/llm/{transcriber,evaluator}.py`（旧蓝本）。
> engine：`grading/{transcribe,evaluate,llm,llm_batch,flow}.py`、`playground/ask.py`。

## 1. 背景与用户裁决

用户主张（2026-10-18）：

- 批阅采用**两段式**：转录（读图，多模态）+ 批阅（只吃文字）。**批阅阶段不应再看图**。
- 转录是**逐个学生**的操作（不是统计群体），要求：**不要把前一张图/前一位学生的上下文带到下一次转录**。
- 同一学生**多页不做逐页独立再合并**，而是放进**同一次**转录请求（裁决 1）。
- skill 放仓库 **`skills/`** 目录（裁决 2）。
- 批阅需**严谨**：错误位置、正确之处、**为什么这样判断**、启发式提问；要补回（裁决 3）。
- 希望 agent 用 **subagent** 并行/隔离不同转录/批阅任务；并需要 **subagent 不可用时的兜底/backup**，以及**执行报告**。

## 2. 现状核查（2026-10-18，代码为准）

| 事实 | 位置 | 结论 |
|---|---|---|
| 转录是**每学生一次独立请求**，多页同一次请求 | `grading/transcribe.py:transcribe_student`、`flow.py:_run_transcribe` | ✅ 已满足"学生间隔离 + 同生多页合并" |
| `LLMClient.request()` **无状态**，每次全新 `messages`，无 session/历史 | `grading/llm.py:99` | ✅ 请求级隔离成立 |
| Playground batch = **全局附件 + 多个问题**（不是每条各附各的） | `playground/ask.py:batch` | ❌ 不支持"每条自带图/问题" |
| Playground 逐条模式：**同一组附件对每条重复拼** | 同文件 `one()` | ⚠️ 多任务场景下会"重复污染" |
| Playground `--combine`：一次请求多问题，附件发一次 | `_batch_combined` | ✅ 省 token，但是"合并"不是"隔离" |
| 评阅 batch 只做**评阅段**，JSONL 每条仅文字 | `grading/llm_batch.py:build_jsonl` | ❌ 转录段无 batch 通道 |
| 评阅 prompt 仅 `json_object`，**无 json_schema** | `grading/evaluate.py:analyze` | ⚠️ 较旧代码退步（旧版有 `json_schema`） |
| 批阅无"引用学生原文出处"、无"置信度" | `grading/evaluate.py` | ❌ 幻觉防线不足 |
| 无统一 `batch-report.json` | — | ❌ 缺执行报告 |

## 3. 关键设计判断：隔离发生在"请求层"，不发生在"会话层"

### 3.1 先认清 agent 的默认运行模型

主流 agent 是**长会话全量重放**：

```
messages = [system, user1, assistant1, user2, assistant2, ...]   # 每次调用都重放全部历史
```

因此若在同一会话里"转录学生 A → 转录学生 B"，**B 的请求里必然带着 A 的图与转录**。
这是 agent 的默认行为，不是 bug；**纯靠 skill 文本"请清空上下文"是不可靠的**
（多数 agent 没有可靠的"清空/新会话"原语，且无法验证是否执行）。

### 3.2 隔离的一般方法（用户问的"还没看明白"点）

- LLM API **无状态**；是否串味只取决于该次请求的 `messages`。
- 因此"不重复传上次上下文"的**一般方法** = **每条任务独立构造 messages + 独立请求**。
  这一步发生在 **HTTP 请求层**（`LLMClient.request` 每次全新 messages、无 session），
  **与 agent 的会话层无关**。程序并发（线程池）即"进程内 subagent"，不依赖 agent 框架。

### 3.3 subagent 的能力前提（决定 skill 能否"让 agent 自己隔离"）

agent 要**原生**读图/批阅且不串味，框架必须提供以下至少一种原语：

| 原语 | 隔离效果 | 说明 |
|---|---|---|
| subagent / 子会话（每次新上下文） | ✅ 真隔离 | skill 可规定"每学生一个 subagent" |
| 新任务/run 隔离 | ✅ 真隔离 | 部分框架 |
| 无状态 tool 调用（LLM 调用封装成 tool） | ✅ 真隔离 | 实质回到"程序调 API" |
| `clear`/`/new` | ⚠️ 靠自觉 | 少数框架，无法验证 |
| 仅长会话 | ❌ 必然污染 | 多数默认行为 |

**结论：框架无 subagent/新 run 原语时，纯 skill 文本无法保证隔离——必须降级到程序 batch。**

### 3.4 无 API key 的回环问题（套餐型 agent）

用户场景：只用某 agent 套餐（模型含多模态），**套餐不提供 API key**，
无法走 `httpx.post(base_url/chat/completions)`。于是出现"程序能否回调 agent 本身"的问题。

**本质**：`assist` 目前**只有 HTTP API + api_key 一条路径**，没有任何"回调外部 agent"的入口。

**三种 agent 能力，对应三种路径：**

| agent 能力 | 路径 | assist 角色 |
|---|---|---|
| 套餐暴露本地 OpenAI 兼容端点 | 直接配 provider（零改造） | 正常调 LLM |
| agent 有 CLI/命令入口 | 新增 provider 类型 `command`（subprocess 回环，每次新进程=天然隔离） | 调 agent CLI |
| 只有交互会话 + subagent | **agent 自己转录/批阅，assist 只做 plan/collect** | 清单 + 校验 + 算分 |

**核心判断（重要）**：
- 有 key：`用户/agent → assist → httpx → 模型`（程序主动调模型）；
- **无 key：LLM 能力在 agent 身上，不在程序里** → assist 不应"召唤" agent 的模型，
  而应**降级为纯工具**：`plan`（生成待办清单+填好的提示词）→ agent 做 LLM 部分 →
  `collect`（校验结构 + Python 算分 + 执行报告）。
- subagent 是**最好的并行/隔离方案**，但依赖框架；`plan/collect` **不依赖 subagent**，
  是更普适的兜底。

### 3.5 由此新增的"无 LLM 也可用"命令（B7）

| 命令 | 作用 |
|---|---|
| `assist grade plan --items batch.json --out task-list.json` | 生成每生图片清单/输出路径/**填好的转录提示词**；不调模型 |
| `assist grade collect --task-list ... --transcripts-dir ...` | 校验 agent 写回的 JSON（schema）+ 生成 `batch-report.json`；不调模型 |
| 评阅同理：`plan` 给批阅提示词，agent 做，`collect` 校验 + **Python 算分** |

这样即使**完全无 API key**，整条链路也能跑通：agent 做 LLM 部分，assist 做确定性部分。

### 3.6 subagent 的诚实边界

- subagent 依赖框架；不可用时**不追求"程序召唤 agent"**，而是"程序让位、agent 干活、程序校验"；
- 隔离的最终保证 = **每个学生的输入是一个独立文件/独立命令调用**（agent 每次只处理一个 task 文件），
  而不是依赖 skill 文本劝说 agent 清空会话。

### 3.7 用户定调：逐条 agent 亲自做 = 高风险，默认禁止

用户判断（2026-10-18 第四轮）：**让 agent 一条一条亲自转录/批阅风险太高**——不可控、
不可复现、token 重复累积、难审计。故：

- **正常路径只有两条**：① agent/套餐有 **CLI 或本地端点** → `assist` 正常转录批阅；
  ② agent 有 **subagent** → subagent 并行/隔离。
- **逐条降级 = 最后手段**，需显式开关 + 强警告，**默认关闭**。

**路径优先级（写入 skill）：**

```
1. type=command / 本地 OpenAI 兼容端点（有 CLI 接口）→ 首选，可控可复现
2. subagent（无 CLI 但有 subagent）→ 次选，框架保证隔离
3. plan/collect（兜底，非默认）
4. agent 逐条亲自做 → 禁止（除非 --allow-manual 且强警告）
```

### 3.8 能力探测：agent 必须先确认有无 subagent / CLI

**两层探测：**

1. `assist doctor` 增加能力项（人类可读 + `--json`）：
   - `llm.api`：是否有可用 provider（base_url + key）
   - `llm.command`：是否有 `type=command` 的 provider
   - `agent.cli`：探测常见 agent CLI 是否安装（opencode/codex/claude…）
2. skill 开头写好探测清单，agent 依次回答：
   1. 是否有 subagent？→ 模式 A
   2. 是否可调用 CLI/本地端点？→ 模式 B
   3. 都没有 → **停止并告知用户如何启用**（不自动降级逐条）

**"如何启用"指引必须具体**（subagent 在哪开、`type=command` 怎么配），
而不是让 agent 自己想办法。

### 3.9 `type=command` provider 设计（让 CLI 接口可用）

```jsonc
{"name": "本地agent", "type": "command",
 "cmd": ["opencode", "run", "--model", "{model}", "--json"],
 "input_mode": "stdin",        // stdin 收 JSON；或 "arg"
 "output_mode": "stdout-json", // 解析 stdout JSON；或 "stdout-text"
 "timeout_s": 300,
 "supports_images": true}
```

- **每次 subprocess 新进程 = 天然隔离**（首选路径的关键优点）；
- 图片：优先**写临时文件传路径**（省内存），agent 不支持路径时回退 base64；
- 失败诊断：超时/非零退出/输出解析失败都要可读；
- 安全：command 只从 workspace 配置读，不来自网络。

### 3.10 结论

- **Python 逐条独立请求 = 主干（兜底且 100% 结构性隔离）**；
- **subagent = agent 侧并行/隔离编排**，前提是框架支持；
- 两者**共用同一份"每条独立"输入契约与执行报告**；
- skill 的职责是**能力探测 + 选择模式 + 禁止危险模式**，而不是假设 agent 会自觉。

## 4. 需求细节

### 4.1 统一 `items` batch 形态（解决"每条自带图+问题、互不重复"）

输入（JSON 或 JSONL）每条：

```jsonc
{"id": "stu001", "question": "请转录这份作业", "images": ["a1.jpg", "a2.jpg"],
 "system": "可选，覆盖默认", "model": "可选"}
```

- 每条**自带** `question` 与 `images`；**禁止**把上一条的题干/图片拼进下一条；
- 同一学生多页 → 一条 item 的 `images[]` 多张（裁决 1）；
- 适用于：Playground 批量、转录 batch、评阅 batch（评阅 item 的 `question`=题目+参考答案，`images` 空）。

### 4.2 转录 batch（新增通道）

- 当前转录逐生串行；新增 batch：`items` 模式 + 受控并发；
- 每生一条 item，`images` 为该生全部页；
- 产出仍落 `transcripts/<student>.json`（契约不变），并记录 usage。

### 4.3 批阅严谨性（裁决 3，补回）

在 `ANALYSIS_PROMPT`/schema 中补：

1. `response_format` 用 **`json_schema`**（严格结构），替代单纯 `json_object`；
2. 每处 `errors[]` 增加 **`evidence`**：引用学生转录中的**原文片段**（用于核对，治幻觉）；
3. 每题增加 **`reasoning.note`**（为什么这样判断，保留）与 **`confidence`**（high/medium/low）；
4. `low` 置信度：报告单列"不确定项"，**默认不计入扣分**；
5. `guidance` 保持苏格拉底式（不直接给答案）；
6. 报告新增"哪里对/哪里错/为什么"三段式，便于教师与 AI 审核。

### 4.4 执行报告（必须）

每次 batch 产出 `batch-report.json`（与产物同目录）：

```jsonc
{"kind": "transcribe|evaluate|playground", "startedAt": "...", "finishedAt": "...",
 "total": 30, "ok": 28, "failed": 2, "concurrency": 3,
 "items": [{"id": "stu001", "status": "ok", "ms": 3210, "usage": {...},
            "out": "transcripts/stu001.json"},
           {"id": "stu003", "status": "fail", "error": "...", "images": ["..."]}]}
```

- CLI 结束打印摘要 + 报告路径；`--json` 输出机器可读；
- 失败项可 `--only-ids` 重跑。

### 4.5 skill（`skills/` 目录）

用 Markdown 写"操作规程 + 边界"，**不替代代码**：

| skill | 作用 |
|---|---|
| `skills/transcribe.md` | 每次转录**独立会话**，禁止同会话读第二个学生；多页同一学生一次读；产出 `transcripts/<student>.json` |
| `skills/evaluate.md` | 只吃**文字转录+题目+答案**，不得看图；必须给 `evidence/confidence`；不得直接算分 |
| `skills/grade-orchestrate.md` | 两段式顺序、目录契约、失败重跑、执行报告解读 |
| `skills/batch-isolation.md` | 说明"独立请求=结构性隔离"、subagent 与兜底的关系 |

#### 4.5.1 skill 必须写"能力探测 + 降级"，而不是一句"请隔离"

```
第 1 步 探测：agent 是否支持 subagent / 新 run？
  ├─ 是 → 模式 A（subagent 原生）
  └─ 否 → 模式 B（程序 batch，兜底且默认推荐）

模式 A（subagent 原生）：
  - 每个学生一个 subagent；其输入**只含**该生图片路径 + 转录指令；
  - 输出必须写 transcripts/<student>.json；
  - 主 agent **只读 batch-report.json**，不读 subagent 对话历史。

模式 B（程序 batch）：
  - 主 agent 只负责：生成 items JSON → 运行 `assist ... batch` → 读 batch-report.json；
  - **禁止**主 agent 自己读图/复述转录正文（避免正文进入长会话）。

模式 C（主会话直做）：❌ skill 明令禁止用于多学生/多任务（无隔离保证）。
```

#### 4.5.2 关键纪律：主会话只读"报告"，不读"正文"

- 转录正文、批阅正文一律**落文件**（`transcripts/`、`evaluations/`）；
- 主 agent 在长会话中只接收 `batch-report.json` 摘要（成功/失败/路径）；
- 这样即使 agent 是长会话，**学生内容也不会累积进上下文**（正文从未进入主会话）。

## 5. 数据/兼容

- `transcripts/*.json`、`evaluations/*.json` 结构在前向兼容基础上**新增字段**（`evidence/confidence`）；
- 旧评阅 JSON 无新字段 → 读入时补默认（`confidence="high"`、`evidence=""`），不破坏报告；
- `json_schema` 不被 provider 支持时 → **自动回退** `json_object`（记录到 diagnostics）。

## 6. 验收标准

1. `items` 模式：每条请求的 `messages` **不含**其它条的题干/图片（单测断言）；
2. 转录 batch：30 生并发跑完，`batch-report.json` 条目齐全、失败可重跑；
3. 评阅：`json_schema` 生效；`evidence` 能对上学生原文；`confidence=low` 默认不计扣分；
4. 无 subagent 时：程序并发即兜底，行为与 subagent 编排产出一致；
5. 全量 pytest 绿 + 脱敏扫描绿。

## 7. 决策定稿（2026-10-18，用户逐条拍板）

### 7.1 转录/批阅隔离与路径

- **逐条 agent 亲自做 = 高风险，默认禁止**（不可控/不可复现/token 重复/难审计）；
- 正常路径仅两条：**① type=command 或本地端点（CLI 接口）**、**② subagent**；
- **路径优先级**：`type=command/本地端点` > `subagent` > `plan/collect`（兜底）> 逐条（禁止）；
- **首选路径失败不自动降级**（避免质量悄悄变化）：停止并提示用户可手动切换；
- 同一学生多页**同一次**转录请求（已确认）。

### 7.2 能力探测

- `assist doctor` 增加能力项，**输出人类可读 + `--json`**（用户确认够用）：
  `llm.api`、`llm.command`、`agent.cli`；
- skill 开头写探测清单；**没有 subagent/CLI 时停止并告知如何启用**，不偷偷逐条。

### 7.3 `type=command` provider

- 通用契约：**stdin 收 JSON、stdout 出 JSON**；为常见 CLI 提供少量 adapter；
- 图片：**临时文件路径优先**，不支持时回退 base64；
- 并发**默认 2**、可配 `--concurrency`；
- **模型可更换，默认用 agent 当前模型**（`--model` 缺省则不传）；
- 两段可分别绑定（`stages.transcription` / `stages.evaluation` 各自指定 command）；
- **单条失败：标记该条失败、继续其余任务**（用户确认 6），进执行报告；
- 安全：command 只从 workspace 配置读。

### 7.4 plan/collect（保留，不删）

- 保留为**非默认兜底**；必须**说明清楚"现在发生了什么"**（用户确认 4）：
  命令输出明确列出"哪些学生的正文需要 agent 自己做、产物应写到哪里、如何校验"；
- 不调模型，只生成清单/校验/算分/报告。

### 7.5 批阅严谨性

- 补回 `json_schema`（provider 不支持则回退 `json_object` 并记 diagnostics）；
- `errors[].evidence`（引用学生原文）、每题 `confidence`（high/medium/low）；
- `confidence=low` 默认不计入扣分，报告单列"不确定项"；
- `guidance` 保持苏格拉底式（不直接给答案）；报告含"对/错/为什么"。

### 7.6 API key 路径（含 Aliyun batch）必须 CLI 完整可用

用户确认：**通过 api_key 调 LLM（包括阿里云 batch）的功能，CLI 里需要实现**——这是另一类用户的选择。

**现状核查（2026-10-18）：**
- `llm provider/config` ✅；实时 `grade` 两段式 ✅；
- `llm batch` 的 `--submit/--poll/--download` 有实现，但属**本机未实测**；
- ❌ **下载结果没有"回灌"到 `evaluations/*.json` 的函数** → batch 结果无法变成评阅产物，链路断裂；
- ❌ batch 只支持评阅段（纯文本），转录段无 batch；
- ❌ 无 `batch-report.json`、无失败重跑。

## 8. 执行顺序（逐批，完成即更新）

| 批 | 内容 | 状态 |
|---|---|---|
| **B1** | `items` 统一输入契约 + 校验（每条独立，禁跨条污染）+ 单测 | **✅ 2026-10-18**（`grading/items.py`，5 测试） |
| **B2** | `doctor` 能力探测（llm.api / llm.command / agent.cli，JSON） | **✅ 2026-10-18**（`providers.capabilities`，4 测试） |
| **B3** | `provider type=command`（stdin JSON→stdout JSON、临时文件传图、失败标记继续、模型可换） | **✅ 2026-10-18**（`provider_command.py` + LLMClient 分支 + CLI 参数，9 测试） |
| **B4** | 转录 batch 通道（items、并发、`batch-report.json`、失败可重跑） | **✅ 2026-10-18**（`batchrun.py`+`transcribe_batch`，flow 已接入，4 测试） |
| **B5** | 批阅严谨性（json_schema/evidence/confidence/low 不计分） | **✅ 2026-10-18**（schema+EVIDENCE_INSTRUCTION，5 测试） |
| **B6** | **API key 全链路 CLI**：`llm batch` + **结果回灌 evaluations** + `engine restart` | **✅ 回灌完成**（`apply_results`+`--apply`，3 测试）；Aliyun 真机待用户验证 |
| **B7** | `grade plan/collect`（兜底，不调模型，讲清"发生了什么"） | **✅ 2026-10-18**（`plan_collect.py` + `grade-plan` 命令，3 测试） |
| **B8** | `skills/` 五份规程（transcribe/evaluate/grade-orchestrate/batch-isolation/provider-setup） | **✅ 2026-10-18**（+README 共 6 文件） |
| **B9** | 文档（docs/13、12、README、使用说明） | **✅ 2026-10-18** |

## 9. 前几轮"已发现未修"合并项（一并执行）

| 来源 | 项 | 归入批次 |
|---|---|---|
| P3 | `engine restart`（非 launcher 场景） | B6 附带 |
| P3 | `notice-send`/`work-publish --json-out` + 发布后回读摘要 | **✅**（本轮） |
| P3 | `kb ai-solve` 并发 | **✅**（本轮：复用 batchrun，`--concurrency`） |
| D98§2 | Playground batch 支持 `items`（每条自带图+问题） | B1/B3 后 |
| D98§2 | `*-example.xlsx` 双通道策略 | B9 文档说明 |
| 早前 | 转录 usage/token 记录（省 token 度量） | **✅**（本轮：LLMClient.usage + flow 汇总 + grade 打印） |

## 10. 验收（每批）

1. 单测覆盖"每条请求不含他条题干/图片"；
2. `batch-report.json` 条目齐全、失败可重跑；
3. `type=command` 失败标记继续、模型可换、临时文件传图；
4. API key 路径：`llm batch` 生成/提交/轮询/下载/**回灌**闭环；
5. `confidence=low` 不计分、`evidence` 可核对；
6. 全量 pytest 绿 + 脱敏扫描绿。
