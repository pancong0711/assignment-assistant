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

---

## D44 · KaTeX 资源归属：npm 依赖 + 构建期拷贝（2026-09-29 拍板 · 本轮实施）

**拍板**：KaTeX 600KB vendor 资产**不入远程仓库**；归属 = `npm 依赖（katex@0.16.4 锁版）+ 构建期拷贝 public/katex`（与 xlsx/jszip 同模式）。用户侧**零配置**（与"设置中心可直接配置、最好不需要用户管理环境"的最优解=无需配置一致）；start.bat/sh 不动。

**落点**：
- `app/package.json`：dependencies + `katex: "0.16.4"`（锁死，勿用 `^`——与 engine `htmlfile.py KATEX_VERSION` / `assignment.html.j2` CDN 口径锁定，parity 哨兵护航）；scripts + `predev/prebuild: node tools/copy-katex.mjs`；
- `app/tools/copy-katex.mjs`：node_modules/katex/dist → public/katex（**选择集**：katex.min.css + katex.min.js + contrib/auto-render.min.js + fonts/*.woff2 ×20 = 608KB，与 D43 前手工 vendor 子集同口径；woff/ttf 不进 dist）；
- `.gitignore` + `app/public/katex/`；`git rm -r --cached app/public/katex`（历史旧 blob 保留，前向不再入库）；
- SettingsView 自检卡不动（语义仍真：资源随 dist 发布）；sheetHtml 三模式/predev 手动跑一次即复原。
- fresh clone 后未 build 时 `npm run dev` 由 `predev` 自动拷贝（dev 无需先 build）。

**候选方案记录（未采纳）**：B = 设置中心运行时装载（多 CDN 源探测 + Cache Storage 写入 + 相对路径经 SW 服务；SW 现有 fetch 处理器零改动即可命中；缺点：LAN http 二屏 insecure context 下 SW 不可用）；C = 引擎侧 /install 管道下载到 workspace/.runtime/katex + serve 挂载（代价：把 PWA 离线能力绑定引擎在线）。两者留作后续可选增强，当前不实施。

**验证**：`npm run build`（prebuild 自动拷贝）dist/katex 608K×20 woff2；dev `predev` 生效（/katex/* 同源 200）；bundle 哈希不变（index-CaeZC7bF.js）；Pages 部署后 /katex/katex.min.js 仍 200。

---

## E1–E4 实施记录（2026-09-29 晚 · 第 10 轮拍板后开工，本批全部完成）

| 批 | 内容 | 状态 | 落点与验证 |
|---|---|---|---|
| E1 | D46-1/2 点名册两级回退 | ✅ | PWA `rosterXlsx.readRosterXlsx`（表头自适应→前15行关键词找表头行→RosterParseError{firstRows}结构化失败）+ `buildRosterPreview` 同口径 notes；引擎 `files/roster.py read_roster` 同款 `_map_from_matrix` 内核；RosterView 失败红条 notice（前3行原文+sheet名+指引）/成功滚宽表 flash。冒烟：zjxu 形态(前8行说明+第9行异序表头) 2 人 PASS、标准表头 PASS、失败诊断 PASS、预览注记"关键词定位表头行（第 9 行…已跳过）"PASS；引擎 stub 直测三场景 PASS；`engine/tests/test_roster_parse.py` 新增（CI pytest 复核） |
| E2 | D43-7 水印双开关 | ✅ | sheetHtml opts `includeWatermark/includePageText`（缺省 true；与 pad.watermark.enabled AND）；③段 ☑显示水印图层 + ☑页码大字（默认勾）经 SheetDesignView 共享至④输出卡（打印/下载/自包含全受控）。body-DOM 冒烟 4/4 PASS（关图层整层含占位框消失；只关大字图层保留） |
| E3 | D46-3 源行内👁预览 | ✅ | 新 `lib/idbRaw.ts`（IndexedDB 轻量封装，不可用静默降级）；ScoreSource.uid + addScoreSource/rescoreWithFamily 存 raw（uid 复用防孤儿键）、removeSource 删 raw；store `previewSource`（raw→PreviewTable 即时重建）+ `reparseFromRaw`（免二次选文件，无留存回退选文件）；RosterView 行尾 👁 按钮 + PreviewTableCard 展示 + 「重解析」替代「重选文件解析」文案 |
| E4 | D46-4 全部成绩总览 | ✅ | 宽表卡更名「全部成绩总览」；综合得分列（浅拷贝 shadow 干跑 computeScoresFiltered，**不污染 store**，随勾选即时重算，正式写入仍走「重算并打 tag」）黄底高亮 + * 号注记；⬇ 导出总览 xlsx（姓名/学号/班级/各源列[未勾选标"[未参与]"]/综合/tag/punish，D46-4③按拍板含灰显列） |

**构建**：vue-tsc+vite 0 err。**红线**：schema 不动；引擎 j2/CLI 除 roster.py 回退外未动（--no-watermark 既有故 D43-7 零新增）。

### B1 · 多 sheet 成绩源支持（E1–E4 同会话追加完成）
- `rosterXlsx.ts`：`readRawSheet` 读全部 sheet → **pickBestSheet 启发式**（①前15行含姓名类表头的候选优先，②非空数据行数最多者）；`readScoreSourceXlsx/buildScoreSourcePreview` 增可选 `sheetName` 显式指定；notes 显示"共 N 张：…可在源行切换"；
- `roster.ts ScoreSource.sheetName` + **normalizeSource 透传修复**（连带发现并修复 E3 的同类隐患：**uid 此前会被 normalizeSource 吃掉**——IndexedDB raw 键实际从未落到最终对象；本轮补透传+冒烟复验，属 E3 关键修复）；
- store：`listSourceSheets(idx)`（raw→SheetNames）+ `setSourceSheet(idx, name)`（切 sheet 按当前 family 重解析，raw 免选文件）；rescoreWithFamily/reparseFromRaw/previewSource 全链带 sheetName；
- RosterView：源行尾 **⇄ sheet** 按钮 → 行内下拉即时切换（单 sheet/无留存给提示）；行信息加 `sheet=` 显示；
- 冒烟：exam/custom 自动选到数据 sheet PASS、三 sheet 干扰项 PASS、显式切换 PASS、uid 存活 PASS；build 0 err。
- 引擎侧说明：`scores.py` 本就按名匹配 sheet（`next(s for s in wb.sheetnames if sheet in s)`），CLI --sheet 语义不变，无需改。

**遗留**：旧数据源（无 uid）首次👁/⇄提示"重选文件一次即可启用"（预期降级）；D46-5/B3 题图真图预览挂后续。

---

## D45 + D43 遗留 实施记录（2026-09-29 下午 · 同日会话）

### D45 设计页段序重排 + 输出段独立拆分（用户拍板「按推荐」）
| 项 | 落点 |
|---|---|
| 段序：①版式 → ②内容 → ③预览/清单 → ④输出（工艺顺序=版式→选题→预览→交付） | SheetDesignView 重排（锚点 sticky 导航同步；form→items→preview→output 四锚 id） |
| 「输出与交付」独立组件 | 新增 `components/SheetOutputSection.vue`（props 注入 currentInput/templateStudents/includeAnswers/showSamples/getKbBinaries/engineButtonsDisabled；自身持 status；`#output` 卡） |
| 「预览与清单」独立组件 | 新增 `components/SheetPreviewSection.vue`（iframe 实时 + 开关 + 清单合卡；开关 defineModel 由父级 SheetDesignView 挂载 → ③/④段共享；`#preview` 卡） |
| ①段瘦身 | SheetLayoutView 只剩 工具栏+版式+头部+水印（535→232 行）；工具栏留在①（新建/克隆/导入/仅保存）；导出 JSON/zip 随④ |
| 工艺闭环 | ①→②→③→④；改动①（如 per_page）→③实时刷新 → ④按同开关口径输出 |

### D43 遗留① 引擎 CLI parity（`assist sheet html` 内容开关）
- `cli.py`：+ `--no-solution`（参考答案开关，与 PWA「显示参考答案」未勾同语义）+ `--students roster|sample|blank`（对应 roster 现状/合成学生A/B/单份空白模板=「显示学生示例」未勾）；
- `htmlfile.py`：`sheet_html_from_task(include_solution, students_mode)` + 公共入口 `render_assignment_html(..., include_solution, blank_header)`（StrictUndefined 安全：模板引用始终有定义）；
- `templates/assignment.html.j2`：`{% if doc.include_solution and fr.solution %}` 参考答案条件化；`{% if doc.blank_header %}` 页眉三空位（＿＿＿＿＿＿，与 PWA BLANK_STUDENT 同口径）；
- `engine/tests/test_sheet_html.py`：新增 ②b 用例（--no-solution 无"参考答案"/公式源码保留；sample=2 份；blank=1 份+三空位+data-student=""）。

### D43 遗留② batch zip 内容 KaTeX 化
- `app/src/lib/variantBatch.ts`：provider 输出改 `katex:'relative'`；新增 `addKatexToZip()`（从 PWA 同源 dist fetch → `sheets/katex/**` 一次 ~608KB：css+js+auto-render+woff2×20）；zip 内嵌后解压整目录打开 → sheets/*.html 公式离线渲染；资源拉取失败静默跳过（HTML 自身 CDN 兜底）。

### D43 遗留③ iframe 键盘可达性（最小补丁）
- ③预览 iframe / 弹层预览 iframe / 整班预览 iframe 均补 `aria-label` + `tabindex="0"`（Tab 聚焦后方向键滚动）。

**未动**：taskpad schema；引擎 make（reportlab PDF 线）；start.bat/sh。

**验证**：`vue-tsc -b && vite build` 0 err（nymHash index-E2K_YjIV.js 257.6KB）；引擎 playwright 性质：AST 解析 0 错，引擎 pytest 在 CI（tests workflow）复核（本地无 pip 环境）。

---

## D43-7 · 预览水印开关（第 8 轮反馈登记 · 待拍板后实施）

**反馈原文**：预览作业纸模板时页面上还有"第 N 页"大字水印和占位水印框——这些也要做勾选，**默认勾选**。

**现状根因（代码考古）**：③段 iframe 渲染的是完整打印 HTML，其中 `wmLayerHtml` 只要
`pad.watermark.enabled=true` 就画两层东西：
1. **页码大字水印**（`pageText !== false` 时的「第 N 页」灰斜大字）；
2. **水印图层**：items 为空时按 legacy 默认三槽出**占位标记** `[水印：university（右上）]`
   （虚线小灰框，sheetHtml.ts L254 `.wm-placeholder`）；items 有图且 wmAssets 命中则真图。
新建作业纸缺省 enabled=true + items=[] → 教师第一眼就看到三框一大字。这不是 bug，是
"PWA 无文件系统 → 引擎素材用路径 hint"的所见即所得提示，但确实不该未经选择就出现在
预览/打印产物里。

**建议方案（与 D43-6 开关体系同构，③段工具栏第三个 checkbox）**：

| 项 | 设计 |
|---|---|
| 新开关 | ☑ **显示水印**（默认**勾选**=保持现状视觉；不勾=预览/打印/下载全部不画水印层） |
| 作用面 | ③实时预览、清单行预览、连排预览、④打印浏览器版、④下载 HTML、弹层预览（与答案/示例两开关完全同机制） |
| 数据面 | `SheetHtmlOptions.includeWatermark?: boolean`（缺省 true）→ pageBlockHtml 的 `${pad.watermark.enabled ? wmLayer : ''}` 改为 `${includeWatermark && pad.watermark.enabled ? ... : ''}`；BLANK/pageText 语义不动 |
| 引擎 parity | CLI **已有** `assist sheet html --no-watermark`（VB-1 时代就在）——PWA 开关=该 flag 的前端镜像，parity 零新增引擎工作（比 D43-6 的答案开关还省事） |
| 与①卡「启用水印」的关系 | 保留两级：①卡=作业纸**属性**（存 JSON，决定引擎打不打水印）；③段开关=**本次查看/输出**的临时口径（不写 JSON）。类比：target_tag 是属性，答案开关是视图口径。UI 提示语注明差异即可 |

**拍板结果（2026-09-29 第 10 轮）**：
a) **拆两个开关**：③段工具栏 = ☑显示水印图层 + ☑显示页码大字水印（各默认勾选=现状）；
   数据面 `SheetHtmlOptions` 增 `includeWatermark?: boolean`（缺省 true，控 wm-anchor 图层含占位框）
   与 `includePageText?: boolean`（缺省 true，控「第 N 页」大字）；pageBlockHtml 的 wmLayerHtml
   拆两段渲染条件；作用于 实时预览/清单行/连排/弹层/④打印+下载（同答案/示例开关机制）；
b) 不勾水印图层时**整层消失**（含三槽占位框；推荐已确认）；
c) **题图占位框不并入水印开关**——题图是题目属性（有图才有 `[题图：path]` 占位，非全局元素），
   语义不同、不该共用开关。处理归入 D46-5（题库编辑器 fig 上传闭环 B3 同批）：PWA 无文件系统，
   kb/fig 真实图片读不到 → 预览显示占位框属预期；后续随 B3 让 PWA 端也能显示真图
   （wmAssets 同款模式：浏览器本地图片库按文件名命中即内联）。

**实施批次**：并入下一批（D45 已上线；本条改动量小：sheetHtml 一参数 + SheetPreviewSection
一 checkbox + 父级透传 + 测试冒烟；可与 D43-7c 一并做）。

---

## D46 · 名单/成绩导入健壮性与预览补全（第 9 轮反馈登记 · 2026-09-29）

### D46-1 · 教务点名册解析失败（现场 bug，最高优先）

**现象**：班级与标签页导入教务点名册 → "未读到学生行"，名单不更新。

**根因（考古确认）**：新旧代码对"点名册"读的是**两种不同文件**——
| | 旧 `_legacy/…/student.py` Student.__init__ | 新 PWA `readRosterXlsx` + 引擎 `files/roster.py` |
|---|---|---|
| 目标文件 | **zjxu 教学系统名册表**（无标准表头） | **姓名/学号/班级 表头的花名册** |
| 取数方式 | 硬位置切片：`df.iloc[8:-3, 列2/列0/列4]`（第 9~倒数第 4 行；name=C 列、number=A 列、class=E 列） | `sheet_to_json` 把**首行当表头**→ HEADER_MAP 匹配 姓名/name/student/学生… |
| 结果 | 旧代码能吃真·点名册 | 真·点名册前 8 行是说明文字、无"姓名"表头 → key_map 全 None → **0 人**（迁移时丢失的形态支持） |

**pandas 回答**：**没有装、也不需要装**。Python 环境 = workspace `.runtime/venv`（uv 管理），依赖清单里
只有 openpyxl/loguru/reportlab/pypdf/Pillow/click/jinja2 等；engine 迁移原则明确"**去 pandas/numpy**"
（report.py/layout.py/watermark.py/grouping.py/rain.py 各文件头注都写着）。旧代码用 pandas 只是历史选择，
openpyxl 完全等价可复刻 iloc 切片语义。**不要**为这个问题引入 pandas（体积/镜像/维护三重代价）。

**修复方案（D46-1a，推荐）**：PWA `readRosterXlsx` 加**回退分支**——
1. 主路径不变（表头自适应，命中即返回）；
2. 若 0 人 → 原始矩阵二次扫描：在前 ~15 行找"姓名/名字/Name"单元格所在行作为表头行，从下行起按该行列位取数
   （比旧代码硬编码 8/-3/2/0/4 稳健，兼容说明行数变化）；
3. 再不行 → 旧式**固定位置回退**（C/A/E 三列 × 第 9 行~倒数第 4 行，姓名列非空过滤），并在预览卡 notes
   标注「按 zjxu 名册位置模式读取（无表头）」让教师可核对；
4. PreviewTableCard 展示实际采用的模式 + 前 3 行，所见即所选。
同步项：`buildRosterPreview` notes 口径一致；引擎 `files/roster.py read_roster` 加同款回退（保持 CLI/PWA 同语义，
D1 超集铁律）；新增自测用例（合成"前 8 行说明+无表头"fixture）。

**其他 family 同类风险排查结论**：
- `exam`（教务期末）：旧代码用 df["姓名"]/df["学号"]/df["期末(必填)"] **具名列**，新版 parseExam 同样按列名定位 → ✅ 无此问题；
- `xuexitong_assignment`（学习通作业统计）：新版按"成绩"行/列关键词定位（parseXuexitongAssignment/Stat）→ 结构假设与旧代码同源，✅ 基本对齐（建议 fixture 实测一次）；
- `rainclass`（雨课堂汇总）：新版 parseRainclass 已实现"无表头、第 2 行列标题、每课两列取均值"特殊结构 → ✅ 有专门处理；
- ⚠️ 唯一系统性缺口 = **roster family 的 zjxu 名册形态**（本 bug）；另注意所有 family 目前只读**第一个 sheet**
  （多 sheet 成绩源 = 既有 backlog B1 尾巴，一并列入待办）。

### D46-2 · 导入名单后"没更新"（同一根因 + UX 加固）
- 直接原因 = D46-1（0 人时 students 不覆盖，仅提示文案，宽表/整班预览自然"没更新"）；
- UX 加固：0 人失败时状态条升级为醒目 notice（附"文件前 3 行原样显示"）；成功时自动滚动到宽表并高亮人数 chip；
- 手动兜底入口（批量粘贴名单）已有，保留。

### D46-3 · 成绩源行内「预览」按钮（VC-6 遗留尾巴）
- 现状：只在**本次导入**后显示 `sourcePreviewLatest` 一张卡；源列表行内只有 重选文件解析/移除，**刷新页面后无法再看某源的解析预览**（且 addScoreSource 未持久化原始 buffer，预览需重新选文件）；
- 方案：每个成绩源行尾加 👁 预览按钮 → 弹 PreviewTableCard（表头+前 3 行+family 定位说明+分数列/权重当前值）；
  数据面：roster store 给每个 source 存轻量 rawMatrix 头部（如前 30 行截断，控制 localStorage 体积）或存整份 ArrayBuffer（IndexedDB），实施时二选一（倾向 IndexedDB 全量，重解析/rescoreWithFamily 也免二次选文件）；
- 名单（students 主表）行不需要（宽表本身就是名单预览）。

### D46-4 · 多成绩源合并总览（全部成绩预览）
- 现状：宽表（VC-5 score-wide-table）其实已存在 = 行学生 × 列(姓名/学号/班级/各源分数/tag/punish)，但入口深、无"合并总览"语义命名，且未勾选列只显示划线值；
- 方案：宽表升级为正式「全部成绩总览」卡：① 每列头显示源名+family+权重+勾选态；② 增加"综合得分列"显式高亮（勾选取舍即时重算预览）；③ 导出 xlsx 按钮（复用 rosterXlsx.writeRosterXlsx，带 tag/punish/score 全列）；④ 与 D46-3 的行内预览互补（总览=横向对比，行内=单源纵向核对）；
- 规模小（现有宽表改造），放 D46-1 之后做。

### D46-5 · 题图占位框（从 D43-7c 剥离，挂 B3 主线）
题图仅存在于部分题目（kb/fig 有 img_path 的行），不是全局元素 → 不做开关；
B3（fig 上传 UI + 引擎写回）落地后，PWA 预览按 wmAssets 同模式显示真图，占位框自然减少；
在那之前占位框保持现状（信息性提示，打印走引擎 CLI 通道 base64 内嵌真图）。

### 拍板结果（2026-09-29 第 10 轮，D46 三条全按推荐）
① **D46-1 两级回退**：表头自适应 → 关键词找表头行（前 ~15 行扫 姓名/名字/Name）→ 失败给醒目诊断；
   固定位置模式**不做**（旧 zjxu 硬切片依赖具体模板行数，脆弱且不可解释；若现场再遇特例按 case 补）；
② **D46-3 raw 留存 = IndexedDB 全量 ArrayBuffer**：每源一份原始文件体，👁 预览/reparse/rescoreWithFamily
   全部免二次选文件；容量粗估 5~10 源 × 数百 KB ≈ 数 MB，可接受；提供「清除原始文件」次级按钮兜底；
③ **D46-4 总览导出含未勾选源列**（灰显标注"未参与综合"），与宽表视觉一致，教师核对不丢信息。

### 实施方案（讨论稿，E1–E4 执行时照此落地）

**E1（D46-1/2 点名册修复）四步**：
1. `rosterXlsx.ts readRosterXlsx`：主路径不动；0 人时二次以 `header:1` 原矩阵扫描前 15 行，
   找到含 HEADER_MAP 姓名列的行 → 该行为表头重跑映射；仍 0 人 → 抛结构化错误
   `{reason:'no-name-column', firstRows:[前3行原文], sheetNames:[...]}`；
2. RosterView importRoster catch：升级红色 notice + PreviewTableCard 原样显示前 3 行 + 一句指引
   （“如为教务名册且前几行为说明文字，请删至仅剩表头行后重试”——两级回退覆盖不到的最后手段）；
3. 成功路径 UX：status 高亮 + 自动滚到宽表（人数 chip flash）；
4. 引擎 `files/roster.py read_roster` 同步两级回退（CLI/PWA 同语义，D1 超集铁律）+
   fixture 自测（合成“前8行说明+无表头”假点名册进 engine/tests）。

**E3（D46-3 源行内预览）**：store 侧 sources[i] 增加 IndexedDB key（idb 封装 30 行内）；
行尾 👁 按钮 → 复用 PreviewTableCard（preview 由 rawMatrix 即时重建 + 当前 family/scoreColumn 口径 notes）。

**E4（D46-4 总览升级）**：宽表卡改名「全部成绩总览」；列头三段元信息；综合分列 sticky 高亮；
导出 xlsx 复用 writeRosterXlsx 扩列（各源分数列+未勾选灰显+tag/punish/综合）。
| 批 | 内容 | 备注 |
|---|---|---|
| E1 | **D46-1(+2)** 点名册两级回退解析（PWA+引擎双侧）+ 失败 UX | 现场可用性 bug，最优先 |
| E2 | **D43-7** 水印双开关（☑水印图层 + ☑页码大字，均默认勾） | 改动小；引擎零新增 |
| E3 | **D46-3** 源行内👁预览（IndexedDB 全量 raw） | 中 |
| E4 | **D46-4** 全部成绩总览升级（导出含未勾选灰显列） | 中 |
| 后续 | 多 sheet 成绩源（B1 尾巴）、D46-5/B3 题图真图预览、其余 family fixture 实测 | 低 |


