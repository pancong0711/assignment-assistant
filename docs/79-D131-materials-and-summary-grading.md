# D131 需求单：课堂资料（`/materials`）→ 知识点清单 → `summary` 批阅联动（P2）

> 日期：2026-10-30
> 状态：**已实施（P2 完成）**
> 关联：`docs/78-D130`（P2 原 T12/T13/T14，本单编号 **T19/T20/T21**）、`docs/12`、`docs/76-D127`

## 0. 一句话

教师把**课堂资料**（授课 PPT / 授课计划 / 讲义 PDF / 照片）放进
`<ws>/materials/<章节>/`，引擎抽取「本章知识点 + 逻辑关系」，
教师确认后生成**本章知识点清单**；`summary` 类作业的批阅以它为依据，
启发式提问可指向"本堂课漏掉的知识点"。

## 1. 为什么需要独立目录（而不是塞进 `kb/`）

| 方案 | 问题 |
|---|---|
| 放 `<ws>/kb/materials/` | **违反 D120 语义边界**：`kb/` 只放题库（xlsx / fig / solutions），`workspace_layout.FORBIDDEN_IN_KB` 明确禁止语义污染；且 `kb/` 会被题库写盘/快照逻辑扫到 |
| 放 `<ws>/classes/<班级>/material/` | 资料是**跨班共享**的（同一门课多个班用同一份 PPT），挂在班级下会重复存放、且换班就找不到 |
| **放 `<ws>/materials/<章节>/`（采纳）** | 与 `kb`、`classes`、`packs`、`tasks` 平级，语义独立；按**章节**组织与题库 sheet 对齐；跨班共享 |

## 2. 目录布局（定稿）

```
<ws>/materials/                          # 课堂资料根（跨班共享，可重建索引）
  <chap>/                                # 章节名，与题库 sheet 同名（如 chap04）
    _source/                             # 教师投放的**原件**（永不改写、不上传、不进模型上下文以外的处理）
      lecture01.pptx
      lecture02.pdf
      plan.md                            # 授课计划（纯文本/markdown）
      fig/                               # 讲义里抽出的图片（教师手工放也可）
    索引.json                            # 引擎生成的清单（见 §3），**不要手改**
    _extract/                            # 引擎中间产物（可删，下次重新生成）
      lecture01.text.txt                 # officecli / pdftotext 抽取的纯文本
      lecture01.pages/                   # PDF → PNG（多模态用）
        1.png  2.png …
    知识点清单.md                        # 教师确认后的**生效**清单（人工可编辑，AI 不覆盖）
    知识点清单.ai.json                   # AI 抽取的原始建议（供对比/回滚）
    知识点清单.journal.jsonl             # 确认/编辑历史
```

**三条硬规则**
1. `_source/` 是**唯一真源**，引擎**只读不改**（教师原件永远安全）。
2. `_extract/` 是**可删缓存**（删了下次自动重建；不进备份关键路径）。
3. `知识点清单.md` 是**生效产物**；AI 只写 `知识点清单.ai.json`，
   **必须教师确认**才生成/覆盖 `.md`（与 D130「AI 要点默认不置顶」同口径）。

> 为什么章节名要与题库 sheet 同名：`summary` 批阅时按题目的 `kb`+`chap` 找对应清单，
> 不需要维护第二套映射表；`chap` 解析复用 `expand_items` 已有的 `chap` 字段。

## 3. `索引.json` schema

```json
{
  "version": 1,
  "chap": "chap04",
  "generatedAt": "2026-10-30 12:00:00",
  "sources": [
    {"file": "_source/lecture01.pptx", "kind": "pptx", "bytes": 123456,
     "sha256": "…", "mtime": "…",
     "extract": {"engine": "officecli", "slides": 24, "chars": 8123,
                 "text_file": "_extract/lecture01.text.txt"}},
    {"file": "_source/lecture02.pdf", "kind": "pdf", "pages": 12,
     "extract": {"engine": "pdftoppm", "images": ["_extract/lecture02.pages/1.png", "…"]}}
  ],
  "summary": {"chars": 19876, "slides": 24, "pages": 12}
}
```

- `sha256` 用于**增量**：文件没变就不重复抽取（省 token、省时间）。
- `extract.engine` 记录实际用的抽取器，便于教师理解"为什么这段没抽到"。

## 4. 抽取链路（按可靠性排序，实测过）

| 输入 | 首选 | 回退 | 实测结论（本机） |
|---|---|---|---|
| `.pptx` / `.docx` / `.xlsx` | `officecli view <f> text --json` | `soffice --convert-to pdf` → PDF 链路 | ✅ `officecli` 可用（v1.0.144，`--json` 给出 `slides[].texts[]`） |
| `.pdf` | `pdftoppm -png -r 150` → 逐页图片 → **多模态**（复用 `chat_with_images`） | `pdftotext`（纯文本，丢图） | ✅ `pdftoppm` 可用（poppler 22.02） |
| `.png/.jpg/.jpeg/.webp` | 直接多模态 | — | ✅ 复用 `imageprep.compress_for_model` |
| `.md/.txt` | 直接读 | — | ✅ |

> ⚠️ **实测发现**：本机 `soffice` 不可用（`DeploymentException`，因 `/run/user/1002` 只读）。
> 因此 LibreOffice **只作为最后回退**，且失败时必须给出**可读提示**而不是抛栈。
> `officecli` 还能直接 `view <f> pdf|screenshot`，需要图时优先走它而不是 LibreOffice。

**多模态为什么重要**：PPT 里的公式、受力图、电路图**纯文本抽不到**（`officecli text` 只给文字）。
凡含图形/公式的资料，走"渲染成图 → 多模态"才能拿到真实内容。

## 5. 知识点抽取与确认

1. `assist materials extract --chap chap04`：抽取 → 写 `索引.json` + `_extract/*`；
2. `assist materials suggest --chap chap04`：把抽取文本（分批，避免超长）喂 LLM，
   产出 `知识点清单.ai.json`：
   ```json
   {"chap": "chap04",
    "knowledge": [
      {"term": "动量守恒", "aliases": ["动量守恒定律"],
       "importance": "core|supporting",
       "evidence": "第 5 页：系统合外力为零时总动量守恒"},
      {"term": "完全弹性碰撞", "importance": "core", "evidence": "第 6 页"}],
    "logic": [{"from": "牛顿第三定律", "to": "动量守恒", "note": "由作用力反作用力等大反向推出"}],
    "covered_slides": [1, 24]}
   ```
3. 与**受控词表**（D130 T8 `<ws>/knowledge-terms.json`）比对：能对上的**沿用既有术语**，
   新术语标 `source: ai` 待教师决定是否入库；
4. 教师确认（`--apply` 或 PWA 勾选）→ 渲染 `知识点清单.md`（人工可再编辑）→ 写 journal。

## 6. `summary` 批阅如何接入

- `rules.DEFAULT_RULES.types.summary` 已有 `checklist`（知识点与概念 / 重要公式及推导 / 示意图），
  本轮**不改扣分规则**，只把它从"凭模型自由发挥"变成"**对着本章清单核对**"；
- 批阅 `summary` 题时，若存在 `<ws>/materials/<chap>/知识点清单.md`：
  - 该清单进 prompt（作为"本堂课应掌握的知识点"依据）；
  - 要求模型输出 `knowledge_missing[]`（**漏掉的本章知识点**）；
  - `guidance` 启发式提问**优先指向遗漏知识点**（用户诉求）；
- **没有清单时行为不变**（不报错、不降级扣分），只少这一层依据。

## 7. 实施清单

| # | 任务 | 产出 |
|---|---|---|
| T19a | 目录骨架 + `materials` 模块（`workspace` 边界、`索引.json` 读写、sha256 增量） | `grading/../materials.py` |
| T19b | 抽取器：`officecli`(pptx/docx/xlsx) / `pdftoppm`+多模态(pdf) / 图片 / 文本 | 同上 + CLI `assist materials extract` |
| T20 | `.pptx` 支持（`officecli` 优先，`soffice` 回退 + 可读错误） | 含在 T19b，单独测试覆盖 |
| T21a | `assist materials suggest`：AI 抽取知识点 + 逻辑关系（分批） | `materials_rubric` 提示词 |
| T21b | 教师确认 → `知识点清单.md` + journal；`assist materials list/show` | CLI |
| T21c | `summary` 批阅接入清单 + `knowledge_missing` + 启发式提问指向遗漏 | `evaluate.py` / `prompts.py` |
| T21d | serve 接口（PWA 后续接）：`/materials/list`、`/materials/show` | `serve.py` |

## 8. 验收标准（P2）

1. 把 `.pptx` / `.pdf` / 图片放进 `<ws>/materials/<chap>/_source/` 后，
   `assist materials extract --chap <chap>` 能产出 `索引.json` 与非空 `_extract/`；
2. 同一文件**二次抽取**因 sha256 未变而跳过（增量生效）；
3. `assist materials suggest` 产出 `知识点清单.ai.json`，**不自动生成** `知识点清单.md`；
4. 教师 `--apply` 后才生成 `知识点清单.md`，且**AI 不覆盖**已有 `.md`（除非 `--force`）；
5. `summary` 题批阅时清单进 prompt；无清单时行为与 D130 一致（不报错）；
6. 批阅结果含 `knowledge_missing[]`，`guidance` 指向遗漏知识点；
7. `officecli` 缺失时给出**可读提示**并走回退；全部失败时报错清楚、不静默产出空清单；
8. pytest / build / selfcheck / 脱敏 全绿。

## 9. 风险

| 风险 | 缓解 |
|---|---|
| 资料含隐私（学生名单/成绩） | `_source/` 只进本地抽取；抽取文本进 LLM 前做**提示**（不自动上传），CLI 打印将发送多少字 |
| PPT 公式/图抽不到 | 优先多模态（渲染成图）；`index` 记录抽取器 |
| AI 知识点编造 | `evidence` 必须引用来源页/行；默认不生效，教师确认 |
| 章节名与题库 sheet 不一致 | 复用题库已有 `chap` 名；`list` 命令显示"题库有但资料缺"与"资料有但题库缺" |
| 大 PPT 超 context | 分批抽取/摘要，单批字符上限可配 |

## 10. 实施记录

### 10.1 T19/T20：目录骨架 + 抽取（2026-10-30 完成）

- **新增** `engine/src/assist/files/materials.py`：布局（`_source/` `_extract/` `索引.json`）、
  sha256 增量、抽取器、知识点抽取/确认/读取。
- **CLI**：`assist materials list | extract | show | suggest | confirm | knowledge`。
- **serve**：`GET /materials/list`、`GET /materials/knowledge`（仅供 PWA 只读展示；
  抽取与确认仍走 CLI，保证教师亲自把关）。
- 抽取实测（本机）：`officecli` v1.0.144（pptx/docx/xlsx，`--json` 给 `slides[].texts[]`）；
  `pdftotext`/`pdftoppm`（poppler 22.02）；图片直传多模态。

**实施中发现并修掉的 2 个真实缺陷**：

1. **增量判定永远不命中**：抽取信息原先**扁平**写在 source 记录上，而代码按
   `prev["extract"]` 判定 → 二次抽取永远重跑（既慢又浪费 token）。
   已改为与 §3 schema 一致的嵌套结构 `{"extract": {...}}`。
2. **`officecli` 驻留缓存返回旧内容**（**影响正确性**）：officecli 会为打开过的文档起驻留进程，
   文件被外部替换后 `view` 仍返回旧内容 —— 表现为"明明改了 PPT，抽出来还是老的"。
   已改为抽取前先 `officecli close <file>` 释放缓存。这是靠"改文件后重抽"的测试发现的，
   只测"能抽出文本"是发现不了的。

### 10.2 T21：知识点抽取 → 确认 → summary 批阅联动

- `assist materials suggest`：把抽取文本（可 `--max-chars` 截断）喂 LLM，产出
  `知识点清单.ai.json`（含 `evidence` 引用、`importance`、`logic` 逻辑关系）；**不自动生效**。
- `assist materials confirm`：教师确认后渲染 `知识点清单.md`；**AI 不覆盖已确认清单**
  （除非 `--force`，且覆盖会记 `知识点清单.journal.jsonl`）。
- `summary` 批阅：若本章有生效清单 → 清单块进 prompt，要求 `knowledge_missing[]`，
  并让 `guidance` 的启发式提问**指向遗漏知识点**；**无清单时行为与 D130 完全一致**（不报错）。
- 评阅结果新增 `knowledge_missing[]`（供教师总结报告 D126-B 聚合）。

### 10.3 验收对照（§8）

| # | 验收项 | 状态 | 依据 |
|---|---|---|---|
| 1 | pptx/pdf/图片 `extract` 产出 `索引.json` + 非空 `_extract/` | ✅ | `test_extract_pptx_produces_index_and_text` / `test_extract_pdf_and_image_and_text` |
| 2 | 同文件二次抽取因 sha256 未变而跳过 | ✅ | `test_extract_is_incremental_by_sha256` |
| 3 | `suggest` 只产出 `.ai.json`，不自动生成 `.md` | ✅ | `test_suggest_writes_ai_json_but_not_effective_md` |
| 4 | `--apply`(confirm) 后才生成；AI 不覆盖已有 `.md`（除 `--force`） | ✅ | `test_confirm_creates_effective_md` / `test_confirm_does_not_overwrite_existing_without_force` |
| 5 | summary 批阅清单进 prompt；无清单不报错 | ✅ | `test_summary_prompt_includes_knowledge_manifest` / `test_prompt_without_manifest_unchanged` |
| 6 | 结果含 `knowledge_missing[]`，guidance 指向遗漏 | ✅ | `test_score_collects_knowledge_missing`（prompt 侧由 §5 块约束） |
| 7 | officecli 缺失给可读提示并回退；全失败不静默产出空清单 | ✅ | `test_office_failure_message_is_readable` / `test_extract_reports_unsupported_file` |
| 8 | pytest / build / selfcheck / 脱敏 全绿 | ✅ | 856 passed / 0 error / 21 全绿 / 通过 |

### 10.4 P2 未做（已记录）

- **PWA 界面**：本轮只做引擎 + CLI + 只读 serve 接口；PWA 的"资料管理页/知识点勾选确认"
  留待下一轮（设计上刻意让**确认动作走 CLI**，避免 AI 直接改生效清单）。
- ~~PDF 多模态抽取未接入 LLM~~ → **已补**（见 §10.5）。
- LibreOffice 回退在本机不可用（`/run/user/1002` 只读），仅作最后兜底；`officecli` 是主路径。

## 11. 下一步建议（优先级）

1. ~~图片/扫描型资料的 suggest 多模态化~~ → **已完成**（§10.5）；
2. **PWA 资料页**：列章节 → 看抽取状态 → 勾选知识点 → 确认（写 journal）；
3. **D126-B 教师总结报告**：聚合 `evaluations[].knowledge[]` 与 `knowledge_missing[]`，
   输出"全班最薄弱知识点 Top N"，正是本轮数据层已备好的能力。

### 10.5 T21 补漏：图片/扫描型资料的多模态抽取（2026-10-30 完成）

**缺口**：图片型/扫描型 PDF 没有文字层，`pdftotext` 返回空；此前 `suggest` 只用文本，
于是"能抽取、但 AI 看不到内容"，甚至直接报"没有可用文本"。

**实现**
- 新增 `materials.read_source_images()`：汇总 PDF 页图 + 教师直接放的图片，
  **按页码数字序**排序（否则 `-2` 会排在 `-10` 之后，知识点 `evidence` 会标错页），
  缓存被删（`_extract/` 可删）时自动跳过而不崩。
- `suggest_knowledge()` 判定：**有页图 且 文本 < 200 字** → 走 `client.chat_with_images`
  多模态；否则仍走纯文本（避免每章都花视觉成本）。
- 超过 `--max-images`（默认 20）时：只送前 N 张，并在 **prompt 里明确告知**
  "共 X 张、本次仅前 Y 张"（不静默截断，防 AI 以为自己看了全章）。
- 抽取模式写入 `知识点清单.ai.json.source.mode`（`text` / `vision`）+ `images_used`，
  教师可据此判断本次结果可信度。

**测试**（新增 8 例）：扫描件走视觉 / 送的是真实页图 / 文字充足仍走文本 /
超限**告知**而非静默 / 既无文本也无图报错可读 / 页序数字排序 / 缓存缺失不崩 /
**扫描件→多模态→确认→summary prompt 端到端**。

**验证**：engine pytest **864 passed**；build 0 error；selfcheck 21 项全绿；脱敏通过。
