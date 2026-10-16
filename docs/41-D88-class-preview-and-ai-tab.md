# D88 任务需求单：整班预览"混合示例"修复 + PWA「AI 辅助批阅」选项卡（方案 A）

> 日期：2026-10-15
> 状态：**§1–§5 全部完成**（整班预览三条 + AI 选项卡重构 + 文档/验证）。验证：engine `pytest` 271 passed；PWA `npm run build` 通过。
> 关联：`docs/39-D86-ai-grading-tab.md`（AI 批阅引擎/端点已就绪）、`docs/40-D87-...`（水印样式库）。

## 1. 整班预览"混合示例"根因（2026-10-15 查证）

`RosterView.buildClassPreviewHtml()` → `stringifySheetHtml(inputs)`（**不传** `opts.students`）；
`buildClassInputs()` 的 groups = **每一份已保存作业纸**（`partitionStudentsByTag` 为每个 pad 建组），
未匹配到学生的 pad → `students: []` → `sheetHtml` 回落 **`SYNTHETIC_STUDENTS`（学生A/classA/2026xxxx01）**
→ 于是出现"有学生的包显示真实学生、没学生的包显示示例学生"的**混合**；
另外 tag 未绑定任何包的学生进 `unmatched` 后**被静默丢弃**（只报数量）。

## 2. 修复（三条全做，已拍板）

- **a) 整班模式禁用合成回落**：`stringifySheetHtml` 增加 `syntheticFallback?: boolean`（**缺省 true** = 模板态，
  设计页"模板预览"仍显示 学生A/B）；**整班预览传 false** → 空学生的包**直接跳过**（不出示例页）；
- **b) 未匹配学生列名**：整班预览提示改为"未出页 N 人（tag 未绑定或未选兜底变体）：姓名…"，
  并把名单暴露到 manifest 文本；仍保留"兜底变体"下拉（选了兜底变体就不再是未出页）；
- **c) 页眉班级字段解析顺序**：由 `stu.class || pad.class || 'classA'` 改为
  **`stu.class → 学习通班级名/class_dir 派生名 → 空（不写班级）`**；同步三端：
  PWA `sheetHtml.ts`、引擎模板 `assignment.html.j2`、引擎 `htmlfile.py`（现也有 `or "classA"`）。

> 注：c 会改动"三端同源渲染"，随带补 `test_sheet_html.py` parity 哨兵断言（不再出现 classA 回落）。

## 3. PWA「AI 辅助批阅」选项卡（方案 A）

- `App.vue` tab：`{ key:'grading', label:'批阅' }` → **label 改为「AI 辅助批阅」**（key/hash 不变，避免破坏 #/grading）；
- `GradingView.vue` 重构为 AI 页，六区：
  ① LLM 设置（provider 管理 + 两段式；key 掩码）
  ② 班级↔作业纸目录映射（class_map）
  ③ 任务（选已下载作业 + 作业包 + 模式 optimized/brute + tags + 限前 N + 开始 AI 批阅 + 进度流）
  ④ 逐生审核（表格：姓名/tag/草稿状态/分数/来源 → 点开 = 现有人工批阅栏，改分/批语/图片、保存到本地）
  ⑤ 报告（一键生成批阅报告：AI 报告 / 人工报告，标注不同）
  ⑥ 上传（一键上传全部批阅（含打分）；只传已批阅；未批阅提示"尚余 N 名" + 一键 AI 批阅）
- **迁移**：把 D86 临时放在 `XxetongView` 的「AI 辅助批阅」折叠面板**整体搬到 GradingView 后删除**；
- **保留** GradingView 原有"选作业纸 JSON + 选本地图片 → CLI 命令"为页内
  **「高级/离线（CLI 指引）」折叠块**（离线可用）；
- 「逐生人工批阅（简易批注风格）」仍留在「作业预览-学习通 → 批阅图片 → 逐生预览」，两种风格并存。

## 4. 分期实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| §1 | 整班预览 a（syntheticFallback 开关 + 空包跳过） | `sheetHtml.ts` + `RosterView.vue` + selfcheck | ✅ |
| §2 | 整班预览 b（未匹配学生列名） | `RosterView.vue`（`buildClassInputs` 返回 unmatchedNames；提示列名前 12 + 总数）| ✅ |
| §3 | 整班预览 c（班级字段解析 + 三端同步 + parity 哨兵） | `sheetHtml.ts`（`stu.class → groupName → 空`）/ `htmlfile.py`（去 classA）/ 模板沿用 class_display + 回归测试 | ✅ |
| §4 | AI 选项卡重构（迁移面板 + tab 改名 + 保留离线块） | 新组件 `components/AiGradingPanel.vue`（六区） + `App.vue` tab 改名「AI 辅助批阅」 + `GradingView.vue` 挂载、原「选包/选图/CLI」收进「高级 / 离线」折叠块 + 删除 XxetongView 临时面板 | ✅ |
| §5 | 文档（docs/13/39/41、docs/15 手册入口指向）+ 验证 | 文档 + build/selfcheck/CI | ✅ |

## 5. 验收

- 整班预览中**不再出现 学生A/classA**；未出页学生**按姓名列出**；页眉班级取真实班级（无值则留空，不回落 `classA`）；
- 「批阅」tab 改名为「AI 辅助批阅」，六区功能可用（设置/映射/任务/审核/报告/上传），离线 CLI 块保留；
- engine pytest / PWA build+selfcheck / CI 全绿。
