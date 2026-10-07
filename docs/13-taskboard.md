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

---

## D50 · 「名单模块」未独立成卡的 F2 实施缺口（第 14 轮教师反馈 · 仅讨论）

### 现象
教师在 PWA 上**找不到「导入名单」按钮**；唯一一个「导入名单 xlsx…」出现在**「特殊标签」卡里**（L750），
教师判断"这应该不是我要的"——并建议若留在特殊标签里应改名为**「导入特殊标签名单」**（更具体）。

### 代码核查（事实）
1. **全页唯一名单导入按钮**在特殊标签卡内，`@click="importRoster"`——功能上它就是**正牌名单导入**
   （readRosterXlsx → store.students，D46-1/E1 两级回退全在）；**不是**特殊标签专属功能。
2. 历史成因：M5 时代"名单管理"与"特殊标签覆盖"同卡开发，F2 重构时只新增了「班级配置栏」和
   「班级清单栏」，**D49 四段结构中的「① 名单模块」没有从特殊标签卡里拆出来**——名单导入/手动增删/
   学生表（姓名/学号/班级/tag/punish 行内编辑）全部还留在特殊标签卡里。这是 **F2 的实施缺口**，
   不是教师看错。
3. 连带问题：该按钮调用的 importRoster 语义 = "建名单 + tag 列原样带入（manualTag=true 即覆盖）"——
   在特殊标签语境下确实兼有"导入带 tag 名单覆盖标签"的作用，**一词两义**正是命名困惑的根源。

### 修法（讨论稿，按 D49 四段结构收口）
| 段 | 动作 |
|---|---|
| ① 名单模块（新卡，紧跟班级配置栏之后、成绩源之前） | 收编：📥 导入名单 xlsx…（建名单语义）/ ＋手动添加学生 / 清空全部 / 学生表（姓名/学号/班级 行内编辑） |
| ③ 标签模块（特殊标签卡瘦身） | 保留：批量打 tag（按姓名）、**punish 勾选**、学生表 **tag 列**（special_tag 覆盖语义）；按钮改名 **「导入带 tag 名单（覆盖特殊标签）」**——同一 importRoster 但文案明确"这是在覆盖标签"（教师建议"导入特殊标签名单"的落实，二选一措辞） |
| 结构 | 页面卡序调整为：班级配置 → ①名单 → ②成绩源+总览 → ③分组比例+特殊标签+translation → ④产出 → 整班预览 → 班级清单 |
| 附带 | 「成绩源解析状态预览」悬浮卡（现挂在班级配置与成绩源之间）归位进②成绩源卡；特殊标签卡里学生表拆分后，名单模块与标签模块**共享同一张学生表**（tag 列在标签语境、基本列在名单语境）——避免两份表重复渲染的实现说明：一张表、两段标题锚点，或按 D49 拆两张聚焦表（推荐后者：名单表=姓名/学号/班级编辑；标签表=tag/punish 批量覆盖，各司其职） |

**待拍板**：① 学生表拆两张（推荐）还是共享一张；② 特殊标签卡里的导入按钮**改名保留**（教师建议）还是
**移除**（单入口原则，特殊标签不再接受导入——覆盖名单一律从①名单模块导）——推荐改名保留
（"带 tag 名单覆盖"是真实使用场景：教师从别处做好 tag 表直接覆盖）；③ 卡序重排是否本批一起做（推荐是，
纯 template 移动）。

---

## D51 · 标签段动线定稿 + 三类预览拆分（第 15 轮教师拍板 · 讨论稿）

### 拍板结论（对 D50 三待拍板的答复 + 新增动线要求）
1. **三类预览拆开**（D50-1 改为拍板项落实）：**名单预览 / 成绩预览 / 标签预览** 各自独立卡片，
   分别挂在对应模块段内：名单模块→名单预览卡；成绩源模块→成绩预览卡（D47 全文件模式 500 行滚动 + ⇄sheet）；
   标签模块→**标签预览卡**（新组件：tag 分布统计 + 每生 tag/punish 一览表，随比例/手动覆盖即时刷新）。
2. **特殊标签卡**：导入带 tag 名单按钮**移除**（D50-2 → 拍板=移除，单入口原则落在 D48 单写路径上）；
   卡名「特殊标签（手动覆盖…）」→ 改为「**标签预览**」（贴合其最终职责）；
   **批量打 tag 按钮行保留**（按拍板保留——覆盖是人工调整的正道）。
3. **translation 分发面板前移**：卡序改为 **分组比例卡（含打 tag 按钮）→ translation 面板 → 标签预览**。
   动线拍板语义："先定 比例（其他 tag 和为 100）→ 再定 translation 随机比例 → 打标签 → 标签预览跟随；
   调比例 → 重打 → 预览自动变化"。
   实施细节：translation 比例输入框**上移**到分组比例卡内部（与其余比例并排/紧随，ratioSum 口径展示
   "其他 tag 合计 / translation 独立"两行），或独立卡紧贴分组比例卡（二选一，实施时以"视觉上是一个
   '比例'动作"为准，倾向并入同一卡的两行）；「重算综合得分并自动切分打 tag」按钮保持（已有），
   卡内提示改写为"调整任何比例 → 点此重打 → 下方标签预览即时变化"。
4. **标签预览卡内容（新）**：tag 分布（label×人数，含 translation/punish 单列）+ 未打 tag 人数 +
   每生一览（姓名/tag/punish，只读，排序=名单序）+ 与宽表综合分列的联动提示；无数据时显示引导文案。

### 修订后的 D50/D49 页面卡序（最终目标序）
```
班级配置栏
① 名单模块（导入名单/手动增删 + 学生基本表 + 名单预览卡）
② 成绩源 + 全部成绩总览（含成绩预览卡[全文件 500 行] + 整班成绩预览）
③ 标签：分组比例卡（比例+translation 比例并入 + 打 tag 按钮）→ 标签预览卡（标签分布+每生一览）
   （原"特殊标签"卡职责收编：手动覆盖/punish/批量打 tag 保留在新标签卡内；csv/带 tag 覆盖导入移除，
     覆盖=在标签预览里逐人下拉改）
④ 产出卡 → 整班作业纸预览 → 班级清单栏
```

### 实施清单（D50+D15 拍板合并 = D50b，一次会话量）
- [ ] 名单模块新卡（从特殊标签卡拆出：导入/手动增删/学生基本表 + 名单预览卡归位）
- [ ] 特殊标签卡 →「标签预览卡」改名；移除导入按钮；保留批量打 tag 行 + 逐人 tag/punish 编辑（移入）
- [ ] translation 面板并入/前移（比例语义两行制：其他合计 + translation 独立）
- [ ] 新增标签预览卡（分布统计 + 每生只读表）
- [ ] 卡序重排为上序；成绩源预览卡归位成绩源卡
- **待确认**：translation 比例"并入分组比例卡内两行制" vs "独立卡紧贴"（我有倾向前者——一次看到两组比例）；
  标签预览是否也显示"按综合得分的档位边界"（即每档分数区间）——信息量大，推荐第一版先不做。

---

## D50b 实施记录（2026-09-30 · 班级与标签"四段+三预览"重排完成）

| 拍板项 | 状态 | 落点 |
|---|---|---|
| ① 名单模块独立成卡（导入 xlsx/xls/csv + 手动增删 + 学生基本表[姓名/学号/班级] + **名单预览**归位） | ✅ | RosterView `#roster-module`（从特殊标签卡拆出；按钮更名带 📥 前缀更醒目） |
| ② 成绩源卡吸收"解析状态预览"悬浮卡（**成绩预览**=全文件模式 500 行滚动 + 行内👁/⇄sheet 保留） | ✅ | `#score-module` 内 PreviewTableCard 归位 |
| ③ translation 比例**并入分组比例卡两行制**（其他档合计 + translation 独立%提示行）；「⚙ 重算并自动切分打 tag」按钮文案强化"调比例后必点" | ✅ | `#ratio-module` |
| ③ 特殊标签卡 → **「标签预览」卡**：移除导入带 tag 名单按钮；新增 tag 分布统计行（label×人数+未打数）；批量打 tag 行保留；每生 tag/punish 只读→下拉覆盖表 | ✅ | `#tag-preview` |
| translation 面板瘦身=仅手动点名 manual 覆盖（比例输入已上移，卡内注明回比例卡统一生效） | ✅ | — |
| 卡序定稿：班级配置→①名单→②成绩源+总览→③比例→标签预览→translation 手动→④产出→整班预览→班级清单 | ✅ | template 重排 |
| sticky 段内锚点导航（D45 同风格 design-anchors） | ✅ | 顶部跳转条 |

**验证**：vue-tsc+vite 0 err；store 冒烟 PASS（recompute/tagCounts/createClass 切换清空/switchClass 回载 students 完整/registerArtifact/classList 三态徽标）。
**红线**：schema/引擎零改动；数据面完全复用（tagCounts getter/students/persist），无新依赖。

---

## D52 · 第 16 轮三问题核查（仅讨论登记）

### ① 班级与标签出现两个 translation —— 确认：D50b 半截工程残留
- 「分组比例卡」内第二行已并入 translation 随机拨给比例输入（L774-779）；
- 但原「translation 拨给」卡的 **h2 标题与首段 hint 仍是旧文案**（"按比例随机点名…（可调）"），
  虽第二行 hint 已注明"比例输入已并入上方"，视觉上仍像有两个比例入口 → **教师看到两个 translation**。
- **修法（待实施）**：该卡整体降格为「标签预览」卡内的附属小节或改名「translation 手动点名（manual 覆盖）」，
  删除 h2 里的"随机比例"字样与重复描述段——只保留手动点名行。一处比例、一处点名、一卡预览。

### ② KaTeX 渲染现状链路确认（回答"要不要下载/代码在哪/如何到本地工作目录"）
| 环节 | 现状 |
|---|---|
| 渲染方式 | `lib/sheetHtml.ts` 三模式：**relative**（预览/打印 iframe→同源 `./katex/`）、**cdn**（引擎 CLI/j2 输出）、**raw**（下载 HTML=css+js+woff2 base64 全内联自包含） |
| 资源本体 | **不在远程仓库**（D44 拍板：`app/public/katex/` 已 gitignore）；归属=npm 依赖 `katex@0.16.4`（package.json+lock），CI `npm ci` → prebuild `tools/copy-katex.mjs` 拷选择集（css/js/auto-render/woff2×20≈608KB）进 dist |
| 用户是否需下载 | **PWA 网页本身零动作**：Pages/引擎 serve 打开时资源随页面同源分发（含 SW 缓存后离线可用）；「下载 HTML」按钮产出的文件已自包含内联，双击即开即渲染 |
| 唯一需要"到本地工作目录"的场景 | 教师用**引擎 CLI** 生成的 HTML（j2 模板走 CDN）。若断网想让它也离线渲染：把 PWA dist 的 katex 子集放进 workspace（如 `<workspace>/sheets/katex/`），HTML 相对路径即可命中——**当前无一键安装入口**（B 方案曾否决因 LAN 二屏 SW 不可用）。可选小补丁（待拍板）：设置中心加「导出 katex 文件夹到 workspace」按钮（FSA 写回 `sheets/katex/**`，~608KB，一次点击，无需用户管环境） |
| 自检 | 设置中心已有「KaTeX 公式资源」自检卡（fetch ./katex/ 验证 200） |

### ③ 竖版 per_page=2/3/4 布局问题 —— 根因定位（两处叠加）
- **数据层没错**：`gridKey()` 竖版 2/3 已是 rows2/rows3（纵向一列均分），**唯独 per_page=4 不分方向都返回 'cross'**（十字 2×2）——这就是"现在的 3/4 都是十字花排布"的直接原因之一（3 其实不该是十字；见下 max-width 效应）；
- **CSS 层主犯**：D41 overflow 修复引入 `.sheet-body.divided .sheet-frame { max-width: 50% }`——本意防横版栏内容跨虚线，但 divided 类对**竖版同样生效** → 竖版 rows2/rows3 的题帧被压成半宽（题干只占一半行宽！）且靠左堆叠，观感直接错乱；
- **修法（待实施，双端同步）**：
  1. CSS：max-width 约束改为**按 grid 类型区分**——`.sheet-body[data-grid^="cols"] .sheet-frame, [data-grid=cross] .sheet-frame { max-width:50% }`（横向分栏才限宽），rows* 不限宽（改 word-break 保留防溢出即可）；`printCss()` 与 j2 `<style>` 两处逐字同步（parity 哨兵护航）；
  2. gridKey：竖版 per_page=4 → `'rows4'`（新增一档：四行均分+三条横线分隔），横版保持 cross?——**待拍板**：(a) 竖版 4=纵向四行、横版 4=十字（推荐，符合"书写区满行"直觉）；(b) 两端都纵向；
  3. gridLines 相应扩 rows4=['h31','h32','h4']（三横虚线）；engine `_grid_key/_grid_lines` 同口径跟改（CLI/PWA 一致）；
  4. selfcheck/engine test 补竖版 2/3/4 断言（frame 宽度不受 50% 限制、rows4 存在）。

---

## D53 · 第 17 轮三拍板落档（仅讨论）

### ① translation 卡去留 —— **你的判断成立，但有一处不等价**
代码事实：`applyManualTranslation()`（手动点名打 translation）与 `applyBatchTag()`（批量打 tag，tag 下拉含
translation）**逐行同构**（split 姓名→findIndex→缺失可新增→赋 tag→touch），唯一差异是 batchTag 下拉可选任意 tag、
translation 版写死 translation——**功能完全被标签预览卡的批量打 tag 覆盖 → 该卡整体删除成立**。
⚠️ 不等价的只剩一项：**"随机拨给比例"**——它不在旧卡里而在 applyAutoTagging（recompute 的随机散布），
且输入框已并入分组比例卡第二行（D50b）。所以删卡不丢任何能力。
**定稿动作**：删除「translation 拨给」整卡 + 其 script（manualTranslationNames/manualCreateIfAbsent/
applyManualTranslation/setTranslationRatio 中 setTranslationRatio 保留——比例输入还在比例卡用）；
页面顶部说明与锚点条同步去掉 translation 段；translation 在系统里的存在形态收敛为三个：
比例卡第二行的"随机拨给%"（自动）、批量打 tag 选 translation（手动点名）、学生表 tag 下拉（逐人）。

### ② per_page 布局语义定稿（用户拍板）
- **竖版 2/3/4 全部纵向一列均分**：rows2（一中横虚线）/ rows3（两横）/ **rows4 新档（三横虚线四等分）**；
  题干满行宽（废除 divided 对 rows* 的 max-width:50% 误伤，改按 `data-grid^="cols"`/cross 限定）；
- **横版维持现状**：2/3=左右栏 cols2/cols3，4=十字 cross 2×2；
- 双端同步：printCss()+j2 <style>（parity 哨兵）+ engine `_grid_key/_grid_lines`（rows4/h4 线）+
  SheetLayoutView? （CSS 近似预览已在 D43-3 删除，无需动）+ selfcheck/engine test 断言补竖版 2/3/4。

### ③ KaTeX 离线方案定稿（用户拍板：下载到 workspace，仓库零容量占用）
**设计 = 设置中心「KaTeX 离线包」卡一键安装到 workspace**：
1. 资源来源=**同源 dist fetch**（./katex/… 随 PWA 构建产物分发，npm 依赖供给，仓库不存资产——与 D44 一致）；
   复用现成 `fetchSelfContainedKatex()` 的资源枚举逻辑（css→woff2 名单解析）；
2. 落点=`<workspace>/sheets/katex/**`（FSA `writeFileInDir` 递归建目录；连接句柄=getKbDirHandle 同款机制）；
   体积 ~608KB 一次写入；重复点击=覆盖更新（幂等）；
3. 引擎侧衔接（零 j2 改动即可用的过渡 + 小补丁终态）：
   - 过渡：教师把 CLI 生成的 HTML 放 `<workspace>/sheets/` 下打开时，CDN 引用不变仍可联网渲染；离线场景走 PWA「下载 HTML（自包含）」通道（已内联）；
   - 终态小补丁（建议同批做）：`assist sheet html` 增 `--katex local|cdn`（缺省 cdn 不动现状），local 时模板输出
     `../katex/...` 相对引用——配合本安装的 sheets/katex/ 目录即全离线；CLI 超集铁律不破（PWA 先行）；
4. UI：设置中心卡片显示状态（未安装/已安装@路径/版本 0.16.4），按钮「📦 安装 KaTeX 到 workspace」
   （无 FSA 上下文降级=打包 katex-folder.zip 浏览器下载+指引解压位置）；
5. 校验按钮沿用现有自检（同源资源可达性）+ 新增"workspace 内已装"探测（FSA getFileHandle sheets/katex/katex.min.js）。

**实施批次**：G1=①删 translation 残卡；G2=②竖版布局双端+测试；G3=③KaTeX workspace 安装（PWA 侧）+ 引擎 --katex local 小补丁。三项互不纠缠，可一批过。

---

## G1–G3 实施记录（2026-09-30 · D53 三批全完成）

| 批 | 内容 | 状态 | 落点与验证 |
|---|---|---|---|
| G1 | translation 残卡删除（与批量打 tag 同构核实后整卡移除；随机比例能力保留在分组比例卡第二行+applyAutoTagging） | ✅ | RosterView：卡+script(manualTranslation*/applyManualTranslation)删净；锚点/顶部说明同步；build 0 err |
| G2 | 竖版 per_page=2/3/4 纵向一列均分：rows2/rows3/**rows4 新档**（三横虚线 h/h31/h32/h4）；max-width:50% 误伤修复（限 cols*/cross）；横版维持 cols/cross | ✅ | 三端同步：sheetHtml gridKey/gridLines/printCss ↔ j2 &lt;style&gt;/&lt;h4&gt;/divided 规则 ↔ engine _grid_key/_grid_lines；冒烟 rows2/3/4+横线数+横版 cross 7/7 PASS；engine test ①b/②更新+parity 哨兵补 .sf-line.h4/[data-grid^="rows"] |
| G3 | KaTeX workspace 离线包：设置中心「📦 安装到 workspace」→ FSA 递归写 `<workspace>/sheets/katex/**`（同源 dist 资源，仓库零占用不变；重复点击幂等更新）；无 FSA 降级 katex-offline.zip 下载+解压指引；引擎 `assist sheet html --katex local\|cdn`（local=../katex/ 相对引用，缺省 cdn 不动现状） | ✅ | sheetHtml.collectKatexFiles()（css→woff2 名单枚举）；SettingsView 卡+按钮+状态；cli/htmlfile/j2 三分支；engine test ②c 断言（local 含 ../katex/、无 jsdelivr）；build+selfcheck 全绿 |

**红线遵守**：taskpad schema 不动；KaTeX 资产仍不进仓库（npm 依赖构建期注入不变）。

---

## D54 · 第 18 轮五问核查（KaTeX 安装直装 / 三处预览重复 / 列勾选失效 / 综合分与权重口径 —— 仅讨论）

### 1️⃣ KaTeX 离线包：能否"直接装到文件夹"、不让用户解压？
**现状代码**（SettingsView.installKatexToWorkspace）：优先用 `getKbDirHandleSafe()`（=**只在用户已连接 workspace 目录时才存在**的句柄）
→ 有句柄=直接 FSA 写入 `sheets/katex/**`（这一步本就是"直接安装"，无需解压）；**无句柄 → 降级 zip 下载**（这才是教师看到"要解压"的来源）。
**直装方案（推荐）**：
- 卡片按钮改为**两态**：① 已连接 workspace →「📦 安装到 workspace（一键，直接写盘）」；② 未连接 →「📂 选择 workspace 目录并安装」
  （点击后 `pickDirectory()` 弹一次目录选择 → 拿到句柄 → 直接递归写入，**零解压**）；
- 只有浏览器**不支持 FSA**（Firefox/Safari）或 **LAN http://IP 非安全上下文** 时保留 zip 兜底（此时协议层不可能直接写盘）；
- 追加引擎通道（覆盖 LAN 场景，可选）：引擎已有 `/install/{item}`+SSE 框架（R1.3/R1.4），可加 item=`katex`
  由引擎服务端写入 `<workspace>/sheets/katex/`（引擎在线时页面按钮直接调，同样零解压）——待拍板是否本批做。

### 2️⃣ 三处"预览重复"审查（结论：两处真重复、一处半重复）
| 组合 | 判定 | 建议 |
|---|---|---|
| 名单模块：学生可编辑表 vs 名单预览（原文件 500 行滚动） | **半重复**：可编辑表=解析后的名单；预览=原文件全貌（含未映射列，核对解析正确性用） | 保留两者但省空间：① 可编辑表**固定高度+滚动**（max-height ~320px，鼠标滚轮，用户建议采纳）；② 名单预览收进 `<details>`（默认折叠）或行内"查看原文件"按钮弹卡 |
| 成绩源解析状态预览（最近导入卡） vs 成绩源行内 👁 预览 | **真重复**（同一 PreviewTableCard、同一数据） | **删除"最近导入"悬浮卡**，只保留每源行内 👁（D46-3 已能回看任意源） |
| 整班成绩预览（👁预览整个班 卡） vs 全部成绩总览（宽表） | **真重复**（同一 wideRows 数据的另一种渲染） | 删除「预览整个班」按钮与卡；宽表本身已滚动；若要大屏视图，改为「导出总览 xlsx」或宽表卡加"放大弹窗"（可选） |

### 2.1️⃣ 成绩源列勾选失效 —— 根因（4 条，全部代码级确认）
| # | 根因 | 证据 |
|---|---|---|
| ① **总览列模型是"每源一列"** | `wideHeaders = scoreSources.map(...)` 每源仅一列（label=源名），单元格取 `sourceScoreMatrix(s)[stu.name]`（单值）→ 勾多列也无处显示 | RosterView L225 |
| ② **sourceScoreMatrix 不消费 includedColumns** | 函数只在"勾选数<总列数"时**绕开 scores**，然后回落用 `scoreColumn` 单列重建（等于把主列再算一遍）——多选勾选从未参与取值 | roster.ts L155-168 |
| ③ **固定 family 未生成 allNumericColumns** | 仅 exam/custom 分支写入 allNumericColumns；xuexitong/rainclass 无勾选框（教师看到"到底勾不勾"的困惑） | rosterXlsx.ts `readScoreSourceXlsx` |
| ④ **数值列枚举未排除元数据列** | `dataNumericColumns` 只排除了姓名列；**序号/学号/班级（数字型）** 会混进勾选框——这正是"序号班级学号的勾选意味着什么"的来源：**它们不该出现，也无任何语义**（勾了只会污染 includedColumns） | rosterXlsx.ts L199+ |
**教师诉求确认**：一个成绩源勾选多列（如 语文+数学+外语）→ 总览出现多列、都参与加权。这需要**数据模型升级**（见 2.2 待拍板 A）。

### 2.2️⃣ 综合得分公式与权重口径 —— 现状与不符预期的根因
**当前实现**（computeScoresFiltered + srcScoreOf）：
```
综合分 = 100 × Σ_i [ (raw_i / max_i) × (w_i / Σw) ]      i=成绩源；max_i=该源全班最大值
```
- **单源时 → 综合分 = 100 × raw / max**，所以勾一列期末（85 分、班内最高 92）→ 综合分≈92.4，**与原始分不等**——这就是教师看到的"综合得分与这列成绩不能对应"；
- **权重**（每源一个 weight）：仅在**多源之间**起作用（相对占比），单源时改权重不改变结果；且权重是"源"级而非"列"级；
- **归一化**是源内按最大值线性缩放（0~max → 0~100），不同源不同量纲靠它对齐——设计初衷如此，但教师要的是"单列=原始分"的直觉。
**建议（待拍板）**：
- **A. 多列模型**：ScoreSource 增 `scoresByColumn: Record<列名, Record<学生, 数>>`（raw 已在 rows，可直接派生）；总览列=Σ(源×勾选列)；
  综合分= 每列归一后按**列权重**（或源权重均分到列）加权；
- **B. 单列直用**：当勾选集合只有一列时，综合分=原始分（跳过归一）——满足直觉；多列/多源时保留归一（并显示"已按班内最高分归一"提示）；
- **C. 公式上屏**：总览卡标题下常显公式文本（当前值：`综合 = 100×Σ(源内归一×权重占比)`），并注明归一规则与"切分口径一致"；
- **D. 列权重 UI**：勾选框旁可编辑每列权重（默认源权重均分），或先保持"源权重"、仅支持多列等权（更简，待拍板）。

### 待拍板清单（D54）
1. KaTeX：直装两态按钮（选目录+写入）+ 是否同批做引擎 `/install/katex` 服务端通道；
2. 预览收敛三件套（可编辑表滚动/原文件预览折叠/删最近导入卡/删预览整个班）是否全做；
3. 多列模型（A）+ 单列直用（B）+ 公式上屏（C）是否本批；列权重 UI（D）先等权还是可编辑；
4. 数值列黑名单（序号/学号/工号/班级/班号…）+ 固定四类也生成 allNumericColumns（勾选对所有 family 生效）。

---

## D55 · 第 19 轮：workspace 句柄根因 + 多列口径拍板 + 引擎一致性发现（仅讨论）

### 1️⃣ "已设置好 workspace 却显示未连接" —— 代码级根因（3 条）
| # | 根因 | 证据 |
|---|---|---|
| ① **设置中心选目录后把句柄丢了** | `SettingsView.chooseWorkspace()` 拿到 `FileSystemDirectoryHandle` 后只调用 `settings.setWorkspace(dir.name, true)`（存的是**名字字符串**），**从未 `setKbDirHandle(dir)`** → `getKbDirHandle()` 为空 → KaTeX 卡判定"未连接" | SettingsView L46-57 / kb.ts L215-221 |
| ② **句柄只存在内存，刷新即失** | 唯一设置句柄的地方是「题库编辑器/导入导出」的「连接本地 workspace 目录」，且 `setKbDirHandle` 写模块级变量，**无 IndexedDB 持久化、无 requestPermission 恢复** → 重开页面必"未连接" | kb.ts L120/216 |
| ③ **"设置好 workspace"的两种语义被混淆** | 教师理解的"设置好"=设置中心填了路径/start.bat 的目录；程序需要的"连接"=浏览器 FSA 句柄。两者互不相通（前者只是显示用字符串） | — |
**结论：直装两态 + 引擎安装能解决，但必须先修①（否则两态的第一态永远进不去）+ 建议②（句柄入 IndexedDB，load 时 queryPermission/requestPermission 恢复）；引擎 `/install/katex` 则覆盖句柄不可得的场景（Pages 跨源、LAN http、Firefox/Safari）——服务端直接写 `<workspace>/sheets/katex/`，零解压零句柄。**

### 2️⃣ 预览收敛 —— 拍板确认（待实施）
名单可编辑表固定高滚动 / 名单原文件预览折叠 / 删"成绩源最近导入"悬浮卡（只留行内👁）/ 删"预览整个班"。

### 3️⃣ 多列模型 + 综合分口径 —— 拍板方向 + 一个必须先解决的一致性问题
**用户拍板**：多列模型；**去掉"除以本班最高分"**；不再用"源权重/权重总和"。
**⚠ 核查发现（重要）**：**PWA 与引擎口径本来就分叉**——
- 引擎 `roster/grouping.py merge_scores`：`mean = Σ(w×原始分)/Σw`（**原始分加权平均**，无班内最大值归一）；
- PWA `roster.ts computeScoresFiltered`：`Σ((原始分/源内最高分)×w/Σw)×100`（**有归一化**）。
→ 同一份成绩在 PWA 切分 tag 与 CLI `assist roster tag` 会得到**不同排序/不同 tag**（D1 parity 破裂），且正是教师看到"综合分≠单列原始分"的原因。
**建议统一到引擎口径（也最贴合玩家直觉）**：
```
综合得分 = 勾选(列)的原始分加权平均 = Σ(原始分 × 权重) / Σ权重     （单列/等权时 = 原始分算术平均）
```
- 单列 → 综合分 = 原始分（满足"对应相等"）；多列/多源 → 权重真正生效（等权即算术平均）；
- 关于用户提"不必乘以权重/权重总和"：若彻底不除 Σw，则公式退化为 Σ(原始分×权重)（是"求和"而非"平均"），分数会随权重和膨胀且无法跨班比较——**不推荐**；推荐"加权平均"（权重默认 1=等权，教师可调列权重）。**请教师确认此点**（区分"不要归一化"与"不要权重平均"两件事）。
- **同步项**：引擎 `merge_scores` 已是该口径（无需改，或仅补列级 weight）；PWA 改 computeScoresFiltered/srcScoreOf/宽表；导出 task-package 的 score_sources 展开为**每勾选列一条**（engine `--score family:file:col:weight` 支持多条，天然兼容）。
- 附加提醒：不同列满分不同（语文 150 vs 高数 100）时原始分平均会混合量纲——后续可选"列满分"或"可选归一"开关，不建议现在做。

### 4️⃣ 黑名单 —— 拍板确认
数值列枚举增加排除：`序号/编号/学号/工号/学籍号/班级/班号/姓名/名字/name/id/number/class/tag/punish/备注`（大小写+去空格匹配），
并加启发式：整列取值唯一且全为整数的列（序号/学号特征）默认不勾选（可见但置灰/或直接不列）。固定四类（学习通/雨课堂）同样生成列集合，勾选对所有 family 生效。

### 本轮新增待拍板
- 3️⃣ 的公式最终选择：**加权平均（推荐，与引擎一致）** vs 纯等权算术平均 vs 不除 Σw 的求和（不推荐）；
- 列权重 UI：每勾选列一个权重输入（默认 1）还是所有列等权第一版；
- KaTeX 修句柄：仅修①（选目录即连接）还是①+②（IndexedDB 持久化+权限恢复）；引擎 `/install/katex` 是否本批；
- 多列导出到 task-package（每列一条 score_sources）是否本批一起做。
---

## H1–H4 实施记录（2026-09-30 · D55 四拍板全落地）

| 批 | 内容 | 状态 | 落点 |
|---|---|---|---|
| H1a | **workspace 句柄根因修复**：设置中心选目录即连接（connectKbDir）；句柄 IndexedDB 持久化 + 启动权限恢复（dirHandleStore + restoreKbDir，App 启动调）；Transfer/KbEditor/Kb 三处调用点统一 connectKbDir | ✅ | SettingsView / kb.ts / dirHandleStore.ts / App.vue |
| H1b | **KaTeX 四态直装**：①已连接句柄→直接写盘；②未连接但可 FSA→弹一次目录选择即连接直装（零解压）；③引擎在线→`POST /install/katex` 服务端直装；④兜底 zip（仅 LAN/无引擎/无 FSA） | ✅ | SettingsView + engine serve.py `install_katex`（同源 dist 复制，回退 jsdelivr）+ INSTALL_ITEMS 增 katex + engine test_katex_install.py 两用例 |
| H2 | **预览收敛**：名单可编辑表固定高 320 滚动；名单原文预览折叠（details）；删"成绩源最近导入"悬浮卡（只留行内👁）；删"预览整个班"卡/按钮 | ✅ | RosterView |
| H3 | **多列模型 + 原始分加权平均（拍板）**：ScoreSource.includedColumns 带 weight；`scoreColumnsOf/columnScoreOf`（rosterXlsx 导出）；`computeScoresFiltered` 重写为 `Σ(原始分×列权重)/Σ列权重`（去掉班内最高分归一，与引擎 merge_scores 同口径）；总览表头=每源×每勾选列（列头：列级勾选 + 权重输入 + 按此列切分）；公式上屏（总览卡 notice） | ✅ | rosterXlsx.ts / roster.ts / stores/roster.ts / RosterView.vue |
| H3b | **列权重新动作**：toggleColumnInclude / setColumnWeight（至少保留一列）；tagByColumn(si, colName) 单列切分（原始分即排） | ✅ | stores/roster.ts |
| H4 | **黑名单**：序号/编号/学号/工号/学籍号/班级/班号/姓名/名字/备注/排名/层次/专业/函授站 + ascii(name/id/number/class/tag/punish/no/index) + 1..n 连续整数行号启发式；固定四类（rainclass 单列集合、crostab 每作业列）也生成列集合 | ✅ | rosterXlsx.ts dataNumericColumns |
| H4b | **task-package 多列展开**：每勾选列一条 score_sources（family/file/col/weight），引擎 `--score` 多条天然兼容；未勾选源保留一条 excluded 核对记录 | ✅ | rosterXlsx.ts buildTaskPackage |
| H4c | **一致性回归**：PWA selfcheck E 块（黑名单/单列=原始分/等权平均/2:1 加权=109.33/scoreColumnsOf）；引擎 test_scores_parity.py（merge_scores 原始分加权平均 109/95/109.33/单列=85） | ✅ | app/tests/selfcheck-roster-fig.mjs + engine/tests/test_scores_parity.py |

**验证**：vue-tsc+vite 0 err；selfcheck 全 PASS（新增 E 块）；engine 测试由 CI 复核。
**红线**：taskpad schema 不动；引擎除新增 katex 安装项与测试外零改动（merge_scores 本就是目标口径，无需改）。
**现场验收**：①设置中心选 workspace 后 KaTeX 卡显示已连接并可直装；刷新后仍连接（Chrome）；②名单表滚动、原文预览折叠；③教务期末导入 → 勾多列（语文/数学/…）→ 总览多列 + 各自权重输入 → 综合分=原始分加权平均；单列时=原始分；④序号/学号/班级不再出现勾选框。

---

## D56 · 第 20 轮代码审核任务单（班级与标签 UI 收敛 + 缺陷修复）

> **状态：⏸ 待执行**（用户将重启 feishu4dsh 服务，重启后通知开工）
> **基线**：`f33c5ce`（CI tests+pages 双绿；`engine/src/assist/roster/` 从未入库缺陷已修复）
> **来源**：2026-09-30 代码审核（仅讨论轮），用户诉求 = 名单预览/标签预览像全部成绩总览一样"折叠 + 滚轮查看"；以下 I/J 两批为审核全量发现。

### I 批 · UI 收敛 + P0 缺陷（先做）

| 编号 | 内容 | 现状证据 | 验收 |
|---|---|---|---|
| I1 | **三表滚动/折叠统一**：①名单可编辑表 → 固定高 320 + 滚动 + 粘性表头；②名单原文预览 → `<details>` 可折叠 + 内部滚动 + 粘性表头；③标签预览表 → 同上（高 360）；④全部成绩总览 → 保留 420 滚动并**补粘性表头**（列名/权重输入吸顶） | 名单表 L557-569 无包裹；原文预览 L570-575 常显；标签预览 L797-816 裸表；总览仅左侧 sticky-col（L676 有 420 滚动） | 三表均可滚轮查看、表头吸顶；折叠状态不影响数据；移动端可用 |
| I2 | **状态反馈可见性**：`status` 共 29 处写入，但仅 L555 一处展示且条件 `v-if="rosterFailNotice"`（只有失败可见）→ 各段独立状态行（名单/成绩/比例/标签/产出/班级清单），失败红条与成功提示分离；或引入统一 toast | RosterView L555 | 任一操作成功/失败均有就近反馈；连续操作不串台 |
| I3 | **`setPunish` 数据丢失修复**：取消 punish 时当前实现无条件 `setManualTag(stu,'')`，会把学生原有 tag（如 copy）清空 → 仅当 `stu.tag==='punish'` 时清空 | RosterView `setPunish` | 勾选再取消 punish 后，原 tag 保持不变；punish 语义与 tag 下拉一致 |
| I4 | **「清空全部」二次确认**（清空当前班级名单+成绩源+比例，目前一键无确认） | L552 | 弹确认；取消不产生任何变更 |
| I5 | **锚点条样式**：RosterView 使用 `class="design-anchors"`，但样式只定义在 SheetDesignView 的 scoped CSS → 无样式不吸顶 → 提取到全局 styles.css（或本页补样式） | L511 / SheetDesignView L108 | 锚点条吸顶 + 与作业纸设计页观感一致；跳转各段正常 |

### J 批 · 一致性 / 文案 / 边界

| 编号 | 内容 | 说明 |
|---|---|---|
| J1 | **成绩源卡文案过期** | L583 仍写"源内按最大值归一到 0~100、weighted mean"，与 D55-H3 定稿（原始分加权平均、不归一、列权重在总览表头）矛盾 → 全文案重写 |
| J2 | **大列数源的勾选行折叠** | 学习通 crostab 源可含 38 列 → 源行横排 38 个 checkbox；改为：默认显示"已勾列 + 权重摘要"，`<details>` 展开全列表；或 `+N 列` 展开 |
| J3 | **旧数据源降级提示** | `allNumericColumns` 仅导入/重解析时生成；存量 localStorage 源无勾选框与权重 → 源行提示"点「重解析」一次可启用多列勾选" |
| J4 | **导出/README 口径同步** | H3 后总览/导出只含已勾列（未勾列不再灰显保留）；`taskPackageReadme()`/docs 旧描述同步；导出列名=`源名·列名` |
| J5 | **KaTeX 卡状态回显 + 决策时序** | 卡片实时显示"已连接 workspace：<目录>/未连接"（反映 `getKbDirHandle()`）；点击安装前先 `pingEngine()` 再决定走引擎直装（避免引擎晚启动时误走 zip） |
| J6 | **改名后源匹配提示** | 名单表改名/改学号后，各成绩源按姓名匹配的分不会自动重映射 → 表旁提示或加"重匹配"说明（不改数据模型） |
| J7 | **deleteClass 清 v1 迁移键** | `deleteClass` 未清 `assignment-assistant.roster.v1`（极小） |
| J8 | **punish 双入口统一** | 标签预览表同时有 tag 下拉与 punish 勾选框，语义重叠 → 保留其一（推荐：punish 勾选框保留，tag 下拉中 punish 选项禁用/隐藏） |
| J9 | **黑名单收紧** | 现黑名单含"编号/专业"等泛词，真实成绩列名若含这些字会被误排（如"作业编号"）→ 改整词/精确匹配 + 自检样例 |
| J10 | 勾选框 title 文案更新（仍写 D47-5，改 D55-H3 多列语义） | 小 |

### 重启后续作指引（给下一次会话）
1. `git pull` → 确认 HEAD ≥ 本任务单所在提交；`npm ci`（app/）后 `npm run build` + `npm run selfcheck:roster-fig` 应全绿；
2. 先 I 批（B 后 J 批），每批：改码 → `vue-tsc+vite` 0 err → selfcheck →（必要时）`/tmp/venv313` 跑引擎 pytest（12/12 基线）；
3. push 注意：GitHub 连接间歇抖动，用"后台重试循环"模式（本会话已验证有效）；
4. 现场验收清单：①三表滚轮+折叠+吸顶；②每步操作有可见反馈；③punish 勾选取消不丢 tag；④清空有确认；⑤成绩源卡文案=新公式；⑥38 列源可折叠；⑦总览列名=源·列、未勾列不出现；⑧KaTeX 卡显示已连接并可直装（引擎离线/在线两路）。

---

## D56 实施记录（2026-09-30 · I/J 两批全部完成）

> 状态更新：本任务单 I 批 5 项 + J 批 10 项均已实施（下表为落地要点与验收）。

| 编号 | 状态 | 落地 |
|---|---|---|
| I1 | ✅ | 名单可编辑表→`.table-scroll.h320`（滚轮+粘性表头）；名单原文预览→`<details>`（默认收起）；标签预览→`<details open>`+`.table-scroll.h360`；总览补粘性表头（全局 CSS `.table-scroll/.score-wide-table/.preview-table thead th{position:sticky;top:0}`） |
| I2 | ✅ | 顶部 `roster-topbar`（锚点条+状态条同时吸顶）：`status` 全量可见，失败态 `.status-fail` 红条；移除旧"仅失败可见"的单点展示 |
| I3 | ✅ | `setPunish`：取消仅当 `tag==='punish'` 才清空，否则保留原 tag（`roster.touch()`） |
| I4 | ✅ | `clearAllAction()` 二次确认（含班级名提示），取消零变更 |
| I5 | ✅ | `.design-anchors` 提为全局样式（styles.css），两页共用；RosterView 顶部套 `.roster-topbar` 吸顶 |
| J1 | ✅ | 成绩源卡文案重写为 D55-H3 口径（多列勾选 / 原始分加权平均 / 不归一 / 列权重在总览表头） |
| J2 | ✅ | 列数 >6 的源：列勾选折叠为 `<details>`（显示"共 N 列/已勾 M 列"），≤6 内联 |
| J3 | ✅ | 无 `allNumericColumns` 的旧源：行内提示"点「重解析」一次启用多列勾选与逐列权重" |
| J4 | ✅ | `taskPackageReadme` 同步：多列展开多条 score_sources / 原始分加权平均 / 未勾列不出现在总览导出；`buildTaskPackage.note` 同步 |
| J5 | ✅ | KaTeX 卡显示 workspace 句柄实时状态（已连接/未连接+目录名）；安装前先 `restoreKbDir()` + `pingEngine()` 再决策（四态顺序不变）；安装成功回写状态 |
| J6 | ✅ | 名单表下提示"改名/改学号后源匹配不自动重映射，请重解析核对" |
| J7 | ✅ | `deleteClass` 顺手清 `roster.v1` 迁移键 |
| J8 | ✅ | tag 下拉（逐人 + 批量）隐藏 punish 选项（punish 统一走行内勾选框），title 注明 |
| J9 | ✅ | 黑名单收紧：按 `/ 、 ，` 拆段做**整词精确匹配**（"作业编号"不再误伤）；ASCII 全等；id/no/index+数字后缀 |
| J10 | ✅ | 勾选框 title 文案更新为 D55-H3 多列语义 |

**验证**：`vue-tsc+vite` 0 err；`selfcheck-roster-fig` 全 PASS（含 E 块多列/加权/黑名单用例，J9 收紧后仍 PASS）。
**现场验收**：①名单/标签预览可折叠+滚轮、表头吸顶；②任一操作后顶部状态条有反馈；③punish 勾选取消不丢 tag；④清空有确认；
⑤成绩源文案=新口径；⑥38 列源可折叠；⑦总览列名=源·列、未勾列不出现；⑧KaTeX 卡显示已连接并四态直装。

---

## D57 · 整班预览/输出的「参考答案/水印」开关对齐（第 21 轮反馈 · 待实施→实施）

### 核查结论（先纠正上轮口头范围）
- **问题成立**：班级与标签页「整班作业纸预览」把 `includeSolution` **硬编码为 true**（预览/打印/下载三处），
  而作业纸设计页 D43-6 早就有「显示参考答案」开关 → 整班要出**学生版（不含答案）**时无路可走，属实施遗漏。
- **范围修正（代码核实）**：
  1. PWA 整班预览/打印/下载走 HTML 模板 → **需要开关**（本单 D57-1）；
  2. batch zip 内嵌的 `sheets/*.html`（variantBatch provider）默认含答案 → **需要开关**（D57-2）；
  3. 引擎 `assist sheet batch` 走 **reportlab PDF（make_pdf）**，`resolve_items → (content, img, tag)`
     **根本不渲染参考答案**（layout.py 无 solution 逻辑）→ 该通道天然是"出题版"，**无需加 `--no-solution`**；
     引擎 HTML 通道 `assist sheet html --no-solution` 已在 D43 遗留①实现（前一轮"batch 缺 flag"的说法作废）。

### 任务项（全部实施）
| 项 | 内容 | 验收 |
|---|---|---|
| D57-1 | 整班预览卡加 3 开关：`☑显示参考答案`（默认**不勾**=出题版）、`☑显示水印图层`（默认勾）、`☑显示页码大字`（默认勾）；作用于 **预览/打印整班/下载 HTML**；切换开关时已打开的预览实时重建 | 不勾答案 → 预览/下载 HTML 无「参考答案：」行；水印/页码开关即时生效 |
| D57-2 | 作业纸内容页「变体编排」卡加 `☑ 内嵌 HTML 含参考答案`（默认**不勾**）；`variantBatch` provider 接该开关 → batch zip 的 `sheets/<id>.html` 按开关出题版/教师版；zip README 提示该开关语义 | zip 内 HTML 默认无答案；勾选后含答案；README 有说明 |
| D57-3 | 文档口径统一：引擎 batch PDF 天然不含答案；`sheet html --no-solution` 已有；三通道（PWA 预览 / zip HTML / CLI html）语义对照表写入 docs | docs/13/14 口径一致 |
| D57-4 | 回归：selfcheck 增 `includeSolution=false 不含'参考答案'` 断言；PWA 构建 0 err | selfcheck 全绿 |

### D57 实施记录（2026-09-30 · 全部完成）
| 项 | 状态 | 落点 |
|---|---|---|
| D57-1 整班预览卡三开关 | ✅ | RosterView：`classIncludeAnswers`（默认不勾）/`classIncludeWatermark`/`classIncludePageText`（默认勾）；`buildClassPreviewHtml()` 统一构建；开关变化时已打开预览实时重建（watch）；预览/打印/下载三处同一 opts；状态文案标注"学生版/教师版" |
| D57-2 batch zip HTML 开关 | ✅ | variantBatch：`setBatchHtmlIncludeSolution`（默认 false）+ provider 传 `includeSolution`；SheetContentView 变体卡加 `☑内嵌 HTML 含参考答案`；生成提示标注口径；zip README 语义由开关决定 |
| D57-3 三通道口径对照 | ✅ | docs/14 新增对照表（模板/整班/zip/CLI html/CLI PDF/KaTeX local） |
| D57-4 回归 | ✅ | selfcheck 新增 F 组：`includeSolution=false 无「参考答案」`、`=true 含答案`、水印图层/页码关断断言 → ALL PASS |

---

## D58 · TinyTeX 专用栏 + 全局返回顶部 + CLI 备份原则（2026-10-07 · 实施记录）

> 来源：用户对"先做 1（交付前收尾）"的追加要求：TinyTeX 像 KaTeX 一样在设置中心做检测/安装，
> 安装包不入远程仓库；所有选项卡加返回顶部按钮；CLI 要全面覆盖 PWA 作为 AI agent 备份。

| 项 | 状态 | 落点 |
|---|---|---|
| TinyTeX 设置中心专用栏 | ✅ | `SettingsView.vue`：检测 `xelatex` + 联网安装；engine `/doctor` + `/install/tinytex` |
| TinyTeX 零仓库资产 | ✅ | `engine/src/assist/paper/tinytex.py`：下载 `rstudio/tinytex-releases` daily 资产，解压 `<workspace>/.runtime/tex` |
| CLI 备份 | ✅ | `assist tex status` / `assist tex install`；`assist doctor` 识别 workspace TinyTeX |
| 全 tab 返回顶部 | ✅ | `App.vue` 全局 `.back-top`（scroll > 360px 显示）+ `styles.css` |
| D53-G2 reportlab 对齐 | ✅ | `engine/src/assist/paper/layout.py` 竖版 per_page=4 → rows4；新增 `test_pdf_grid.py` |
| 回归 | ✅ | engine pytest 18/18；PWA build 0 err；selfcheck ALL PASS |

**后续**：继续 B2（学号匹配回退）/B4（xlsx 样式写回）/B6（教师手册）与真实环境验收；
之后进入阶段6 学习通专项。

---

## D59 · B2 学号回退 + B4 样式保留写回（2026-10-07 · 实施记录）

| 项 | 状态 | 落点 |
|---|---|---|
| B2 引擎 | ✅ | `roster/scores.py` 输出 number；`roster/grouping.py merge_scores` 姓名→学号回退 |
| B2 PWA | ✅ | `ScoreSource.numberColumn/numbers`；`columnScoreOf`/`computeScoresFiltered`/总览宽表透传 number |
| B4 引擎 | ✅ | `files.kb_io.write_chapters_preserving`（openpyxl 只改 cell.value 保留样式） |
| B4 CLI | ✅ | `assist kb write --input <json> [--kind]`，写前自动 `.history` 快照 |
| B4 serve/PWA | ✅ | `POST /kb/write` + CORS OPTIONS；`saveKind` 引擎优先 → FSA → 下载 |
| 回归 | ✅ | engine pytest 22/22；PWA build 0 err；selfcheck ALL PASS（含 B2 number fallback） |

## D60 · 作业纸网格布局讨论（2026-10-07 · 未实施）

- 用户想法：`rows×cols` 可选（4×1 行均分、2×2 十字），2/3 题也可横/纵；
  增加「按行 / 按列 / 均匀分布（自动最接近方阵）」选项。
- 结论：可行；建议保留 `layout.per_page`，新增可选 `grid_mode/grid_rows/grid_cols`，
  旧任务包无需迁移；均匀分布按最接近方阵的因子对计算，不用 N² 个空位。
- 待拍板：① 数据模型方案；② 质数/非完全平方数退化方向；③ UI 放版式卡还是预览卡。
