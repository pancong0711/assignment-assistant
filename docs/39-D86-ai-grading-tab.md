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

### 4.0 D89 增补（2026-10-16）

- ③区「选择作业包(taskpad)」升级为可选**作业包（D89 pack，多作业纸按 tag）**，或退回单张作业纸；
  引擎 `grade --pads-dir` 按 tag 全量匹配（服务端点 `/xxt/grade/ai-run` 接受 `pads[]`）。
- 新增 **⑦ 题库 AI 作答**（AI 相关集中本选项卡）：对题库题目生成参考答案，**不覆盖**、多版本、
  标 `source=ai`+模型+时间戳；端点 `/kb/ai-solve`、CLI `kb ai-solve`（默认 dry-run）。

### 4.0bis D90 增补（2026-10-16）

- 新增 **⑧ Playground**（AI 相关集中本选项卡）：单次调用大模型做试验（**无多轮上下文**）——
  问题 + 图片/文档附件 + **provider/模型选择** → 一次调用 → 回复（KaTeX 渲染）；
  支持批量；问题与答案本地留档（`<ws>/playground/`）+ 文件夹/勾选/移动/删除。
  端点 `/playground/*`、CLI `assist playground …`。

### 4.0ter D92 增补（2026-10-16）

- ③ tags 改**多选下拉**（当前作业学生 tag 集合，**默认全选**）；
- ④ 逐生审核改**左右两栏弹窗**（`StudentReviewModal`）：左=作答图，右上=AI 批语（可**另存修订版**），
  右下=人工批阅 + 模式（none/replace/append/revise）；**AI 原文不被覆盖**；
- ⑤ **去掉手选「报告标注」**；报告类型由逐生模式**自动**决定（5 种，见 docs/04 D92）；
- ⑦ 题库 AI 作答 = kind/章节/题号/模型**真下拉**（空选项保留）+ 题目预览框；`GET /kb/catalog`；
- ① 区模型改**真下拉**，与 ⑦/Playground **共享** `providers[].models[]`。

### 4.1 页面重构

- 「逐生批阅」= **人工批阅**（沿用 D85 逐生预览里的人工批阅栏）：**批语默认留空、分数默认 100**，由教师填写/修改；
- 「批阅」选项卡 → 改名 **「AI 辅助批阅」** 选项卡（AI 设置 + 任务 + 审核 + 报告 + 上传集中在此）。

### 4.2 设置区：provider 统一管理 + 两段式引用（2026-10-15 用户细化）

设计为**两层**：provider 建一次、两段式只做"勾选 + 填模型名"。

**A. Provider 管理区（统一设置，只做一次）**

- 列表式管理，每个 provider 一条：
  `{name, base_url, api_key, models[], batch_support}`；
- 支持 新增 / 编辑 / 删除 / 「清除 key」；
- `base_url` 提供内置默认可下拉（如 Aliyun DashScope OpenAI 兼容模式
  `https://dashscope.aliyuncs.com/compatible-mode/v1`）+ 自定义；
- `batch_support` 标记该 provider 是否支持 batch（用于 §4.11 的开关可用性）。

**B. 两段式批阅设置（只引用 provider）**

| 段 | 控件 |
|---|---|
| 转写（图片→Markdown，多模态） | **勾选 provider**（单选） + **模型名输入框** |
| 评阅（文本→分数/评语） | **勾选 provider**（单选） + **模型名输入框** + `batch` 开关（provider 不支持则置灰并提示） |

- 两段**可以选不同 provider**（例：多模态用 A 家、文本评阅用 B 家）；
- **模型名"填写即记录"**：按 provider 累积为候选列表（去重、上限如 20），
  下次直接下拉勾选；也可从 provider 拉取模型列表（可选增强，失败不阻断）。

**C. 记忆与回显（用户要求）**

- provider 列表、每个 provider 的模型名历史、两段式的 provider/模型选择
  **全部"填写即保存"**，下次打开即回显；无需"保存"按钮；
- 选择项以**勾选/下拉**呈现，避免每次手打 base_url/key。

**D. 密钥（沿用"统一管理"）**

- **每个 provider 各存一份 key**（已拍板），落 `settings.local.secrets.json`（0600，见 §4.12）；
- PWA 只回显掩码 `sk-****abcd`；编辑时**留空 = 不修改**；清除需显式操作；
- 引擎日志/journal 只记 provider 名与 base_url host，绝不记 key。

**E. 兼容/迁移**

- 旧配置 `llm.base_url` / `llm.api_key` / `llm.model` → 迁移为 `providers[0]`，
  两段式默认引用它；PWA 提示一次"已迁移"。

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
- 落点（已拍板）：`settings.local.json → xxt.class_map: {"<courseId>:<classId>": "classes/化工25"}`；
- **按文件名自动建议**（已拍板：用 roster/名单**文件名**与学习通班级名匹配，比目录名更准确），教师确认后写入；
- 该映射同时供 CLI 使用（`assist grade --xxt-class <courseId>:<classId>` 直接解析 class_dir + 作业包）。

**⚠️ 与"成绩单"的区别（用户 2026-10-15 提醒，重要）**：

- `class_map` 只解决"学习通班级 → 本地班级目录"，**与成绩源无关、不涉及覆盖**；
- **一个班级对应多份成绩单**（自定义 / 雨课堂 / 学习通导出…），且**随时间更新/新增**：
  按我们的打分标准是**多份成绩加权**，因此 **不得简单覆盖**；
- 现状已支持该模型：roster store 的 `sources[]`（每源 `uid` / `fileName` / `sheetName` /
  `includedColumns[].weight` / `weight`）+ `merge_scores` 加权平均；同班多次成绩**各自成源、共存**；
- 本单后续只需保证：**导入新成绩单 = 新增一个源（可重名区分/带日期）**，绝不覆盖已有源；
  在「AI 辅助批阅」选项卡里如需展示"某次作业对应哪个 tag"，只做**只读引用**。

### 4.6 作业行显示与操作

- 作业行标题后增加：**按 tag 勾选 AI 批阅**（默认全部勾选）+ **开始 AI 批阅**；
- 增加 **逐生查看**：查看 AI 批阅情况，并支持**修改 AI 批语/评语与分数**；
- 未勾选 AI 批阅的 tag → 走**人工批阅**（页面结构与 AI 查看相同）；
- 所有修改/新增批阅**保存到本机**（尽量自动保存），**支持 LaTeX 语法 → 转图片**（§4.7）。

### 4.7 批阅报告（固定版式，AI / 人工两种）

- 需要一个**固定、专业严谨的版式**（参考旧代码报告），用于"查看批阅情况"时**直接修改**（含 LaTeX 与插入附件如图片）；
- **人工批阅也要形成报告**，版式与 AI 报告一致，但**明确标注「人工批阅报告」**（AI 报告标注「AI 批阅报告」）；
- **两档报告（已拍板）**：
  - **正式报告**（本选项卡）：带标题/分段落/逐题依据，AI 与人工同版式仅标注不同；
  - **轻量批语图**（「预览-学习通」里的人工批阅）：**也要出 PNG**（LaTeX → 公式），
    但不追求正式报告的标题/分段落结构，够用即可；
- **尺寸/字号（已拍板）**：两档 PNG 均为 **A4 纸宽**（210mm）；轻量批语图字号 **小四（12pt）**；
  输出为**长图**（高度随内容增长）。

**实施状态（2026-10-15）**：engine 侧已实现并通过真机出图验证——
`report.py::report_html / html_to_png / render_report_png / render_comment_png`，
CLI `assist render --md|--text --out --kind ai|human`；实测输出 **794px 宽（A4@96dpi）× 长图**，
公式经自托管 KaTeX 渲染；`generate_report(..., kind=...)` 随批阅流程出 md/html/png。

**渲染方法（旧代码确认，2026-10-15）**：`_legacy/2601playwright/src/report_generator.py`

- Markdown → HTML（`markdown` 库 + tables/fenced_code）；
- HTML 模板：`@page A4 + margin 2cm`；`body{font-family:SimSun,…; font-size:12pt; line-height:1.8;
  width:210mm; padding:25mm; margin:0 auto}` ← 与本次拍板一致；
- 公式：**MathJax 3 CDN**（`tex-chtml.js`，inlineMath `$…$` 与 `\(…\)`），
  等 `MathJax.startup.documentState === 'ready'`（超时容忍）+ 1s 缓冲；
- 出图：**Playwright Chromium**，`viewport=794×1123`（≈A4@96dpi），
  **`page.screenshot(full_page=True)` → 长图**，落 `reports/<student>.png`。

**本项目的移植口径**：

- 公式渲染改用**自托管 KaTeX**（与作业纸/预览同源、离线可用；`app/public/katex/` 已入库），
  保留 `$…$`/`\(…\)` 口径；截图前等 KaTeX 渲染完成（`renderMathInElement` 后置标志）；
- 截图实现 = `engine/src/assist/grading/report.py::_html_to_png`（已有 TODO 位），
  复用 Playwright Chromium；**playwright 缺失时降级**只出 md/html 并在结果里提示
  （引擎自身把 playwright 作为可选依赖，与 xxt 同一档）；
- 字体沿用引擎字体注册（SimSun/Noto Sans SC，缺失回退 wqy），长度不受限（长图）。
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
- 已拍板：**不做合并选项**，一律整段替换（本地=平台，语义最简、可重复执行）

### 4.10 AI 批阅两种模式

1. **brute-force（最直接）**：把**作业纸原件图片 + 学生作答图片**都给 LLM → 先确认基本情况
   （题目是否一致、姓名是否一致，防分层作业纸与学生错配）→ 再转录并评阅。最费 token，但**不依赖我们预先整理答案**；
   保留为可选模式（"简单粗暴"兜底）。**该校验默认开启**（已拍板）：不一致只在报告里标注，不阻断评阅。
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

### 4.12 配置与密钥：`settings.local.json` 的边界与拆分（回答"3.1"）

**现状（实测）**：`settings.local.json` 只被读到两类键——
`xxt.*`（`write_allowlist` / `notice_attachment_exts`，未来 + `class_map`）与
`llm.*`（`base_url` / `api_key` / `model` / `transcription_model` / `evaluation_model` +
`transcription/evaluation` 覆盖）；另有 `watermark` 覆盖与字体 `user_cfg` 同源读取。
当前文件 **< 1 KB**（本机实测 136 B）——即使存 10 个 provider + 50 个班级映射也只有几 KB，
**不是体积问题**。

**真正的问题**是"密钥与非敏感配置混在一个文件"，不利备份/同步/排错。建议拆分（已拍板方向）：

| 文件 | 内容 | 权限/红线 |
|---|---|---|
| `settings.local.json` | `xxt.*`（白名单/附件名单/**class_map**）、`watermark`、AI 偏好（模式/provider 勾选）、非敏感开关 | 非敏感；`.gitignore` 已忽略 |
| **`settings.local.secrets.json`** | `llm.providers[]` 的 `api_key`（**每个 provider 各一份**） | 0600；`.gitignore` 已覆盖 `settings.local.*.json`；check-secrets 红名单 |

- PWA 只显示掩码（`sk-****abcd`）；「清除 key」删除对应 provider 的密钥；
- 引擎日志/journal **只记 provider 名与 base_url host**，绝不记 key（沿用 docs/26 §D75-9 口径）；
- 兼容：若仍写在 `settings.local.json` 的 `llm.api_key`，按"单 provider 缺省"读取，并在 PWA 提示迁移。

## 5. 分期实施（进度表，待执行）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| §1 | 班级↔工作区映射（`xxt.class_map` + 按文件名建议 + CLI/PWA） | `xxt/classmap.py` + CLI `xxt class-map` + serve `/xxt/class-map` | ✅ engine/CLI/serve 完成（单测 3 例）；PWA UI 随 §6 |
| §2 | AI 设置区 + **配置/密钥拆分**（多 provider 记忆/勾选/掩码/清除；一般/batch 开关） | `settings_store.py` + `grading/providers.py` + CLI `llm config\|provider` + serve `/llm/*` | ✅ engine/CLI/serve 完成（单测 7 例）；PWA UI 随 §6 |
| §3 | 作业包挂接（tag ↔ taskpad；最简包优先）+ tag 勾选 | `grading/inputs.py`（pads_by_tag / students_with_tags / build_plan） | ✅ engine 完成（PWA UI 随 §6） |
| §4 | engine：`assist grade` 串"批阅下载目录 + 作业包"；两模式；tag 指令；诊断 | `grading/{inputs,prompts,flow}.py` + CLI `--xxt-class/--plan/--mode/--tags/--limit/--dry-plan` | ✅ engine/CLI 完成（单测 5 例；`diagnostics.jsonl`） |
| §5 | 批阅报告（固定版式 md/html/png；AI/人工标注；LaTeX→PNG；上传前生成） | `report.py`（A4/小四/长图 + KaTeX）+ CLI `assist render` | ✅ engine/CLI 完成（真机出图 794px 宽/长图、公式渲染）；PWA 随 §6 |
| §6 | PWA「AI 辅助批阅」面板：provider 管理、班级映射、作业包选择、模式/tags、开始 AI 批阅、一键生成批阅报告；逐生审核复用 D85 人工批阅栏；一键上传全批复用 D85 | `XxetongView.vue` + `engineClient.ts` + serve `/xxt/grade/ai-run|render-drafts` + `grading/drafts.py` + CLI `grade-drafts` | ✅ 代码+tsc/build/selfcheck；serve 端点参数与白名单校验冒烟通过；**D88 §4：面板由 XxetongView 折叠件迁出为独立「AI 辅助批阅」选项卡（`components/AiGradingPanel.vue` 六区 + `GradingView.vue` 挂载，原学习通页临时面板已删除，离线 CLI 块收进「高级 / 离线」折叠）**；真机 AI 跑通待教师机配 key |
| §7 | batch（DashScope）+ 成本/诊断信息 | `grading/llm_batch.py` + CLI `llm batch` | ✅ engine/CLI（默认 dry-run；JSONL+说明+submit/poll/download 诊断；单测 5 例含 key 掩码回归） |
| §8 | 文档与真机验证 | docs/16 §28 解冻记录、docs/15 教师手册章节、docs/04 配置契约、docs/13 状态、HelpView 卡片 | ✅ 文档完成；**教师机实测（配 key 跑一班 + batch）待用户** |

## 6. 拍板与待定（2026-10-15）

**已拍板**
1. ✅ 勾选粒度：**多级列表直接勾到"作业"**（方案 A，逐生/逐 tag 勾选在作业行体现）；
2. ✅ 作业包挂接：**"最简作业包 + tag"为主**，整班包仅 brute-force/核对时用；
3. ✅ 映射表落点：`settings.local.json → xxt.class_map`，**按班级名自动建议**后由教师确认；
   并明确：**成绩单是"多源共存 + 加权"、随更新只增不覆盖**（见 §4.5 警告）；
4. ✅ 二次上传：**整段替换**（不做合并）；
5. ✅ 默认模式：**优化模式为默认**（brute-force 可选兜底）；
6. ✅ 报告：AI/人工**版式一致、仅标注不同**；**人工报告也要 PNG**（轻量档不必正式版式）；
7. ✅ batch 顺序：先做 **一般提交（实时+并发）闭环**，再上 DashScope batch；
8. ✅ 多 provider：**每个 provider 各存一份 key**，PWA 掩码显示，代码/日志严格保密（见 §4.12 拆分）。

**实施补充（2026-10-15）**：AI 结果统一落**本地批阅草稿**
（`grading/drafts.py`：score=total_score、comment=feedback_md 纯文本化、images=[报告 PNG base64]），
因此「逐生审核/修改」与「一键上传全部」直接复用 D85 的人工批阅栏与上传链路；
「一键生成批阅报告」= `/xxt/grade/render-drafts`（可标注 ai/human）。

**已拍板（补充 2026-10-15 第二轮）**
9. ✅ 报告尺寸/字号：两档 PNG 均 **A4 宽**；轻量批语图 **小四（12pt）**；均**长图**；
   渲染方法 = HTML(KaTeX/MathJax) → Playwright `full_page` 截图（旧代码方法已确认，见 §4.7）；
10. ✅ `class_map` 自动建议按 **文件名**匹配（更准确）；
11. ✅ brute-force **默认开启题目/姓名一致性核对**（不一致只标注，不阻断）。

**待定（实施时再定）**
- 轻量批语图是否带"人工批阅"字样水印；
- 模型名历史是否额外提供"从 provider 拉取模型列表"（可选增强）；
- 是否加"默认 provider"标记（新建任务预选）。

## 7. 验收（初拟）

- 能从 AI 选项卡：配置 provider → 关联班级 → 挂接作业包 → 按 tag 跑 AI 批阅 → 逐生审核/改分 →
  生成报告 → 一键上传（只传已批阅，未批阅给 N 提示与一键 AI）；
- 两种模式可切换（brute-force / 优化）；转写与评阅模型可分别配置；
- 报告版式固定、AI/人工可区分、支持 LaTeX（渲染为图片上传）与附件；
- 覆盖语义明确；已批阅默认不重复提交（force 可覆盖）；
- batch 失败时输出足够诊断信息（批次 id/状态/错误原文/JSONL 路径）。
