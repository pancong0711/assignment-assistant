# D92 任务需求单：题库下拉/模型共享 + 逐生审核双栏弹窗 + 报告五模式（构成×修订）

> 日期：2026-10-16
> 状态：**已拍板**（讨论定调），按 §6 执行。
> 关联：`docs/39-D86`（AI 批阅引擎/草稿/报告）、`docs/42-D89`（AI 集中选项卡）、
> `docs/44-D91`（Playground 模型下拉）、`docs/04`（数据模型）；
> engine `grading/{drafts,report,flow}.py`、`serve.py`、`cli.py`。

## 1. 背景（2026-10-16 讨论）

1. ⑦ 题库 AI 作答的 **kind/chap/ids/model 都是自由输入**，不便操作；题库 kind 还是硬编码。
2. **模型候选存储本就共享**（`settings.local.json → llm.providers[].models[]`），但 **UI 没共享**：
   ① 区是 datalist（需手输才弹）、⑦ 区没接、Playground 是真下拉（D91-M3）。
3. ⑤ 区「报告标注」**手选 AI/人工**——语义错乱（AI 批阅的报告可被手标成"人工"）。
4. ④ 逐生审核是**页内表格 + 下方编辑块**；且草稿是**单套**批语（人工一改覆盖 AI），
   **无法保留 AI 原文、无法 diff 标红**，也无法表达"人工在前 + AI 作附件"的版式。

## 2. 核心决策（拍板）

### 2.1 报告 = 二维坐标（比 5 个平铺模式更清晰）

- **维度 A · 报告构成**：`ai`（仅 AI）/ `human+ai`（人工在前 + 【附件】AI 在后）/ `human`（仅人工）；
- **维度 B · AI 是否被人工修订**：`false` 原版 / `true` 修订（标红）；"仅人工"恒 `false`。

由此推导 **5 种**：

| # | 构成 | 修订 | 报告标注 |
|---|---|---|---|
| 1 | ai | 否 | AI 批阅报告 |
| 2 | ai | 是 | AI 批阅报告（人工修订） |
| 3 | human+ai | 否 | 人工批阅报告 + 附件：AI 批阅报告 |
| 4 | human+ai | 是 | 人工批阅报告 + 附件：AI 批阅报告（人工修订） |
| 5 | human | — | 人工批阅报告 |

### 2.2 草稿 = 双套批语 + 模式（关键修正）

```jsonc
{
  "key": "<workAnswerId|姓名>",
  "ai":    { "score": 88, "comment": "AI 批语原文", "reportImages": ["base64:..."] },
  "human": { "score": 90, "comment": "人工批语", "images": ["base64:..."], "used": true },
  "humanMode": "none" | "replace" | "append" | "revise",
  "revision": { "text": "AI 批语的人工修订版（另存，不动 ai.comment）", "at": "..." },
  "revised": false            // 派生：revision 存在且与 ai.comment 不一致
}
```

- `humanMode`：`none`=仅 AI；`replace`=人工覆盖 AI；`append`=人工在前+AI 附件；`revise`=人工对 AI 文本的修订；
- **AI 原文永不被覆盖**；人工修订另存 `revision.text`；
- 兼容：旧草稿（单 `{score,comment,images}`）读入时映射为 `ai.*`，`humanMode='none'`。

### 2.3 逐生审核 → 左右两栏弹窗（与「作业预览-学习通」逐生预览**不同**）

- 左栏：学生**作答图片**（复用 XxetongView 的图片读取/旋转/上下位）；
- 右栏上：**AI 批语（只读）** + 「另存修订版」按钮（生成 `revision.text` 可编辑）；
- 右栏下：**人工批阅**（分数/批语/图片）+ 模式选择（不批阅 / 覆盖 AI / 人工在前+AI 附件 / 修订 AI）；
- 每生独立 `humanMode`（**逐生决定版式**）。

### 2.4 diff 标红（修订）

- 用标准库 `difflib` **按行/按句**比对 `ai.comment` vs `revision.text`；
- **公式块（`$$...$$`/`$...$`）整块为原子**，只在段落级标红（不拆公式内部）；
- HTML 加 `.revised{color:#c00}`；经 KaTeX → PNG 保留标红。

### 2.5 分数规则

- `none` → AI 分；`replace` → 人工分；`append` → 两段各自标注各自分；
- `revise` → 以 AI 分为主，标出人工改动（若人工改了分则以人工分为准并标注）。

### 2.6 顺序

**先 AI 批阅（tag 多选、默认全 tag）→ 逐生审核（可选叠加人工/修订）→ 一键生成报告（逐生按模式拼装）**。

### 2.7 下拉与共享

- ⑦ 题库 AI 作答：kind/chap/ids/model 全改**真下拉**（保留空=整库/整章/评阅段）；新增只读
  `GET /kb/catalog`（引擎读 `<ws>/kb`：`{kinds:[{kind, chapters:[{chap, ids:[...]}]}]}`）；
  题目内容**预览框**（单行、可滚动）。
- 模型候选 UI 三处统一（①/⑦/Playground）共享 `providers[].models[]`；① 区 datalist → 真下拉 + 自定义 + 记录/删除候选。
- ③ tags → **多选下拉**（当前作业学生 tag 集合）+ **默认全选**。
- ⑤ 去掉手选「报告标注」；改为**只读展示**"将生成的报告类型（自动，按逐生模式汇总）"。

## 3. 端点 / CLI

| 类型 | 名称 | 说明 |
|---|---|---|
| serve | `GET /kb/catalog` | 题库 kind/章节/题号（下拉数据源） |
| serve | `POST /xxt/grade/ai-run` | 已有；`tags` 支持多选（PWA 传数组） |
| serve | `POST /xxt/grade/render-drafts` | 扩展：`mode`（构成）/`revise` 由草稿逐生决定；去 `kind` 手选 |
| CLI | `assist kb catalog` | 只读列出题库目录（JSON） |
| CLI | `assist grade-drafts …` | 扩展：按草稿 `humanMode/revision` **逐生**生成报告 |
| 内部 | `grading/report.py` | 新增 `diff_mark(text, revised) → html`（difflib，公式原子） |
| 内部 | `grading/drafts.py` | 读旧草稿归一；报告拼装按 `{构成 × 修订}` 逐生 |

## 4. 数据/兼容

- 草稿 `grade-drafts/<classId>/<workId>.json` 结构升级（双套 + mode）；**读旧兼容**；
- 报告产物命名不变（`reports/<name>.md|html|png`）；新增"人工在前+AI附件"拼装；
- 不新增第三方依赖（difflib 标准库）。

## 5. UI 落点

| 模块 | 改动 |
|---|---|
| `AiGradingPanel.vue` | ③ tags 多选下拉默认全选；④ 改为弹窗入口；⑤ 去手选标注 |
| `components/StudentReviewModal.vue`（新） | 左右两栏审核弹窗（左图 / 右上 AI 批语+另存修订 / 右下人工批阅+模式） |
| `AiGradingPanel.vue` ①/⑦ | 模型真下拉；⑦ kind/chap/ids 下拉 + 题目预览框 |
| `engineClient.ts` | `fetchKbCatalog`；`renderReports` 去 kind；draft 结构类型 |
| `engine/.../report.py` | `diff_mark` + 五模式拼装 |
| `engine/.../drafts.py` | 双套草稿读写 + 兼容 |
| `engine/.../serve.py`、`cli.py` | `/kb/catalog`、`kb catalog`、报告逐生模式 |

## 6. 分期实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| R1 | 引擎：`GET /kb/catalog` + `assist kb catalog` + 单测 | `serve.py`/`cli.py`/`kb_io.catalog` | ✅ |
| R2 | 引擎：草稿双套结构 + 兼容 + 五模式报告拼装（含 difflib 标红）+ 单测 | `drafts.py`/`report.py`/`grade_store.py` + CLI `grade-render` + serve `/xxt/grade/render-from-drafts` | ✅ |
| R3 | PWA：⑦ kind/chap/ids/model 下拉 + 题目预览框；①/⑦/Playground 模型共享真下拉 | `AiGradingPanel.vue`/`engineClient.ts` | ✅ |
| R4 | PWA：③ tags 多选默认全选；④ 逐生审核左右两栏弹窗（AI/人工分开 + 另存修订 + 模式）；⑤ 去手选标注 | `StudentReviewModal.vue` 等 | ⏳ |
| R5 | 文档（docs/04/13/15/39/45）+ 验证 + 去敏 push | 文档 + CI | ⏳ |

## 7. 验收

- ⑦ kind/chap/ids/model 均可下拉（空选项保留）；①/⑦/Playground 共享模型候选；③ tags 多选默认全选；
- 逐生审核=左右两栏弹窗：左作答图、右上 AI 批语（可另存修订）、右下人工批阅（可选）；
- 草稿双套：AI 原文**不被覆盖**，人工可选 none/replace/append/revise；
- 一键生成报告：**逐生**按 `{构成 × 修订}` 出 5 种版式之一；"人工+AI"=人工在前 + 【附件】AI 在后；修订处**标红**（公式整块原子）；
- ⑤ 不再手选标注（只读展示自动类型）；
- engine pytest / PWA build+selfcheck / 脱敏扫描 全绿。
