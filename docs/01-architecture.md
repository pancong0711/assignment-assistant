# 01 — 宏观架构设计（讨论稿 v0.1）

> 本文档是合并 2601playwright（AI 辅助批阅）与 2603paperDesign（作业纸设计）
> 为统一项目 `assignment-assistant` 的架构讨论稿。只讨论，未动手开发。

## 1. 项目定位

- 单一 PWA（可作为静态站点发布，GitHub Pages / 用户自托管），教师浏览器打开即用；
- 数据全部保存在教师本地（浏览器 OPFS / IndexedDB + 本地文件导入导出）；
- 配套 **Python CLI 引擎**：承担浏览器无法做的事（学习通自动化、LaTeX 渲染、
  批量批阅任务），也是 AI（代理）最顺手的操作入口；
- 长远目标：更多教师零门槛使用，仓库 MIT 协议，仓库内不含任何题库数据、
  学生数据、批阅记录、apikey/token。

## 2. 两层架构：Engine（引擎）+ App（应用）

```
┌────────────────────────────────────────────────────────┐
│                App 层（PWA 前端，纯静态可部署）           │
│  学习通辅助 │ 作业纸设计 │ AI批阅工作台 │ 本地文件管理 │ 设置 │
│  数据层：OPFS/IndexedDB（题库、任务、批阅结果、导出包）     │
├────────────────────────────────────────────────────────┤
│                Engine 层（Python CLI + 可选本地服务）      │
│  xuexitong:   登录/查看/下载/上传/公告（Playwright）       │
│  paper:       样题渲染(LaTeX)/分组/排版(reportlab)/水印    │
│  grading:     转录(多模态LLM)→评阅(LLM)→报告              │
│  files:       题库xlsx/json 读写、导入导出、归档           │
├────────────────────────────────────────────────────────┤
│              数据文件（教师目录，始终在本地）               │
│  kb/  sheets/  tasks/  grades/  roster/  exports/        │
└────────────────────────────────────────────────────────┘
```

两种运行形态，同一套逻辑：

1. **静态模式**（默认，任何老师双开即用）：浏览器内完成题库编辑、
   作业纸设计与版式预览、题库/作业配置导入导出、批阅结果查看。
2. **Companion 模式**（教师安装 Python 环境/下载 CLI 后）：前端检测
   `http://127.0.0.1:<port>` 引擎是否在线，在线则解锁学习通自动化、
   批量 AI 批阅、LaTeX 精确排版等扩展功能。

> 关键原则：**静态模式下功能可有降级，但不出现死页面**。
> 例如静态模式里作业纸用 CSS 分页预览 / 浏览器打印输出 PDF；
> companion 模式下由引擎用 reportlab/LaTeX 输出打印级 PDF 并带水印。

## 3. 功能模块划分（对应用户提到的 4 块）

### M1 学习通辅助（Engine 为主）
- 登录（二维码/网页 session，由 Playwright 承载 —— 见 02-PWA 可行性：浏览器
  PWA 无法跨域操作学习通，此模块必须留 Engine）；
- 课程/班级/作业浏览与 ID 字典（沿用 2601 的 ids_collector 思路）；
- 作业下载（学生图片、状态）、批阅结果上传（评语+图片）、打分；
- 后续：发公告/通知（含附件）。
- App 侧职责：任务清单、进度展示、日志流、参数表单；生成"任务指令"
  提交给 Engine（或教师手动复制命令）。

### M2 作业纸设计（核心，App 为主）
- 题库管理：xlsx ↔ JSON 双轨（Engine `files` 模块互转；App 内 JSON 增删改查，
  含图片附件存 OPFS），兼容现有列结构
  `id/content/img_path/page/related/type/solution/note`，但内部以 JSON 为源，
  xlsx 为导入/导出格式（向量：**JSON 为 source of truth**）；
- 作业纸构建：选章、选题、分层标签（copy/distinguish/innovation/qa/summary/
  copySp/copyOnly/translation…）、页眉页脚（课程名/班级/学期/姓名学号栏/水印）；
- 版式：竖版 A4（现状）；**新增横版 A4 左右两半各一题**（reportlab
  BaseDocTemplate 支持 landscape + 两 frame，改动小）；
- 预览：静态模式用 HTML/CSS（@page 分页）真实预览，题目图片直接渲染；
- 水印/防顶替：每生唯一水印标识继续保留（PDF 打印由 Engine 完成）。

### M3 AI 批阅（核心，Engine 为主 + App 工作台）
- 流程沿用 2601：下载图片 → 多模态转录(图片→Markdown/LaTeX) → LLM 评阅
  → 报告(MD/HTML/PNG) → 上传；
- **新增的协同点（也是合并的最大收益）**：作业纸上打印的题干与参考答案
  （`solution` 列）可作为评阅的参照系，LLM 评阅 prompt 可精确绑定本题
  内容与评分点 —— 旧批阅项目对学生可能写的是另一题（顶替）会更敏感；
- 评阅规则按题分层标签差异化（copy 只查完整性、qa/summary/innovation 各有侧重），
  迁移 2601 evaluator 的标签规则；
- 与 M1、M2 共用同一作业任务实体（见 04）。

### M4 本地文件管理
- App 端：File System Access API（Chrome/Edge 稳定支持，写教师指定目录）+
  导出包（zip：题库 JSON+图片+配置+批阅记录）；
- Engine 端：`assignment files` 命令族：`import xlsx/export xlsx`、
  `import zip/export zip`、`gc`（清理转写/评阅临时产物）；
- 学生名单（roster）与成绩分组沿用 2603 的 exceltools/student.py。

## 4. 仓库布局（monorepo 提议）

```
assignment-assistant/
  LICENSE            MIT
  README.md
  docs/              本文档系列
  engine/            Python 包（uv 管理）
    src/assist/  xuexitong/  paper/  grading/  files/  serve/
    pyproject.toml
  app/               PWA 前端（Vite + TS，可 GitHub Pages 纯静态部署）
    public/  src/  （含 manifest、service worker）
  tools/             CI/脱敏检查脚本
  .gitignore
```

引擎入口统一：`assist`（click 命令组，继承两个旧项目的 cmd 结构）：
`assist serve`（本地 http API + 静态托管 app 构建产物）、
`assist xuexitong ...`、`assist paper ...`、`assist grade ...`、
`assist files ...`。

## 5. 待定的开放问题（请老师拍板）

1. 前端技术栈是否接受 Vite(+React/Vue)；无框架纯原生也可，但状态管理会累。
2. Companion 模式引擎通信协议：本地 HTTP（推荐，沿用 webui.py 经验）还是
   仅"前端导出任务包 → CLI 执行 → 前端导入结果包"的离线握手？
   （可两者都支持：HTTP 优先，导出/导入包为降级路径。）
3. 题库唯一真相源定为 JSON 是否可接受？xlsx 保留为导入导出格式。
4. 多教师/多班级的数据隔离粒度：单目录单学期，还是单目录多学期？
5. 学习通"上传批阅"是否保留自动打分（旧版可打分+传图），还是先只传评语？
6. MIT 协议 + 第三方库（reportlab、Playwright、pydantic/pyyaml…）以
   NOTICE/依赖清单方式声明，是否还需在 README 单列？
