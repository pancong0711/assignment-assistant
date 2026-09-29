# 13 — 任务需求单（2026-09-29 重建 · 网页结构两轮反馈拍板）

> 分工：docs/12-backlog.md = 总账（历史批次与实施日志）；**本文 = 当前活动需求单**。
> 说明：上一版（R1–R4 系列）在 commit 5e3e092 被清空（当时 commit 信息称"D41 任务需求单"、
> 实际 diff 为 231 行全删；D41 系列实施记录实际落在 docs/12 的 2026-09-28 条目）。
> 本文自本轮起恢复需求单职能；决策编号接全库 D 序列（D41/D42 已用，本单 = D43）。
> 来源 = 2026-09-29 两轮"仅讨论"会话（用户拍板 + 新需求登记）。

---

## D43-1 · 设计页「输出与交付」模块沉底（已拍板）

**内容**：从 SheetLayoutView 卡①（标题"① 版式 / 页眉页脚 / 作业纸头部"）迁出与其标题无关的全部输出类操作，
集中为设计页**底部**独立卡「输出与交付」：

| 动作 | 现位置 | 去向 |
|---|---|---|
| 🖨 打印浏览器版 / ⬇ 下载整班 HTML / 📖 打印教程 | 卡① "浏览器打印主通道" h3 | 底部输出卡 |
| 🖨 打印级 PDF（需引擎） / ⬆ 上传到学习通（需引擎） | 卡① "引擎依赖按钮" h3 | 底部输出卡 |
| 导出作业纸 JSON + 仅保存 | 卡① **grade details 折叠块内部** | 保存进工具栏（D43-2）；导出 JSON 进输出卡 |
| 导出全部（zip） | 卡③ 清单区 | 输出卡（清单卡只保留浏览/载入/删除/单包预览） |

**验收**：卡①只含 版式 + 页眉页脚 + 作业纸头部；输出操作全部在页面最后一段；
条件置灰语义（D13 引擎在线检测）不变；build/vue-tsc 0 err。

---

## D43-2 · 「保存」进「新建」工具栏行（已拍板）

**内容**：「仅保存」上移至设计页顶部卡（与 新建作业纸 / 新建（克隆当前版式）/ 导入作业纸 JSON 同一行）；
「导出作业纸 JSON」建议同排（最终 UI 评审定）。文件动线 = 新建→导入→保存→导出 一行齐。

**验收**：顶部一行覆盖五操作；grade details 内的兜底按钮（现状历史遗留）消失；
保存后清单即时出现条目的反馈文案不变。

---

## D43-3 · 预览合并为单一 HTML 模板渲染（已拍板 · 原则）

**内容**：废除"CSS 近似预览 + HTML 打印版预览"双轨，页内预览改用 `stringifySheetHtml`
（即 CLI `assist sheet html` 同模板的 TS 同构）+ iframe 实时渲染（编辑防抖刷新；KaTeX 含接线审计项见下）。
"显示为浏览器打印版（HTML overlay）"弹窗与页内预览同模板同源，语义=同一预览的两种观察方式。

**落点/审计项**：`lib/sheetHtml.ts`（唯一模板）+ `SheetLayoutView` 预览段（删 `.sheet-page` CSS 近似实现，
保留 wm-pos-grid 等纯编辑辅助可视化）；`lib/classOverlay.ts`（VC-3 整班 fallback）与
`stringifySheetHtml` 的学生分页块形状对齐审计——本批顺带收敛双实现。

**验收**：预览 = 打印产物同源（WYSIWYP）；分隔线/页眉页脚/水印层只在 sheetHtml 模板一处定义
（历史 D21/D42 类"预览与打印对不齐"补丁不再需要）；性能可接受（防抖 ≤200ms）。

**KaTeX 接线审计项（本批顺带）**：`app/public/katex/`（600KB 自托管副本：katex.min.css + katex.min.js +
fonts，D38 随 083347d 入库）**已就位但两份模板都未接线**——`sheetHtml.ts` katexHead() 与
`engine/templates/assignment.html.j2 :31-33` 仍写死 jsdelivr CDN。离线/内网时 iframe 预览与
CLI 下发 HTML 的公式均按 $..$ 源码降级。本批决定接线策略：同源相对路径（engine serve/页内预览）
vs base64 内联（下载/CLI 分发版内包含）vs 保留 CDN——衔接 docs/14 §VB-2 登记项；
`KATEX_VERSION` 常量在 sheetHtml.ts 与 htmlfile.py 各一份，顺带合并口径；
帮助页文案修正：HelpView 帮助卡宣称"PWA 自带 KaTeX 离线（0.16.4）"与实现不符
（模板仍走 CDN、自托管副本未接线）——随本批改正表述或接线后删除。

---

## D43-4 · 作业纸清单 + 预览 合卡（已拍板 · 原则）

**内容**：设计页"作业纸清单"目前**出现两次**（SheetLayoutView 卡③尾部一次、SheetContentView "④ 作业纸清单"一次）。
合并为一张卡：清单行（载入/删除/预览）+ 同卡展示实时预览（或紧邻预览面板）；
内容块只保留 选题篮 / items / target_tag 绑定面板；"预览全部连排"入口随清单卡。

**验收**：全页"作业纸清单"出现次数 = 1；点清单行即可预览（省一次滚动）；
预览读同一 taskpad store，数据流无新增状态。

---

## D43-5 · 批阅独立选项卡（grade 移出作业纸设计页）（已拍板 · 本轮）

**考古**：docs/05-D25（R2.3）当时记录为「批阅工作台并入"学习通"或独立保留待定（实施时定）」——
两条路当时并存，实施走了"并入学习通"（M-A S1）。本轮用户拍板反转：**独立选项卡**。
现状 = XxetongView 下半段是原 GradingView 逻辑 1:1 迁入件（onPadFile/onImages/copyGradeCmd 等 6 组函数），
且 `GradingView.vue` 仍完整保留但已成无引用孤儿文件。同时 `DesignerView.vue` 也是孤儿（旧版式视图，未在导航注册）。

**内容**：
1. TABS 新增 `{ key:'grading', label:'批阅', component: GradingView }`（GradingView.vue 复活）；
   **导航位置已拍板（2026-09-29）**：设置中心 | 题库编辑器 | 作业纸设计 | 班级与标签 |
   **批阅** | 学习通 | 导入导出 | 使用说明（8 项；批次=现役可用功能优先于占位卡）；
2. XxetongView 删除下半段（批阅工作台迁入件），恢复纯学习通占位；
3. SheetLayoutView 卡① 的 grade details 整块删除（其内兜底的导出/仅保存随 D43-1/D43-2 迁出）；
   **schema 不动**：taskpad JSON 的 `grade` 节保留（默认空 = 仅出作业纸），仅 UI 归属变更；
4. 批阅页加"当前作业纸 grade 配置"卡：初期只显示节状态（空/含 steps·models）+ 说明
   "留空 = 仅出作业纸，批阅走引擎默认值"；编辑器（steps/models）随阶段3 AI 批阅细化一并定；
5. HASH_ALIASES：删 `grading:'xxetong'`（#/grading 自动直达新 tab；designer/layout/content/sheet 重定向不动）；
6. 孤儿清理决策：`GradingView.vue` 复活引用；`DesignerView.vue` 建议删除（历史遗留，避免双份语义）。

**验收**：导航 8 项含批阅；作业纸设计页 0 处 grade 字样（帮助文案同步）；
批阅页"导入 JSON / 摘要 / 选图片 / 复制 CLI"原有功能全部可用且不再重复出现；
学习通页无批阅混合内容；build 0 err。

---

## D43-6 · 预览/打印内容开关：参考答案 / 学生示例 + 预览域分层（本轮口径修正 · 2026-09-29）

> 本条对两轮讨论中的"D43-6"做了**口径修正**（旧写法"按勾选学生过滤打印范围"作废，以本条为准）。
> 考古结论仍有效：与"勾选"相关的既有实现只有成绩源**列**勾选（R3.3/VC-5）与 punish 行勾，
> "预览/打印内容开关"同样从未立项。

**两个开关的定义**：
| 开关 | 未勾选 | 已勾选 |
|---|---|---|
| ☑ 参考答案 | 预览/打印**不含**"参考答案：…"行（答案区整块移除，题框只保留 题干+题图） | 预览/打印含参考答案（现状行为） |
| ☑ 学生示例 | 班级 / 学号 / 姓名三处**空白**（保留手写空位线），预览/打印 **1 份**（纯模板） | 按合成 学生A/B 方法预览/打印 **2 份**（可检视页眉/学籍栏/水印字的摆位） |

**生效面（三个模板级预览 + 两个模板级输出动作，同一对开关统一生效）**：
1. 设计页**当前编辑实时预览**（D43-4 合卡内的预览面板）；
2. 清单行「预览」（每类作业纸一份预览）；
3. 「预览全部作业纸（连排）」（N 份作业纸 ×（1 份空白 或 2 份示例）连排）；
4. 输出与交付卡（D43-1）的「🖨 打印浏览器版」「⬇ 下载 HTML」——同样按开关出 1 份空白或 2 份示例。

**预览域分层（本条拍板的架构约束）**：
- **作业纸设计选项卡 = 模板级预览/打印**：只看"一份作业纸长相"（空白 1 份或示例 2 份），
  **不做整班展开**；
- **整班分层作业纸预览 = 仅在「班级与标签」选项卡**：每生按 tag→作业纸映射领包、每生一页
  （VC-3 唯一入口放 RosterView）；SheetContentView 现存重复的「预览整班」卡（classOverlay 第二入口）
  **移除**（与 D43-3 classOverlay 收敛同批处理——删除即收敛，无需对齐审计）；
- 连带语义修正：现状清单行「预览」/「预览全部」在有名单时会 **全班逐生展开**
  （`sheetStudents()` = roster.students，28 人 × N 包），与以上口径冲突——预览入口全部切回模板态。

**数据面（stringifySheetHtml 选项化）**：
- 新 opts：`includeSolution: boolean`（默认 true 兼容现状）；`students: []`（空学员 = 页眉三空位）
  或 `SYNTHETIC_STUDENTS` 或（仅班级页整班通道）roster.students；
- 页眉空态渲染：班级/学号/姓名留手写空位线（`班级：____ 学号：____ 姓名：____`），作业 id/course/页码照常；
- 水印层照常预览占位（"每生唯一标识由 engine 打印时注入"语义在空白模板下不注入标识）；
- 引擎 CLI parity（可选、非阻塞）：`assist sheet html` 增 `--no-solution` / `--students blank|sample`；
  D1 超集铁律不受影响（PWA 先行，CLI 随后补齐）。

**待拍板**：a) 两开关默认值（建议：参考答案=开、学生示例=开，预览看得全；打印前手动反转）；
b) 班级与标签的整班预览要不要也加「参考答案」开关（建议：加——出题版/教师版双用）；
c) 开关状态是否跨会话持久化（建议：不持久化，页内即用即态）。

---

## 实施批次建议

| 批 | 覆盖 | 规模 | 备注 |
|---|---|---|---|
| A | D43-1 + D43-2（设计页输出沉底 + 保存上移） | 小 | 一个会话，纯前端重排 |
| B | D43-5（批阅独立 tab + 孤儿清理） | 小 | GradingView 复活 + XxetongView 减重 |
| C | D43-3 + D43-4 + D43-6 域分层（预览合一 + 清单合卡 + 整班入口归班级与标签页） | 中 | 含 classOverlay 双实现审计 |
| D | D43-6（勾选打印范围） | 中 | 三处细节拍板后实施 |

> 红线不变：taskpad schema 不动（grade 节保留）；D1 CLI 超集铁律不变；
> 预览合并后以 `lib/sheetHtml.ts` 为唯一版式事实源（与引擎 j2 模板对齐口径沿用 docs/05-D30/D36）。

---

## D43 实施记录（2026-09-29 · 全批次落地，同日会话）

| 批 | 内容 | 状态 | 落点 |
|---|---|---|---|
| A | D43-1 输出与交付沉底 + D43-2 保存进"新建"栏 | ✅ | SheetLayoutView：新「输出与交付」卡（id=output）+ 工具栏「仅保存」；grade/打印/导出全数迁出卡① |
| B | D43-5 批阅独立选项卡 | ✅ | App.vue TABS 8 项（批阅=班级与标签与学习通之间）；GradingView 复活注册；XxetongView 撤出迁入件恢复纯学习通；HASH_ALIASES 删 grading→xxetong（#/grading 直达）；DesignerView.vue 孤儿删除 |
| C | D43-3 预览合一（iframe·同一模板） + D43-4 清单合卡 + 整班入口归班级页 | ✅ | SheetLayoutView ③卡 iframe 实时（防抖 180ms，相对 KaTeX）；CSS 近似预览删除；SheetContent ④清单删除（唯一清单在③卡）；SheetContent「预览整班」卡删除；RosterView VC-3 = 唯一整班入口，改用 stringifySheetHtml（partitionStudentsByTag 分段；classOverlay.ts 删除第二套页块模板） |
| D | D43-6 内容开关（参考答案/学生示例，默认**均不勾**） | ✅ | sheetHtml.ts 增 includeSolution / per-pad students 覆盖 / BLANK_STUDENT 空白学籍（页眉手写空位线）；开关作用于 实时预览/清单行预览/全部连排/打印/下载 |
| — | KaTeX 接线（D43-3 审计项） | ✅ | app/public/katex 补 contrib/auto-render.min.js；katexIncludeHtml 三模式：relative（预览/打印，离线渲染）/cdn（缺省=引擎 parity）/raw（下载/CLI 外发文件 base64 内联 srcipt+css+woff2 → file:// 离线可开）；fetchSelfContainedKatex() 模块级缓存；SettingsView 增「KaTeX 公式资源」自检卡；HelpView 帮助卡文案改正 |

**验证**：`vue-tsc -b && vite build` 0 err（dist/assets/index-*.js 256KB）；esbuild+node 冒烟 pass（相对 KaTeX 头/无答案行/空白学籍＿线/示例 2 份/整班分段 data-student/CDN parity 哨兵标记留存）；引擎 pytest（parity 哨兵）由 CI 复核（引擎 j2/CLI 未动）。

**未动**：taskpad schema（grade 节保留）；引擎代码 0 改动（CLI parity `--no-solution/--students blank|sample` 留待后续，见下"遗留"）。

**遗留（非阻塞）**：① 引擎 j2/CLI 的 content 开关 parity；② batch zip 内 sheets/*.html 仍 CDN 态（体积考量）；③ WCAG：iframe 键盘导航提示。
