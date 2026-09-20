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
