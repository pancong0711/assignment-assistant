# 14 — 任务需求单（2026-09-22 · 用户拍板："先完善一键安装 → 而 S3 后做 HTML"）

> 变化点：HTML 主通道（H1/H2）**后移**——它需要重新开发（旧项目没有该部分），本次
> 一键安装先行。R 组/批次仍以 docs/13 为主框架，本文档作为**任务需求单（细化）**。
> 决策依据：docs/05-D25–D30；C 组（学习通）仍最末。

---

## VA · 一键安装"完善收口"（本轮主任务）

### 现状盘点 v6（已实现）
- `start.bat/.sh`：uv→Python 3.13（uv 托管）→ venv→ 依赖→ serve→ 浏览器；
- **镜像三件套**：uv 下载 ghfast 代理降级、`UV_DEFAULT_INDEX` 清华 PyPI、
  `UV_PYTHON_INSTALL_MIRROR` defaults（见 D29-cn 记录）；
- **workspace = bat 所在目录**（D28）；`/doctor` id 定版 + `/install` + SSE + 【修复】按钮。

### 待完善（按相关性聚簇：**同域一次完成**）

| 组 | 子项 | 说明 |
|---|---|---|
| **VA-1 engine 获取** | ① bat 旁既有 `engine/`（检测 `pyproject.toml`）→ `uv pip install -e`；② 否则自动**下载仓库 zip**（ghfast 代理 / `https://github.com/.../archive/refs/heads/main.zip`）解压至 `workspace/_repo/`，再 `uv pip install -e workspace/_repo/engine` | 当前缺②——teacher 独立目录双击必挂"PyPI 找不到包"；这是"纯零依赖"唯一缺口 |
| VA-2 | `uv python install` 下载**换 ghfast 反代镜像**（npmmirror 路径 bug 修掉：`UV_PYTHON_INSTALL_MIRROR=https://ghfast.top/https://github.com/astral-sh/python-build-standalone/releases/download`）；实测耗时由 11min → 分钟级 | 镜像生效性验证（修复用户日志中"下载 11 分钟"） |
| VA-3 | **uv.exe 自下载**（免 powershell irm）：ASCII curl/Invoke-WebRequest 拉官方单文件 uv.exe 到 `workspace/.runtime/uv`（对应"没有用户目录残留"）；失败时 fallback：irm 官方），CN_OFFICIAL 情形可退出 | 完全去系统态残留（2.1 请求） |
| VA-4 | **Playwright** 预置（可选、非主线）：`PLAYWRIGHT_DOWNLOAD_HOST=npmmirror` 默认化；体检安装项 active | 阶段6 前置 |
| VA-5 | 体检页【修复】按钮"安装"语义对齐：区分"复制命令（step by step）"与"点装"（deps/fonts/playwright 在线可装；python/uv/tex 查指引）——统一从 fix 哨兵来，一致性显示 | 前端 |
| VA-6 | **镜像输出可观测**：/doctor 返回 `sources_used{uv, pip, python_dl, playwright, fonts}`（详情查 D29），并暴露到 PWA 修复按钮旁（"当前源：清华/official"）；`CN_OFFICIAL=1` escape 保留 | 可观测性 |
| VA-7 | **start 脚本/ /install 端到端联调**脚本：tools/check-install.sh（模拟教师流：bat 装步一遍的 dry run），CI 接进 tests | 脚本自测 |

**验收**：
1. 教师唯一提交：下载 `start.bat` → 移至目标资料目录 → 双击；全程零输入；
2. 网络弱的情况下也应该能因降级镜像（ghfast/清华）而成功；
3. `workspace` 内 `.runtime` 之外**不产生任何文件**；
4. 卸载=删除 workspace 全部（含 start.log）。

---

## VB · HTML 打印主通道（H1/H2/H4 核心实现，需求单，下一会话开工）

> 旧代码无此部分——**全新开发**；仅模板视觉与 D27 高保真预览共用理念；
> reportlab PDF 线保留（不在本项中）。

| 组 | 子项 | 说明 |
|---|---|---|
| **VB-1 模板（单一事实源）** | **`templates/assignment.html.j2`**（Jinja2，由 CLI 使用）+ TS 同结构实现（web 端同排版语义）：每生页块（`@page A4`），页眉（课程/班级/学号姓名行+作业标识+日期）、页脚（"签名/日期"线）、水印层（items 逐层）+ `@media print`；**auto page-break**（每生 `page-break-after: always`；横/竖版面 `size: A4 landscape/portrait`；H3 per_page 2/4=网格列/行） |
| VB-2 | 题图 base64 内嵌（读 kb/fig）；未插图时占位框；**KaTeX** 渲染题干 `$..$`（KaTeX 本地打包离线，字体 base64 内嵌/或走 CDN fallback） |
| VB-3 | CLI：`assist sheet html --task <json> [--roster xlsx]`：从任务包 + roster 产出**一个自包含 html 文件**（整班多页）+ `--email`（可选，后续别用）；CLI 尊重 D1 超集 |
| VB-4 | PWA 按钮"打印浏览器版"（作业纸版式页内）：任务包→HTML→`window.print()`；**直接由前端 TS 实施**（不依赖引擎在线） |
| VB-5 | **批量整班输出**（生成逻辑与 roster/变体编排绑定）——teacher 端 batch zip 中 html（或 CLI 生成后教师挑选） |
| VB-6 | 打印教程（浏览器对话框：A4/边距=关/页眉页脚=关/背景图形=开）+ Firefox/Safari 打印差异 |
| VB-7 | AI 批阅报告 HTML 复用同模板（H4）——报告页头/页脚/水印风格统一 |

**验收**：
1. `assist sheet html --task` 出单文件整班 HTML（浏览器打开→打印→PDF 与预览一致）；
2. PWA"打印浏览器版"按钮在无引擎/未登录时仍可用（纯前端，双端一致）；
3. 公式 KaTeX 应用打印并精确保留 telemetry（页面中的数学分数/积分样式清晰）；
4. `assist sheet html` 与 PWA 输出**同一模板**（D1 超集铁律，无差异化输出）。

---

## 执行顺序（更新后）

| 会话 | 内容 |
|---|---|
| **S1.1（本次）** | VA-1 ~ VA-7（start 双脚本改进 + /install 引擎双向 + doctor sources_used + 镜像）——一件"收口到零依赖装通"的完整会话 |
| S1.2 | **VB-1/2/3/4**（HTML 打印：模板 + CLI + PWA 按钮 + KaTeX）——即"重新开发的相当一部分" |
| S1.3 | M-C 成绩宽表+勾选列打 tag+“生成全班"主按钮 |
| S1.4 | M-D/S3 剩余（TinyTeX 可选修复按钮 + R1.1 清单卡微调） |
| S1.5 | M-B 保真剩余（PNG 引擎 render/批阅报告 PNG 导出——保留逐生 PDF 路线） |
| S1.6 | M-E 杂项 + B5 PyPI 发版 + 手册 |
| 末位 | 学习通（C 组） |

**冲突**：VA（engine/脚本）与 VB（app/）文件互不交叉——可并行推进。

---

## VC · 预览体系（2026-09-22 用户增补：预览 = 全功能版图，审核后整合）

> 用户明确：预览不是"作业纸设计页里的一块"，而是**全链路能力**——
> 作业纸模板 / 不同类型作业纸 / 整班作业纸 / 导入的名单与成绩，都要有预览。
> 勾选成绩列 = 分层依据（默认全勾，可取消勾选排除某列）。
> 现有实现盘点：作业纸模板预览已有（版式页 CSS 预览）；类型间切换/整班/narrow成绩预览/勾选列 **尚未整合**。

| 子项 | 内容 | 去向 |
|---|---|---|
| VC-1 | **作业纸模板预览**（版式页 remodel）：现状 CSS 预览保留；加"**显示为浏览器打印版**"切换（同一 HTML 模板预览 overlay，双实现复用） | 版式页 |
| VC-2 | **不同类型作业纸预览**（作业纸内容页）：清单里任一任务包可以"预览版式"——**切换包**即可看到每份的预览（版式/水印/内容全量）。**在清单表格增加"预览"按钮（或行内预览）**，选择包 → 版式页预览同一模板 | 内容页 |
| VC-3 | **整班作业纸预览**（作业纸内容页）：变体编排卡"预览全班"模式——按 tag→任务包+名单范围生成**完整多页 HTML overlay**（H1/H2 模板）在网内浏览（不依赖引擎） | 内容页 |
| VC-4 | **点名册导入预览**（班级与标签页）：读入名单 xlsx 后先以表格形式预览/校验（姓名/学号/班级），**编写/纠错窗口**（无 score 也可用，tag 列空白） | 班级与标签页 |
| VC-5 | **成绩源预览 + 勾选列打 tag**：导入的每个成绩源**默认全部勾选**（被用户可勾选排除某列不参与分层）；点多选切换"此列作为分层依据"——重新计算时用勾选列的**加权/平均**作为综合得分（等价 D30 已有的 sources 设置列勾选，但所见即所选）+ 每源一行“去/留”开关；**导入名单表和成绩导出/预览界面都各自显示节点预览** | 班级与标签页 |
| VC-6 | **点名册/成绩导入的"独立预览"卡**：读入后以"表头+前 3 行"预览（表格下方），让教师看到解析后的结构（用于核对列映射是否正确） | 班级与标签页 |

**验收**：教师可在各页内**直接预览**：作业纸模板 / 任一类型作业纸 / 整班 / 点名册 / 成绩源（含未勾选列的排除/加权）——**不需要先走 CLI 或 batch 窗口**；PWA 前端限制内完全不依赖引擎在线。

## 执行顺序（VC 整入后）

| 会话 | 内容 |
|---|---|
| **S2a（本轮开工）** | **VB-1/2/3/4**（HTML 打印模板 + CLI `assist sheet html` + PWA 同模板按钮 + KaTeX；**VC-1/VC-2 模板/内容预览切分**——同一会话完成，共用模板对象） |
| S2b | **VC-3/VC-4/VC-5/VC-6**（班级与标签页整班/导入的预览集合 + 勾选成绩列打 tag） |
| S2c | VB-5/6/7（batch zip + 打印教程 + 报告模板复用） |
| S2d | M-E 杂项（xlsx 样式回写/B5 PyPI 发版/手册） |
| 之后 | 学习通 C 组（放最后） |

（以下均为 VC 实现约束：**在线检测**/`fix` 哨兵只在需要引擎的按钮前显示；**不依赖引擎**的预览（VC-1~6）**始终可用**（含手机/未装引擎的 PWA）——为 VC-5 里"导入 csv 解析预览"等零依赖教师体验服务。）
