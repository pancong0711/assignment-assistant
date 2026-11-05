# 12 — 未完成工作总览（2026-09-21 · 检测反馈后重整）

> 按模块整理所有已登记未完成事项 + 今日反馈新增；推进顺序见文末。
> 与 docs/06-roadmap.md 的阶段编号互引；冲突时以本文档为准（更新时同步 06）。

## A · 阶段 4a 收尾（小、纯缝合）

- ✅ **A3 /doctor 检查项 id 定版**（d3136aa：检查项含 id + fix 指引；CHECK_IDS 固化）；

- ✅ A1 引擎 token 贯通（设置中心 token 输入 + engineClient /status /doctor 传参；commit fd85107）；
- A2 selfcheck 入 CI：app/tests（watermark-doctor/family/lan-selftest）在 GitHub
  Actions 跑（现在 pages.yml 只 build+deploy）；顺带加 engine pytest；
- A3 /doctor 检查项 name 定版（PWA 端按 name 归并，改名自动追加——避免歧义）；
- A4（需你配合）真实 LLM key 跑 `assist grade` 一次，回提 prompt/评分口径反馈；
- A5 预览水印与引擎打印的一致性复核（今日已修"预览不显水印"兜底与虚线，待复测）。

## B · 阶段 5（M5 补强 + 作业纸多类型个性化 + 后勤）

- ✅ B3.5 变体编排前后端闭环（target_tag 标注/绑定面板/一键 batch zip/docs/04 字段；引擎 `assist sheet batch` 已实测 2 tag×多生；额外 TODO：`--batch batch.json` 元数据直读、--default tag 别名）。
- ✅ B1 rainclass 签到明细分析迁 engine（commit dc7fa3a：roster rain 解析/聚合/xlsx 导出；**多 sheet 成绩源仍待**）；
- B2 名单↔成绩学号匹配回退（现按姓名）；
- B3 fig 题图上传 UI + 引擎写回（OPFS→workspace），题库编辑器配图闭环；
- B4 SheetJS 写回 xlsx 样式丢失 → 引擎 openpyxl 补样式；
- B5 便携引擎包（Releases：engine-portable-<platform>.zip，D5/D14）；
- B6 教师使用手册 + Pages 用户教程 + 卸载指引；手机第二屏细化（D9）；
- ✅（M-D 前移）R1.2 start 脚本 + R1.3 /install jobs+SSE + R1.4 修复按钮（docs/13 M-D；commit d3136aa）——剩余仅：Windows start.bat 实测、静态清单卡微调；
- **B7（今日新增，重点）多类型/多层作业纸的"变体编排"**：
  目标 = 旧 2603 build_cfg_list 的网页化——按 tag 生成多份变体任务包、
  自动绑定 roster 分组（tag→任务包 映射表），一键发"每组不同的作业纸"。
  设计要点：
  1. taskpad 增加 `variant_of/组标签 field`（或独立"变体组"store）；
  2. 班级与成绩页导出时可直接生成 "tag→任务包id" 映射 JSON；
  3. 引擎 `assist sheet batch --roster tagged.xlsx` 按 tag 自动选用
     对应任务包出 PDF（每生取其 tag 对应的变体）。
- B8 Windows 实测批阅→ 反馈 prompt（需你配合，可提前）。

## C · 阶段 6（学习通，最后；D22 已拍板）

C1 登录/课程/作业浏览/下载（迁 2601 xuexitong 模块）；C2 上传=评语+图片+
自动打分（D7）+可选预览确认+三代上传策略择优；C3 grade flow download/upload
挂点补齐；C4 公告/通知（含附件）；C5 serve --https、PNG 截图。

## D · 验证/卫生

- D1 `app/dist-lan` 已移出库；确认无其他构建产物残留；
- D2 demo `sheet demo` 输出目录目前是 kb/.demo，应改走 classes/<class>/sheets/out；
- D3 bundle 拆分（SheetJS/JSZip 异步 chunk）；
- D4 Windows 实批（测试同学）。

## 推进顺序（方向 · 2026-09-21 修订：LLM/学习通等实时交互后置，先做完作业纸线）

1. **A 全清**（半天：A1/A2/A3 引擎+CI 缝合；A5 复测等你的反馈）；
2. **B1+B2+B3**（M5 精化：rainclass、学号回退、题图 UI）；
3. **B3.5 变体编排**（今日反馈 #3 的正解设计：见后文"变体方案"小节）；
4. B4/B5/B7（样式回写、便携包、手册）；
5. 阶段 6 学习通（真实账号配合一次性收尾）。

## 变体方案（B3.5 设计草案，先讨论后实施）

**目标**（对齐旧 2603 的 build_cfg_list 多套变体轮换，D23 落位阶段5）：
- 概念：一个"作业集"= N 份任务包（每份可对应不同 tag 集合/题量/版式）；
- 班级与成绩产出后，每生携带 tag → 引擎按 `tag→任务包` 映射自动选择
  变体（`assist sheet batch`），同一 tag 内题/人顺序可轮换防抄袭；
- PWA：DesignerView 增"变体组"概念（清单多选）与"按 tag 分配"面板；
  预览/导出保持现单任务包不变，仅新增"组"概念；
- 现阶段可用的操作路径（无需等开发）：
  1. 任务包清单里为每个 tag 各建一份任务包（横竖版/题量随意），
     标注在 id/标题上；
  2. 导出全部 zip 后在本机跑 `assist sheet make --task <各名册对应用包> --roster <tagged名单>`
     按班级分发；手动往复。变体编排上线后此流程自动化。
- 跨 kind 题：任务包 items 里 kind 与 tag 本就独立（你可以 browse problems
  同时 tag=copy）；若你遇到"不能实现"，多半是操作路径不直观——设计改造为
  "按 tag 提选题篮（跨 kind/章）+ 存为变体"。

## 今天的代码修正（已提交 9d4ff5d + 4021649）

| 反馈 | 修正 |
|---|---|
| 1 水印预览不显 | 预览兜底：items 空 → legacy 三槽占位（rt/lc/lb 与引擎一致）；items 有 → dataURL 真图预览 |
| 2 预览/印刷版式 | 网格语义定版：4=十字 2×2；横版 2/3=左右栏；竖版 2/3=上下行；**所有分隔线改虚线**（引擎 onPage setDash(4,3)，预览覆盖层 repeating-linear-gradient），不穿页眉页脚；预览不再画题目外框 |
| 3 多类型/变体 | 见"变体方案"（跨 kind/tag 任务包构建现可用；变体编排待实施） |
| 4 名单页排版 | 头部说明卡移除，特殊标签栏常显；导入/手动/批量/清空全部集中于此，位于产出栏之前 |


## 2026-09-23 · S2 系列收割（三批并行合流后）

- ✅ **S2a HTML 主通道**（2fcaf51+ec4da98）：`assist sheet html`（CLI/Jinja2+KaTeX+水印 items/dataURL 题图),PWA同构 print/preview overlay（SheetLayout/Content 视图内两处），4 tests；egration fix：roster 英文表头同名映射；
- ✅ **S2b 成绩宽表+勾选列、整班 overlay**（c4dca40）：VC-3/4/5/6 + M-C R3.2/3.3 数据流 *"所见即所选"*；
- ✅ **S2c batch zip/print guide/TEMPLATE_HINT**（f686045）；**S2 合流 wiring**（8cab206）：PrintGuideModal 接版式页 / setSheetHtmlProvider 接线（默认 sheetHtml 模块惰性注入）/ `assist sheet html` CLI 超集定版（D30 主通道）+ CLI `_setup` str/Path 归一；
- 验证：engine pytest 4/4（含 sheet-html 双版式/parity 哨兵）、app build+l dist-lan 0 错、lint-bat/secrets 全绿；
- 复测入口（**手机/浏览器均可，无引擎）**：`作业纸版式`→「🖨 打印浏览器版」按钮（当前任务包→浏览器打印/PDF）、「⬇下载整班HTML」；`作业纸内容`→清单行「预览」/copy「预览全部任务包」（多包连排）；`班级与标签`→名单/成绩预览卡（表头+前3行）、「按勾选源重算/按此列切分」、整班预览（"预览整班"卡在 SheetContent 变体编排区）；
- 后续（S1.2 下一批）：VA-1 引擎 zip 下载 fallback（start.bat 实施到脚本内）、`include_in_aggregation` 引擎侧自动省略、KaTeX 离线打包、VB-7 pull ref、`_setup(--workspace)` 全局归一后的其他命令（batch/make）等（docs/13 §S2a/S2b/S2c 遗留，均不阻塞验收）。




---

# 2026-09-23 · Windows 现场验收记录（第 4 轮）＋ 剩余工作汇总

## 现场（教师机 D 盘 workspace，v6→v10.2 共 4 轮实测）
✅ **Python-first 全链路通过**（v9 重写后）：py -3 检测 → venv → TUNA 依赖
（assist-engine 0.1.0 + 24 wheels）；
✅ Pages 主源 engine-main.zip **81KB 秒级下载**（v10.1 链）；
❌ **仅剩 [6/6]**："all ports busy"（D35：findstr /R 空格分词 OR 坑——
   用户 netstat 验证：机器上 8601+ 无真实监听；扫描误判）→ **v10.3 待修（唯一禁手）**；
- 里程碑：**第一台教师机完整环境就绪**（依赖已进 workspace/.runtime/venv，
  "删区=卸载"语义闭环）。

## 下一轮（v10.3 即开工）
1. **v10.3 lombok**：bat 端口扫描两段 findstr（/C: 字面量 + 二级 LISTENING 过滤）
   + lint 规则第 9 条（findstr /R 空格分词禁令）+ 残留引擎自动 kill 分支：
2. **S3 批次收尾**：TinyTeX 可选按钮（体检页）、R1.1 清单卡微调；
3. **KaTeX 离线打包**（CDN 目前可用，可选）；
4. **D32/D36 reportlab+HTML 双引擎长期规划**（功能等价，渐进对齐）；
5. **docs/11 部署页**补"教师机 Windows 一键部署"教程（3 步图文）；
6. （待用户窗口）PyPI 发版流程恢复后执行，pypi.org outage 记录。

## 教师手册要点（docs/14 补条）
- [Windows 双击 start.bat] → 自动浏览器 → 体检变绿 → 使用端点；
- 日志（workspace/start.log）与 "start_log 只有一行" 的排障案例；
- 双击模型：**工作区=start.bat 所在目录**（docs/05-D28 的网页引导同步）。


---

# 2026-09-28 · v10.3 部署完成（D35 收口，最后一堵墙已推倒）
- ✅ **端口扫描 findstr /R 空格分词坑修复**（bat L104-111：两段 `findstr /C:":%%p "` 精确字面 +
  二级 `LISTENING` 过滤；括号平衡（FOR 内层 `)`/`IF` 括号结构整理）；
- ✅ **lint 规则第 9 条**已进 CI（tests workflow 中 python3 tools/lint_bat.py，
  其中含 D35 的 findstr 空格分词规则），与 Windows 现场验证 4 轮全部绿；
- ⏭️ **Windows 复测（你侧 v10.3 验证之后）**：主链 Pages → venv → engine 源码 zip →
  全部就绪后，到 **[6/6] start engine** 这一步——现在应该能正常启动 engine serve 在
  8601..8649 的空档端口上。start.log 会留下最后一行 "engine http://127.0.0.1:XXXX"；
- 设计仍然不变（ck：docs/12 priority）。


---

# 2026-09-28 · S11 作业纸设计合并视图 部署（D39 记录 + VC-C/D40 等待项）
- ✅ **SheetDesignView**（wrapper 合并视图）：SheetLayoutView + SheetContentView 同 pinia store 同屏渲染；
  hash /#/layout /#/content /#/designer /#/sheet 全部重定向 #/design；
  页内锚点锚座（"①版式 / ②内容 / ③预览导出"——快速跳转 / sticky 顶部导航）；
- 其他选项卡（题库/班级与标签/学习通/导入导出）不合并——保持独立（D39 用户拍板）；
- kox canti 后续： **VC-C.5 translation**（kbXlsx 中文表头 + 特殊标签栏/独立面板）——独立 session 收口；
- Windows v10.3 → S11 合并视图复测（你手机或电脑鉴试的"LIVE 页面流程"）—— 等两端反馈后一起更新 docs/12 (第 6 轮课本记录)。


---

# 2026-09-28晚 · D40 translation（方案 C）实装第 1/3 部分 —— PWA/kbXlsx 中文表头
- ✅ **PWA `kbXlsx.ts` 支持 `translation.xlsx` 中文例外表头解析**：
  `parseTranslationAoA/isTranslationXlsx`（名言/作者/出处/年份 → 拼接"请翻译以下内容…"，与引擎
  `read_translation` 同语义）；`readKbXlsx` kind='translation' 时走专用解析分支；
- **这一补丁使 translation 题目从“无法读取 xlsx”变为“可读/可编/可进任务包”**——
  而 `target_tag=translation` 任务的引擎 batch 分发链早已通（tag→任务包绑定）；
- **剩余（D40 方案 C 后半）**：特殊标签区"translation 专属"独立面板（比例输入 + 手动名单/分布统计）；
- CI 双工作流全绿（pages/tests）；`node self-check` 通过。


---

# 2026-09-28 · D41-A 数据流修复交付（Duplicates removed / sourcePreview latest mode / build 0 err）
- sourcePreview 改为单一 latest 模式（不再 stale "per-source record" 分散 state）—— compiler clean；
- translation 分发面板/宽表/打印相关 string 检查均通过（live bundle content = 想要的 UI）；
- D41-B/D41-C/D41-D 仍待实施（预览虚线 overflow fix，code-split，binary removal），已在 docs/13 D41 列为下轮 roll；
- 页面：essay 4 轮lined已final（贴你的 start.log 反馈即可）


---
# 2026-09-28 · D41 全系列实施完成（数据流/预览 CSS/UI重排/Playwright/binary cleanup）

- ✅ **sourcePreview cleanup**：per-source overwrites resolved to "latest" 模式，build 0 err
- ✅ **CSS overflow**：deck-view divided .sheet-frame content max-width + word-break → 不跨虚线
- ✅ **UI renames**（任务包→作业纸 etc 弃语版 manifest pull across views/lib）
- ✅ **Playwright semantic**（status "yellow" 可跳过 note，green = 已装）
- ✅ **binaries removed from repo** (~40 MB git tree clean → future engine-main.zip 80KB 不再 hit)

---

# 2026-09-29 · 两轮网页结构讨论拍板 → docs/13 重建需求单（D43 系列）

- **docs/13-taskboard.md 已重建**：上一版在 36aaa88 被清空（当时 commit 信息称"D41 任务需求单"，
  实际 diff 为 231 行全删；D41 实施记录以本文档 2026-09-28 条目为准）。docs/13 现恢复为
  "当前活动需求单"，本档保持总账职能；
- **已拍板**：D43-1 输出与交付沉底 / D43-2 保存上移至新建工具栏 / D43-3 预览合并（单一 HTML 模板渲染，
  删 CSS 近似双轨）/ D43-4 清单+预览合卡（现状清单在设计页出现两次）/ D43-5 批阅独立选项卡
  （grade 移出作业纸设计；GradingView.vue 复活 + DesignerView.vue 孤儿清理；#/grading hash 改向真 tab；schema grade 节保留不动；
  **导航位置已拍板**：班级与标签 与 学习通 之间）；
- **D43-6 口径修正（2026-09-29 第二次反馈）**："勾选"= **预览/打印内容开关**：
  ☑参考答案（未勾→预览/打印不含答案行）+ ☑学生示例（未勾→页眉三空位、1 份空白模板；
  勾→按合成 学生A/B 2 份），统一作用于设计页实时预览/清单行预览/预览全部连排/输出卡打印与下载；
  **预览域分层拍板**：作业纸设计=模板级预览（仅）、整班分层预览=仅在班级与标签页（VC-3 唯一入口，
  SheetContent 重复的"预览整班"卡移除）；现状清单预览按 roster 全班展开（28 人×N 包）须切回模板态；
  细节（默认值/班级页是否加答案开关/持久化）见 docs/13 D43-6 待拍板；
- 本轮为仅讨论会话：**未改任何代码**；批次顺序 A→D，红线不变（schema 不动 / D1 CLI 超集）。


---

# 2026-09-29 · D43 全批次实施完成（docs/13「实施记录」同条）

- ✅ A 输出沉底+保存上移；B 批阅独立 tab（GradingView 复活/学习通纯净/#/grading 直达/DesignerView 删除）；
- ✅ C 预览合一（同模板 iframe + 相对 KaTeX）+ 清单合卡 + 整班预览唯一入口归班级页（classOverlay 第二套模板删除）；
- ✅ D 内容开关（参考答案/学生示例，默认不勾）+ KaTeX 三模式接线（relative/raw 内联自包含）+ 设置中心自检卡 + 帮助页文案改正；
- 验证：vue-tsc+vite 0 err；node 冒烟 pass；引擎 pytest 待 CI（j2 未动）。

---

# 2026-09-29 · D44 KaTeX 去仓库化（npm 依赖 + 构建期拷贝）

- ✅ `katex@0.16.4` 进 `app/package.json`（锁版）；`tools/copy-katex.mjs` + predev/prebuild；
  `.gitignore app/public/katex/` + `git rm --cached`（600KB vendor 资产退出版本控制，~600KB×1 前向不再入 git）；
- ✅ dev/build 全链自愈（fresh clone `npm run dev` 先经 predev 拷贝）；dist/katex 608K×20 woff2 与 D43 手工 vendor 同口径；
- ✅ 未采纳方案（SW 运行时装载 / 引擎 /install）与理由记 docs/13-D44 & docs/05-D44；start.bat/sh 未动；
- 决策依据：xlsx/jszip 同模式先例、LAN 二屏 insecure context 对 SW 的硬伤、零用户动作优于一键安装。

---

# 2026-09-29 · D45 段序重排 + D43 遗留三件收口

- ✅ **D45**（docs/05-D45）：作业纸设计页工序化重排 ①版式 ②内容 ③预览/清单 ④输出与交付；
  输出/预览独立成组件（SheetOutputSection / SheetPreviewSection），SheetLayoutView 瘦身至表单；
  开关挂父级共享；动线 = 版式 → 选题 → 预览 → 交付（同日反馈四段一序拍板）；
- ✅ D43 遗留①：`assist sheet html` + `--no-solution` / `--students roster|sample|blank`
  （与 PWA 内容开关同语义；j2/CLI/测试全通；StrictUndefined 默认值兜底）；
- ✅ D43 遗留②：batch zip `sheets/*.html` 换 relative KaTeX + 内嵌 `sheets/katex/**`（一次性 608KB，离线渲染）；
- ✅ D43 遗留③：三类预览 iframe aria-label + tabindex="0"；
- 备查：D43 遗留② 的 CDN 兜底语义保留（fetch 失败静默跳过）；引擎 make（reportlab）仍不关 answer（教师 PDF 命令行按需 --no-solution 候补）。

---

# 2026-09-29 · 第 8 轮反馈登记：D43-7 预览水印开关（仅讨论未实施）

- 诉求：预览里的「第 N 页」大字水印 + legacy 三槽占位框要可勾选隐藏，**默认勾选**（=现状）；
- 结论：与 D43-6 开关体系同构（③段第三个 checkbox，作用于预览/连排/清单行/④输出）；
  数据面 = stringifySheetHtml 增 includeWatermark（缺省 true）；引擎侧**零新增**
  （CLI 已有 --no-watermark，前端镜像即可）；①卡「启用水印」= 属性，③段开关 = 视图口径，两级并存；
- 三个待拍板细节（总开关 vs 拆分 / 占位框隐藏方式 / 题图占位是否同批）见 docs/13 D43-7；
- 另记：D45+D43 遗留已于 fb391f2 推送部署成功（Pages/tests CI 双绿，线上 index-CMVEb0st.js）。

---

# 2026-09-29 · 第 9 轮反馈：D46 导入健壮性登记（仅讨论未动代码）

- **D46-1 教务点名册解析失败**（现场 bug）：根因=新旧代码读的点名册形态不同——旧 `_legacy student.py`
  按 zjxu 名册**硬位置**切片（iloc[8:-3, C/A/E 列]），新 PWA/引擎按**表头自适应**（姓名/学号/班级），
  真·点名册无标准表头 → 0 人。修复=表头自适应 + 关键词找表头行回退（+可选固定位置模式）；
  **pandas 没装也不需要装**（engine 迁移原则"去 pandas"，openpyxl 等价实现）；
- 其他 family 排查：exam/学习通×2/雨课堂 均按列名/结构关键词定位，✅ 无同类硬伤；
  系统性小缺口=所有 family 只读第一张 sheet（B1 多 sheet 尾巴）；
- **D46-2** 导入后名单"没更新"= D46-1 的直接后果 + 失败态 UX 加固；
- **D46-3** 成绩源行内👁预览按钮：VC-6 只做了"导入当次"预览，缺持久回看（store 需留 raw，IndexedDB vs 截断矩阵待拍板）；
- **D46-4** 多源合并总览：宽表已存在，升级为正式「全部成绩总览」（列头元信息/综合分高亮/导出 xlsx）；
- 批次：E1=D46-1/2 → E2=D43-7 水印开关 → E3=D46-3 → E4=D46-4；细则与待拍板三点见 docs/13-D46。

---

# 2026-09-29 · 第 10 轮拍板：D43-7 拆两开关 + D46 三条全按推荐（仅文档，未动代码）

- **D43-7-a 拍板**：水印拆两个开关 ☑水印图层 + ☑页码大字（各默认勾）；sheetHtml 增
  includeWatermark/includePageText 两 opts；作用面同答案/示例开关；引擎零新增；
- **D43-7-c 修正**：题图占位框**不并入**水印开关（题图=题目属性非全局元素）→ 剥离为 D46-5，
  挂 B3（fig 上传闭环）主线：PWA 预览后续按 wmAssets 模式显示真图；
- **D46 三拍板全按推荐**：① 点名册两级回退（表头自适应→关键词找表头行；固定位置模式不做，
  失败给前3行诊断+指引）；② 源 raw 留存=IndexedDB 全量 ArrayBuffer（预览/reparse 免二次选文件）；
  ③ 总览导出含未勾选源列（灰显）；
- 实施方案四步细则（E1/E3/E4）见 docs/13-D46「实施方案（讨论稿）」；批次序不变 E1→E2→E3→E4。

---

# 2026-09-29 · E1–E4 实施完成（点名册回退/水印双开关/源行内预览/成绩总览）

- ✅ **E1 D46-1/2**：readRosterXlsx 两级回退（表头自适应→前15行关键词找表头行）+ RosterParseError 结构化失败
  （前3行原文诊断进红色 notice）；引擎 read_roster 同语义；zjxu 名册形态冒烟 PASS×3；新 engine test_roster_parse.py；
- ✅ **E2 D43-7**：☑水印图层 + ☑页码大字双开关（默认勾），sheetHtml includeWatermark/includePageText，
  ③④段共享；关图层=整层含占位框消失（body-DOM 冒烟 4/4）；引擎零新增（--no-watermark 镜像）；
- ✅ **E3 D46-3**：idbRaw.ts IndexedDB 留存原始 ArrayBuffer（uid 键，降级 no-op）；行尾👁回看 + reparseFromRaw 免二次选文件；
- ✅ **E4 D46-4**：宽表升级「全部成绩总览」：综合分列（shadow 干跑不污染 store，随勾选即时重算）+ 导出 xlsx（未勾选列标[未参与]）；
- 构建 0 err；细则见 docs/13「E1–E4 实施记录」。遗留：无 uid 旧源首次👁引导重选文件；B1 多 sheet；D46-5/B3 题图真图。

---

# 2026-09-29 · B1 多 sheet 成绩源完成（+E3 关键修复：uid/sheetName 被 normalizeSource 吞）

- ✅ pickBestSheet 启发式（表头候选优先→数据行数最多）；read/preview 全链可选 sheetName；
- ✅ ScoreSource.sheetName + normalizeSource 透传修复（**E3 隐患**：uid 之前被 normalize 吃掉 → IDB raw 键没落盘，本轮修复并冒烟复验 uid 存活）；
- ✅ store listSourceSheets/setSourceSheet；RosterView 行尾 ⇄ sheet 切换按钮 + sheet= 显示；
- ✅ 引擎 scores.py 本按名匹配 sheet，CLI 不动；冒烟 4/4 PASS；build 0 err。

---

# 2026-09-29 · B3/D46-5 题图素材库完成（预览真图 + kb/fig 写回 + 回归自检上 CI）

- ✅ settings.figAssets（wmAssets 同模式）；KbEditorView 行内📷上传→即时入库+缩略+img_path 自动填 fig/名；
- ✅ FSA 连接时写回 kb/fig/<文件名>（引擎 CLI base64 通道打通）；未连接给手动指引；
- ✅ sheetHtml figAssets opt + figHtml()：命中→<img class=q-img>（与引擎同视觉），未命中→占位框现状；③④/整班/自包含全链透传；
- ✅ app/tests/selfcheck-roster-fig.mjs 11 断言 ALL PASS（多sheet/点名册回退/题图三族），CI tests.yml 硬门禁挂载；
- build 0 err；localStorage 超限静默降级=回占位框（后续可迁 IndexedDB，idbRaw 现成）。
- 至此第 9/10 轮反馈全部清账：D46-1~4 + D43-7 + B1 + B3(前端半) 全部上线。

---

# 2026-09-29 · 第 11 轮：真实文件核测揭穿 4 个解析缺陷（D47 登记·仅讨论未动代码）

- 用教师 legacy 真文件（namelists/xxt/custom/rainclass）node 直跑核测：
  ① **.xls 学号被改写**（12 位号错位/XLS 精度）→ roster 名单学号列内容错；
  ② **exam 前两行标题表头** → "期末"列定位失败 scores=0；
  ③④ **学习通 assignment/stat crostab 两行表头列错位** → scores=0（PWA+engine 同病）；
  ⑤ rainclass pickBestSheet 误选课堂子表（应锁"汇总"表）；
- 教师体感："导入点名册名单没更新+总览 姓名/学号 两列空白+成绩列勾选死硬编码" —— 与以上根因吻合；
- **D47 设计**：三段式表头定位器 / 学习通 crostab 解析重写 / .xls 数字列字符串化 / rainclass 汇总锁定 /
  **perColumn 成绩列多选勾选**（扩展 includeInAggregation）/ 全文件完整预览（预览卡升级）×
  整班模式；细则与待教师提供的样例请求见 docs/13 D47。**批次：E5（先 1-4 骨架 → 5 勾选 → 6 预览）。**

---

# 2026-10-15 · 学习通成绩源 PWA↔engine 口径回归修复（E5 crostab 重写尾巴）

**现象**：`app/tests/selfcheck-family.mjs` 第 3 例 `xuexitong_assignment` 断言 A=75 实得 80（干净 HEAD 即失败），
CI 因 `|| true` 软容错一直掩盖。

**根因**：
- 测试 fixture（D19 提交）忠实编码了 docs/05-D19 口径「前 8 行扫描**含"成绩"的行**（子串）+ 各成绩列均分」，
  引擎 `read_xuexitong_assignment` 实测 A=75/B=70 一致；且合成 fixture 用 `作业1成绩` 表头、无姓名列。
- PWA `detectCrostab`（E5 `5f34228` 重写）改为「标题行含**姓名** + 标记行**恰好等于"成绩"** + 姓名列必须命中」，
  合成/旧形态 `作业1成绩` 不触发 → 落入 custom 兜底按「数值最多列」取错列 → A=80。
- E5 文档自注「建议 fixture 实测一次」未落实，fixture 未同步。

**修复**（PWA 向引擎口径对齐，docs/05-D19 为准）：
1. PWA `detectCrostab`：标记行改**子串**匹配"成绩"（≥1 列即可），不再硬性要求标题行含姓名；
2. PWA `buildCrostabSource`：姓名列缺省回落第 0 列（引擎 name_i=0 同口径）；scoreCols 用子串；
   `xuexitong_stat` 非 0 才计入（引擎 `read_xuexitong_stat` 迁移语义）；
3. PWA 多 sheet 探测按 family 优先锁定（assignment→作业统计 / stat→章节测验）；
4. 引擎 `_rows_of`：按名字关键词命中 sheet 时直接用名字定位（此前 `int(name)` 对中文表名 ValueError）；
5. 引擎 `read_xuexitong_assignment/stat`：`float()` 增捕 `ValueError`（openpyxl 空格 = `''`）。

**验证**：合成 fixture 5 例（app selfcheck-family 全部通过）+ engine pytest 6 例
（`engine/tests/test_scores_xuexitong.py`）+ 真实 legacy 文件（xxt_0518 作业统计 67/67、章节测验 44/44、
rainclass 67/67，PWA↔engine 全等，仅末位浮点四舍五入噪声）。

**门禁加固**：新增 npm `selfcheck:family` / `selfcheck:variants` / `selfcheck`；CI `tests.yml` 去掉
`selfcheck-family.mjs || true`，改为 `npm run selfcheck` 硬门禁；`selfcheck-roster-fig.mjs` D47 legacy 块
改按存在文件动态发现、断言结构性（锁定 sheet + 解析出人），不再因文件名漂移静默跳过。

**遗留（已知 PWA/engine 仍未对齐，另行任务）**：
- ✅ `exam` 真实「成绩统计」表首行是标题行而非表头：engine `read_exam`/`read_flex` 已补
  `_locate_header_row` 三段式（与 PWA `locateHeader` 同口径），真实文件 化工251(34人)/化工252(33人)
  验证通过（2026-10-15，见 docs/36）。
- `xuexitong_stat` 的 sheet 关键字匹配：engine 默认"章节测验"，PWA 现按 family 优先——已一致，但真实文件
  若关键字命名不同仍需放宽。

---

# 2026-09-29 · E5 实施完成（真实形态适配大修）—— 第 11 轮反馈全部清账

- ✅ 通用三段式 locateHeader（上溯 extent 至 20 行）+ 数据区 .xs 文件学号无损（zjxu 名册 13 位文本原值）；
- ✅ exam 列名放宽 /期末|成绩|得分|总分|score/；xxt crostab 全 sheet 探测重写（B1 pickBestSheet 误选表也兜得住）；
- ✅ rainclass 锁"汇总"表（真实文件选错课堂子表 bug 修复）；
- ✅ perColumn 成绩列勾选（exam/custom 默认全勾）+ 源行 checkbox；总览/加权随勾选；
- ✅ 全文件预览（500 行滚动）；总览卡 👁「预览整个班」按钮；
- ✅ legacy 真文件回归：请教师用样例核测后可直接验收（roster 69 人学号原值、exam 33、xxtA/S 31、rain 67、custom 34）；
- selfcheck-roster-fig.mjs 11→14 断言（+D47 legacy×3）；CI 硬门禁。

---

# 2026-09-29 · D48 根因确认（第 12 轮教师症状 4 条=同一个案：双入口语义混乱）

- 教师点名册走了「成绩源→roster 预设」而不是「导入名单 xlsx」，特写：sources 侧 roster 源灰列出现 +
  roster.students=[] → 总览姓名/学号空 + 分组比例区"名单为空"；
- 修法草案（docs/13 D48）：单写路径（addScoreSource roster→also 写 students）/双入口 UI 硬分流/
  空名单警示。待拍板（改名 vs 移除 roster 下拉选项），师重发点名册 .xls 可同验；
- **历史教训**：本批 D19 初期设计与 roster family 的"接表"语义在 M-C 的 UI 里出现了两个入口——
  教师预告的/errors 与 'roster' family 的红色灰显 Filtering 兼容性提醒不足，本批落 D48 予以授权修复。

---

# 2026-09-29 · D49 登记（第 13 轮：accept 扩展 + 班级为中心重设计 + 产出文件管理）

- 原因补充分析：除 pickXlsx accept 只认 .xlsx 外，主因仍是 D48 双入口（点名册走成绩源入口→roster.students 从未写入）；
  另列旧 bundle 缓存/提示性不足两个次因；accept 修正=.xlsx,.xls,.csv 三处（FSA+input）；
- **班级与标签重设计**（教师提案结构化）：班级配置栏 + 名单/成绩加权/标签/产出四模块 + 班级清单栏（载入/删除）；
  多班级 store（classes: Record<id, workspace> + activeClassId）；班级清单字段建议 6 项（人数/tag 分布/源清单/
  缺源警示/关联作业纸/最近产出物+三态徽标）；
- **产出文件管理三件套**：产出登记簿（artifacts[] 元数据）/ overview/ 归档路径 / 目录定位按钮；未连接降级语义；
- 批次：F1(D48+accept) → F2(多班级) → F3(登记簿) → F4(产出段整合)；四项待拍板见 docs/13-D49。

---

# 2026-09-30 · F1–F4 实施完成（D49 四拍板全落地；班级与标签"班级为中心"重构上线）

- ✅ F1：accept .xlsx/.xls/.csv；roster 预设从成绩源下拉移除；单写路径（roster 源→students merge）；
- ✅ F2：多班级 store（v2 键+迁移）；班级配置栏 + 班级清单栏（载入/删除/三态徽标/tag 分布/最近产出）；
- ✅ F3：产出登记簿 artifacts[]（cap 30）：roster.xlsx/json/task-package.zip/总览/batch zip 五产出点全登记；
- ✅ F4：产出卡收口（集中入口+FSA 归档说明+batch 产出指引）；
- build 0 err；selfcheck 14/14；引擎零改动。
- 教师现场验收清单：新建/载入/删除班级；点名册从两入口导都写名单；.xls 可选；空名单黄条；产出簿显示。

---

# 2026-09-30 · D50 登记（第 14 轮：名单模块未独立成卡 = F2 实施缺口）

- 现象：教师找不到导入名单按钮；唯一入口藏在「特殊标签」卡里（一词两义：建名单 vs 覆盖标签）；
- 核查：importRoster 全页仅此一处，功能=正牌名单导入；F2 只做了班级配置栏+清单栏，
  D49 四段中的「①名单模块」未拆出——实施缺口；
- 修法（讨论稿）：①名单模块新卡（导入/手动/学生基本列表）+ 特殊标签卡瘦身（改名「导入带 tag 名单（覆盖特殊标签）」
  或移除，待拍板）+ 卡序重排（班级配置→名单→成绩→标签→产出→清单）+ 预览卡归位；
- 三项待拍板见 docs/13-D50（学生表拆两张/改名保留 vs 移除/卡序是否同批）。

---

# 2026-09-30 · D50b 拍板（第 15 轮）：三类预览拆开 + 标签段动线定稿

- **三类预览拆开**：名单预览/成绩预览/标签预览 各归各段（名单模块/成绩模块/标签模块）；
- **特殊标签卡**：移除导入带 tag 名单按钮；改名「标签预览」；批量打 tag 行保留（教师钩选）；
- **translation 前移**：卡序=分组比例（其他 tag 和=100）+ translation 随机比例 → 打 tag → 标签预览跟随；
  打 tag 按钮已在比例卡内，动线成立；translation 比例并入比例卡"两行制"（倾向）待实施确认；
- 页面最终卡序与实施清单（D50b）见 docs/13；纯前端重排，量小一次会话。

---

# 2026-09-30 · D50b 实施完成（班级与标签四段+三预览重排上线）

- ✅ 名单模块独立卡（导入/手动/基本表+名单预览）；成绩源卡吸收成绩预览悬浮卡；
- ✅ 特殊标签→「标签预览」卡（移除导入按钮、tag 分布统计、批量打 tag 保留、逐人下拉覆盖）；
- ✅ translation 比例并入分组比例卡（两行制），面板瘦身为手动点名；卡序定稿+sticky 锚点导航；
- store 冒烟 6 项 PASS；build 0 err；纯前端零 schema/引擎改动。

---

# 2026-09-30 · D52 三问题核查登记（仅讨论）

- ① 双 translation = D50b 残留：比例已并入分组比例卡，但旧卡标题/hint 未清理 → 改名"translation 手动点名"+删重复描述；
- ② KaTeX：npm 依赖+构建期注入（仓库不存资产）；PWA 零下载；下载 HTML 自包含；唯一缺口=引擎 CLI 产物离线渲染，
  可选补丁=设置中心「导出 katex 文件夹到 workspace」（FSA 一次点击），待拍板；
- ③ 竖版 2/3/4 半宽错乱根因=D41 的 `.divided .sheet-frame{max-width:50%}` 误伤竖版 + gridKey 竖版4恒十字；
  修法=max-width 按 cols*/cross 限定 + 竖版4→rows4（新档三横线）；engine 双端同步；两小案待拍板（4 的竖/横语义）。

---

# 2026-09-30 · D53 三拍板落档（translation 卡删除/per_page 竖横语义/KaTeX workspace 安装）

- ① 核实：手动点名打 translation 与批量打 tag 逐行同构 → 「translation 拨给」卡整体删除成立；
  随机比例能力在 applyAutoTagging+比例卡第二行（不受影响）；
- ② 定稿：竖版 2/3/4 全纵向一列均分（rows4 新档三横线）+ rows* 解除 max-width:50% 误伤；横版维持 cols/cross；
  printCss/j2/engine _grid_key 三端同步；
- ③ 定稿：设置中心「KaTeX 离线包」一键 FSA 写 `<workspace>/sheets/katex/**`（同源 dist 资源，仓库零占用）；
  引擎 `assist sheet html --katex local|cdn` 小补丁配套；无 FSA 降级=zip 下载+指引；
- 批次 G1/G2/G3 独立可一批。详见 docs/13-D53。

---

# 2026-09-30 · G1–G3 实施完成（D53 清账）

- ✅ G1 translation 残卡删除（双入口彻底消失；translation 仅剩比例卡随机拨给%+批量打tag+学生表下拉三形态）；
- ✅ G2 竖版 2/3/4 纵向满行均分（rows4 新档三横线；max-width 误伤按 cols/cross 限定）三端同步+测试；
- ✅ G3 KaTeX 一键装进 workspace（sheets/katex/，FSA/zip 双路）+ 引擎 --katex local 配套；仓库零占用不变；
- build 0 err；布局冒烟 7/7；selfcheck 14/14；engine tests 新增 ①b/②c+② 更新。

---

# 2026-09-30 · D54 第 18 轮五问核查登记（仅讨论）

- ① KaTeX 直装：无句柄才降级 zip；建议加「选择 workspace 目录并安装」两态直装，LAN 走引擎 /install/katex（待拍板）；
- ② 预览重复：成绩源"最近导入卡"与行内👁真重复（删）；"预览整个班"与总览真重复（删）；名单可编辑表+原文件预览半重复
  （表固定高滚动、原文件预览折叠）；可编辑名单表改滚动省空间（教师建议）；
- ③ 列勾选失效四根因：总览每源一列模型 / sourceScoreMatrix 不消费 includedColumns / 固定 family 无列集合 /
  数值列枚举未排元数据列（序号学号班级混入）；
- ④ 综合分=100×Σ(raw/max×w/Σw)：单源=100×raw/max≠原始分（教师困惑根因）；权重为源级、仅多源生效；
  建议多列模型+单列直用+公式上屏+列权重（细节见 docs/13-D54 待拍板 1-4）。

---

# 2026-09-30 · D55 登记（第 19 轮：workspace 句柄根因/多列口径拍板/引擎- PWA 打分口径分叉）

- ① 未连接根因：SettingsView 选目录后只存名字丢句柄；句柄仅内存无持久化；"设置路径"≠"FSA 连接"。
  直装两态+引擎 /install/katex 可解，但需先修①(+建议②IDB 持久化+权限恢复)；
- ② 预览收敛拍板确认（表滚动/原文件预览折叠/删最近导入卡/删预览整个班）；
- ③ 多列模型拍板：去掉班内最高分归一；**发现 PWA(带归一) 与引擎(原始分加权平均) 打分口径分叉**
  → 建议统一为引擎口径：原始分加权平均（单列=原始分）；请确认"加权平均 vs 纯等权"；
- ④ 黑名单拍板确认（序号/学号/工号/班级…+唯一整数列启发式）；固定四类也生成列集合；
- 新增待拍板 4 项见 docs/13-D55。

---

# 2026-09-30 · H1–H4 实施完成（D55 清账：直装/预览收敛/多列加权/黑名单/引擎一致性）

- ✅ H1 workspace 句柄修复（设置中心丢句柄根因）+ IDB 持久化/权限恢复 + KaTeX 四态直装 + 引擎 /install/katex；
- ✅ H2 预览收敛（名单表滚动/原文预览折叠/删最近导入卡/删预览整个班）；
- ✅ H3 多列模型 + 综合=原始分加权平均（去班内最高分归一，与引擎 merge_scores 同口径）+ 列权重输入 + 公式上屏；
- ✅ H4 非成绩列黑名单（序号/学号/班级…）+ task-package 按列展开 + PWA/引擎一致性回归用例；
- build 0 err；selfcheck 全绿；engine 测试新增（CI 复核）。

---

# 2026-09-30 · 重大仓库缺陷修复：engine/src/assist/roster/ 从未入库（D55 收尾发现）

- **根因**：`.gitignore` 的 `roster/` 规则本意拦截学生数据目录（classes/*/roster/），
  却同时命中了 `engine/src/assist/roster/` 源码目录 → 该包 4 个文件（__init__/grouping/rain/scores）
  **从未进入 git**；此前 CI 全绿只是因为既有测试不在模块级 import 它（CLI 内为延迟导入），
  而 H1–H4 新增的 `test_scores_parity.py` 顶层 import 触发 `ModuleNotFoundError: No module named 'assist.roster'`；
- **影响面**（此前被掩盖）：任何 fresh clone / 仓库快照 engine-main.zip / CI 安装的引擎，
  其 `assist roster tag`、scores 读取等基于 roster 包的功能都会缺模块而失败；
- **修复**：`.gitignore` 增 `!engine/src/assist/roster/`（与 grading 同款例外）；
  `tools/check-secrets.sh` 对 `engine/src/assist/roster/*` 放行（学生数据目录 classes/*/roster/ 仍拦截）；
  `git add engine/src/assist/roster/*.py`（4 文件入库）；校验：全部 engine/src *.py 已入库 + 脱敏通过；
- **CI 增强（保留）**：pytest 失败时上传完整日志 artifact + 关键行 error 注解（无 admin 亦可经 annotations API 排障）。

---

# 2026-09-30 · D56 任务单建立（第 20 轮审核；待 feishu4dsh 重启后执行）

- 用户诉求：名单预览/标签预览与全部成绩总览一致（折叠 + 滚轮 + 吸顶表头）；
- I 批（UI 收敛+P0）：三表滚动折叠统一 / status 反馈可见性（29 处写入仅失败可见）/ setPunish 误清 tag /
  清空全部确认 / 锚点条样式失效；
- J 批（一致性）：成绩源卡公式文案过期 / 大列数源勾选折叠 / 旧源降级提示 / 导出&amp;README 口径同步 /
  KaTeX 卡句柄状态回显+点击前 ping / 改名匹配提示 / punish 双入口 / 黑名单收紧 / title 文案；
- 状态 ⏸ 待执行；续作指引与验收清单见 docs/13-D56。基线 84fc2f3（CI 双绿，引擎 roster 入库修复已完成）。

---

# 2026-09-30 · D56 实施完成（I 批 UI 收敛+P0 / J 批一致性，共 15 项）

- ✅ I1 三表滚动/折叠/粘性表头统一；I2 顶部状态条（status 全量可见+失败红条）；I3 setPunish 不再误清 tag；
  I4 清空二次确认；I5 锚点样式全局化+吸顶；
- ✅ J1 成绩源文案=D55-H3 口径；J2 大列数源勾选折叠；J3 旧源重解析提示；J4 task-package README/note 同步；
  J5 KaTeX 卡句柄状态回显+决策前 ping；J6 改名匹配提示；J7 deleteClass 清 v1 键；J8 punish 单一入口（下拉隐藏）；
  J9 黑名单整词收紧；J10 title 文案；
- build 0 err；selfcheck 全绿；下一步：现场验收（清单见 docs/13-D56）。

---

# 2026-09-30 · D57 实施完成（整班预览/输出参考答案开关对齐）

- ✅ D57-1：班级与标签「整班作业纸预览」卡新增 ☑显示参考答案（默认不勾=学生版）、☑显示水印图层、☑显示页码大字；
  统一 `buildClassPreviewHtml()`，作用于 预览/打印整班/下载 HTML；开关变化实时重建已打开预览；状态标注学生版/教师版；
- ✅ D57-2：作业纸内容页「变体编排」卡新增 ☑内嵌 HTML 含参考答案（默认不勾）；variantBatch provider 接
  `setBatchHtmlIncludeSolution` → batch zip 的 sheets/*.html 按口径输出；
- ✅ D57-3：docs/14 增"三通道语义对照表"（模板/整班/zip/CLI html/CLI PDF/KaTeX local）；
  口径澄清：引擎 `assist sheet batch` 走 reportlab PDF，**天然不含答案**，无需 --no-solution；`sheet html --no-solution` 已有；
- ✅ D57-4：selfcheck 新增 F 组（答案关/开、水印图层关、页码关断言）→ ALL PASS；
- build 0 err；脱敏通过。

---

# 2026-10-07 · D58 实施（TinyTeX 设置中心专用栏 + 全 tab 返回顶部 + CLI 备份原则）
- ✅ **TinyTeX 可选依赖**：设置中心新增专用卡（检测/联网安装）；安装包不入仓库，下载
  `rstudio/tinytex-releases` 官方 daily 资产并解压到 `<workspace>/.runtime/tex`；
  引擎 `/doctor` 识别 workspace TinyTeX 并给 `fix.install=tinytex`；`/install/tinytex`
  服务端通道；CLI `assist tex status/install`。文档见 docs/05-D58。
- ✅ **全局返回顶部**：App.vue 全 8 个选项卡共用悬浮按钮（scroll > 360px 显示）。
- ✅ **D53-G2 补收口**：reportlab `layout.py` 竖版 per_page=4 从 2×2 cross 改为 rows4
  （三横虚线 25/50/75%），与 HTML/PWA 对齐；新增 `engine/tests/test_pdf_grid.py`。
- ✅ **CLI 备份原则**：D58 定稿——后续新增 PWA 功能必须同步提供/登记 CLI 等价命令，
  让 AI agent 可在 PWA 不可用时通过 CLI 完成设计/发布/批阅。
- 验证：engine pytest 18/18；`npm run build` 0 err；`selfcheck:roster-fig` ALL PASS。

---

# 2026-10-07 · D59 B2/B4 实施 + D60 网格布局讨论
- ✅ **B2 学号匹配回退**：引擎 adapter 透传 number、`merge_scores` 姓名→学号回退；
  PWA `ScoreSource.numberColumn/numbers`、`columnScoreOf` 回退、总览/重算传 `student.number`；
  selfcheck 增 B2 块。回归 engine 22/22。
- ✅ **B4 样式保留写回**：`write_chapters_preserving`（openpyxl 原位改值）；
  CLI `assist kb write --input <json> [--kind]`；serve `POST /kb/write` + CORS OPTIONS；
  PWA `saveKind` 引擎优先、FSA/下载降级；translation 例外表暂不走该通道。
- 💬 **D60 网格布局讨论**：用户提出 `rows×cols` 灵活选项（如 4×1、2×2）与
  行优先/列优先/均匀分布；结论可行，建议保留 `per_page` + 新增 `grid_mode/grid_rows/grid_cols`
  向后兼容，待拍板数据模型/均匀分布退化策略/UI 位置；本轮不改布局代码。

---

# 2026-10-07 · D61 实施收口（feishu4dsh 重启续作）

- ✅ rows×cols 显式网格上线（数据模型/解析内核/CSS Grid 渲染/虚线百分比内联/UI 双输入/三端 parity）；
- ✅ engine test_grid.py 新增 + test_sheet_html 更新 D61 口径（本地 26 passed）；PWA build/selfcheck 全绿；
- ✅ 修复：engine data-grid 去 `grid` 前缀与 PWA 统一；test_grid 断言按真实实现口径修正；
- D60 讨论条目标记已实施。
---

# 2026-10-07 · D61 收尾（文档口径同步 + 清单显示网格）
- ✅ HelpView/docs/04/docs/15/taskpad.ts/SheetLayoutView.vue 的旧「per_page 1–4/横竖十字」口径
  统一为 D61「N(1..12) + 显式 行×列」；
- ✅ 作业纸清单「版式」列显示实际 `行×列`；
- 验证：engine pytest 26/26；PWA build 0 err；selfcheck ALL PASS；lint/secrets 全绿。

---

# 2026-10-07 · D62 登记：化工24/环24 班"人数 0"现场反馈（docs 已记核查路径与请文件请求）

- 症状=班级名对、人数 0；代码链：新班=空初始 → 导入应写 students/persist；0 人分支不覆盖且顶部状态条提示；
- legacy 无 24 级名册文件 → 无法仅凭代码判定；候选=解析层形态漂移 / 导入进了另一班（多班级工作区混淆）；
- **待教师提供两份原始文件 + 操作序列**；对应修复=locateHeader 精校 / 导入绑定当前班级的 UI 强化。

---

# 2026-10-07 晚 · D62 收口：化工24/环24 "0 人"根因定案（extractor 导航缺陷，非解析/工作区问题）

- 三轮探针（.scratch/xxt_probe1/2/3 + xxt-session-check.json）收口：班级/作业/名单数据**全部在场**；
- 真因=只读提取流水线三缺陷叠加：①单 page 导航进 mark 后 li.classli 归零致后续班静默 False（主因）；
  ②wait_for_selector 默认 visible 断言撞上 display:none 收起侧栏（探针误判）；③名单唯一来源=第一个作业批阅页（无作业班结构性 0，且名单=提交者非花名册）；
- **D62 原登记候选（解析漂移/工作区混淆）两均不成立**——点名册文件不再为本次故障所需（但仍用于"名单解耦"路线）；
- 锚点：化工24≈67、环24≈43（通知已读分母）；批阅名单 59/40 vs 分母差 8/3=未交者；两班各 9 作业；
- 详情与次轮清单见 docs/13-taskboard.md D62 收口节；scratch 明细见 .scratch/xxt-readonly-confirm.md 附录；
- ⚠ 隐私：probe JSON/HTML 含真实学生姓名，仅存 .scratch/（gitignored），**不入库**。

# 2026-10-08 · D62 续：作答状态字段确认（零新增请求）+ PWA 列表交互需求入 docs/16 §15–§16

- 作业列表 li 自带 待批/已交/未交+作答时间（wid15 区块），probe3 读法同构即可提取，无需进批阅页；
- 现有存档已全量核实化工24 9 份作业统计；口径警报：参作 64~65/42 ≠ 通知分母 67/43 ≠ 点名册（待教师对差值语义）；
- PWA 需求（讨论稿）：登录仅扫码+体检显式分离；列表呈现基本信息；行置顶（头部/尾部浮钮，sticky 对齐 D56-I1）；列表滚动不撑页；
- 名单默认仅示数字（PII 最小化），点开见详情；未决：置顶持久化层级/上限/触屏热区。

# 2026-10-08 · T1–T4 落地（commits: T1 会话CLI / T2 master花名册 / T3 schema定稿 / T4 extract v2 实况）

- T1 `assist xxt check/login`：三信号判活+回写（.scratch 探针逻辑入 engine，playwright optional）；
- T2 25C1 master 花名册：化工24=66（2023级插班1）、环24=47（47/47 全交叉）；按值形态分类破解超星双错位表头；
- T3 extract v2 schema（docs/16 §19）：三分类 status（extracted/empty_confirmed/not_extracted）；
- T4 三类对照实况：22 份 work 名单数==已交数全等；未交名单按 master差集落名；环24 roster_delta=5 灰注（口径性）；
- 待办：**T5 教师审核**（审核 .scratch/xxt-20261008-113601-v2.json 摘要）→ 通过后 T6 放量 26 班 ∥ T7 PWA。

# 2026-10-08 · D63 批次二落地（T6-T9；docs/16 §21）
- T6 放量：30班/5课 全量提取（25 extracted + 5 empty_confirmed, 106 作业, failures=0）；已结课班/断崖后置班/容器班全部正确——容器班真伪定案=有真实作业（非空班）；
- T9：engine `run_extract` + CLI `assist xxt extract`（体检前置+ROSTER 差集+脱敏摘要）；
- T7/T8：serve xxt 端点组（status/qr/runs/run + login-start job）+ PWA XxetongView 实装（QR↔登录卡；课程分组滚动列表；置顶 10 可调/移出/从学习通恢复=回放最近 run 零网络）；
- 事故记录：CI 脱敏红线误触（已清洗回绿）+ serve patch 静默 no-op 两枚（冒烟抓出修复）；头像 selector 待办顺延（缺省「已登录」卡兜底）；
- 次步：T10 写操作维持冻结；剩 §22 待办三项。

# 2026-10-09 · D65 立项：浏览器获取/安装优先级 + 代码审核

- 用户重新明确：昨晚根因是旧 `engine/` 目录导致 start.bat 跳过在线更新；删除后恢复。随后 chromium 下载卡在 `chromium-headless-shell`。
- 目标链：本机浏览器优先 → 无则下载 → 多镜像源备用 → 网页直下包并注明安装位置、由 PWA 启动安装。
- 事实核查（R0 复验）：当前只读抽查 Playwright 1.57 默认 `install chromium` 涉及 headless shell；`--no-shell` 可跳过；默认 `headless=True` 未显式 channel/executable_path 时可能选 headless shell。
- 前置：D65-R0 代码审核；当前工作区已有未提交改动引用不存在的 “D64 §26 A1/A2/A3”，待审，不得视为完成。
- 主需求：`docs/16-xuexitong-integration.md §27`；任务板索引：`docs/13-taskboard.md D65`。
- R0 结果（2026-10-09，只读）：不通过原样合入；确认幻觉编号、华为云伪源、`--no-shell`/去重缺失、start.bat 旧 `engine/` 遮蔽；详细见 docs/16 §27.8。
- P0/P1 核心（2026-10-09）：start.bat 加 `ASSIST_ENGINE_LOCAL` 显式开关；浏览器优先级 + probe 验证；installer 改 `--no-shell`、去重、真实镜像、zip 校验；`/pw/pkgs` 前置数据就绪；PWA 直下 UI 仍待 P2。验证：46 tests + lint_bat + secrets 通过。
- P2 备用方案（2026-10-09）：PWA 设置中心已接 `/pw/pkgs`，展示直下链接/收包路径/目标目录，并可触发“从收包目录安装”。验证：`npm run build` + `selfcheck:roster-fig` 通过。P3 教师引导已落地（HelpView + docs/15）。
- start.bat 更新策略补充（2026-10-09）：远端 `engine-version.json` vs 本地 `_engine\engine-version.json` 先对比，相同复用、不同才下载；版本检测失败回退本地；更新后启动新引擎进程生效。CI 随 Pages 发布版本标记。
- 决议修订（2026-10-09 用户拍板）：更新检测/更新引擎主入口改到 PWA「检测更新 / 更新引擎」按钮（D65-P4）；start.bat 保留快速缓存启动。start.bat 启动时版本对比视为过渡实现，P4 落地时简化/可选化。P4 已实施：/engine/version + /install/engine_update + PWA 更新卡 + CLI engine version/update；更新后自动 restart 轮询。验证：52 tests、npm build、selfcheck 通过；远端版本标记待 CI 首次发布。
- ✅ P1.5（2026-10-18，见 docs/13「CLI 与 serve 边界澄清 + 并发写安全」）：
  `kb export/snapshot`、`sheet demo/make` 的 `-w` 静默失效已修；`kb export --fmt` 假参数已修；
  新增 `assist/filelock.py`，草稿/答案版本/发布索引/作业包改为加锁 + 原子写（并发不丢更新）。
- ✅ P2 · CLI 面向 AI/脚本的健壮性（2026-10-18，见 docs/13「P2 · CLI 面向 AI/脚本的健壮性收尾」）：
  - `ASSIST_JSON_ERRORS=1` → 异常统一为结构化 JSON（stderr 一行，稳定退出码）；
  - `assist engine status [--json]` + `engine update --json` + journal；
  - `playground batch --combine`（附件只发一遍，省 token）；
  - `pack save` 校验 id 一致；`kb export/snapshot/stats` 补 CLI 测试。
- P3 · 剩余：`engine restart`（非 launcher 场景）；`notice-send`/`work-publish --json-out`；
  README 补 JSON 错误约定；`kb ai-solve` 并发。

# 2026-10-18 · D98：LLM 两段式批量隔离 / 执行报告 / skill（已定稿执行）
- 主需求单 `docs/51-D98-llm-batch-isolation-skill.md` §7 决策定稿 / §8 执行顺序。
- **B1–B9 执行清单**：items 契约 → doctor 能力探测 → type=command provider → 转录 batch →
  批阅严谨性(json_schema/evidence/confidence) → **API key 全链路(含 batch 回灌)** →
  plan/collect 兜底 → skills 五份 → 文档。
- 合并执行：`engine restart`、`notice-send/work-publish --json-out`、`kb ai-solve` 并发、
  Playground batch items、token usage 记录。
- 隔离原理：程序层"每任务独立请求"= 结构性隔离；subagent 为 agent 侧编排。
- **执行进度（2026-10-18）**：B1 items ✅ / B2 doctor ✅ / B3 type=command ✅ / B4 转录 batch ✅ /
  B5 批阅严谨性 ✅ / B6 batch 回灌 ✅（`llm batch --apply`）/ B7 plan-collect ✅ / B8 skills ✅；
  B9 文档收尾中。engine pytest 457 passed。
- **待真机验证**：Aliyun batch submit/poll/download（本机无网）；command provider 接真实 agent CLI；
  subagent 路径需具体 agent 框架。
- ✅ 收尾（2026-10-18）：`kb ai-solve` 并发（`--concurrency`）、`notice-send`/`work-publish --json-out`、
  `work-publish` 发布后回读摘要、**token usage 度量**（LLMClient.usage + run summary + grade 打印）。
  全量 pytest 461 passed。
- 剩余（P4）：Aliyun batch 真机验证；`type=command` 接真实 agent CLI 的 adapter；subagent 路径真机；
  基于 usage 度量的省 token 优化（同 tag 合并评阅、图片压缩、prompt caching）——待讨论。

# 2026-10-18 · CLI 盘点后的遗留（题库/通知/作业；P0 已完成）

- ✅ P0（已做，见 docs/13「P0 · 题库/通知/作业 CLI 一致性清理」）：删通知硬编码白名单；
  修 `kb stats` 提示；`notice-send --target` 透传 className；`kb write` 校验章节名。
- ✅ P1 · 补齐 CLI 超集（已完成 2026-10-18，见 docs/13「P1 · 补齐 assist xxt 配置类 CLI」）：
  - `assist xxt allowlist list/add/rm`（对应 serve `/xxt/write-allowlist`）；
  - `assist xxt attachment-exts get/set`（对应 `xxt.notice_attachment_exts`）；
  - `assist xxt work-rename`（封装 `work.py:rename_work`，并补 workspace 透传）；
  - `assist xxt work-folder-default show/set`（对应 `allowlist.set_work_folder_default`）；
  - 归属拍板：统一挂 `assist xxt`（不新开 `assist config`）；测试 `test_p1_xxt_config_cli.py` 6 例。
- P1 · 输出/脚本体面：`notice-send`、`work-publish` 加 `--json-out`（`requests/responses` 过大易刷屏）；
  `work-publish` 加发布后回读摘要（对齐 `create_work.directoryCheck`）。
- P2 · 题库：`kb export/snapshot/stats` 补 CLI 级测试；`kb write` 对 `*-example.xlsx` 与
  主文件的双通道策略定版（当前 CLI 只写 `<kind>.xlsx`，不碰 example；`snapshot` 按 stem 精确匹配会漏 example）；
  `kb ai-solve` 串行调用改并发/批量。
- P2 · 注释：`notice.py` 的 `ATTACH_SUFFIXES` 仅兼容保留，后续确认无引用后可删；
  `serve.py` 与 CLI 的配置类端点建议补一份「配置项 ↔ 命令/端点」对照表。

- ✅ Playground batch `--items`（每条自带图+问题）已完成；✅ qwen 系 skill 适配（`skills/providers-qwen.md` + adapter）。
- ✅ D98 第四批（2026-10-18）：doctor 转录/图片风险检查项（`transcription_command_no_images`）；
  QwenWork / WorkBuddy / qwen CLI 官网调研；原生 skill 包（QwenWork `SKILL.md`、WorkBuddy `skill.yml`）。
- 平台结论：QwenWork/WorkBuddy 为 GUI agent、无 CLI/API，**不能**作为 `type=command` 后端；
  只能作为宿主装载我们的 skill 调 `assist`。
- ✅ D98 第五批（2026-10-18）：`tools/skill_installer.py`（list/check/install/verify，`--json`）；
  QwenWork/WorkBuddy skill 安装与校验自动化；6 测试；全量 475 passed。
- 仍待真机：QwenWork/WorkBuddy 中实际触发 skill；qwen CLI 读图能力确认。

- ✅ D98 第六批（2026-10-18）：自检/回执机制——`assist doctor --report [--json]` 分层诊断
  （environment/config/capability/data/artifact，含 code+fix）；`skill_installer check` 同口径；
  WorkBuddy `run.py` 失败写 receipt；QwenWork SKILL 加自检步骤。9 测试；全量 484 passed。

---

## D126-B 教师总结报告（易错知识点汇总 + 共现/得分率图）— ✅ 已实施（2026-10-30）

> 需求单：`docs/80-D126B-teacher-report.md`。
> 来源：2026-10-29 用户提出，明确"先记着，不用着急做"。
> 现状：引擎侧已完成（分析 + MD + stats JSON + CLI + 批阅流程集成）；**PWA 可视化图未做**（数据已备好）。

- 面向**教师**的总结报告（区别于 D126 已实现的"转写 + 批阅"学生报告）；
- 内容：**全部作业的易错知识点**汇总，并指出**易错点之间的关联**；
- 计划与另一教学工具项目的「**知识点共现矩阵 + 得分率图**」结合展示；
- 数据源：`<ws>/<class_dir>/grading/<task>/evaluations/<学生>.json`
  的 `questions[].errors[]`（`knowledge` / `description` / `evidence` / `confidence`）
  + `per_question_scores`；
- 产出形式：汇总 MD/HTML/PNG（教师版），不与学生报告混在一起。

---

## D109–D126 对账（2026-10-30 核对）

> 说明：`docs/13-taskboard.md` 的活动记录停在 D108，D109 起均只有独立需求单
> （`docs/6x`–`docs/7x`）与提交记录。本段仅记录**当前仍未完成**的项，避免重复登记。

- ✅ D126 同批补漏（2026-10-30）：部分失败中止时转写丢失 + 草稿 key 退化 + PWA `allowPartial` 无入口；
  详见 `docs/75` §6。engine **726 passed** / build 0 err / selfcheck 34 全绿。
- ⏳ **产物版本号过期**：`report.build_report_md` 页脚、`evaluate.py`/`transcribe.py` 的
  `version` 仍为 `assist-engine 0.1.0`（实际 `0.4.0`）。属历史元数据，需先定"产物版本是否参与
  比对/迁移"再改，暂不动。
- ✅ **D126-B 教师总结报告**：引擎侧已完成，见 `docs/80`（PWA 画图未做）。

---

## D130 · 按题目来源分型的评阅规则 + 知识点体系（2026-10-30 需求定稿）

> 需求单：`docs/78-D130-source-aware-grading-rules.md`。分 P1/P2/P3 三阶段，P1 独立可交付。

- 现状问题：评阅规则硬编码、教师看不到；非计算题无差异标准；报告无预览入口。
- 已核实：题目来源（`kb` kind）**数据已具备但未透传**；题库 `related` 列已存在；AI 作答可置顶生效。
- P1：来源透传 → `grading-rules.json` 三层规则 → 分型 prompt/计分 → AI 生成评阅要点（不自动置顶）
  → 知识点标注（四种粒度）+ 术语归一（教师勾选确认）→ 受控词表 → 评阅规则卡 → 报告预览。
- P2：课堂资料（PDF/图片/PPT）→ 知识点提取 → `summary` 批阅联动。
- P3：**Assistopia**（assist+utopia）：AI 调用本项目工具的可视化工作区，分级白名单 + 审计 +
  `<ws>/extensions/` 用户扩展隔离（升级不覆盖用户改动）。
- 与 D126-B（教师总结报告）的关系：知识点标注 + `evaluations[].knowledge[]` 即其数据基础。

---

## D131 · 课堂资料 → 知识点清单 → summary 批阅联动（P2，2026-10-30 完成）

> 需求单：`docs/79-D131-materials-and-summary-grading.md`（原 docs/78 P2 的 T12/T13/T14，已顺延为 T19/T20/T21）。

- **目录定稿**：`<ws>/materials/<chap>/{_source,_extract,索引.json,知识点清单.md,知识点清单.ai.json}`
  —— 与 `kb/`、`classes/` 平级，**不放 kb/ 下**（D120 语义边界），跨班共享。
- 抽取：`officecli`（pptx/docx/xlsx，主）/ `pdftotext`+`pdftoppm`（pdf）/ 图片多模态 / md-txt；
  sha256 增量。
- 知识点：`materials suggest`（AI 建议，**不自动生效**）→ `materials confirm`（教师确认，AI 不覆盖）
  → `summary` 批阅时进 prompt，产出 `knowledge_missing[]` 且启发式提问指向遗漏知识点。
- ✅ 图片/扫描型 PDF 已接入**多模态**（文本 <200 字且有页图 → 看图；超限提示不静默），
  详见 docs/79 §10.5。
- **未做**：PWA 资料页（确认动作刻意留在 CLI，避免 AI 直接改生效清单）。

---

## D132 · Assistopia（AI 调用本项目工具的安全工作区，P3，2026-10-30 起）

> 需求单：`docs/81-D132-assistopia.md`。

- ✅ **P3-1 已完成**：工具白名单（27 个）+ L0/L1/L2/L3 分级 + 参数白名单 +
  `extensions/` 只升不降 + 子进程执行器（超时/截断/journal）+ 护栏硬顶。
  `assist assistopia tools|run|journal`。
- ✅ **P3-2 已完成**：扩展覆盖（rules/ + knowledge-terms.json，深合并且算法名只读）、
  `limits` 写接口（超硬顶拒绝）、升级不触碰 extensions 的快照比对。
- ✅ **T16 已完成**：`assist assistopia ask` JSON 指令会话，与 CLI 共用同一 Gate
  （L3 拒绝 / L2 二次确认 / 护栏），非 JSON 回复不猜意图。
- ✅ **PWA Assistopia 工作区已完成**：工具分组 / L2 二次确认 / 审计日志；
  真实浏览器回归验证「确认前未执行」。P3 全部完成。

---

## D134 · Atopia 专用工作区 + summary 双轨评阅（2026-10-31 完成）

> 需求单：`docs/83-D134-atopia-workspace-and-summary-grading.md`。

- ✅ **T1 重命名**：`assistopia` → `atopia`（包/CLI/HTTP/前端）。旧名保留兼容：
  `assist assistopia ...` 经 argv 别名、`/assistopia/*` 经前缀转发。
- ✅ **T2 `atopia/` 工作区**：`limits.json`、`journal.jsonl`、`extensions/` 收拢到
  `<ws>/atopia/`；旧位置**幂等迁移**（冲突时新目录优先、旧的留 `.bak-<ts>`）。
  **硬性质**：删掉 `<ws>/atopia/` 后引擎/评阅照常、护栏回默认、扩展不生效，
  且 `materials/` 与 `grading-rules.json` 不受影响（测试锁定）。
  新增 `assist atopia migrate|reset`（reset 属 L3，不给 AI）。
- ✅ **T3 上传与文件管理**：PWA 可上传到 `materials/<chap>/_source/`
  （扩展名白名单 / 20MB / **同名不覆盖**）；`materials.files`(L0)、
  `materials.remove`(L2，**只移入 `_source/_trash/` 不真删**)。
- ✅ **T4 summary 保底口径**：无课堂资料时按「知识点总结 / 公式推导 / 示意图 / 长度」
  四维判定，**缺项不扣分**，只扣「过简」；`summary_basis="heuristic"` 降级可见。
- ✅ **T5 summary 资料口径**：仅在**本章有已确认 `知识点清单.md`** 时生成要点；
  有资料时优先且不叠加保底口径。
- 顺带修复：`rules.read_rules` 首次落盘跳过扩展覆盖；`build_result_from_analysis`
  缺 `feedback_md`/summary 元数据；`registry._SAFE_STR` 正则双反斜杠导致
  **所有 str 参数被误拒**。
- **未做**：回收站恢复入口（`materials restore`）；`.zip` 上传（刻意不收）。

---

## D135 · 跨多次作业的知识点趋势（2026-10-31 完成）

> 需求单：`docs/84-D135-knowledge-trend.md`（落实 docs/80 §8 的"跨多次作业趋势"）。

- ✅ 作业序列 = 同一 `class_dir` 下**按评阅时间升序**的作业包；
  同一知识点在 ≥2 次作业出现 → **反复出错**，并判定**改善 / 仍在持续**。
- ✅ `assist trend --class-dir ...`、`GET /grade/trend`、PWA `TrendCard.vue`。
- 口径：只用 `errors[].knowledge[]`（排除低置信度）；用**出错率**判定改善
  （班额可能变化）；不做按章节串（缺可靠映射）。
- **未做**：跨班级对比；知识点同义词需先 `kb check-knowledge` 归一。

---

## D136 · opencode-go 会话头 + provider 级自定义请求头（2026-10-31 完成）

> 需求单：`docs/86-D136-opencode-go-session-header.md`。

- 现象：`/inference/go/openai/v1` 报 `MissingSessionID`。**根因是服务端对 go 路由
  新增要求**（curl 实测：旧 `/zen/go/v1` 同样报错），不是改 URL 改坏的。
- 官方要求：客户端**用自己的 UA** + 每个**对话**带稳定的 `x-opencode-session`。
- ✅ provider 支持 `headers` / `user_agent`（**白名单**：只 `x-*` 与 `user-agent`，
  禁止 `Authorization`/`Host` 等，防配置即提权）。
- ✅ `LLMClient`：`{session}` 占位替换；缺 session 报 `LLMConfigError` 且不发请求；
  默认 UA `assignment-assistant/<版本>`。
- ✅ 会话粒度：Playground/Atopia 一会话一 id；批阅按作业切分。
- ✅ 修复 `provider=-`（报错定位字段取错）与语义化错误提示。
- **明确不做**：自动给 opencode 补默认 session（显式配置、缺失即报错）。

---

## D137 · PWA ↔ CLI 能力对齐（2026-10-31 完成）

> 需求单：`docs/87-D137-pwa-cli-parity.md`。

核对结论：日常动线（题库/AI 作答/LLM 配置/学习通全链路/规则卡/教师报告/趋势/
作业包/水印/备份/资料上传与回收站）**基本已对齐**；补了三个真缺口：

- ✅ **A1**：provider `headers` / `user_agent` PWA 可编辑（折叠块 + 二次确认显示实际内容；
  白名单仍由引擎强校验）。
- ✅ **B1**：Atopia 护栏 PWA 可改（二次确认 + 显示硬顶；超限由引擎拒绝）。
- ✅ **A2**：资料页「① 抽取 / ② AI 建议 / ③ 确认生效」。
  「确认生效」保持 D131 原意：**弹窗展示清单全文**（与写入同一渲染函数）+
  必须教师显式确认 + 默认不覆盖 + journal 记 `confirmed_by`。
- **明确不做**：`atopia reset` / `migrate-grading-dir --apply` /
  `workspace clean-migrated --apply` / `engine update`（L3 类，不给 PWA 一键入口）。

---

## D138 · 知识点两层分类（章 → 主题 → 术语）（2026-10-31 完成）

> 需求单：`docs/88-D138-knowledge-topic-layer.md`（docs/85 方案 B 被采纳）。

- ✅ 词表新增 `topic`（**不做** parent/child）：`kb vocab add --topic`、
  `kb vocab set-topic`；工具 `kb.vocab.set-topic`（L2）。
- ✅ `materials suggest` 产出 `topic`；`知识点清单.md` 按主题分节，
  无 topic 归「其他」（不丢）；整份无 topic 时保持旧格式。
- ✅ `knowledge_terms()` 兼容新旧格式；`## 逻辑关系` 段的 `A → B` 不再误当术语。
- ✅ 教师报告 / 趋势报告按主题分组（无主题时**行为与之前完全一致**）。
- ✅ PWA：资料页与教师报告卡均按主题分组展示。

---

## D140 · Atopia 独立选项卡 + 对话模式（2026-10-31 完成）

> 需求单：`docs/89-D140-atopia-chat-tab.md`。

分工定稿：**Playground = 单次调用测模型（不给工具）**；
**Atopia = 唯一能调工具的入口（多轮对话 + L2 确认 + 审计 + 护栏）**。

- ✅ Atopia 独立为顶层选项卡，含「💬 对话 / 🧰 单一工具执行」两个页签；
  原 `AiGradingPanel` 底部内嵌面板移除（无双入口）。
- ✅ `POST /atopia/ask`：多轮 + 工具，全部经 `run_tool()` 同一 Gate；
  原生 tools 优先、不支持时自动降级 JSON 指令协议。
- ✅ L2 确认用「拒绝 + 返回 pendingConfirm + 前端弹窗 + 带 confirmed=true 重发」，
  避免在 HTTP 线程里阻塞等待。
- ✅ 会话历史落 `<ws>/atopia/sessions/*.jsonl`（可整体删除），可回看。
- ✅ Playground 加了分工说明。
- 已知限制：无流式输出；L2 确认粒度为"本次请求全部确认"。

---

## D143 · 翻译题库题号重复修复（2026-10-31 完成）

> 需求单：`docs/90-D143-translation-question-id.md`。

- 现象：告警 `translation@translation/translation/…（×16）`。
- 根因：`read_translation()` 给**每行**都写 `id="translation"`；
  答案版本库以 qid 为键 → 多道翻译题答案写进同一文件**互相覆盖**。
- ✅ 改为按行序生成 `translation-01…`（与其它题库命名一致、重读稳定、空行不留空洞）。
- **不改** `paper/task.py` 的"每题纸 1 道翻译题"（D93 刻意的旧语义）。
- ⚠️ 历史残留的 `translation` 单文件无法自动还原到具体题号，建议重新作答一次。

---

## D144 · 删除规则卡里的「生成 AI 评阅要点」开关（2026-10-31 完成）

> 需求单：`docs/91-D144-remove-rubric-toggle.md`。

- 教师指出该开关位置错误：挂在评阅规则卡里，但**批阅根本不读它**，
  且与「AI 作答时同时生成要点」是两套规则，极易误解。
- ✅ 删除 `types.*.generateRubric` 字段与前端复选框；规则卡只管"怎么扣分"。
- ✅ 改为**代码口径**：copy 永不自动生成（需 `--force`）、summary 看本章是否
  有已确认清单、其它允许。
- ✅ 旧配置残留该字段**不报错、不再生效**；**批阅计分不受影响**（有测试锁定）。
- 教师侧唯一入口：**⑦ 题库 AI 作答 → 同时生成评阅要点**。

---

## D145 · provider 请求头 UI 重做（2026-10-31 完成）

> 需求单：`docs/92-D145-provider-header-ux.md`。

教师反馈"没成功配置请求头、操作不符合习惯"。核查四条全部成立：

- ✅ **顺序**：高级块移到「保存 provider」**上方**（并修了它被误插进 flex 行导致塌成 1px 的布局缺陷）
- ✅ **勾选式会话头**：`☑ 需要会话头` + 头名输入；`{session}` 由前端代填，**界面不再出现占位符**
- ✅ **留空语义写明**：其他自定义头留空=不发任何头；user-agent 留空=用默认值（并显示默认值）
- ✅ **保存反馈**：显示"请求头 N 项"与"已分配到 X 段 / ⚠️ 未分配→现在不会生效"
- ✅ 编辑回填：含 `{session}` 的头拆成勾选状态，其余留在文本框

---

## D146 · Atopia 可选 provider / 模型（2026-10-31 完成）

> 需求单：`docs/93-D146-atopia-provider-model.md`。

- 此前 `/atopia/ask` 只接 `model`，provider 固定取「评阅段」→ 换不了、headers 也未必生效。
- ✅ 新增 `build_client_for()` 公共构造函数，**Playground 与 Atopia 共用**（防口径漂移）。
- ✅ `/atopia/ask` 接 `provider`；Atopia 对话页加 provider/模型选择器（记忆在 localStorage）。
- ✅ 切换 provider 自动新建会话并提示（避免上下文/缓存错位）。
- 不选 provider → 行为与改动前**完全一致**（向后兼容，有测试锁定）。

---

## D149 · AI 批阅成绩作为成绩源（2026-10-31 完成）

> 需求单：`docs/96-D149-grading-as-score-source.md`。

教师：批阅好了就不必再去学习通下载成绩，应能像勾选表格成绩一样勾选批阅成绩。

- ✅ 引擎 `roster/grading_scores.py`：每作业包一列，取 `total_score`；
  **未批阅/未提交记 0 分**（带 `graded/submitted` 标记可区分）。
- ✅ serve `/roster/grading-packs`、`/roster/grading-scores`。
- ✅ PWA 成绩源新增「＋加入 AI 批阅成绩」，该列只读但可勾选/调权重。
- ✅ 与 Excel 成绩源**完全同一套加权聚合**（`merge_scores`），可混算总成绩。

---

## D150 · 规划记录：Atopia 工作区 + 拷贝到课堂资料（未实施）

> `docs/97-D150-plan-atopia-workspace.md`（教师要求先记录）。

- 三层目录：`materials/<chap>/_source/`（AI 只读）/ `atopia/work/<chap>/{_upload,_parsed}`（AI 可写）；
- 「📥 复制到课堂资料」按钮与 `materials.confirm` 同口径（显式点击 + 全文 + journal）；
- JSON + MD 双写；复用 D138 两层分类；
- 待定口径：上传入口位置 / 产物与清单的关系 / 长文档分片 / AI 题库数据结构。

---

## D156–D160 · 批阅正确性与质量（2026-10-31 完成）

> 需求单：`docs/103-D156-D160-grading-quality.md`。

教师报三个现象：逐生批阅落错人、两次结果完全一样、批阅太简略。根因与修复：

- ✅ **D156 落错人**：`--students` 只过滤转写、评阅仍扫整个 transcripts 目录
  → 评阅也按名单过滤；前端去掉多余 `tags`（`students` 已精确到人）。
- ✅ **D157 结果不变**：未强制时**跳过已有**转写/评阅（省额度但表现为"没变"）
  → 新增 `--force-rerun`，逐生补批固定 `force: true`；行内标注历史时间。
- ✅ **D158 批阅太简略**：`ANALYSIS_PROMPT` 是旧项目简化版
  → 重写为评阅规范（evidence 逐字引用 / why 写物理依据 / 必须给 correct_points /
  苏格拉底式追问 / 按题型给视角 / 输出前自查）；`max_tokens` 提到 12288。
- ✅ **D159**：新增"评阅信息量不足"检测，报告标注建议复核。
- ✅ **D160**：转写加 `response_format` schema（此前只有评阅有）+ 结构校验 + 三档降级。

---

## D161 · 翻译题随机种子（2026-10-31 完成）

> 需求单：`docs/104-D161-translation-seed.md`。

- 问题：新建作业纸时**从不写 `random_seed`** → 永远取 0 → 每次抽到同一道翻译题；
  CLI 也没有 `--seed`。
- ✅ PWA `emptyTaskpad()` 写入时间戳种子；作业纸设计页加「🎲 换一题」。
- ✅ CLI `paper.task.ensure_random_seed()` + `sheet make --seed N | --reseed`。
- 口径：**只在"新建/重抽"时随机，一旦记下就固定**（同份作业纸重出仍是同一题）。

---

## D152/D153 完成（同日）

- ✅ **D152**：⑦ 区抽成 `KbAiSolvePanel.vue` 整体搬入「题库AI+」；
  新增「同时标注知识点到题库」（`--tag-knowledge` → `apply_related`）；批阅页留指引。
- ✅ **D153**：教师报告支持**班级/作业包/tag 多选**（`collect_multi` + 名单 join tag）；
  报告卡与趋势卡搬入题库AI+，批阅页留指引。

---

## D162 · 一批问题修复（2026-10-31 完成）

> 需求单：`docs/105-D162-batch-fixes.md`。

教师一次性反馈 9 条，核实后 4 条是**真实缺陷**：

- ✅ **LaTeX 裸换行**：模型把真实换行写进 JSON 字符串 → 解析失败。修 `parse_llm_json`
  （先修 LaTeX 反斜杠、再转义裸控制字符）。
- ✅ **标注后题库编辑器看不到**：编辑器用浏览器内存副本，引擎写 xlsx 后不重读
  → 新增 `GET /kb/full` + 「🔄 从引擎重载题库」。
- ✅ **章节下拉为空**：`fetchKbCatalog` 失败时静默返回空 → 改为显示错误 + 重试。
- ✅ **种子往返丢失**：`parse/serializeTaskpad` 都没处理 `random_seed`
  → 保存后载入种子丢失（翻译题回到同一道）。已修 + 同毫秒递增。
- ✅ **作业包计数不减**：删作业纸只删清单、没清包内引用 → `removeFromLibrary` 同步清理。
- 已确认**不是** bug：translation tag 是确定性等距选点（不会重新随机）；
  逐生补批固定 `force:true`（会覆盖，是刻意）；translation 题号换行来自 content 本身。

---

## D163 · 课堂资料页可用性 + 翻译题题号不换行（2026-10-31 完成）

> 需求单：`docs/106-D163-materials-page-and-translation-line.md`。

- ✅ **课堂资料页为空**（三个原因）：① 没有「新建特征名」入口（`list_chaps` 只认有
  `_source/` 的目录）+ ② 上传键只在选中章节后出现 + ③ 手建目录缺 `_source/` 不列出。
  新增 `POST /materials/create` + 「＋ 新建资料文件夹」+ 三步空态引导。
- ✅ **translation 题号另起一行**：`read_translation` 的 content 以 `\n` 开头
  → 改为同行（引擎 `kb_io` 与 PWA `kbXlsx` 同口径）。

---

## D164 · Atopia 工作区 + 课堂资料「从 Atopia 复制」+ 标注章节联动（2026-10-31 完成）

> 需求单：`docs/107-D164-atopia-work-and-materials-upload.md`。

- ✅ **标注区不能选章节**：`loadChaps` 读错字段（`r.catalog` vs 实际 `kinds`）
  → 章节列表永远为空。改读 `kinds` + 章节跟随题型联动。
- ✅ **Atopia 工作区**：`<ws>/atopia/work/<特征名>/{_upload,_parsed}`，
  与 `materials/_source` **物理隔离**；Atopia 页新增「📁 工作区」上传页签。
- ✅ **「📥 从 Atopia 复制」**：必须预览全文 + 教师显式确认（缺 confirm → 403），
  写入 `materials/<特征名>/知识点清单.json+.md`，可进 summary 批阅。

---

## D168 · T13 整班输出追溯 sidecar（2026-11-05 完成）

> 需求单：`docs/112-D168` §4.8

教师习惯：「预览整班作业纸后打印 PDF 保存，信息会丢」→ PDF 零元数据，事后无法追溯。

- ✅ `app/src/lib/sheetSidecar.ts`（纯函数）：记录 包/作业纸/学生tag/开关/未绑定tag
- ✅ 落点是**整班预览**的真实路径（打印整班 → 先出 sidecar 再打印；下载 HTML → 同批出 JSON）
  > 排查发现 `SheetOutputSection` 的「打印级 PDF」是**禁用占位按钮**，不是真实路径
- ✅ `padId` 由 tag→作业纸绑定推出；`unboundTags` 显式列出（事后看得出谁当时没作业纸）
- 验收：pytest 1466 · build 0 error · selfcheck **38/38**（+1 纯函数自检 9 断言）· 脱敏通过
- 剩余：T14 共现图节点交互（待做）

---

## D168/D169 · B6 工具治理 + 权限收紧（2026-11-05 完成）——本轮规划收口

> 需求单：`docs/113-D169` §6.4

教师关切：「工具越来越多，可能导致使用出错，要写好注释/说明」+「AI 可写 atopia 外有误删风险」。

- ✅ **权限收紧**：`kb.write` / `kb.tag-knowledge.apply` / `kb.check-knowledge.apply`
  → **L3 拒绝**（AI 不得直接写题库）；L3 从 5 增至 8（是收紧不是放松）
- ✅ 新增安全替代 `atopia.suggest-kb`（L2）：只写 `atopia/work/<特征名>/suggest-kb.json`
- ✅ **工具分组**：8 组（kb/materials/rules/grading/fs/prompt/atopia/misc），
  `tools_by_group()` 把选择空间从 35 降到个位数；`GET /atopia/tool-groups`
- ✅ **工具说明升级**：`Tool.when`（给 AI 的"何时用/何时不用"）与 `summary`（给教师）分离；
  35 个工具全部补齐；`_tool_list_text` 改用 `when`
- ✅ **CLI Examples**：`kb` / `materials` 两组补 `Examples:` 段
  （踩坑：`@cli.group(help=...)` 会覆盖 docstring，必须去掉 `help=`）
- 🐞 又踩一次"只读接口放 `do_POST`"（`/atopia/tool-groups` → 302 到 Pages）；
  已修 + 加逐路由回归测试
- 验收：pytest **1466**（+15）· build 0 error · selfcheck **37/37** · 脱敏/lint_bat 通过
- **至此 D168/D169 六批全部完成**（B1 快照 → B2 统计 → B3 可视化 → B4 一键解析 → B5 例题库 → B6 治理）
- 剩余小项：T13 打印 PDF sidecar、T14 共现图节点交互

---

## D168 · B5 例题库 + 标准共现图（2026-11-05 完成）

> 需求单：`docs/112-D168` §4.7

- ✅ `example` kind（**分析专用**：不布置/不批阅；`rules.ANALYSIS_ONLY_KINDS`）
  > 陷阱：`normalize_kind()` 未知会回落 `problems`，所以刻意不放进 `SUPPORTED_KINDS`
- ✅ `grading/kb_examples.py`：解析产物 → 题库条目（跳过无题干、字符串 knowledge 拆词）
  → 写 `kb/example.xlsx`（追加续号/整章替换 + **写前快照**）
- ✅ `examples_as_records()`：转成共现算法认识的记录形状（标 `source="example"`）
- ✅ 接口：`POST /kb/examples/import`（缺 confirm→403）、`GET /kb/examples`、
  `GET /analysis/standard-cooccurrence`（例题不足→404 + 可读指引）
- ✅ 前端：Atopia「📚 导入例题库」+ KnowledgeView「⑤-A 标准共现图」
  （与 ⑤-B 作答共现图**并列**，文案区分「授课结构」vs「学生错误」）
- 验收：pytest **1451**（+14）· build 0 error · selfcheck **37/37** · 脱敏通过
- 下一步：B6 工具治理 + 权限收紧

---

## D168 · B4 Atopia 一键解析 + 任务模板（2026-11-05 完成）

> 需求单：`docs/113-D169` §6.3

- ✅ `atopia-task` 第 7 类模板（复用 D151 CRUD）+ 新字段 `outputSchema`/`inputKinds`
- ✅ 内置三任务：`knowledge-outline`（默认）/ `chapter-tag` / `example-extract`
- ✅ 工步 0 `extract_uploads()`：md/txt/Office/PDF/图片，**确定性免费**，逐文件报错
- ✅ 工步 1 `parse_with_task()`：选模板 → AI 结构化；有页图走 vision；产物只落 `_parsed/`
- ✅ 接口 `POST /atopia/work/extract`、`POST /atopia/work/parse`
- ✅ Atopia 工作区「🚀 一键解析」：① 抽取（免费）/ ② AI 解析（二次确认会花钱）
- 🐞 **修一个一直坏着的接口**：`/prompts/templates` 是只读却写在 `do_POST`，
  前端 GET → 302 到 Pages → **模板下拉永远空且不报错**（D151 遗留）。已移入 `do_GET` + 回归测试
- 安全：有测试断言解析产物**绝不写 `materials/`**（D131 硬规则）
- 验收：pytest **1437**（+22）· build 0 error · selfcheck **37/37**（+1 浏览器回归）· 脱敏/lint_bat 通过
- 下一步：B5 `example` 题库 + 标准共现图

---

## D168 · B3 可视化 + 版本 0.5.0 + README 更新（2026-11-05 完成）

> 需求单：`docs/112-D168-metrics-and-snapshot.md` §4.6、`docs/113-D169` §4.4

- ✅ `grading/viz.py`：移植 2508 组合份额/关联势/社区划分（**去 pandas**）+ 两张图
- ✅ **依赖改 optional extra `[viz]`**（matplotlib/networkx/numpy），不拖慢主安装
  > 我上轮"matplotlib 会撑大引擎"的判断是错的，已在需求单留档更正
- ✅ 依赖缺失 → `VizUnavailable` **可读中文**，不是 ImportError 堆栈
- ✅ 接口 `/analysis/chart`（出图）+ `/analysis/chart/file`（读 PNG）；缺依赖 501 + hint
- ✅ 体检项 `viz`（green/yellow + 一键修复）；`start.sh`/`start.bat` 安装失败改 **WARN 并说明后果**
- ✅ 前端「🖼 生成图表」→ 引擎出图 → `<img>`（守"引擎算数"铁律）
- ✅ **版本升 0.5.0**（engine `pyproject.toml` + app `package.json`，此前长期停在 0.4.0/0.1.0）
- ✅ **README 更新**：版本/当前重点/依赖 extras 说明/文档索引过期标注/里程碑
- 验收：pytest **1415**（+11）· build 0 error · selfcheck **36/36** · lint_bat 通过 · 脱敏通过
- 下一步：B4 atopia 一键解析（工步 0 抽取 + 工步 1 提示词任务）

---

## D168 · B2 统计核心（2026-11-05 完成）

> 需求单：`docs/112-D168-metrics-and-snapshot.md` §4.5

- ✅ `grading/error_stats.py`：失误次数（同题同知识点错 2 次记 2 次）→ 按 tag 加权
  （分母=**已提交人数**）→ 跨班两层 → 跨包 **Σ失误÷Σ总题数**（教师拍板）
- ✅ `grading/cooccurrence.py`：n 元共现 + **归一化关联** `P(组合)/∏P(单项)` +
  **每个 tag 一张图** + 自然聚类（不依赖章节）
- ✅ 词表别名归并（`alias_map`/`normalize_terms`/`add_alias`）+ `term_tags`
- ✅ 可信度判据（提交率<60% 或 人数<5 → ⚠️）
- ✅ `teacher_report.collect_multi` 的 tag **优先取 roster 快照**，并标 `_tagSource`
- ✅ 接口 `/analysis/errors`、`/analysis/cooccurrence`；前端「⑤-B 知识点失误分析」卡
- 🐞 修正两个真 bug：①归一化关联恒为 1.0（除法写错）②空词表导致统计全空
- 验收：pytest **1404**（+29）· build 0 error · selfcheck **36/36** · 脱敏通过
- 下一步：B3 可视化（2508 matplotlib 出 PNG）/ B4 atopia 一键解析

---

## D168 · B1 数据快照（2026-11-05 完成）

> 需求单：`docs/112-D168-metrics-and-snapshot.md` §4.4

解决教师问题：「换作业包后 roster 变了，批阅之前的作业时 tag 依据会不会丢？」

- ✅ 新增 `grading/snapshots.py`：`roster-tags/<packId>.json`（**学号主键**）+ `submissions.json`（含图片张数）
- ✅ 批阅集成 `_write_grade_snapshots()`：**快照存在 → tag 以快照为准**（可复现）；
  不存在 → 自动补写（`auto-at-grade`）；与当前 roster 不一致 → 警告不阻断；失败只告警
- ✅ 接口：`POST/GET /roster/tags-snapshot`、`GET /grade/submissions`
- ✅ 前端：「重算并打 tag」下加**作业包下拉**（不选=旧行为；选了=冻结快照）
- ✅ **T5 调整**：学生级 tag 映射**只存 `roster-tags/`**，`pack.json` 不重复（避免双写不一致）
- 验收：pytest **1375**（+21）· build 0 error · selfcheck **36/36**（+1 浏览器回归）· 脱敏通过
- 下一步：B2 统计核心（T6 词表归并 → T7 失误次数 → T8 加权 → T9 提交率 → T10 分 tag 共现）

---

## D168/D169 · 统计口径 + 数据快照 + 实现路线（2026-11-05 登记，待实施）

> 需求单：`docs/112-D168-metrics-and-snapshot.md`（口径）、`docs/113-D169-roadmap-and-architecture.md`（路线/架构）

本轮为**长任务方向定稿**，未动代码。关键决定：

- **指标改名**：「人均错误次数」→ **「加权失误率」**（次/人）；
  ❌不用「失分率」（与 2508 的分数比混淆）。
- **为什么不用得分率**：我们的作业是**扣分制且扣分有上限**（不固定每题总分），
  得分率无意义；**失误次数**才是主指标。同一题同一知识点错 2 次**记 2 次**。
- **加权公式**（教师定）：按 tag 算失误率 → 按「已提交人数」占比加权；
  跨班再按班级提交人数占比加权（两层）。
- **可信度保护**：任何失误率**必须与提交率成对出现**；
  提交率 < 60% 或人数 < 5 → ⚠️（防「提交少 + 正确率高 → 假性低失误率」）。
- **辛普森悖论保护**：合并值**始终并列分班级值**；差异 > 50% 标「该班主导/偏离」。
- **粒度**：全局 / 分班 / **分班分 tag（最小推荐）** / 分班分 tag 分包；
  单个学生**不做主方向**（偶然性大）。
- **两套共现图**：① 标准图（**例题**知识点，反映授课结构）；② 作答图（`errors[].knowledge[]`，
  反映学生错误）。**tag 必须拆开**（top/middle 错法不同，混算会糊）。
- **需要 `example` 新 kind**：标准共现图只能从**例题**得出（大纲/PPT 只有清单没有共现结构）。
- **数据快照**（保证历史可复现）：新增 `roster-tags/<packId>.json`（学号主键）+
  `submissions.json`（作答名单含图片张数）；「重算并打 tag」加**作业包下拉**，
  选了就写快照；批阅时无快照自动补写（标 `auto-at-grade`）。
- **提交率** = `submissions.json` ÷ `roster-tags/<packId>.json`（教师定）。
- **受控词表**补齐：`split_terms` 增加**别名归并**；统计只计词表内/`related` 内术语，
  词表外单独计数不进主统计。
- **人工清空知识点 = 待补**（AI 可重标）；「锁定为空」是显式操作（人机结合）。
- **atopia 权限收紧**：AI **只能写 `atopia/**`**；`kb/`、`materials/` 等只能引擎执行（教师确认）。
  `kb.write` 升 L3 拒绝。**不需要"复制 kb 到 atopia"**——只读权限已够，xlsx 用 `kb.export` 转 JSON。
- **可视化**：撤回我上轮"matplotlib 会让引擎体积暴涨"的错误理由（源码 zip 不变，依赖是用户下载）。
  定稿：**引擎算数 → 输出 PNG（报告/页内看图）+ JSON（前端渲染）共存**；
  节点明细登记待做（引擎算坐标 → 前端 SVG，**算法不翻译**）。
- **一键解析**：两段式（工步 0 抽取免费 + 工步 1 AI 结构化），**不做工作流编排**；
  任务模板作 `atopia-task` 第 7 类（复用 D151 CRUD，加 `outputSchema`/`inputKinds`）。
- **不给 Atopia 写 skill**（它靠工具 description）；**不做插件系统**；
  改为：description 升级 + 按场景分组暴露 + CLI `Examples:` 段。
- **三条铁律**：单一能力源 / 写分层 / 白名单执行；附加「**如果 CLI 也要这个结果，就必须在引擎**」。

批次：B1 快照 → B2 统计核心 → B3 可视化 → B4 一键解析 → B5 example+标准图 → B6 工具治理。

---

## D166 · LaTeX 转义根因 + 知识点 JSON 化 + AI 再整理（2026-11-05 完成）

> 需求单：`docs/109-D166-escape-and-related-json.md`

- ✅ **LaTeX 乱码根因**（三条）：`\times` 被吃成「制表符+空格+imes」、`\frac`→`rac`、
  `\nabla`→换行；旧修复正则要求「控制符紧贴尾巴」，**图案对不上就完全不触发**。
- 🔴 **同时发现更严重的问题**：`parse_llm_json` 会**主动弄坏**合格输出——
  模型守规矩写 `\\frac` 时，被当成"被吃掉的 \"再补一个 → `\\\f`（静默坏数据，
  1298 个测试全绿也没发现，因为测试只用单反斜杠构造输入）。
- ✅ 三层防护：prompt 写清坏法→后果（L1）/ 反斜杠**奇偶配对**判断（L2）/
  解析后 `_sanitize_latex` 还原 4 种形态（L3）。**43 项测试**含三态矩阵 + 反例不误伤。
- ✅ **知识点 JSON 化**：`knowledge-meta.json` 扩展 `versions[]`（与 D89-N3 答案版本库同构），
  xlsx `related` 保留速查；新增 `GET /kb/related/<qid>`、`POST /kb/related/apply`。
- ✅ **题库编辑器** `related` 列加 🔍 预览弹窗（版本/来源/词表命中/编辑写回）。
- ✅ **AI 再整理**（`related_tidy.py`）：同义合并/词表归一/粒度统一，**只出建议 → 逐题勾选 → 写回**；
  教师锁定（`pinned_by=human`）默认跳过。
- ✅ **「同时标注知识点」默认勾选**（此前默认关 → 教师看不到 AI 已经算出来的知识点）。
- ✅ 顺带修 `write_xlsx` 表头污染（新建题库读回时 `solution` 列消失）。
- ⚠️ 调试踩坑（已加注释防复发）：`re.sub` 替换串写 `"\" + head` 会被当转义；
  快速跳过只看控制符会漏「反斜杠+字母」形态；POST 路由误塞进 `do_GET` 导致 404。

---

## D165 · 跨班发布误判「已发布」（2026-10-31 完成）

> 需求单：`docs/108-D165-publish-cross-class.md`。

- 根因：发布设置页 URL **只带 courseid、没带 clazzid** → 平台按**课程**维度判断
  "是否已发布"，同课程其它班发过就拒绝（报错里 `requests: []` 说明是前端校验拦截）。
- ✅ URL 补 `clazzid`；✅ 重复校验改为**逐班**（此前只查第一班）；
  ✅ 失败时带出页面提示文字（`pageHint`），无请求时明确说"前端校验未通过"。
- ⚠️ 需实测确认（本机无法验证学习通真实行为）。

---

## D147 · Atopia L2 确认精确到「工具 + 参数」（2026-10-31 完成，安全修复）

> 需求单：`docs/94-D147-confirm-scope.md`。

- 核查发现 D140 的"已知限制（整次请求全部确认）"其实是**漏洞**：
  教师为 A 确认后，同一次请求里模型改请求另一个 L2 工具也会被自动执行（实测可复现）。
- ✅ 后端抽 `serve.make_atopia_confirm()`：必须 `confirmedTool` 匹配
  （可选 `confirmedArgs` 也匹配）才放行；带 confirmed 却不指明工具 → 拒绝。
- ✅ 前端确认时回传 `confirmedTool` / `confirmedArgs`。
- ✅ 同时修正 docs/83、docs/86、docs/89 中已被后续提交推翻的"已知限制"表述。
