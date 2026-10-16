# D93 任务需求单：summary/copy/translation 合成题 + 水印预览修复 + 清单列 + 整班预览页码/公式

> 日期：2026-10-16
> 状态：**已拍板**（讨论定调），按 §6 执行。
> 关联：`docs/43-D90`/`docs/45-D92`；旧代码 `_legacy/2603paperDesign/src/paperdesign/kbtools.py`
> （`_summaryChap`/`_oneChap`/`_translationChap`）、`kb_reader/loader.py`（copy 的 page 列、translation 表）；
> engine `paper/task.py`、PWA `lib/sheetHtml.ts`/`lib/taskpad.ts`、`configs`。

## 1. 问题查证（2026-10-16）

| # | 现象 | 根因（代码） |
|---|---|---|
| Q1 | summary tag 未自动加"总结题" | **当前系统无此合成逻辑**（引擎/PWA grep 全空）；旧码 `_summaryChap` 有固定模板 |
| Q2 | copy 题库未把 `page` 拼进题干 | 同上，无 `请抄写：{page}页 {content}，并画出示意图` 合成 |
| Q3 | 水印矩阵"全选当前包/应用"预览不变 | PWA `sheetHtml.ts:resolveWmItems` **只读 `pad.watermark.items`，不解析 `style_ref`**（引擎已解析，PWA 预览漏了） |
| Q4 | 清单列无"章节+题号"，含无用"学期/班级" | `SheetPreviewSection.vue` 列表头固定；未从 `pad.items` 拼章节/id |
| Q5 | translation 未随机加翻译题 | 无合成逻辑；旧码 `_translationChap` 从 `translation.xlsx` 随机抽 |
| Q6 | 整班预览页码不连续、未按学号排序 | `stringifySheetHtml` 的 `pageN=pi+1`（每生从 1 起）；整班按 `partitionStudentsByTag` 分组排序，非学号 |
| Q7 | 整班预览公式不渲染（设计页正常） | 两处同调 `stringifySheetHtml`；`katexScript()` 仅监听 `DOMContentLoaded`（defer 时序竞态），需改为**等 KaTeX 就绪再渲染** |

## 2. 旧代码规格（原样保留语义）

- **summary**：`content = "请总结课堂内容。（提示：列出主要概念、定律，包括定义、公式、示意图，指出概念之间的关系，如xx是xxx的前提条件、xx经求导积分可得到xxx等。）"`，id=`summary`，**每题纸自动 1 道**。
- **copy**：`content = f"请抄写：{page}页 {content}，并画出示意图。（{id}）"`（源码 `kbtools._oneChap`，仅当 `the_kb is kb_copy` 且行有 `page`）。
- **translation**：从 `translation.xlsx`（表头 名言/作者/书名/年份）**随机抽一行** →
  `content = "请翻译以下内容：\n{saying} (by {author}, {book}, {year})\n并回答：（1）介绍一下作者及相关理论，（2）结合个人经验谈一谈对上述内容的理解。"`，id=`translation`。

## 3. 设计决策（拍板）

### 3.1 合成题的触发与"切换 tag 智能移除"
- **按 tag 触发**：作业纸 `target_tag`（或 items 里 tag）为 `summary`/`translation` 时，
  展开题目阶段**自动追加**对应合成题（无需手动选题）；
- **copy**：`kb='copy'` 分组展开时，行有 `page` → 改写题干；
- **智能移除**：把 `summary`/`translation` 合成题作为**派生题**（在展开时生成，不写进 `pad.items`）；
  因此**切 tag 时自然消失**（不残留）。若已在 items 里手工加过同 id 合成题，则**去重**（不重复）。
  - 实现：展开函数根据当前 `tag` 决定是否追加；非该 tag 不追加 → 切换即无。

### 3.2 translation 随机且**一次作业内同一道**
- 作业纸 JSON 增 `random_seed`（整型；缺省生成一次并保存）；
- 展开时以 `seed` 固定随机 → **同一作业纸每次展开同一道**；"一次分层作业"若多张作业纸需同题，
  则由 PWA 在建/绑定时**共享同一 `random_seed`**（或提供"整包统一 translation"开关）；
- 三端同源用**同一随机算法**（Python 与 TS 都实现 `seed → index`，用可移植的确定性公式，如
  `idx = seed % n` 或简单 LCG，避免语言 RNG 差异）。

### 3.3 水印预览修复（Q3）
- `sheetHtml.ts:resolveWmItems` 增加 `style_ref` 解析：`items`（内联）优先 → 否则 `style_ref` 命中样式库
  → 否则默认三槽；样式库数据来自 `settings.wmStyles`（新增 `opts.wmStyles` 入参）；
- 矩阵"全选当前包"后给明确提示 + 提供"全选并应用"一键（避免只勾不点应用）。

### 3.4 清单列（Q4）
- 去掉「学期」「班级」列；新增「**选题（章节/题号）**」列：从 `pad.items` 拼
  `chap: id1、id2；kb: …`，单行截断 + `title` 悬浮显示完整。

### 3.5 整班预览：学号排序 + 连续页码（Q6）
- 整班预览**按学号排序**学生（无学号者排末尾，保持稳定）；
- 页码**跨整班连续递增**（`pageN` 不再每生从 1 起）；新增 `opts.continuousPage`（整班预览=true）；
- 页脚 `${pad.id}-第 N/总页数` 的 N 同步为连续值；总页数 = 整班总页块数。

### 3.6 整班预览公式渲染（Q7）
- `katexScript()` 改为：**等待 KaTeX 就绪**（`load` 事件 + 轮询 `renderMathInElement` 存在）后再渲染，
  不依赖 `DOMContentLoaded` 与 defer 的时序；两种预览同享。

## 4. 涉及改动

| 模块 | 改动 |
|---|---|
| `engine/src/assist/paper/task.py` | `resolve_items` 支持 summary/copy-page/translation 合成（读 `translation.xlsx`、copy 的 page；注入 seed） |
| `engine/src/assist/files/kb_io.py` | 提供 translation 条目读取（已有 `read_translation`）；copy page 列已在行 dict |
| `app/src/lib/taskpad.ts` | `Taskpad` 增 `random_seed?`；`expandPadItems` 同源合成（与引擎同算法） |
| `app/src/lib/sheetHtml.ts` | `resolveWmItems` 解析 `style_ref`；`stringifySheetHtml` 连续页码 + 学号排序开关；`katexScript` 就绪等待 |
| `app/src/views/RosterView.vue` | 整班预览传 `continuousPage` + 按学号排序 |
| `app/src/components/SheetPreviewSection.vue` | 清单列改（+章节/id，−学期/班级） |
| `app/src/views/SheetLayoutView.vue` | 矩阵全选后"应用"提示/一键 |
| 文档 | docs/04（random_seed/合成契约）、docs/13/15/39 |

## 5. 合成题三端同源（关键）

- 引擎（出 PDF/HTML）与 PWA（预览）**必须同算法**：
  - summary/copy：确定性，无差异；
  - translation：`index = seed % n`（n=translation 行数）+ 同一模板 → 两端一致；
- 新增 **parity 哨兵**：同一 seed + 同一 translation 表 → 引擎与 PWA 展开的 translation 题面一致
  （engine pytest + PWA selfcheck 各断言）。

## 6. 分期实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| S1 | 引擎：summary/copy-page/translation 合成 + `resolve_items` 注入 seed + 单测 | `paper/compose.py` + `paper/task.py`（含 batch/htmlfile 调用）+ 单测 | ✅ |
| S2 | PWA：`expandPadItems` 同源合成 + `random_seed` 字段 + selfcheck（含跨语言 parity） | `lib/taskpad.ts` + `lib/sheetHtml.ts` + selfcheck | ✅ |
| S3 | 水印预览修复：`resolveWmItems` 解析 `style_ref` + 矩阵"全选并应用" | `lib/sheetHtml.ts` + 各视图传 `wmStyles` + `SheetLayoutView.vue` + selfcheck | ✅ |
| S4 | 清单列：+章节/题号，−学期/班级 | `SheetPreviewSection.vue` | ✅ |
| S5 | 整班预览：学号排序 + 连续页码 + KaTeX 就绪等待 | `lib/sheetHtml.ts` + `RosterView.vue` + selfcheck | ✅ |
| S6 | 文档 + 验证 + 去敏 push | 文档 + CI | ✅ |

## 7. 验收

- summary 作业纸自动含 1 道总结题；copy 题干含"{page}页…画出示意图"；translation 随机且**同一作业纸稳定**、一次作业多纸同题；
- **切 tag** 后已合成的 summary/translation 不残留；
- 水印：写 `style_ref`（含矩阵批量应用）后 **PWA 预览立即显示**；引擎 PDF/HTML 一致；
- 清单显示章节/题号，无学期/班级；过长截断 + 悬浮完整；
- 整班预览：**按学号排序**、**页码跨班连续递增**、**公式正常渲染**（离线也渲染）；
- engine pytest / PWA build+selfcheck（含 parity）/ 脱敏扫描 全绿。
