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

**遗留**：旧数据源（无 uid）首次👁/⇄提示"重选文件一次即可启用"（预期降级）。

### B3/D46-5 · 题图素材库 + 预览真图（同会话追加完成）
- **settings store `figAssets`**（wmAssets 同模式独立 localStorage 键 `fig.assets.v1`）：basename→dataURL；
- **KbEditorView**：img_path 列行内 📷 上传按钮 → dataURL 入 figAssets（即时生效）+ 空 img_path 自动填 `fig/<文件名>` + **FSA 可用时写回 `<kb目录>/kb/fig/<文件名>`**（引擎 CLI base64 内嵌通道从此有真图）；行内缩略图显示命中状态；未连目录给出"手动放 workspace/kb/fig/"指引；
- **sheetHtml `figAssets` opt**：`figHtml()`——命中 basename → `<img class="q-img" src=dataURL>`（与引擎同视觉、复用既有 CSS）；未命中 → 原占位框（现状保持）；无 img_path → 不渲染；透传链=③预览段/④输出卡/整班预览/自包含下载 全场景；
- **fsAccess `readFileInDir`** 备用读取工具（写回失败重试/未来扫描用）；
- **回归自检 `app/tests/selfcheck-roster-fig.mjs`**（A 多sheet×4 + B 点名册×4 + C 题图×3 = 11 断言 ALL PASS），package.json `selfcheck:roster-fig` 脚本 + CI tests.yml 挂载（硬门禁，不带 || true——它稳定）；
- localStorage 容量注意：题图 dataURL 比水印更耗空间，超限静默降级=预览回到占位框（持久化 try/catch 已有）；后续如需扩容再迁 IndexedDB（B1 同款 idbRaw 可复用）。

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

---

## D47 · 导入链真实文件核测（第 11 轮反馈登记 · 仅讨论未动代码）

**背景**：教师用 `_legacy/2603paperDesign/data/` 的**真实历史文件**现场实测：
点名册照旧读不进名单/总览空白 → 要求用项目已有文档核测根因，不要自造文件。

### 真实文件实测结论（node 直跑真实 xlsx，非合成）

| 源类型 | 真实文件 | 实测结果 | 根因 |
|---|---|---|---|
| **roster 点名册** | `namelists/点名册-化工25-0320.xls` | ❌ **学号被损坏**：读出 69 人但学号=`202343870511**7**`/`202543881510**1**`（Excel 科学计数串改写：真实 12 位号 202543881510 被复用+尾数变化——raw 值即已错） | **.xls（BIFF） SheetJS 读数列精度/类型问题**：12 位数字被 number 解析，xls 单元格 15 位精度+Serial 处理异常（第 9 行起 name/班级 列位移正确，**学号列错**）；而 sheet_to_json 后 name 仍对——补核对原 cell 值后按"字符串列"读取 |
| #### 现象匹配 | 教师端：导入后总览空白/姓名学号列空白或数字对不上 | | |
| **exam 期末** | `data/custom/化工251-成绩统计.xlsx` | ❌ **scores=0**：前 2 行是标题（"化工251成绩统计"/空行），表头在第 3 行 → parseExam 只看 row0 表头，未见"期末"列 | 固定格式解析器都按**陈旧假设**（row0=表头）；真实教务导出都带封面/标题行 |
| **xuexitong 作业统计** | `xxt/teachera-化工25_统计一键导出-0317.xlsx`（sheet=作业统计） | ❌ scores=0："成绩"行在 row3（前 8 行内✓）但 parseXuexitongAssignment 用 **rows[sr][k].includes('成绩')** 而 row3 前几列是""+"成绩"（索引 5 起）→ name 取 r[0]（姓名在 row2 表头 row3/4 是数据）——**姓名列定位错**：数据姓名在 row2 的 c0=学生姓名，但数据行 row4 姓名 c0；密码式两行表头未按列索引对齐 | PWA 解析器把 row3 的"成绩"行当列索引 r[0]？核心 bug = "成绩" 行+标题行组合的 crostab 结构没有按正确列坐标读取；engine `read_xuexitong_assignment` 同样只从 row0 扫姓名 → **PWA/engine 同病** |
| **xuexitong_stat 章节测验** | 同上文件 | ❌ scores=0 | 同结构（row2 标题行+row3 成绩行）→ stat 语义和 assignment 一样要 crostab |
| **rainclass** | `rainclass/大学物理C1-化工25--汇总-数据表-*.xlsx` | ⚠️ **1 人**：B1 pickBestSheet 选了"01-数学前测"课堂 sheet（非汇总 sheet） | rain 结构（无表头+第2行列题）只在第一张汇总表成立；B1 的"数据行数最多"启发式反而选了错误的课堂 per-lesson sheet（数据行 70 vs 汇总 70 平手→取首个错误者） |

**pwa→总览空白根因链**（教师症状"姓名/学号两列空"）：
① roster 读进来但 `read_roster`/HME 后学号内容错+姓名空 → **总览 blank**；或
② **exam/xxt 家族全部 scores=0** → computeScoresFiltered 生成 0 分/空 → 总览♦只有单独勾位；③ roster 源 family=roster 本身**不计分**语义正常（该源列头"—"不可勾=设计使然）。
→ 真正的修复 = **卷首/标题行跳过 + crostab（学习通两行表头）范式统一** + **.xls 数字列以文本读取** + **rainclass 锁定汇总 sheet（名称含"汇总"优先）**。

### D47 设计方案（讨论稿，待拍板——重点问教师：请发点名册 xls 样例）

**E5 · 真实形态适配大修**（引擎+PWA 双侧同修，D1 超集铁律）：
1. **通用"表头行定位器"升级**（E1 的两级回退→三段式）：
   roster/exam/score 全部 = “扫描前 20 行中：含姓名列语义的行 + 姓名列下首个有效率>50% 数据行”→ 动态 hdr_row；
   exam family 表头列名改**子串匹配集合**（`期末|成绩|score` ——教师点名册/期末的实际列都带"成绩"字样变体）；
2. **学习通 crostab 解析器重写**（assignment/stat 同构）：定位"成绩"子行 sr → cols=[各包含'成绩'的列 k] → 数据姓名列 = **标题行(sr-1) 里 c0="学生姓名" 或 数据行首列非空**（引擎 _legacy 的 `rows[sr-1]` 上两行制）→ 每生取 k 列均分（现有逻辑列错位修正）；
3. **.xls 数字串精度防护**：学号/工号列 **force string**（xlsx cellDates:false + raw:false 或对 12 位数字 `Math.floor` 全位显示裁决）——**建立 fixture：真实点名词 .xls 化为自测样本**（ Copy 允许）；
4. **rainclass 锁定"汇总表"**：pickBestSheet 的 family=rainclass 分支优先匹配名称含"汇总/统计"的 sheet，其次才数据行最多；
5. **成绩列勾选（新功能，教师提案）**：
   - exam/custom 等 score 家族：源对象记录**全部数值列 rawMatrix**+默认勾选列（自动猜+教师**全员切换多选**），勾选参与综合（扩展 includeInAggregation→**perColumn**：`includedColumns: string[]`）；
   - 总览列=每源每勾选列一列（列头=源名+列名）；综合分=勾选列加权均值；
   - family=固定四类仍默认猜列，但**总允许教师改**（点列头勾选）。
6. **全文件预览（教师提案2）**：PreviewTableCard 已只显示前 3 行 → 升级为**完整滚动表**（cap 500 行）+ sheet 切换（B1 raw 机制复用）；"预览整个班" = 总览卡加"整班模式"（把 wideRows 转预览卡）。

**待教师提供**：请教师发一份**真实教务点名册**（.xls 或 xlsx 均可，可直接隐私脱敏姓名列）——项目内已有 5 份 zjxu 名册 .xls 样例可对照核验（`_legacy/…/namelists/`），若教师发的与现有样例同构即可直接修复。**不自造数据的精神保留**：本轮核测全部用项目内真实历史文件（汇总见上表）。

**批次建议**：E5（形态适配+成绩列勾选+全文件预览）为下一个大批次，先修 parse 骨架（1-4）→ 成绩列勾选(5) → 全文件预览(6）。

---

## E5 实施记录（2026-09-29 深夜 · 用户拍板「用当前样式的点名册开发=以 legacy zjxu 形态为准」，全项完成）

| 项 | 状态 | 落点 |
|---|---|---|
| 1. 三段式 locateHeader（:title skip→姓名语义行→数据行） | ✅ | readRosterXlsx / readScoreSourceXlsx 通用 |
| 2. exam 列名放宽 | ✅ | `/期末|成绩|得分|总分|score/` 子串；未命中=最末数值列 |
| 3. xxt crostab 重写（assignment/stat 同构）+ 全 sheet 扫描 | ✅ | detectCrostab + buildCrostabSource；xuexitong_* 家族在全部 sheet 里找 crostab 命中者（B1 pickBestSheet 选错表也兜得住） |
| 4. .xls 13 位学号字符串读取 | ✅ | zjxu 名册学号本就是 SST 13 位文本，实测 69 人/学号**原值无损**（此前核测误判为精度损坏——w=t=s 显证）；跨 family 的数字串防护已由 str() 全路径覆盖 |
| 5. rainclass 锁"汇总"表 | ✅ | readRawSheet(family) 分支：名称含 汇总|统计 优先，其余回 pickBestSheet |
| 6. perColumn 成绩列勾选 | ✅ | ScoreSource.allNumericColumns/includedColumns（exam/custom 默认全勾）；RosterView 源行内 checkbox；sourceScoreMatrix 对"教师取消部分列"的源切换按列重建；store.toggleSourceColumn |
| 7. 全文件预览（D47-6） | ✅ | PREVIEW_ROW_LIMIT 500 + PreviewTableCard 420px 滚动（"全文件预览模式"）；总览卡 👁「预览整个班」→ wideRows→PreviewTable 走 PreviewTableCard |
| 8. 真实文件回归 | ✅ | selfcheck:roster-fig 新 D) 块：legacy 真文件（exam 33/xxtA 31/rain 67）全部 PASS；CI skip-safe（文件不在检出时跳过） |

**真实文件终测**（node 直跑）：
- 点名册 .xls：**69 人，学号 13 位原值无损**（此前误判"精度损坏"，实为教师端旧 12 位认知差异=Excel 显示截断；以项目内真文件为准实测这版即原数据）；
- exam：33 人 scores 即时全解析（表头在 row2 跳标题）；includedColumns=7 门课程全勾；
- xxt assignment/stat：crostab 命中「章节测验统计」→ 31 人 × 38 作业均分全轨；includedColumns=38 列作业/测验全勾；
- rainclass：锁定「大学物理C1_化工25_数据汇总」→ 67 人签到得分；
- custom：34 行 × 7 勾选列（姓名列被自动排除出数值列）。

**遗留**：①姓名列放第 3+ 列/异序的多 xxt 分发 sheet（本次 crostab 用"学生姓名"标题行定位已覆盖）；
② legacy `.xls`（BIFF）若用户设备上仍显示尾字符差异（历史读到 2025438815101 vs 浏览器 w="2025438815101"）——本轮核验=原文件 SST 就是 13 位文本，浮点伪造旁路**未实际损坏**——本轮不加额外护栏，现场以教师文件复核为准。

---

## D48 · 导入双入口语义混乱根因确认（第 12 轮教师反馈 · 仅讨论）

### 教师现场症状（重现报告）
1. 导入点名册 → **滚动预览正常**（69 行全见）；**但总览姓名/学号两大列仍空白**；
2. 点名册"文件名列"在总览里**灰色**；
3. 导入期末成绩 → 预览正常；总览**只有该源列可勾**，无其他信息；
4. 「分组比例＋自动切分打 tag」显示**名单为空**。

### 根因（一案三症，非解析层问题）
**教师把点名册走了「成绩源导入」入口（preset=教务点名册 roster）**，而不是专用「导入名单 xlsx…」按钮：

| 证据链 | 说明 |
|---|---|
| 总览点名册列**灰色** | only family='roster' 源会被 `excluded:true`（col-excluded 灰显+"—"不可勾）——总览里多了一列 roster 源 = **它进了 sources[]** |
| 总览姓名/学号两列空白 | **`roster.students=[]`**——总览行由 `roster.students.map()` 驱动；而「成绩源导入」路径的 `addScoreSource` 只 push 进 sources，**从不写 students** |
| 分组比例区显示"名单为空" | 同上——整页唯一的 students 写入点 = `loadRosterFile`（专用按钮那条路），教师没走到 |
| 名册源行内全文件预览正常 | D46-3 的 👁 用 raw 恢复 = 成功展示——但只展示给 sources 侧；对 students 无写回——**新形态的 roster "add-as-source" 把名单只挂在源里** |

**语义根因**：成绩源的格式预设下拉里把「教务点名册（仅接表，不计分）」列为选项之一 → 名义上是
"把名册当源（用于学号/班级对齐）"（D19 语义），与"名单导入按钮"**双入口并存但互不通信**：
- 专用按钮 → 写 `students[]` ✅
- 成绩源入口 → 只写 `sources[]` ❌ 不写 students、不提示"名单还没进"

D19 时代的 roster family 本意 = 让引擎批阅时对齐学号（score_sources[].family），M-C 时代 UI 把
它变成了教师容易误触的第二个名单入口——没有写回 students 的语义，也没有 UI 警示。**E5 修好了解析
/**********************************************underlying使 roster 源内部可读 69 人（教师预览看到 69 行），反而强化了"应该已经导入成功"的错觉。******

### 修复方案（D48，待拍板后实施）
1. **单写路径原则**（推荐拍板）：`addScoreSource(family='roster')` → **同时写回 `students[]`**
   （学号/姓名以 roster 源为准；已存在 students 时按学号 merge，无 students 时全量填充）——
   fromPWA/store 侧一次校准，双入口语义合一；引擎侧不动；
2. **UI 硬分流**：成绩源预设下拉里把 roster 选项**改名+加注**：
   "教务点名册·仅接表（选我=会作为名单导入+列对齐源）"；或干脆**从成绩源下拉里移除
   roster**（名单=专用按钮的唯一入口，分流干净；引擎 score_sources[] 里 roster 类型照旧导出）；
3. 空名单警示强化：总览卡在 `students[].length===0 && sources（非 roster）>0` 时加黄色 notice
   「名单尚未导入——请点上方『导入名单 xlsx…』」（D46-2 红条的同族语义）；
4. 成绩源添加完成后的提示文案若 family==='roster' 则追加一句：
   "⚠ 点名册请使用「导入名单 xlsx…」导入；此处仅供引擎 score_sources 对齐使用。"
5. （教师体验）分组比例区的"尚无学生"提示旁加跳转锚（`#form` style）或内嵌第二导入按钮同款。

### 另一条排查椅（若教师确实点了专用按钮）
E1 success 路径已有 `requestAnimationFrame → scrollIntoView → wideFlash`；若教师**没有看到 flash**
且分组比例区空——则说明 `list.length===0` 分支走进来了（0 人）。此时 preview 照常出 69 行
（preview builder 独立成功——两套引擎同事同 matrix 而 mapStudentsFromMatrix 分叉，理论上同源同错）。
此分支**在教师浏览器上才可见**，无法自证——若附截图确认红条/黄条缺失，则此假设排除。

**待拍板**：方案 2 的两版（改名 vs 移除 roster 选项）——我推荐 **移除**（名单导入专用化，
score_sources 的 roster 语义由系统内部在导出时自动生成，教师不需要手点"把名单当源"）；
1+2+3 一并做，量小（store 一处 + RosterView 两处文案+控件）。

---

## D49 · 班级与标签「班级为中心」重设计（第 13 轮教师提案 · 讨论稿）

### 一、教师症状补充分析：除 pickXlsx accept 过滤外，还有哪些原因？

**症状**：点名册/期末在源行内**单文件预览正常**（D46-3 👁 = IndexedDB raw 即时重建），
但「全部成绩总览」姓名/学号两列空白、分组打 tag 区显示"名单为空"。

**原因清单（按可能性排序；均已代码核位）**：

| # | 原因 | 机制 | 判定依据 |
|---|---|---|---|
| ① | **双入口语义（主因，D48 已登记）** | 教师把点名册走了「成绩源→roster 预设」→ `addScoreSource` 只写 `sources[]` **从不写 `students[]`**；总览行 = `roster.students.map()` 驱动 → 空；分组比例区读同一 students → "名单为空"；点名册列灰色 = family='roster' 被标 excluded（设计使然） | 四个症状 100% 自洽；且"点名册列灰色"只有 roster-as-source 才会出现——**说明点名册确实进了 sources** |
| ② | **pickXlsx accept 只认 `.xlsx`**（教师已点名） | FSA 弹窗 `.xls` 灰显；file-input 兜底 `input.accept='.xlsx'` 同样过滤。教务点名册恰恰是 `.xls`（BIFF）→ **专用「导入名单」按钮大概率也选不到文件**，教师自然改走成绩源入口（回落到①） | fsAccess.ts L162/L147 两处 accept 均无 `vnd.ms-excel/.xls` |
| ③ | **旧 bundle 缓存** | SW runtime cache-first；若浏览器未强刷，跑的还是 E5 前的解析（当时 zjxu .xls 读 0 人） | 症状与 E5 前版本表现一致；但"预览正常"（预览走 E1 两级回退，E1 已上线较久）不能反推运行时版本——需教师强刷一次排除 |
| ④ | `.xls` 学号精度（已排除） | legacy 样例逐字节核验 = SST 13 位文本原值，无损坏 | E5 结论维持 |
| ⑤ | roster 源"仅接表不计分"的**提示性不足**（次因） | roster 源列头"—"不可勾 + 无"此源不提供分数"的显式提示，教师误以为导入失败 | 文案问题，随 D48 一并改 |

**修复集**（并入 D48 一起拍板）：
1. **accept 修正**：`pickXlsx()` → accept 扩为 `.xlsx,.xls,.csv`（FSA types 数组 + input.accept 双处）——.xls/.csv 都是真实输入形态（点名册 .xls、成绩 custom .csv）；
2. D48 单写路径（roster 源导入 → 同步写回 students，按学号 merge）+ UI 硬分流/移除 roster 预设（待拍板二选一）；
3. 空名单黄条（总览/分组比例两处，指向「导入名单 xlsx…」）；
4. 强刷提示：设置中心自检卡或页脚加"当前版本 hash"徽标，便于教师核对是否在跑最新 bundle。

### 二、「班级为中心」重设计（教师提案 → 结构化）

**提案要点**：班级与标签页从"散装卡片"重组为**以班级为单元的工作区 + 班级清单**，与作业纸设计页（D45）同构。

**四段结构（教师原文的结构化）**：
```
班级配置栏（新建 / 保存 / 导入 / 载入历史班级 —— 当前班级的"名字"）
├─ ① 名单模块：教务点名册 / 简单姓名列表 / 自定义文件 / 手动增员（含 📷式 预览/⇄sheet/移除/重载 按钮族）
├─ ② 成绩加权管理：各类成绩文件导入 + custom + 总览加权（perColumn 勾选、综合分预览）
├─ ③ 标签模块：分组比例 / translation 面板 / 特殊标签 / 按综合得分切分 + 标签预览
└─ ④ 整班作业纸预览及产出：预览全部作业纸 / 产出带成绩和标签的名单 / 下载作业纸
班级清单栏（汇总已添加班级：各导入文件名、人数、作业纸页数/类型数…+ [载入][删除]）
```

**与现状的差距（迁移映射）**：
| 现状 | 目标 |
|---|---|
| 单班级工作区（localStorage 单份 roster store，无"班级"概念） | **多班级 store**：`classes: Record<classId, RosterWorkspace>` + `activeClassId`；载入=切 activeClassId |
| roster.students/sources/ratios 无命名空间 | 每班级一份独立 workspace（含 sources uid→IndexedDB raw 天然按源隔离，不冲突） |
| 「保存」无显式按钮（touch() 自动持久化） | 显式「保存班级」+ 自动持久化并存；班级元数据（名称/学期/创建时间/人数/源清单/关联作业纸）入班级清单 |
| 产出（tagged.xlsx/总览导出）散在卡片里 | 集中到 ④ 产出段；产出文件登记进班级元数据（中间产物管理见下） |

**班级清单栏建议补充的字段**（教师问"还可以补充哪些"）：
- 班级人数 / 已打 tag 人数分布（distinguish×n、copy×n…）/ 未打 tag 人数；
- 成绩源清单（源名×family×行数）与**缺源警示**（如 roster 已导但 exam 未导）；
- 关联作业纸清单数（pad.saved 中绑定到本班 tag 的份数）；
- 最近产出物（tagged-roster.xlsx / 成绩总览.xlsx / batch zip 的文件名+时间戳）——**中间产物登记**；
- 状态徽标：仅名单 / 已打 tag / 已产出（三态）；最后编辑时间。

### 三、PWA 网页对文件夹的操作配套（教师提醒的"产出及中间产物文件管理"）

现状盘点：
- **FSA 已连接 workspace 时**：kb 写回（原地）、roster tagged.xlsx 写回 classes/<cd>/roster/、batch zip 下载（手动解压）——写路径是"点到点"的，**没有产出清单/管理面**；
- **未连接（纯 Pages/LAN）**：全部走浏览器下载文件夹，产物散落。

**D49 配套设计（文件管理三件套）**：
1. **产出登记簿**：每次「产出」（写回 FSA / 浏览器下载）都登记到班级元数据 `artifacts[]`（文件名、类型、目标路径/下载、时间戳、字节数）——班级清单栏可见"这个班产出过什么、何时"；
2. **FSA 目录树约定**（docs/04 已有 classes/<cd>/roster|sheets|grading；补）：
   `classes/<cd>/overview/成绩总览-<日期>.xlsx`（D46-4 导出落点，FSA 连接时直写）；
3. **"打开 workspace 输出目录"按钮**：FSA 可用时一键 `showDirectoryHandle` 定位 classes/<cd>/（Chrome 支持 revealDirectoryHandle 的场景直接高亮）——降低"产物在哪"的查找成本；
4. 未连接时的降级：产出登记簿仍记录（浏览器下载路径语义），并提示"连接 workspace 后可自动归档到 classes/<班级>/"。

**实施分批建议**（D49）：
| 批 | 内容 | 规模 |
|---|---|---|
| F1 | D48+原因①②：accept 扩展 + 单写路径 + 分流/移除 roster 预设 + 空名单警示 | 小-中 |
| F2 | 多班级 store + 班级配置栏 + 班级清单栏（载入/删除） | 中（一次会话） |
| F3 | 产出登记簿 + FSA 归档路径 + 目录定位按钮 | 中 |
| F4 | ④产出段整合（预览全部作业纸/产出名单/下载作业纸集中化） | 中 |

**待拍板**：① roster 预设"改名"还是"移除"（推荐移除）；② 多班级 store 的持久化键升级（`roster.v1` → `roster-classes.v2`，需一次性迁移老数据到"默认班级"）；③ 班级清单栏字段取舍（上面 6 项是否全要）；④ 产出登记簿是否也记"源导入"动作（推荐只记产出，导入史由 sources.uid+时间戳自然承载）。

---

## F1–F4 实施记录（2026-09-30 · D49 四拍板全按推荐，全部完成）

| 批 | 内容 | 状态 | 落点 |
|---|---|---|---|
| F1 | accept 扩 `.xlsx,.xls,.csv`（FSA types 三 MIME + input 串）| ✅ | fsAccess.ts 两处；RosterView pickXlsx |
| F1 | roster 预设**移除**（成绩源下拉 filter）；**单写路径**：addScoreSource(family='roster') 同步写回 students（按学号 merge 补齐） | ✅ | RosterView + store |
| F1 | 空名单黄条（总览卡：⚠ 名单尚未导入…指向专用按钮） | ✅ | RosterView 总览卡 |
| F2 | **多班级 store**：`classes: Record<cid, RosterClass>` + classOrder + activeClassId；v2 键 `roster-classes.v2`；**v1→v2 一次性迁移**（老数据自动入"默认班级"）；state 代理字段（students/sources/ratios）保持旧视图代码零改动 | ✅ | roster.ts loadClasses/persist 重写 |
| F2 | 班级配置栏（改名/学期/新建/保存 + 人数·源·产出计数）+ **班级清单栏**（表格：名称/学期/人数/tag 分布/源数/三态徽标/最近产出/更新时间 + 载入/删除；删除清 IndexedDB raw） | ✅ | RosterView 顶部/底部两卡 |
| F3 | **产出登记簿** `registerArtifact`（cap 30 条）：roster.xlsx（下载/FSA 写回两路）、roster.json、roster-task-package.zip、成绩总览 xlsx、batch zip（SheetContentView 产出点）全部登记；班级清单栏显示最近产出 | ✅ | store + 两视图 |
| F4 | 产出卡文案收口（集中入口说明 + FSA 归档路径说明 + batch 包产出点指引） | ✅ | RosterView 产出卡 |

**红线**：taskpad schema 不动；引擎零改动；视图层旧字段（students/sources/ratios）读写代理保持兼容（E1–E4/B1/B3 全部功能不受影响）。
**验证**：vue-tsc+vite 0 err（index-BwrlFyW8.js 287KB）；selfcheck-roster-fig 14 断言 PASS。
**待现场验收**：多班级载入/删除/新建、点名册从两入口导入都写名单、.xls 可选中、总览空名单黄条、产出登记显示。