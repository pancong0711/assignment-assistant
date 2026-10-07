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

- **docs/13-taskboard.md 已重建**：上一版在 5e3e092 被清空（当时 commit 信息称"D41 任务需求单"，
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
- 另记：D45+D43 遗留已于 bc6f055 推送部署成功（Pages/tests CI 双绿，线上 index-CMVEb0st.js）。

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
- 状态 ⏸ 待执行；续作指引与验收清单见 docs/13-D56。基线 f33c5ce（CI 双绿，引擎 roster 入库修复已完成）。

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