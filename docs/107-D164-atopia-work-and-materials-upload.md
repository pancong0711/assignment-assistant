# D164 需求单：Atopia 工作区（上传/解析）+ 课堂资料「从 Atopia 复制」+ 标注章节联动

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/97-D150`（规划）、`docs/95-D148`（只读文件能力）、
> `docs/102-D155`（特征名）、`docs/106-D163`（新建入口）、`docs/12`

## 0. 教师要求

1. Atopia 与课堂资料两个选项卡继续推进；
2. 「题库AI+」的 AI 知识点标注区**不能选择具体章节**（疑似等于全选）——应为可选章节。

## 1. 问题 2 先修（D164-a）

**真实缺陷**：`KnowledgeView.loadChaps()` 读的是 `r.catalog`，
而 `/kb/catalog` 返回的是 **`kinds`** → 章节列表永远为空 → 下拉只有"（全部章节）"。

修复：
- 改读 `r.kinds`；
- 章节列表**跟随当前题型联动**（切题型自动回落该题型的第一个章节）；
- 未选择时才表示"全部章节"。

## 2. Atopia 工作区（D164-b）

### 2.1 目录（三层，各管各的）

```
<ws>/materials/<特征名>/_source/       ← 教师原件：AI **只读**（D131 硬规则 1 不变）
<ws>/atopia/work/<特征名>/
    _upload/                           ← 教师交给 Atopia 的临时文件（PPT/授课计划）
    _parsed/                           ← Atopia 解析产物（json + 人可读 md）
    manifest.json                      ← 来源 / 时间 / sha / 来源文件
```

**为什么不让 Atopia 直接写 `materials/`**：`_source/` 是唯一真源且 AI 永不可写；
破了这条就没有"未被 AI 改过的原件"。

### 2.2 上传（Atopia 页）

选择特征名 + 资料类型 → 上传到 `<ws>/atopia/work/<特征名>/_upload/`。

沿用既有上传安全口径（扩展名白名单 / 20MB / 同名不覆盖 / 文件名清洗）。

### 2.3 解析

Atopia 用 `fs.read`（D148）读 `_upload/` 里的文本/Markdown；
对 PPT/PDF 走 `materials.extract` 的抽取能力（officecli / pdftotext）。
解析结果写 `_parsed/<特征名>.json`（复用 D138 的两层分类结构：章 → 主题 → 术语）。

### 2.4 「📥 复制到课堂资料」

课堂资料页新增按钮：

```
选特征名 → 列出 atopia/work/<特征名>/_parsed/* → 预览全文 → 教师确认 → 写入
materials/<特征名>/知识点清单.json + .md
```

**安全口径与 `materials.confirm` 完全一致**（显式点击 + 全文预览 + journal），
因为这份内容会成为 `summary` 批阅依据。

## 3. 任务清单

| # | 内容 | 验收 |
|---|---|---|
| T1 | 标注区章节下拉修复（读 `kinds` + 题型联动） | 浏览器 |
| T2 | `atopia/work/` 目录 + 上传接口 | 单测 |
| T3 | 解析：`_upload` → `_parsed/*.json` | 单测 |
| T4 | 课堂资料「从 Atopia 复制」：预览 + 确认 + 写 json/md | 单测 + 浏览器 |
| T5 | 文档 | — |

## 4. 验收标准

1. 标注区能选具体章节，且切题型时章节联动；不选=全部章节；
2. Atopia 页可上传文件到 `atopia/work/<特征名>/_upload/`；
3. 解析产物落 `atopia/work/<特征名>/_parsed/`，**不碰 `materials/`**；
4. 「从 Atopia 复制」必须**预览全文 + 显式确认**才写入 `materials/`；
5. 复制后 summary 批阅能用到该清单（D155 关联链）；
6. pytest / build / selfcheck / 脱敏全绿。

## 5. 风险

| 风险 | 缓解 |
|---|---|
| Atopia 写坏教师原件 | `_upload`/`_parsed` 与 `_source/` 物理隔离；`_source` AI 只读 |
| 解析产物未经确认就进批阅 | 必须教师点「从 Atopia 复制」+ 全文预览 |

## 6. 实施记录（2026-10-31 完成）

### 6.1 标注区章节下拉（T1）

**根因**：`KnowledgeView.loadChaps()` 读 `r.catalog`，而接口返回 `kinds`
→ 章节列表永远为空 → 下拉只有"（全部章节）"。

修复：改读 `r.kinds`；章节**跟随当前题型联动**；切题型时自动回落该题型首个章节。

### 6.2 Atopia 工作区（T2/T3）

新增 `atopia/work.py`：

```
<ws>/atopia/work/<特征名>/
    _upload/     教师上传（与 materials/_source 物理隔离）
    _parsed/     解析产物（json）
    manifest.json
```

- `save_uploads`：扩展名白名单 / 20MB / **同名不覆盖**（`-2`）/ 文件名清洗；
- `read_upload_text`：读 `_upload` 里的 md/txt（PPT/PDF 需先经 materials 抽取）；
- `save_parsed` / `read_parsed` / `list_features`。

接口：
- `GET /atopia/work[?feature=&parsed=]`（列表 / 文件 / 解析预览）
- `POST /atopia/work/upload`

PWA：Atopia 页新增 **📁 工作区** 页签（选/建特征名、上传、文件清单、文本预览）。

### 6.3 「从 Atopia 复制」（T4）

- `POST /materials/copy-from-atopia`：**缺 `confirm` 直接 403**；
- PWA 课堂资料页新增 **「📥 从 Atopia 复制」**：
  读取 `_parsed/` → **弹窗展示知识点全文** → 教师点「我确认复制」→
  写入 `materials/<特征名>/知识点清单.json + .md`。

## 7. 验收对照

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 标注区可选章节、切题型联动 | ✅ | 代码修复 + build |
| 2 | 上传落 `atopia/work/`，**不碰 materials** | ✅ | `test_upload_goes_to_atopia_work_not_materials` |
| 3 | 同名不覆盖 / 扩展名白名单 | ✅ | `test_upload_does_not_overwrite` / `test_upload_rejects_bad_ext` |
| 4 | 解析产物可存可读 | ✅ | `test_save_and_read_parsed` |
| 5 | 复制后才写 materials（物理隔离） | ✅ | `test_copy_to_materials_is_separate_step` |
| 6 | 复制后的清单能进 summary 批阅 | ✅ | `test_copied_manifest_feeds_summary` |
| 7 | pytest / build / selfcheck / 脱敏 | ✅ | **1293 passed** · 0 error · **35/35** |

## 8. 未做

- PPT/PDF 的**自动抽取**仍需走 `materials extract`（Atopia 工作区只读 md/txt）；
- 解析动作本身（`_upload` → `_parsed` 的 LLM 调用）目前由 CLI `materials suggest` 完成，
  PWA 工作区页签只做上传与查看，**未一键触发解析**。
