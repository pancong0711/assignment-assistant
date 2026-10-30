# D127 需求单：作业包为中心的批阅流水线 + 结构化批语/报告

> 日期：2026-10-30
> 状态：**已执行完成（2026-10-30）**
> 关联：`docs/69-D119`（批阅产物目录）、`docs/71-D121`（班级目录绑定）、`docs/74-D125`（分步批阅）、`docs/75-D126`（逐生审核/报告拆分）

## 0. 一句话

把「作业包」确立为**唯一作业批次载体**（单张作业纸也入包），并据此重排批阅流水线：
**转写只给图片 → 评阅只给该生 tag 那张作业纸 → 报告纯组装（不调 LLM）**。

## 1. 现状审查（全局）

### 1.1 已确认的操作流程（用户口径）

```
① 设计作业包（含 N 张作业纸，每张 target_tag 对应一个分层）
② 班级学生按成绩打 tag
③ 生成全班学生作业纸   ← 应使用「当前作业包」
④ 发布通知/作业
⑤ 学生作答 → 提取作答图片
⑥ AI 转写 → AI 评阅 → 人工审核 → 生成报告 → 一键上传
```

### 1.2 审查发现的偏差

| # | 问题 | 证据 |
|---|---|---|
| **P1** | **整班作业纸不认作业包**：按 tag 从**全库已保存作业纸**反推 | `RosterView.vue: partitionStudentsByTag(roster.students, pad.savedJsons(), fallbackId)` |
| **P2** | **批阅产物按作业纸 id 落目录**，而非作业包 | `flow.grading_dir(): grading/<task.id>`，`task` 是单张 pad |
| **P3** | 取题逻辑**四套各写各的**（整班预览 / 作业纸生成 / 变体 zip / 批阅 plan） | `inputs.pads_by_tag()` vs `RosterView` vs `variantBatch` |
| **P4** | 转写**不知道题目**，输出是一坨 markdown（题目/作答不分） | `TRANSCRIPTION_PROMPT` 只要求 `{markdown, quality}` |
| **P5** | 报告**由引擎拼固定版式**，但它是「批阅流水线的一步」且默认随批阅执行 | `grade.steps` 默认 `[transcribe, evaluate, report]` |
| **P6** | `append` 与 `replace` **生成完全相同的报告** | `_mode_report_md`: `if hm in ("append","replace")` 同一分支 |
| **P7** | 测试配置用 HTTP 400 表达业务失败，前端只显示 `HTTP 400` | `serve.py: self._json(..., 200 if ok else 400)` |
| **P8** | `errors[]` 无 `knowledge` 字段（旧题库已有 `related` 列未被用上） | `EVALUATION_SCHEMA` / `kb_io.COLUMNS` 含 `related` |

## 2. 决策（已拍板）

| # | 决策 |
|---|---|
| **D1** | **作业包是唯一批次载体**：单张作业纸也必须属于某个包；任何批阅都必须指向 `packId` |
| **D2** | 批阅产物目录改为 `grading/<packId>/`；**不自动迁移**老目录，提供迁移命令 |
| **D3** | 整班取题**限定在当前包内**；**不新增“关联作业包”按键**（当前包即上下文） |
| **D4** | **转写阶段不发送任何作业纸信息**（避免模型用题干“脑补”笔迹） |
| **D5** | **评阅阶段只发该生 tag 对应的那一张作业纸**（题目+参考答案）+ 转写内容；要求**先判题目是否对应，再评阅** |
| **D6** | 题目一致性**由 LLM 判断**（Python 只提供事实依据，不预先拦截、不代替判断） |
| **D7** | **报告纯组装，不调 LLM**；由「一键生成批阅报告」按键触发，**可反复生成** |
| **D8** | 顶部按钮组：`[🔍测试配置] [①仅转写] [②仅评阅] [③完整批阅]`。**不加“仅报告”键**——报告在逐生审核下方的「📄 一键生成批阅报告」 |
| **D9** | 「完整批阅」= 转写 + 评阅（**不含报告**）；报告是审核后的独立工序 |
| **D10** | 转写结构**不做旧版兼容**：检测到旧结构 → 提示“请重新转写” |
| **D11** | 评阅结构化新增 `errors[].knowledge[]`（知识点，可多个）；**不做题库知识点标注工程**（简版先行） |
| **D12** | 人工批语三态：`none`（纯 AI，默认）/ `replace`（**纯人工**，替代 AI）/ `append`（AI 在前 + 人工在后） |
| **D13** | **报告生成后不自动上传**，必须手动点「上传」 |
| **D14** | “顶替嫌疑”**从学生报告正文移除**，仅保留教师侧提示与 `evaluations/*.json` |

## 3. 实施清单

### T1 · 作业包为唯一批次载体（P1/P2/P3/D1/D2）

| # | 动作 | 文件 |
|---|---|---|
| T1.1 | 新增 `paper/pack.py::current_pack_context(ws, pack_id)`：解析包 → `[{padId, tag, pad, items}]` | 新增 |
| T1.2 | 新增 **`pick_pad_for_tag(pack_ctx, tag, fallback)`** —— 唯一“包内按 tag 取作业纸”入口 | 新增 |
| T1.3 | `flow.grading_dir()` 改为 `grading/<packId>`；`task` 必须带 `pack_id` | `grading/flow.py` |
| T1.4 | `inputs.build_plan()` 的题目来源改为“当前包内按 tag 取”，**禁止回退到全库/全量 taskpad** | `grading/inputs.py` |
| T1.5 | `RosterView` 整班预览/打印改用 `pick_pad_for_tag`（当前包） | `views/RosterView.vue` |
| T1.6 | 变体 zip / 作业纸生成统一走同一函数 | `lib/variantBatch.ts` 等 |
| T1.7 | serve `/xxt/grade/ai-run` 接收并校验 `packId`；缺失时返回可读错误 | `serve.py` |
| T1.8 | `assist migrate grading-dir --dry-run/--apply`：把 `grading/<padId>/` 迁到 `grading/<packId>/pads/<padId>/`（幂等、失败回滚） | `cli.py` 新增 |
| T1.9 | 落盘 `grading/<packId>/pack.json`（包快照，供事后审计） | `flow.py` |

**目标目录**
```
classes/<班级>/grading/<packId>/
    ├─ pack.json                 包快照（含每张作业纸 id/tag）
    ├─ pads/<padId>/             （可选）按作业纸细分
    ├─ transcripts/ evaluations/ reports/     ← 作业级共享
    └─ drafts/<workId>.json
```

### T2 · 转写结构化（P4/D4/D10）

| # | 动作 | 文件 |
|---|---|---|
| T2.1 | 重写 `TRANSCRIPTION_PROMPT`：输出 `{items:[{no, printed_question, answer, diagrams:[{for_question, kind, description}]}], unmatched_notes, quality}` | `grading/prompts.py` |
| T2.2 | **明确禁止画图**：不输出 SVG/ASCII，只用 1–3 句描述图的物理含义 | 同上 |
| T2.3 | `transcribe.py` 兼容两种返回（`items[]` 优先，纯 `markdown` 视为旧版）；写 `_trans_version: 2` | `grading/transcribe.py` |
| T2.4 | 新增 `transcript_to_markdown(data)`：把 `items[]` 渲染成“题目/作答/示意图”分明的 markdown（供报告与草稿复用） | 新增 |
| T2.5 | 旧结构（无 `items[]`）→ 评阅/报告前置检查给出“请重新转写”，不静默降级 | `flow.py` / `drafts.py` |
| T2.6 | PWA 逐生审核「AI 转写」区按新结构分段展示（题目/作答/示意图） | `StudentReviewModal.vue` |

### T3 · 评阅：只给对应 tag 的作业纸 + 先判题目（D5/D6/D14）

| # | 动作 | 文件 |
|---|---|---|
| T3.1 | prompt 明确三段：① 本次作业应含哪些题（题号+题干）② 学生转写（题目+作答）③ **先输出 `question_match`，再评阅** | `grading/evaluate.py`、`prompts.py` |
| T3.2 | `question_match` 升级为 `{match: bool, evidence: string, reason: string}`；**LLM 判断，不拦截** | `EVALUATION_SCHEMA` |
| T3.3 | 题目来源**只取该生 tag 那张作业纸**；取不到 → **报错并写诊断**，禁止“AI 自己猜题目”兜底 | `flow._run_evaluate` |
| T3.4 | 删除兜底文案「未提供题目/参考答案：请你先自行判断题目」 | `prompts.py:112` |
| T3.5 | `errors[]` 增 `knowledge[]`（来自题干 `related` 提示 + 模型判断，允许多个） | `EVALUATION_SCHEMA` / `evaluate.py` |
| T3.6 | 记录审计字段：`used_pad_id`、`question_numbers`、`knowledge` | `evaluations/*.json` |

### T4 · 报告：纯组装 + 新结构（P5/P6/D7/D9/D12/D14）

| # | 动作 | 文件 |
|---|---|---|
| T4.1 | `grade.steps` 默认改为 `[transcribe, evaluate]`；读到旧 `report` 步骤**忽略**（兼容历史任务包） | `flow.py` |
| T4.2 | 报告结构：`一、AI 转写`（题目/作答/示意图）→ `二、AI 批阅`（**先列正确题目** → 评阅 → 启发式提问） | `grading/report.py` |
| T4.3 | 修正 `_mode_report_md`：`replace` = **纯人工**；`append` = AI 在前 + 人工在后；`none` = 纯 AI | 同上 |
| T4.4 | “顶替嫌疑”从报告正文移除；题目不一致改为**中性并列**“作业纸题目 vs 你的转写题目” | 同上 |
| T4.5 | 报告可重复生成（幂等覆盖 `reports/<学生>.{md,html,png}`） | `drafts.render_reports_from_drafts` |
| T4.6 | PWA：逐生审核弹窗提供 `[↩ 仅 AI] [✏ 人工替代 AI] [➕ 追加到 AI 后]` 三键 | `StudentReviewModal.vue` |

### T5 · 按钮组与测试配置（P7/D8）

| # | 动作 | 文件 |
|---|---|---|
| T5.1 | 顶部按钮：`[🔍测试配置] [①仅转写] [②仅评阅] [③完整批阅]`；**移除「③转录+评阅」「④完整批阅(含报告)」**语义重叠 | `AiGradingPanel.vue` |
| T5.2 | 「📄 一键生成批阅报告」保留在逐生审核下方；补“审核完成后再生成”的提示 | 同上 |
| T5.3 | `/llm/test` 改 **HTTP 200 + `ok:false`**；前端展示每段 `provider/base_url/model/ms/error` 原文 | `serve.py` / `engineClient.ts` |
| T5.4 | 测试 `max_tokens` 16 → **256**（避免推理型模型思考被截断） | `serve.py` |
| T5.5 | 前置缺失给**明确提示**（“请先跑①/②”），不置灰 | `AiGradingPanel.vue` |

### T6 · 逐生审核表格语义（D12）

| # | 动作 |
|---|---|
| T6.1 | 列改为「tag · AI 状态 · 人工状态 · 报告模式」；AI 状态区分 `未跑/已转写/已评阅/有报告` |
| T6.2 | 报告模式默认显示 `auto(AI)`，不再是 `—` |

## 4. 验收标准

1. 单张作业纸也必须属于包；`grading/<packId>/` 存在且含 `pack.json`；
2. 整班预览只从**当前包**取题；包里没有该 tag → 明确提示，不静默用别的包；
3. 转写产物为 `items[]` 结构，含题目/作答/示意图描述，**无 SVG/ASCII 图**；
4. 评阅 prompt 只含该生 tag 那张作业纸的题目；取不到题目时**报错**而非自由发挥；
5. 报告为「一、转写 / 二、批阅」，批阅段**先列正确题目**；**无“顶替嫌疑”字样**；
6. `replace` 与 `append` 产出**不同**报告；
7. 完整批阅**不出报告**；报告由「一键生成批阅报告」生成，可反复点；
8. 生成报告**不自动上传**；
9. 测试配置失败时前端能看到 `error` 原文，不再是 `HTTP 400`；
10. 旧转写提示重新转写；旧 `grading/<padId>/` 可用迁移命令处理。

## 5. 风险

| 风险 | 缓解 |
|---|---|
| 目录重构影响全部历史产物 | 不自动迁移 + `--dry-run` 迁移命令 + 老目录只读回退 |
| `grade.steps` 默认值变化影响历史任务包 | 读到 `report` 自动忽略，行为向后兼容 |
| 转写结构变更使旧产物不可用 | 明确提示重写，不做静默降级 |
| 评阅禁兜底后可能出现“无题目→批阅失败” | 在 plan 生成阶段**提前列出**“tag 无对应作业纸”的学生 |
| prompt 改动影响批阅质量 | 保留 D108 提示词模板插入点；首批用真实数据对比 |

## 6. 实施记录（2026-10-30）

> 说明：D7「报告纯组装不调 LLM」与 D8「不在按钮行加生成报告键」已按最终口径执行。

### 6.1 已完成清单

| 项 | 落地内容 | 文件 |
|---|---|---|
| **T1.1/T1.2** | 新增 `paper/pack.py`：`pack_context()` / `pick_pad_for_tag()` / `tags_without_pad()`；tag 归一（全角转半角/大小写/空白） | `paper/pack.py`（新增） |
| **T1.3** | `grading_key()`：目录名**优先 pack_id**，无则回退作业纸 id（兼容历史） | `grading/flow.py` |
| **T1.4** | `build_plan(pack=...)`：题目**只从包内按 tag 取**；包内无该 tag → 题目为空，**不回退全库** | `grading/inputs.py` |
| **T1.9** | 批阅开始时落 `grading/<packId>/pack.json` 快照（包/作业纸/题数/时间） | `grading/flow.py` |
| **T1.8** | `assist migrate-grading-dir [--dry-run/--apply]`：`<padId>/` → `<packId>/`，复制不删源、幂等 | `cli.py` |
| **T2.1/T2.2** | 重写转写 prompt：输出 `items[{no,printed_question,answer,diagrams}]`；**明令禁止 ASCII/SVG 画图**，只做 1–3 句语义描述 | `grading/prompts.py` |
| **T2.3/T2.4** | `TRANS_VERSION=2`；`is_structured()` / `transcript_to_markdown()`；删除 `transcribe.py` 里重复的旧 prompt | `grading/transcribe.py` |
| **T2.5** | 报告/草稿均走 `transcript_to_markdown`（旧 markdown 原样返回，评阅入口另行提示） | `grading/report.py`、`drafts.py` |
| **T3.1–T3.4** | 评阅 prompt：**先判题目是否对应，再评阅**；删除「未提供题目请自行判断」兜底；plan 模式下无题目→**跳过并写诊断**，不兜底整包题目 | `grading/prompts.py`、`evaluate.py`、`flow.py` |
| **T3.5/T3.6** | `EVALUATION_SCHEMA`：`question_match{match,evidence,reason}` + `errors[].knowledge[]`；产物记 `audit{pad_id,question_numbers}`、`knowledge[]` | 同上 |
| **T4.1** | `grade.steps` 默认 `[transcribe,evaluate]`；历史 `report` 步骤**忽略** | `grading/flow.py` |
| **T4.2/T4.4** | 报告「二、AI 批阅」**先列作业纸正确题目**，题目不一致改为中性提示；**移除“顶替嫌疑”告警**（含 batch 回灌路径） | `grading/report.py`、`evaluate.py` |
| **T4.3** | `replace`=纯人工；`append`=AI 在前+教师补充；`none`=纯 AI（此前 append/replace 产出相同） | `grading/report.py` |
| **T4.6** | 逐生审核三键：`↩ 仅AI` / `✏ 人工替代AI` / `➕ 追加到AI之后` | `StudentReviewModal.vue` |
| **T5.1** | 按钮组：`🔍测试配置 ①仅转写 ②仅评阅 ③完整批阅`；移除「转录+评阅」 | `AiGradingPanel.vue` |
| **T5.2** | 「📄 一键生成批阅报告」保留在逐生审核下方（**不在按钮行新增**） | 同上 |
| **T5.3/T5.4** | `/llm/test` 改 **HTTP 200 + ok:false**，返回可读摘要；`max_tokens` 16→**256**；前端逐段展示 error 原文 | `serve.py`、`engineClient.ts`、`AiGradingPanel.vue` |
| **T5.5** | 前置缺失给明确提示（“先跑①仅转写”），不置灰 | `AiGradingPanel.vue` |
| **T6.1/T6.2** | 表格列改为「AI 状态（未跑/已转写/已评阅/有报告）· AI 分 · 人工 · 报告模式（auto(AI) 等）」 | `AiGradingPanel.vue` |
| **T2.6** | 转写/批语按 `renderRich` 富文本渲染（公式、结构可读） | `StudentReviewModal.vue` |

### 6.2 验证

| 项 | 结果 |
|---|---|
| 新增 `test_d127_pack_pipeline.py` | **14 passed**（含"包内无该 tag 不回退全库"、"无题目跳过评阅"、"三态报告不同"） |
| engine pytest 全量 | **744 passed** |
| app `vue-tsc` / build | 0 error |
| app selfcheck | 37 项全绿（新增 `selfcheck-d127-pack-pipeline.mjs`；`d125` 断言随按钮调整更新） |
| 脱敏 | 通过 |

### 6.3 补做：整班预览跟随当前作业包（2026-10-30，用户拍板）

原遗留项已收口（对应 §2 **D3**）：

| # | 改动 | 文件 |
|---|---|---|
| F1 | `packStore.packPadJsons(saved)`：返回**当前包内**的作业纸 JSON（id/json/tag），并报告 `dangling`（包内引用但找不到的 padId）；包内声明 tag 优先于作业纸自身 `target_tag` | `stores/packs.ts` |
| F2 | 整班预览/打印/manifest 的取题改为 `classPadJsons()`（= 当前包），**不再用全库 `pad.savedJsons()` 按 tag 反推** | `views/RosterView.vue` |
| F3 | 未选包 / 包内无作业纸 / 包内引用悬空 → **明确提示**并中止，不静默回退全库 | 同上 |
| F4 | 整班预览卡显示“当前包：`<id>`（N 张作业纸，⚠ 悬空 M 个）”，让教师一眼确认没选错包 | 同上 |

验证：`selfcheck-d127-pack-pipeline` 新增第 8 组断言（禁止全库映射 / 未选包有提示 / 悬空引用可报）；
engine pytest 744 passed；app build 0 error；selfcheck 全绿。

### 6.4 已知遗留

- 旧 `grading/<padId>/` 需教师手动执行 `assist migrate-grading-dir --apply`（不自动迁移）。
- 教师总结报告（D126-B）尚未实施；`evaluations/*.json` 已带 `knowledge[]`，为其做好了数据准备。
- `SheetContentView.vue` 的变体编排仍用全库 `pad.savedJsons()`（整班 zip 入口）；
  与整班预览口径尚未统一，**下一轮**处理。
