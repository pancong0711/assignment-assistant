# D91 任务需求单：清单限定当前包 + 作业纸跨包移动/复制 + 水印「作业纸×样式」二维 + Playground 模型下拉/自动保存

> 日期：2026-10-16
> 状态：**已拍板**（2026-10-16）。跨包复制 = 引用 + 另存新作业纸（默认引用）；水印矩阵放水印编辑器内、行=当前包；模型候选在 ⑧ 区就地管理。按 M1–M5 执行。
> 关联：`docs/42-D89-...`（作业包 / style_ref）、`docs/43-D90-...`（Playground）、
> `docs/40-D87-...`（水印样式库）、`docs/04`（数据模型）。

## 1. 问题查证（2026-10-16，代码核对）

| # | 现象 | 根因（代码位置） |
|---|---|---|
| Q1 | ③段清单"显示全部作业纸" | `SheetPreviewSection.vue` 的 `library`：**选了包才过滤，未选包显示全部**（N2 只做了一半）；且无"移动/复制到其他包" |
| Q2 | 水印"一样式多作业纸"未默认全选、无二维视图 | `SheetLayoutView.vue`：`wmApplyTargets` 默认空、`allSavedPads()` 取**全部**作业纸（非当前包）；UI 是"选样式→勾作业纸"单向，无「作业纸×样式」矩阵 |
| Q3 | Playground 模型不能下拉点选 | `PlaygroundPanel.vue` 用 `<input list=...>` + `<datalist>`（原生建议，需手输才弹；非真下拉）；且 `provider.models[]` 只有"填写即记录"过才有值 → 新装时为空 |
| Q4 | Playground 无自动保存 | 面板无输入草稿的 localStorage；仅"提问成功后"落工作区记录 |

## 2. 修复与新增

### 2.1 ③段清单：只显示**当前包**的作业纸（Q1）
- 未选包时**不显示任何作业纸**（提示"请先在上方选择/新建作业包"），不再回落"全部"；
- 清单增加操作列：**移动**、**复制副本**（到其他作业包）。
  - 移动 = 从当前包 `pads[]` 移除 + 加入目标包；
  - **复制引用**（默认，轻量、不产生重复真源）= 保留当前包引用 + 目标包加入**同一** padId（改一处两包同步）；
  - **另存为新作业纸到目标包**（可选，深拷贝）= 以当前作业纸内容**生成新 id** 的新作业纸存入目标包（两包独立，可分别改）。
- 目标包下拉（排除当前包）。

### 2.2 水印：作业纸 × 样式 **二维矩阵**（Q2）
- 现状：`style_ref` 是**每张作业纸一个字段** → **不同作业纸用不同样式，引擎已支持**（PDF/HTML 同口径）。
- 新增 **矩阵视图**（在「版式」页水印编辑器内，或独立小节）：
  - 行 = 当前包内作业纸；列 = 命名样式（含「默认/不引用」）；
  - 每个交叉点单选（该作业纸用该样式）→ 写该作业纸 `style_ref`；
  - 「应用」按钮保存整列/整行；**默认全选**：新建矩阵时默认勾选"当前包全部作业纸"（原 D89-N6 的批量应用）；
  - 清晰显示"某作业纸当前生效样式"（横排高亮）。
- 保留现有"批量应用一个样式到多张"但：目标改为**当前包内作业纸**（而非全部），且**默认全选当前包**。
- 优先级不变：`作业纸 items > style_ref > 默认样式 > 内置三槽`。

### 2.3 Playground：模型真下拉 + 自动保存（Q3/Q4）
- **模型选择**：`<datalist>` → **`<select>`**（当前 provider 的 `models[]`）+「自定义…」可切回输入；
  - 在 ⑧ 区加"provider 模型候选"的**管理**：可为该 provider 记录/删除候选模型名（写 `providers[].models[]`）；
  - 与 ① 区 LLM 设置的"填写即记录"同源（保存 stage 模型时也累积到 `models[]`）。
- **自动保存**：提问框/批量框/附件/参数 输入**即存 localStorage**（`playground.draft.v1`），刷新不丢；
  - 与"提问成功后落工作区记录"分离（草稿是本机输入态，记录是留档）；
  - 草稿可"清空"。

### 2.4 拍板结论（2026-10-16）
- D-1 跨包：**两种都给** —— 「复制引用」（默认）+「另存为新作业纸到目标包」（深拷贝新 id）。
- D-2 水印矩阵：放「版式」页水印编辑器内；行 = **当前包内**作业纸。
- D-3 模型候选：在 ⑧ 区模型下拉旁就地管理（＋记录当前模型名 / 删除候选）。

## 3. 涉及改动

| 模块 | 改动 |
|---|---|
| `app/src/components/SheetPreviewSection.vue` | 清单只显示当前包；加"移动/复制"操作 + 目标包下拉 |
| `app/src/stores/packs.ts` | 新增 `movePadToPack` / `copyPadToPack` |
| `app/src/stores/taskpad.ts` | 复用/新增 `applyWatermarkStyleRef`；矩阵批量写入 |
| `app/src/views/SheetLayoutView.vue` | 水印矩阵视图 + 默认全选当前包；目标改为当前包 |
| `app/src/components/PlaygroundPanel.vue` | 模型 `<select>` + 自定义；输入草稿 localStorage 自动保存 |
| `app/src/lib/engineClient.ts` | 可能需要 `fetchLlmConfig` 已有；模型候选记录复用 `postLlmProvider` |
| 引擎（如需） | 模型候选记录已由 `save_provider(model=...)` 支持，无需新增；矩阵为 PWA 本地操作 |

## 4. 分期实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| M1 | 清单限定当前包 + 移动/复制引用/另存新作业纸到其他包 | `SheetPreviewSection.vue` + `packs.ts` + `taskpad.ts` + selfcheck | ✅ |
| M2 | 水印二维矩阵（作业纸×样式）+ 默认全选当前包 | `SheetLayoutView.vue` + `taskpad.ts` + selfcheck | ✅ |
| M3 | Playground 模型真下拉 + 模型候选记录/删除 | `PlaygroundPanel.vue` + `engineClient.ts` + `providers.py`/`serve.py`（forget_model） + 单测 | ✅ |
| M4 | Playground 输入草稿自动保存 | `PlaygroundPanel.vue` + selfcheck | ✅ |
| M5 | 文档（docs/04/13/15/40/42）+ 验证 + 去敏 push | 文档 + CI | ⏳ |

## 5. 验收

- ③段清单**只显示当前作业包内**作业纸；未选包时提示选择包；可"移动/复制"某作业纸到其他包（引用），操作后两包清单正确；
- 水印支持**不同作业纸用不同命名样式**且 UI 以**二维矩阵**清晰呈现；批量应用**默认勾选当前包全部**作业纸；
- Playground **模型可下拉点选**（当前 provider 候选 + 自定义输入），候选可记录；
- Playground 提问/批量/附件/参数**输入即自动保存**，刷新不丢，可清空；
- engine pytest / PWA build+selfcheck / 脱敏扫描 全绿。
