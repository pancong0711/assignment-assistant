# D86 任务需求单：AI 辅助批阅选项卡（两段式 + 报告 + batch）

> 日期：2026-10-15（讨论稿，边讨论边补）
> 状态：需求整合中；确认后按 §5 分期执行。
> 关联：`docs/26-D75-preview-ai-grading-writeops.md`（D75-3 两段式 / D75-9 AI UI 原始设计）、
> `docs/32-D80-grade-upload-collab-test-plan.md`、`docs/37-D84-grade-upload.md`（回传 CLI，已真机验证）、
> `docs/38-D85-...`（人工批阅栏：本地草稿 + 上传）。
> 旧代码蓝本：`_legacy/2601playwright/src/llm/{transcriber,evaluator}.py`（两段式与提示词）。

## 1. 目标

把「批阅」选项卡重构为 **AI 辅助批阅**选项卡：在这里配置两段式 LLM、把学习通班级/作业与
本地「作业纸设计」产物（作业包 + tag）挂接、按 tag 勾选跑 AI 草稿、逐生审核（可改 AI 批语/分数、
也可纯人工批阅）、生成**统一版式**的批阅报告（AI 报告 / 人工报告分别标注），最后**一键上传**
（只上传已批阅的，未批阅的提示剩余人数并可从弹窗直接一键 AI 批阅）。

同时保留两种 AI 批阅模式：**brute-force（作业纸原件+作答图都交给 LLM）** 与
**优化模式（我们提供题目/参考答案/评分点 + tag 指令）**；batch（Aliyun）作为可选加速/降本通道。

## 2. 现状盘点

| 能力 | 现状 |
|---|---|
| 两段式 engine | ✅ `assist grade --task --images`：transcribe（多模态，图→Markdown+quality）→ evaluate（文本→分数/评语/逐题依据，**LLM 只发现、Python 算分**）→ report（md/html）；产物 `classes/<dir>/grading/<task>/{transcripts,evaluations,reports}` |
| 模型配置 | ✅ `llm.transcription` / `llm.evaluation` 可各自覆盖 base_url/api_key/model；`batch_chat` 目前是**线程池并发**，非 provider batch |
| 批阅下载 | ✅ `assist xxt review-download` → `<xxt_home>/pages/review/<classId>/<workId>/`（图片名 `姓名_班级+作业_pNN.jpg`，**可直接被 `group_images` 解析**）+ `students.json`（workAnswerId/分数/两栏批语） |
| 回传 | ✅ D84：`grade-upload`（批语/图片/分数/提交，白名单+dry-run）、`mark-submitted`；D85：本地草稿 + PWA 人工批阅栏 |
| PWA 入口 | ❌ 无 AI 设置区、无「开始 AI 批阅」、无逐生审核预填、无报告生成/上传编排 |
| 报告 | ⚠️ 只有 md/html；**无 PNG**（上传评语图片需要）；人工批阅报告不存在 |
| 班级↔工作区关联 | ❌ `class_dir` 只是 taskpad 里的自由字符串（如 `classes/化工25`），与学习通 `courseId/classId` **无映射** |
| batch | ❌ 未实现（需调研 DashScope batch 提交/轮询/下载） |

## 3. 关键数据模型（讨论确认）

- **tag**：来自「班级与标签」选项卡的带 tag 名单（`roster tag` 产物 `tagged-roster.xlsx` / `roster.xlsx` 的 `tag` 列）；
- **作业包**：`tasks/<id>.taskpad.json`，`items[].tag` + `target_tag` 决定"一份作业纸对应一个 tag"；
- **整班作业包**：batch 包 = `classes/<dir>/roster/roster.xlsx`（带 tag）+ `tasks/<id>.taskpad.json` ×N + `sheets/<id>.html`（每生一份按 tag 选变体）——见 `app/src/lib/variantBatch.ts`；
- **token 角度**：评阅需要的是「该生 **tag** 对应的那份作业纸的题目/参考答案」，**不需要整班所有变体** → 见 §4.4；
- **xxt 关联**：需要一张映射表把 `(courseId, classId)` → workspace `class_dir`（从而拿到该班 roster/tag 与 taskpad），见 §4.5。

## 4. 需求细节（2026-10-15 用户讨论）

### 4.1 页面重构

- 「逐生批阅」= **人工批阅**（沿用 D85 逐生预览里的人工批阅栏）：**批语默认留空、分数默认 100**，由教师填写/修改；
- 「批阅」选项卡 → 改名 **「AI 辅助批阅」** 选项卡（AI 设置 + 任务 + 审核 + 报告 + 上传集中在此）。

### 4.2 设置区（两段式 LLM）

- 字段：provider/base_url、api_key、（可选）转写模型、评阅模型、batch 开关；
- **每次填写默认保存**、自动记忆、下次打开即回显；支持保存多个 provider 并**勾选当前使用**；
- key 安全沿用 docs/26 口径：`type=password`、引擎写入 `settings.local.json`(0600)、只回显 `sk-****abcd`、日志只记 provider 名/base_url host；提供「清除 key」。

### 4.3 AI 批阅班级范围（白名单的"AI 版"）

- 与「发布-学习通」的白名单 UI 类似，但语义是**允许跑 AI 批阅的班级**；
- 讨论点：**多级列表直接勾选到"作业"**，还是先勾班级、再在班级内勾作业？
  - 方案 A（推荐）：班级 → 作业 两级可勾选（作业行即 §4.6 的显示单元，勾选状态即"是否参与 AI/批量上传"）；
  - 方案 B：仅班级白名单，作业级勾选放在 §4.6 的作业行（两处都能取消）。

### 4.4 作业包挂接（省 token 的核心）

每批学习通作业（作业行）后面要挂接"本地作业纸设计的产物"：

- 候选一：**最简作业包 + tag**（`tasks/<id>.taskpad.json` ×N，每个 tag 一份）→ 评阅时按学生 tag 取对应题目/参考答案/评分点；
- 候选二：**整班作业包 json**（batch 包，含每生作业纸）→ 信息全但**冗余、token 贵**；
- 倾向：**候选一**（省 token）；整班包只在"brute-force 模式"或需要逐生核对版式时用；
- 需参考旧代码两段式的提示词构造（见 §4.10）。

### 4.5 班级 ↔ 工作区关联（新增，缺少的一环）

- 目标：在学习通班级/作业行上直接看到并用上"该班的 tag/作业纸"；
- 设计候选：`settings.local.json → xxt.class_map: {"<courseId>:<classId>": "classes/化工25"}`（或 workspace 内 `classes/_xxt-map.json`），PWA 提供"关联班级目录"的选择/自动建议（按班级名相似度）；
- 该映射同时供 CLI 使用（`assist grade --xxt-class <courseId>:<classId>` 直接解析 class_dir + 作业包）。

### 4.6 作业行显示与操作

- 作业行标题后增加：**按 tag 勾选 AI 批阅**（默认全部勾选）+ **开始 AI 批阅**；
- 增加 **逐生查看**：查看 AI 批阅情况，并支持**修改 AI 批语/评语与分数**；
- 未勾选 AI 批阅的 tag → 走**人工批阅**（页面结构与 AI 查看相同）；
- 所有修改/新增批阅**保存到本机**（尽量自动保存），**支持 LaTeX 语法 → 转图片**（§4.7）。

### 4.7 批阅报告（固定版式，AI / 人工两种）

- 需要一个**固定、专业严谨的版式**（参考旧代码报告），用于"查看批阅情况"时**直接修改**（含 LaTeX 与插入附件如图片）；
- **人工批阅也要形成报告**，版式与 AI 报告一致，但**明确标注「人工批阅报告」**（AI 报告标注「AI 批阅报告」）；
- 报告应在上传**之前**生成：即按钮顺序为 **一键生成批阅报告 → 一键上传批阅报告**；
- 与「预览-学习通」里的人工批阅可以**不同风格**（本处 = 报告风格）。

### 4.8 一键上传全部（含"未批阅"提示）

- 放在该显示块**上方**；上传**全部已批阅**（AI + 人工）的批语/评语与打分；
- **既无 AI 也无人工作业的 → 不上传**，并提示「尚余 N 名学生未完成批阅」，可点击**查看这些未批阅作业**；
- 该弹窗内提供 **一键 AI 批阅**。

### 4.9 覆盖语义（回答用户提问：二次提交会覆盖吗？）

会覆盖，且当前实现是**整段替换**而非追加：

- 作业批语：`UE.setContent(html)` → **整段替换**（原批语里已有的图片不会保留，除非我们重新带上）；
- 总分：写 `#tmpscore` → **覆盖**；每题分同理（逐题输入框覆盖）；
- 提交：`markAction(1)` 再次提交 → 平台以本次内容为准；
- **幂等保护**：`grade-upload` 若读到该生已是「已批阅」状态，默认**拒绝**（需 `--force` / PWA「强制覆盖上传」）。
- 待确认：是否需要"**合并**（保留原批语再追加）"选项？（默认建议仍是替换，保持本地=平台）

### 4.10 AI 批阅两种模式

1. **brute-force（最直接）**：把**作业纸原件图片 + 学生作答图片**都给 LLM → 先确认基本情况
   （题目是否一致、姓名是否一致，防分层作业纸与学生错配）→ 再转录并评阅。最费 token，但**不依赖我们预先整理答案**；
   保留为可选模式（"简单粗暴"兜底）。
2. **优化模式（默认）**：我们提供该 tag 的**题目 + 参考答案/评分点**（来自作业包），
   LLM 只吃"作答转录 + 题目/答案"→ 不需要 LLM 先自己作答；配合 tag 差异化评阅指令（旧代码口径）：
   - `copy/copyonly/copysp`：只查抄写完整性，不评推导/计算/精度；
   - `summary`：侧重归纳与概念；`translation`：翻译准确性；`innovation`：创意与独立；`distinguish`：概念区分与论证；
   - 旧代码提示词要点（迁移参考）：**LLM 只"发现"（结构化 JSON：question_match/逐题 errors+guidance/has_diagram/has_signature/summary/strengths/weaknesses），算分由 Python 做**；转写提示词强调 LaTeX、精度（小数/指数/希腊字母）、JSON 转义。
   - 成本策略：题目/答案做成**共享前缀**（prompt caching 友好）、图片压缩、结构化 JSON 输出。

### 4.11 batch（Aliyun DashScope）

- 目标：评阅段（纯文本）走 batch 以降低单价；转写（多模态）走实时；
- 需调研：DashScope batch 任务接口（JSONL 生成 → 提交 → 轮询 → 下载 → 失败重试/断点续跑）、多模态是否支持 batch；
- 先设计好 **base_url / api_key / 模式开关**（一般提交 vs batch 提交），**在教师电脑上实测**（本机无法测）；
- 因此代码要**输出足够诊断信息**（请求 id、批次 id、状态、错误原文、可复制的 JSONL/日志路径），便于教师把报错发给开发者。

## 5. 分期实施（进度表，待执行）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| §1 | 班级↔工作区映射（`xxt.class_map` + PWA 关联 UI + CLI `--xxt-class`） | `settings`/`workspace` + PWA | ⏳ |
| §2 | AI 设置区（多 provider 记忆/勾选/掩码/清除 + 一般/batch 开关） | `settings.local.json` schema + PWA 设置区 + serve 端点 | ⏳ |
| §3 | 作业包挂接（tag ↔ taskpad；省 token 的最简包优先）+ tag 勾选 | PWA + engine 解析 | ⏳ |
| §4 | engine：`assist grade` 串"批阅下载目录 + 作业包"；两模式（brute-force / 优化）；tag 指令；诊断信息 | `grading/*` + CLI | ⏳ |
| §5 | 批阅报告（固定版式 md/html/png；AI/人工标注；LaTeX→PNG；上传前生成） | `grading/report.py` + render CLI + PWA | ⏳ |
| §6 | PWA「AI 辅助批阅」选项卡：开始批阅（job/进度）、逐生查看/修改、一键生成报告、一键上传全部（含未批阅提示 + 弹窗一键 AI） | `XxetongView.vue` + serve | ⏳ |
| §7 | batch（DashScope）+ 成本/诊断信息 | `grading/llm_batch.py` + CLI | ⏳ |
| §8 | 文档与真机验证（教师机实测两种提交模式） | docs/13/16/39 | ⏳ |

## 6. 待讨论 / 待拍板

1. §4.3 勾选粒度：多级列表勾到"作业"（A）还是"班级白名单 + 作业行勾选"（B）？
2. §4.4 作业包挂接：确认"最简作业包 + tag"为主、整班包为辅？
3. §4.5 映射表落点：`settings.local.json` 还是 workspace 文件？是否要自动建议（班级名相似度）？
4. §4.9 二次上传：确认"整段替换"；是否需要"合并（追加）"选项？
5. §4.10 默认模式：优化模式为默认、brute-force 作为可选？
6. §4.7 报告：AI 与人工报告版式完全一致（仅标注不同）？人工报告是否也要导出 PNG？
7. §4.11 batch：先做"一般提交（实时+并发）"闭环，再上 batch？（建议是）
8. §4.2 多 provider 记忆：key 是每个 provider 各存一份，还是共用一份？（建议各存一份，均掩码）

## 7. 验收（初拟）

- 能从 AI 选项卡：配置 provider → 关联班级 → 挂接作业包 → 按 tag 跑 AI 批阅 → 逐生审核/改分 →
  生成报告 → 一键上传（只传已批阅，未批阅给 N 提示与一键 AI）；
- 两种模式可切换（brute-force / 优化）；转写与评阅模型可分别配置；
- 报告版式固定、AI/人工可区分、支持 LaTeX（渲染为图片上传）与附件；
- 覆盖语义明确；已批阅默认不重复提交（force 可覆盖）；
- batch 失败时输出足够诊断信息（批次 id/状态/错误原文/JSONL 路径）。
