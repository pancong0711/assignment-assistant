# 05 — 决策记录（Decisions）

> 讨论中已拍板 / 已澄清的事项，按时间顺序记录。改动现有决策需在此追加新条目说明理由。

## D1 · "CLI 超集"铁律（2026-09-20，用户提出）

**所有 PWA 可以实现的功能，CLI 都必须可以同样实现。**
CLI 是完整能力本体；PWA 是 CLI 的"参数化界面 + 结果展示器"。
- AI 代理使用路径：读任务包 JSON → 调用 CLI 命令，能力不打折；
- 普通用户路径：网页按钮 = 已填好的任务包 / CLI 调用；
- 校验方式：任何新功能实现时先在 CLI 落地（或至少可复现），再在前端展示。

## D2 · 引擎通信：本地 HTTP 在线为主，任务包文件为降级路径

两种形态并存：
1. **在线握手**（首选）：教师本机运行 `assist serve`，PWA 检测 `127.0.0.1:<port>`
   引擎在线即启用在线自动执行（进度/SSE 日志实时回传）。
2. **任务包**（降级/跨机）：一单任务的所有参数固化为一个任务包文件
   （JSON+附件 zip，可导出），用户或 AI 代理拿去在装有引擎的机器上
   `assist run <taskpad>` 执行，产物导回/导出。

任务包的意义：把"做什么"固化下来，人与 AI 都能直接执行；同时它是
`assignment task` 的持久化存储本体（同一份 JSON，只是抽象出"可携带"属性）。

## D3 · 题库主格式：xlsx 为主（2026-09-20，用户拍板）

- **xlsx = 主编辑/主数据（source of truth）**：保持教师既有编辑习惯。
- JSON = 导出/交换/AI 阅读副本/diff 基准，由引擎一键生成并自动同步
  （`assist files sync`）。
- 网页端题库编辑器直接读写 xlsx（前端 SheetJS 读 → 编辑 → 引擎写回；
  纯静态模式下导出 xlsx 文件让用户替换）。
- 每次写盘前自动快照到 `kb/.history/`（xlsx 无版本历史的补丁）。
- 多个 sheet（章）与其列结构（id/content/img_path/page/related/type/
  solution/note）保持兼容。

## D4 · 前端栈：Vue 3 + Vite + TypeScript + Pinia

- 应用形态为"表格 CRUD + 表单 + 预览 + 日志流"，Vue 响应式正对口；
- 构建产物纯静态，可部署 GitHub Pages；
- 用户不需要 Node（构建在开发时/CI 完成）。

## D5 · 环境安装：平台三脚本 + 手机端定位 + 便携包 + 镜像源

- **平台安装脚本**：Windows `install.ps1`、Linux/macOS `install.sh`
  （统一脚本按参数分支亦可），覆盖 uv 安装、依赖同步、Playwright 内核；
- **手机/Pad**：无法本地安装引擎（浏览器/系统限制），定位为「远程第二屏」：
  本机电脑跑 `assist serve`，手机 PWA 通过配置的引擎地址（局域网 IP:端口，
  访问令牌防蹭网)查看进度/结果/作业纸；触发的重活仍在电脑端执行；
- **便携引擎包（有必要，列为里程碑后段）**：GitHub Releases 提供
  `engine-portable-<platform>.zip`（uv/pyapp 自引导 Python + 预装依赖 +
  脚本），解压即运行，免除"装 Python"；用户验证好用后再推广；
- PWA 内置「环境体检」页：逐项检测 Python/uv/依赖/Playwright 内核/TeX
  （可选）与引擎在线状态，输出绿黄红状态表 + "复制命令"按钮；
- PWA 支持自定义引擎地址，不写死端口；
- 明确边界：浏览器无法静默代装系统软件，引导式安装 + 便携包是上限。

## D6 · 数据目录粒度（多学期多班级，kb 在根目录）

- workspace = 教师管理根目录，**多学期多班级长期使用**；
- **kb/ 题库置于根目录**（跨学期复用、最常编辑的部分）；
- `classes/<学期批号>-<课程简称>-<班级名>/` 子目录并列放所有 班级×学期，
  各自含 roster/（点名册/成绩/分组）、sheets/（作业纸任务包+PDF）、
  grading/（批阅产物）；
- 目录树与命名约定详见 04 §1；CLI/PWA 支持 workspace 切换与班级新建向导；
- 你问的 roster/sheets/grading：roster=点名册+成绩+分层分组结果；
  sheets=作业纸设计产物（任务包与生成的 PDF）；grading=批阅产物
  （下载的学生图片、转录、评阅、报告、汇总表）。

## D7 · 批阅上传：保留自动打分（确认）

上传阶段继续"评语文字 + 批阅图片 + 自动给分"全自动（用户已确认）；
提供**可选**的"上传前预览确认"步骤（默认可关闭），满足教师抽查需求。

## D8 · 任务包 = 执行历史（journal 任务包方案确认）

- 任务包同时是：CLI 完整参数、Web 端按钮的后台实体、可执行/可重跑记录；
- `assist run` 默认 `--journal on`：每次执行在任务包内追加运行记录
  （时间戳、步骤、日志路径），便于 debug 与 AI 代理复盘；
- 失败可 `--rerun <task>`（整单重跑或按步骤重跑），参数与产物始终绑定。

## D9 · 手机/Pad 可用性边界

- 引擎类功能（学习通、打印 PDF）必须在电脑端执行；
- 手机端 PWA 通过局域网连接电脑引擎作远程查看/触发（见 D5）；
- 不为手机端引入任何"本地引擎"方案（技术不可行）。

## D10 · 国内镜像源

- 安装脚本默认配置国内镜像：uv 用 `UV_DEFAULT_INDEX`（清华 PyPI）、
  pip 提供 `-i https://...tsinghua...` 回退、Playwright 用
  `PLAYWRIGHT_DOWNLOAD_HOST`（npmmirror）拉内核；
- 提供 `--official` 开关走官方源；
- 脱敏无关，脚本直接入库。

## D11 · 前端降级提示（澄清）

- 所谓"指引下载 Chrome/Edge"与 Playwright 无关（Playwright 自带内核）；
- 它针对的是 **运行 PWA 的浏览器本身**：Firefox/Safari 不支持
  File System Access API/OPFS 等关键能力时，前端检测后提示换用
  Chrome/Edge 获得完整体验（不强制，具备降级 UI）。


## D12 · 学习通自动化安全边界

- 登录态/cookie 存教师本地浏览器 profile，绝不上传/入库；
- 自动操作默认限流（逐条上传、间隔与失败重试上限），保留 2601 v1/v2/v3
  三代上传策略择优；上传含自动打分（见 D7）；
- 所有自动动作均有本地运行日志（不入库，仅教师本机）。

## D13 · 程序与数据分离；settings.local.json；向导式首次运行

- **引擎（程序）与 workspace（数据）分离**：引擎默认装
  `~/.assignment-assistant/engine/`（或便携包解压目录），workspace 自定义
  自选；两者通过 settings 关联（`engine_dir` 可改）。安装脚本不把 .venv
  写进 workspace（避免打包/同步污染，多 workspace 可共用一个引擎）。
- **workspace 根放 `settings.local.json`**（JSON 优先于 .env）：apikey、
  模型名、引擎地址、默认班级、开关项；引擎与 PWA 都读它；不入库；
  纯 CLI 场景保留 `.env` 作为兼容别名。
- **设置中心（PWA 基础设置页）**承载：workspace 管理、环境体检与安装
  向导按钮、引擎地址、apikey、镜像源开关、上传前确认开关等。
- **首次运行向导（Onboarding）**：选 workspace → 环境体检 → 完成；
  可跳过；跳过或未完成时**不整体置灰**：
  - 纯静态可用的选项卡（作业纸设计、题库浏览）保持可用；
  - 依赖引擎的功能（学习通、批阅、打印级 PDF、写回 xlsx）按钮灰 +
    页面顶部黄色横幅提示"需引擎在线 → 去体检"；
- 体检页输出逐项绿黄红 + "复制命令"按钮（引用 install.ps1/install.sh）。

## D14 · 引擎环境收纳进 workspace（修订 D13 第一条，用户拍板）

**变更**：引擎 .venv 与相关缓存**收纳在 workspace 内**，不再放系统级目录。
- 布局：`workspace/.runtime/venv`（虚拟环境）、`.runtime/cache/uv`（
  `UV_CACHE_DIR` 重定向）、`.runtime/browsers`（Playwright 内核,
  `PLAYWRIGHT_BROWSERS_PATH` 重定向）；
- **卸载即删除 workspace 一个目录**（用户核心诉求）；
- TeX 例外：体积大且系统级安装，保持可选外部依赖，卸载时单独提示清理；
- **导出/导入白名单**（kb/tasks/classes/reports…），`.runtime/` 永不打包，
  旧文件不入 zip，导入端 `assist doctor` 校验引擎可用性；
- `assist bootstrap`（安装脚本第一步）负责设置上述环境变量并建 venv；
- **跨机可执行迁移**：
  - 主路 = uv/pyapp 便携引擎包（Releases，见 D5），拷贝即用；
  - 备选（延后验证）：PyInstaller/Nuitka 单文件可执行，体验更"零依赖"，
    但体积/杀软误报/调试成本高，仅作为后段可选懒人包；
- 多 workspace 共用引擎的需求降级为可选（用户明确更看重"一处删除即卸载"）。

## D15 · 开源字体替代与教师覆盖（2026-09-20，用户提出"字体可选择开源对应字体"）

- 中文字体 fallback 链改为"版权字体 → 开源替代 → 系统字体"三级：
  - 黑体类：文泉驿微米黑（wqy-microhei.ttc，GPL+字体例外，多数 Linux 自带；
    Windows 教师可继续用 simsun.ttc/simkai.ttf）;
  - 楷体类：霞鹜文楷 LXGW WenKai（SIL OFL），不入库，`tools/fonts-download.sh` 下载到
    engine/assets/fonts/；
  - 映射表 engine/assets/fonts/fonts.json；教师可用 settings.local.json 的
    "fonts" 键覆盖任意键（指向自备字体路径）。
- 字体文件一律不随仓库分发（脱敏+版权双约束）。

## D16 · 横版版式先与竖版完全一致（2026-09-20，用户决定）

- 边距、字号、头部/页脚带区比例横竖统一（实现：landscape_frames 与
  _make_onpage 全部沿用 portrait 常量；标题字号横竖均 18pt）；
- 生成真实文档后统一验收时再按效果细调（先一致、后调优）。

## D17 · 分层标签体系 9 个固定保留（2026-09-20，用户强调）

`copy / copySp / copyOnly / qa / summary / distinguish / innovation /
translation / punish`（punish 为新固定项：期末补作业，统一题集不按层）。
- 三个"非题库文件"的标签再次确认：summary 与 punish 不依赖题库 kind——
  summary 由点名/成绩打标签得到；punish 期末补交统一题集（学生 A 也可用）；
- app：设计器 tag 下拉 + `STUDENT_TAGS` 常量；引擎：evaluator 标签规则映射
  表含 punish（沿用"完整性自查"差异规则并放宽）。

## D18 · 成绩管理独立成模块 M5（用户提出，2026-09-20）

将"点名册导入、学习通成绩、雨课堂成绩、期末成绩导入 → 学生打分层标签
→ 分组比例 → 按比例生成作业变体切片"从"作业纸设计"里独立为 **M5 成绩管理**
（目标用户/数据形态与 ①学习通辅助 ②作业纸设计 ③大模型批阅 ④本地文件
管理 不同：它管理"关于学生的数据资产"）。落位：
- engine：`assist roster *`（迁 student.py/exceltools/rainclass 分析）
- app：新选项卡「班级与成绩」（点名册导入/成绩导入/标签产出/分组比例）
- 阶段：**3.5**（排在阶段4 学习通之前，纯本地即可闭环，不依赖学习通）
- 分组比例 UI 放此选项卡；2603 的 default_group_cfg 数值作为默认模板。

## D19 · 成绩源适配层 + 版式反馈（2026-09-20，检测后反馈）

**成绩源分层**（与 legacy 排版格式一致，参考旧解析代码逐条迁移）：
- 固定四类（hard-code 对齐旧项目口径）：`roster`（教务点名册：姓名/学号/班级）、
  `exam`（教务期末：列"期末(必填)"）、`xuexitong_assignment`（作业统计：
  前 8 行扫描"成绩"行 + 上行作业标题 + 数据行）、`xuexitong_stat`
  （按 sheet 关键字如"章节测验"匹配、第 4 行"成绩"列、非 0 均分）、
  `rainclass`（雨课堂汇总表：header=None，第 2 行标题，前 3 列学号/姓名/汇总，
  每课 2 列取均值）；
- **custom**：列名 list / 用户手选列 + 权重（其他成绩如高考数学/大一高数等）；
- CLI：`--score family:file[:col[:weight]]`（family 可省=custom）；
  app 端成绩源表单配"格式预设"下拉同口径。

**版式反馈**：
- 预览虚线框仅为 UI 区分；实际打印（engine）多题/页时加"实线分隔"
  （横版=栏间竖线、竖版=行间横线）；
- 每页题数 `per_page` 可设 1–4（任务包 layout.per_page；缺省 竖1横2），
  竖版为上下行、横版为左右栏；引擎帧按 per_page 切分。

## D21 · 版式网格语义 + 虚线分隔（2026-09-21 用户反馈拍板）

- per_page 语义：**4 = 十字 2×2**；横版 2/3=左右栏；竖版 2/3=上下行；
- 分隔线一律**虚线**（引擎 setDash(4,3)，预览 repeating-linear-gradient 覆盖层），
  只画"格与格之间"且止于内容区（不穿页眉页脚）；**不画题目外框**
  （预览 .divided .sheet-frame 去 border）；
- 水印预览兜底：items 空 = legacy 三槽占位（rt/lc/lb），与引擎默认一致。

## D22 · 阶段顺序修订（2026-09-21）

学习通整模块（登录/下载/上传/公告/HTTPS）后置为**阶段 6**；
阶段 4a 只做纯本地闭环；rasterclass 明细分析并入阶段 5（M5 补强）。

## D23 · 多类型/多层作业纸"变体编排"方案（阶段 5 重点）

- 概念：作业集 = N 份任务包（tag 变体）；班级名单带 tag → 引擎按映射自动选
  变体出 PDF；同 tag 内题目顺序轮换防抄袭；
- 交互：设计器"变体组"多选 + 班级与成绩页"tag→任务包"分配面板；
- 引擎 `assist sheet batch --roster tagged.xlsx`（按 tag 自动选用对应包）。


## D24 · translation 标签语义（用户确认与 legacy 校准，2026-09-21）

`translation` **不参与比例切分**，也不占"比例合计"：
- legacy `_tag()` 语义：非 translation 比例组顺序切分（合计可 <100%，余数补末档 copyOnly）；
  然后按 `int(人数×translation比例) 名学生随机替换为 translation。
- 引擎 engine/roster/grouping.py：顺序切分跳过 translation/punish，translation 用可复现等距
  选点替换 k 个位置（可复现版 np.random）；引擎比例校验以非 translation 合计 >1 报错。
- PWA：比例表 UI 单独抽出 translation 为"独立随机拨给"；比例合计不含 translation
  （stores/roster.ts ratioSum 已过滤）；">100%" 与 "<100%" 告警口径同步。

## D25 · 选项卡重组与一站式安装（2026-09-22，用户电脑端检查反馈）

**导航重组**（7 个顶层选项卡）：
1. 设置中心（含一站式环境安装，见下）；2. 题库编辑器；3. **作业纸版式**（orientation/per_page/页眉页脚/水印/模板级预览+打印模板 PDF）；4. **作业纸内容**（kind/章/选题篮/target_tag/任务包清单/变体编排绑定）；5. **班级与标签**（原"班级与成绩"更名：点名册+成绩源+全表视图+勾选列打 tag）；6. **学习通**（新模块：发公告带附件〔主用途=发布作业纸〕、批阅下载/上传/打分等，随阶段6落地，先立占位卡）；7. 导入导出。批阅工作台并入"学习通"或独立保留待定（实施时定）。
- 拆分原则：版式=一份模板的"长相"；内容=一份模板的"题目构成"；两者共同生成一个任务包（现有 schema 不变，仅 UI 分屏，字段归属清晰）。

**一站式环境安装（倾向方案）**：
- 静态端：给出"需安装软件清单 + 逐项复制命令 + 平台脚本"（现状增强：列表化 Python/uv/依赖/Playwright/TeX/字体，每项状态+命令）；
- Companion 端（推荐路径）：教师先双击 `start.bat`/`start.sh`（便携引擎一键入口，阶段5-B5 提前），页面点"安装全部"→ `POST /install/{item}` → 引擎执行 uv 依赖安装/playwright install/fonts-download/xelatex 指引，SSE 回显进度；无法静默装系统级的（Python/TeX）给"下载页直达+命令复制"；
- 体检页从"只读报告"升级为"报告+修复按钮"。

## D26 · 班级与标签页交互升级（2026-09-22）

- 名单/各成绩源读入后显示**宽表**：行=学生，列=各成绩源分数列（可多列），支持横向滚动；
- **勾选任意一列**（或多列加权）→ 点"按此列打标签"→ 按当前分组比例切档赋 tag（等价现 recompute，但数据源即所见列）；
- 特殊标签栏（批量姓名输入/手动覆盖/punish）保持并紧邻表格；
- 产出顺序：名单(带tag) → 变体编排 → **"生成全班作业纸"**（调 batch zip/引擎）。

## D27 · 作业纸生成语义与预览保真（2026-09-22）

- "打印级 PDF"按钮语义 = **模板级**（当前任务包×合成学生A/B），适合单类型全班统一场景；产物可直接作为**学习通公告附件**发布；
- **整班分层生成**入口放"班级与标签"页（打完 tag 之后一步到位），走 `assist sheet batch`；
- 预览≠打印是已知局限（HTML/CSS vs reportlab+LaTeX）：新增**高保真预览**通道——引擎把任务包渲染成 PDF 后用 pdftoppm 转 PNG，PWA 翻页浏览（上一页/下一页/页码输入框）；无引擎时回退 CSS 近似预览并标注"近似预览"；
- LaTeX 公式在 CSS 预览中只显示源码 → 引入 KaTeX 前端渲染（数学公式近似显示），与高保真预览互补。


## D28 · workspace 约定 = start 脚本所在目录（2026-09-22 用户拍板）

- start.bat / start.sh **由双击处定位 workspace**：教师把脚本放在自己惯用资料目录
  （例如 `D:\我的资料\班级\`），双击该脚本 == 该目录即是 workspace（kb、
  classes/、.runtime 全在其中）。网页设置中心已注明；
- PWA 设置页"一键启动/安装卡"文案同步："下载 start.bat → 移动到你常用的
  资料目录 → 双击即用"；前端 FSA 所选目录与 bat 侧工作区通过**同一路径**统一。

## D30 · 输出主通道 = HTML + 浏览器打印（2026-09-22 用户拍板）

- **作业纸/整班/批阅报告输出主通道 = HTML + 浏览器打印**（零安装）：
  - 每生分页块 + `@page A4`；KaTeX 端上渲染数学公式；题图 base64 内嵌；
  - PWA 在线即时 `window.print()`；CLI `assist sheet html` 同模板双实现（超集铁律 D1）；
  - 整班大 HTML 一个文件承载（几十/上百页 OK），打印对话框=保存为 PDF；
- **TinyTeX 与完整 TeX 均为可选增强**（不再主依赖）：TinyTeX 装进
  `workspace/.runtime/tex`（体检页可点修复按钮安装，tlmgr 清华镜像）；
  完整 TeX Live/MiKTeX 不自动装（检测到则可用）；
- **reportlab→PDF 引擎线保留**：逐生独立 PDF、水印精修、批阅报告 PNG 场景（阶段6内挂学习通上传）。

---

## D32 · 启动脚本顺序反转 + 安装完全入 workspace（2026-09-22/23 用户拍板）

- **v9 同型：** start.bat / start.sh **Python 优先**：
  1. 系统有 `py/python` → 用其直接 `python -m venv workspace\\.runtime\\venv`（不动用户环境）；
  2. 无 Python → **Miniconda3-latest 从 TUNA 静默装入 `workspace/.runtime/miniconda`**（脚本 curl
     拉 TUNA 镜像为 fallback 首选源——非 ghfast/github）；
- **依赖安装全走 TUNA index**（`UV_DEFAULT_INDEX` 或 start.bat/setx 中默认），失败时提示 last-resort
  `assist-engine` 从 PyPI（TUNA）安装——避免教师 download GitHub zip 失败后走 PyPI 的
  “assist-engine not found in the package registry” 报错；
- **隔离设计（D14 强化）**： uv（如果用户需要）/Python/venv/缓存/浏览器内核/日志全在
  workspace/.runtime 内；工程师 unset `,localappdata\Programs\uv` 中的内容不往教师系统注册
- **长期目标**：报告/作业纸输出 documents 双通道：
  - **引擎通道（reportlab + latex/tinytex optional）**：水印精修、逐生 PDF、版户控制；
  - **HTML 通道（PWA 打印浏览器版）**：零安装（D30）
  两通道持久化（同一任务包，输出两条路），功能等价。


## D33 · engine 获取通道 = Pages 托管 `engine-main.zip`（与仓库快照同步，2026-09-23 用户拍板）

- **CI（pages.yml）新增一步**：`git archive main engine/ tools/start.bat tools/start.sh README.md LICENSE`
  → `app/dist/dl/engine-main.zip`（≈80KB）——与仓库代码**每次 push 同步**（教师一定拿到最新 engine 源码）；
- **engine 获取链（bat/sh）**：主源=**我们自己的 Pages**(`dl/engine-main.zip`)；备 1=ghfast 代理；
  备 2=github 直连；PyPI `assist-engine` 作为 last resort（B5 提级设定——未发版前为降级路径）；
- **zip 内容仅 engine 源码 + 启动脚本 + README/LICENSE**（~80KB）：不含 PWA（线上 Pages 自带）、
  不含 uv/Python 二进制（见 D32：Python 优先、PyPI/TUNA 提供）。
- **教师路径（零依赖完整版）**：下载 start.bat → 放到 workspace 资料目录 → 双击：
  bat 检查 `engine/pyproject.toml`（旁有/`_repo/assignment-assistant` 内有）→
  engine zip 下载与解压 → venv pip TUNA 安装 → assist serve 起来。


## D34 · engine 下载链定型（2026-09-23 用户拍板）

- **主链：github.io（Pages）`dl/engine-main.zip`**（5 次尝试 × sleep10 重试窗；长连接窗
  `--connect-timeout 60 --max-time 180`）；
- **次链：github Release 附件**（github.com 域，你机已实测 41MB 可达）——CI `dl` tag
  固定 Release；`engine-main.zip` 由 CI push 时同步产出；
- **兜底：ghfast → 整仓 main.zip**（最后手段：兼容任何内层目录名——`find -maxdepth 3 -name engine -type d`）；
- **PyPI 兜底段删除**（先舍弃；恢复条件：pypi.org 状态稳定 + `assist-engine` 发版流程完备）；
- 下载逻辑从「20 秒失败立刻切下一链」升级为「主源长窗重试」——对教师网络波动
  更友好（实际报错案例：v6/v7 中 20s 就切链， 导致整仓 41MB 下载与解压 mismatch）：
- **解压兼容**：Windows 自带的 Expand-Archive；匹配 `engine/pyproject.toml` 时以
  `find`/`IF EXIST` 双层定位（兼容 `assignment-assistant-main/` 与 `engine/` 两种内层）。
