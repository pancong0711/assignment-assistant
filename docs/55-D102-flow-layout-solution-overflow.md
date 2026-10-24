# D102 任务需求单：参考答案溢出 → 流式排布（答案必须完整）

> 日期：2026-10-24
> 状态：**T1–T6 完成**
> 关联：`docs/54-D101-...`（公式渲染）、`docs/46-D93`（合成题）、`docs/13-D43`（参考答案开关）、
> `docs/14 §VB`（HTML 打印主通道）、`docs/42-D89`（solution 多版本）

## 1. 问题来源（用户反馈）

参考答案在当前页放不下时**没有换行视觉、出现截断**；若强行完整显示又会顶破作业纸版式。

## 2. 实测复现与根因（Chromium，4 题/页 + 超长 AI 答案）

| 指标 | 实测 |
|---|---|
| `.sheet-frame` 高度 | 296px（网格等分，硬性） |
| 答案内容高度 | 483px |
| **被裁像素** | **237px**（`overflow:hidden`） |
| `.sheet-page` 溢出 | +89px（页面被顶破） |
| `white-space` / `word-break` | `normal` / `break-word` → **文字本来就在正常折行** |

> 重要：用户描述的“没有换行”实为**纵向被裁**（后续行被 `overflow:hidden` 切掉），
> 不是 `white-space` 问题。据此排除了 `white-space`/`margin-top` 一类无效修法。

根因是三层硬约束叠加：

```
.sheet-page  height:296mm; overflow:hidden
  .sheet-body  display:grid; grid-template-rows:repeat(N, minmax(0,1fr))  ← 等分、不随内容长
    .sheet-frame  overflow:hidden                                          ← 直接裁掉
```

**“答案撑开 + 后续题后推”与“先按 per_page 纯切片再渲染”在结构上不兼容**：
切块时尚未知每题实际高度。

实测排除的非方案：

| 尝试 | 结果 |
|---|---|
| `white-space: normal` / `margin-top: 0` | 无变化 |
| `.sheet-frame { overflow: visible }` | 溢出页外 147px，仍被 `.sheet-page hidden` 裁 |
| `.sheet-body { grid-auto-rows: auto }` | **整份文档崩坏**（pageOverflow 11022px） |
| 答案 `max-height + hidden` | 截断受控，但答案仍不完整 |
| 缩字号至 8pt | 页不溢出，但**仍裁 86px**，且不可读 |

## 3. 设计决策（用户拍板 2026-10-24）

| 项 | 决定 |
|---|---|
| 答案完整性 | **必须完整显示**，溢出时把后续题目往后推（允许破坏原版式） |
| 页面留白 | **可以填不满**（接受页尾留白，不做测量重排） |
| 分页粒度 | 题目之间不共处同一格；**单题内部允许跨页切分**（见 §5 已知边界） |
| 分隔虚线 | **跟随题目**：废弃百分比绝对定位虚线，改用题框 `border-bottom` |
| `per_page` 语义 | 改为**每页最多 N 题**（答案长时自动减少） |
| 学生版 | 与教师版**同一套流式布局**（单套 CSS，避免双份维护） |
| 分页实现 | **保持单个 `.sheet-page` 容器**，内容超出 A4 时由浏览器自动分页；不做 JS 测量重排（CLI/Jinja 无法测量，双端会分裂） |
| 页码准确性 | 多页时“第 N/M 页”**暂不准确**（历史限制，单独立项），本单不修 |

## 4. 目标布局（已实测验证）

```css
.sheet-body   { display:flex; flex-direction:column; gap:0; overflow:visible; }
.sheet-frame  { flex:none; overflow:visible;
                border-bottom:1px dashed #777;          /* 虚线跟随题目 */
                break-inside:avoid; page-break-inside:avoid; }
.sf-line      { display:none; }                          /* 废弃绝对定位虚线 */
.sheet-page   { height:auto; min-height:296mm; overflow:visible;
                display:flex; flex-direction:column; }
.sheet-footer { flex:none; }
@media print { .sheet-page{position:relative} .sheet-footer{position:absolute;bottom:12mm;left:14mm;right:14mm} }
```

实测效果（同一复现场景）：

| 指标 | 改前 | 改后 |
|---|---|---|
| 题框裁剪 | 237px | **0** |
| 页内溢出 | +89px | **0** |
| 题框高度 | 固定 296px | **392px 随内容自增** |
| 页高 | 固定 296mm | **自适应（min 296mm）** |
| 页脚 | 被挤出 | **在页内** |
| 虚线 | 绝对定位错位 | **跟随题框底边** |

## 5. 过程中发现并解决的坑

| # | 坑 | 解法 |
|---|---|---|
| P1 | 页脚跑到最后一页顶部（`margin-top:auto` 跨页失效，实测 p3 顶部出现“第 1/1页 签名”） | 打印时 `.sheet-page{position:relative}` + `.sheet-footer{position:absolute;bottom:12mm}` |
| P2 | `break-inside:avoid` 被覆盖，题目被横切（实测 `breakInside=auto`） | 同时写 `break-inside` 与 `page-break-inside`，并保证 `!important` 生效 |

## 6. 任务分解

| # | 任务 | 文件 |
|---|---|---|
| T1 | `printCss()` 改流式布局：`.sheet-body` flex 列、`.sheet-frame` 自然高 + 底边虚线、`.sheet-page` 自适应、`.sf-line` 废弃 | `app/src/lib/sheetHtml.ts` |
| T2 | j2 模板同步上述 CSS（D1 超集铁律） | `engine/templates/assignment.html.j2` |
| T3 | 打印规则：`break-inside:avoid` + 页脚绝对定位 | 同上两处 |
| T4 | UI 文案：“每页 N 题” → “每页最多 N 题（答案较长时自动减少）” | `SheetLayoutView.vue` 等 |
| T5 | `gridBodyStyle` 不再输出固定行高（保留 `data-*` 属性供旧测试/排查） | `lib/taskpad.ts`、`paper/grid.py` |
| T6 | 自检：结构断言 + Playwright 回归（无裁剪/页脚在页内/虚线跟随/不横切） | `selfcheck-d102-*`、`test_sheet_html.py` |

## 7. 已知边界（本单不修，登记）

1. **单题内部跨页**：`break-inside:avoid` 保证“题目之间不合并”，但单题内容超过一整页时仍会被分页切开（受 A4 物理限制，无解）。
2. **多页时页码不准**：仍是“第 1/1 页”（分页由浏览器完成，HTML 无法预知）。
3. **页尾留白**：不测量重排的自然结果（用户已接受）。

## 8. 回滚

- 布局为纯 CSS 变更，回滚即恢复等分网格；`data-grid` 等属性保留，旧测试不受影响。

---

## 9. 实施记录（2026-10-24）

### 9.1 变更清单

| 文件 | 改动 |
|---|---|
| `app/src/lib/sheetHtml.ts` | `printCss()`：`.sheet-page` 改 `min-height:296mm + height:auto + overflow:visible`；`.sheet-body` 改 `flex` 列（去等分行高）；`.sheet-frame` 改 `flex:none + overflow:visible + break-inside:avoid` + **底边虚线**；`.sf-line` 默认 `display:none`；`.sheet-footer` 加 `flex:none + margin-top:auto`；`@media print` 加页高自适应、页脚绝对贴底、题目不横切 |
| `engine/templates/assignment.html.j2` | 同步上述全部 CSS（D1 超集铁律） |
| `app/src/lib/taskpad.ts` | `gridBodyStyle()` 改输出 `display:flex;flex-direction:column;gap:0;overflow:visible;`（rows/cols/order 保留为参数，`data-*` 属性不变） |
| `engine/src/assist/paper/grid.py` | `grid_body_style()` 同上（保留 rows/cols/order 形参） |
| `app/src/views/SheetLayoutView.vue` | 「每页题数」→「每页**最多**题数」；说明文案改为流式语义；`gridWarning` 不再做容量校验（行/列已不参与排版） |
| `engine/tests/test_grid.py` | 断言改为「不得输出等分行高」 |
| `engine/tests/test_sheet_html.py` | D61 断言更新为 D102 语义（`sf-line` 保留但隐藏、`.sheet-body` 为 flex 列） |
| `app/tests/selfcheck-d102-flow-layout.mjs`（新增） | 6 组断言：gridBodyStyle / 无等分行高 / 题框不裁切 / 虚线跟随 / 页高自适应 / 打印态 |
| `app/package.json` | selfcheck 家族追加 D102 |

### 9.2 实测对比（同一复现场景：4 题/页 + 超长答案）

| 指标 | D102 前 | D102 后 |
|---|---|---|
| 题框裁剪 | 237px（答案被切） | **0** |
| 页内溢出 | +89px（页被顶破） | **0** |
| 题框高度 | 固定 296px | **随内容（392→616px）** |
| 页高 | 固定 296mm | **自适应（467→704mm）** |
| 页脚 | 被挤出 / 跨页跑到下一页顶部 | **在页内；打印态绝对贴底** |
| 分隔虚线 | 百分比绝对定位（错位） | **跟随题框底边** |
| 题目合并 | — | **每页恰好从一道题开始（实测 p1–p4 各含且仅含第 1/2/3/4 题）** |

### 9.3 验收

| 项 | 结果 |
|---|---|
| engine pytest 全量 | **512 passed** |
| app `vue-tsc -b` / `vite build` | **0 error** |
| app `npm run selfcheck` | **全绿**（含 D102 6 组） |
| 变异验证（把 `gridBodyStyle` 改回等分行高） | D102 自检**失败** → 断言有效 |
| Chromium 端到端（真实 HTML） | 零裁剪、页高自适应、虚线跟随、页脚在页内、旧虚线隐藏 |
| 真实 PWA（vite preview + 设计页 iframe） | `display:flex` / `flex-direction:column` / `gridTemplateRows:none` / `.sf-line` 隐藏 |

### 9.4 过程中额外发现并修复

1. **`vue-tsc` 查不出模板字符串内的反引号**：CSS 注释里误写 `` `data-grid…` `` 使 esbuild 打包失败而 `vue-tsc` 静默通过。
   → 已把 esbuild 打包作为 D102 自检的第一步（充当语法哨兵）。
2. **CSS 注释导致 `--no-solution` 断言失败**：注释里出现「参考答案」字样，被既有断言当成内容泄漏。
   → 改为「答案文本」，而非放宽断言（保留该哨兵价值）。

