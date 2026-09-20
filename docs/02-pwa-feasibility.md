# 02 — PWA 化可行性分析（"Python 程序能否套网页壳"）

## 结论先行

**"纯 PWA 网页壳直接包住现有 Python 程序"不可行；"PWA 静态前端 + Python CLI 引擎
分层共生"完全可行，且正是本项目两个旧代码库的自然形态。**
建议：CLI 为本体（source of truth），PWA 是 CLI 之上的交互层。

## 1. 硬性技术边界（事实，不是偏好）

| 需求 | 纯静态 PWA 能否 | 原因 |
|---|---|---|
| 题库增删改查、搜索 | ✅ | OPFS/IndexedDB，数据全本地 |
| 作业纸版式设计与所见即所得预览 | ✅ | HTML+CSS `@page` 即可精确分页 |
| 作业纸导出/打印 | ⚠️ | 浏览器打印可出 PDF，但页边距/字体控制弱 |
| 横版 A4 双题版式预览 | ✅ | CSS 可控 |
| 学生成绩评分分组 | ⚠️ | 等逻辑可在 JS 重写；大量 xlsx 处理仍适合 Python |
| 作业纸打印级 PDF + 水印 | ❌（静态不可） | 需 reportlab/字体；Pyodide 里 reportlab 基本不可用，pdflatex 需完整 TeX = 上百 MB 不同部署 |
| **学习通登录/下载/上传/打分** | ❌ | 浏览器沙箱禁止跨域操控第三方站点，且学习通页面结构需 Playwright/UI 自动化；无绕过方案 |
| 本地批量图片处理、SSE 日志、长任务 | ❌/⚠️ | PWA 页面受限；可用 OPFS 缓解部分 |
| 保存 apikey/token | ⚠️ | 放浏览器存储可（本地不出网），但调 LLM API 有 CORS 限制，部分供应商可行（OpenAI/DeepSeek 允许浏览器直连），需用户自担 |

## 2. Pyodide（浏览器内 Python）评估

Pyodide/WASM 可以让纯计算 Python 在浏览器跑（pandas 有些 wheel 可用），但：

- `reportlab`（纯 Python 组件理论上可被打包，但依赖 C 扩展/字体生态，工程量大）；
- `pdflatex` 完整 TeX 发行版：WASM 途径（等)体积巨大且中文/CJK 字体配置复杂；
- `Playwright`：根本不可用（需要真实进程与浏览器内核）；
- 需要网络调用大模型 API：可行但受 CORS + 打包体积限制。

**结论：Pyodide 只适合做"锦上添花"（比如在浏览器里跑纯 Python 小逻辑），
不能作为本项目运行时。不要押注它。**

## 3. 推荐路线：CLI 本体 + 双形态 UI

1. **Engine = Python 包（uv 管理）**，从两个旧项目提炼：
   `xuexitong`（2601 的 auth/homeworks/browser）、`paper`（2603 的 kbtools/
   reportlabtools/watermark）、`grading`（2601 llm/evaluator）、`files`。
   全部先做成熟 CLI（click 命令组），非常适合 AI 代理直接调用。
2. **UI 后端 = `assist serve`**：本地起 HTTP 服务（沿用 2601 webui.py 的成熟经验：
   端口探测、SSE 日志、sendBeacon 自停），前端是同一份 PWA 静态页；
   —— 这样 PWA 不需要服务器，部署在 GitHub Pages 也能工作；
   引擎在线时前端自动升级为 Companion 模式。
3. **数据接口即文件**：引擎读写的是教师本地目录（kb/、tasks/、grades/...），
   前端用 File System Access API 直接读写同一目录（同一台机器时），
   或走引擎 API。两种路径指向同一份文件，不做第二真源。
4. **不引入云后端**。服务器零依赖，仓库即产品。

## 4. 开发顺序建议（CLI 先行的落点）

| 阶段 | 内容 |
|---|---|
| 0 | 仓库骨架、MIT、脱敏 gitignore、CI（脱敏检查） |
| 1 | Engine：包结构 + `files`（kb JSON↔xlsx）+ `paper` 竖版迁移 + **横版双题版式** |
| 2 | App：PWA 骨架（manifest/SW/OPFS），题库编辑（xlsx 读写为主，见 05-D3）+ 作业纸设计 + 预览/导出 |
| 3 | Engine：`grade` 迁移（转录→评阅→报告），App 批阅工作台静态部分 |
| 4 | Companion：`assist serve` + 前端在线检测 + 学习通辅助/上传/公告；PWA「环境体检/安装向导」页（05-D5） |
| 5 | 打磨：导入导出 zip 包、错误恢复、教师文档 |

## 5. 风险清单

- **CORS/浏览器直连 LLM API**：不同供应商响应头不一；Companion 模式下由引擎代理请求即可根治（key 只在引擎侧本地文件）。
- **学习通页面改版**：沿用 2601 的经验（已有 v1/v2/v3 多套兜底上传策略），自动化代码天然脆弱期，需保留版本化适配层。
- **OPFS 兼容性**：File System Access API 在 Chrome/Edge 完备，Firefox 大部分不支持——需要在"纯静态"功能里给 Safari/Firefox 用户降级为"下载/上传文件"交互（可用）。
- 双路径一致性：同一逻辑在 JS（预览）与 Python（成品 PDF）复算时，需用同一数据契约（JSON 题库 schema + 版式描述 JSON），反差只能源自渲染器差异，不来自数据。
