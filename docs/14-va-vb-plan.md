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
