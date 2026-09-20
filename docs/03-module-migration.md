# 03 — 模块迁移映射（旧 → 新）

## 2603paperDesign（作业纸）迁移

| 旧模块/文件 | 新位置 | 处置 |
|---|---|---|
| `src/paperdesign/kb_reader/loader.py` | `engine/src/assist/files/kb_io.py` | 重构：JSON 为主数据源，xlsx 仅导入/导出 |
| `src/paperdesign/kbtools.py` | `engine/src/assist/paper/kb.py` | 选题/抽题逻辑迁移，去 pandas 硬依赖（可留） |
| `src/paperdesign/latextools.py` | `engine/src/assist/paper/latex.py` | 样题图渲染保留；作为可选渲染器 |
| `src/paperdesign/output/reportlabtools.py` | `engine/src/assist/paper/layout.py` | 竖版迁移 + 新增横版双题 frame |
| `src/paperdesign/output/watermark.py` | `engine/src/assist/paper/watermark.py` | 直迁，参数化样式 |
| `src/paperdesign/student/`（student.py/exceltools.py） | `engine/src/assist/roster/` | 直迁：点名册/成绩分组/标签 |
| `src/paperdesign/wizard/`（webserver.py/interactive.py） | 被 app/ 前端 + `assist serve` 取代 | 逻辑参考后废弃 |
| `configs/assignment_cfg_*.json` | `tasks/*.json` | 配置格式合并（见 04） |
| 根 `cli.py`（click） | `engine/src/assist/cli.py` | cmd 结构保留：`assist paper ...` |
| `kb/*.xlsx`（题库，含图片 kb/fig） | **不入库**（脱敏） | 教师本地资产管理，提供"示例空库"模板进 repo |
| `tools_dev/2605-rainclass-analysis` | `engine/src/assist/roster/rainclass.py`（可选） | 签到分析延后 |

## 2601playwright（批阅）迁移

| 旧模块 | 新位置 | 处置 |
|---|---|---|
| `src/xuexitong/`（auth/browser/courses/homeworks） | `engine/src/assist/xuexitong/` | 直迁，session 管理独立化（登录态存本地 profile，不同步） |
| `src/uploader.py`、`submit_v2/v3.py`、`submit_runner.py` | `engine/src/assist/xuexitong/upload_*` | 三代上传策略合并/择优保留 |
| `src/llm/transcriber.py` | `engine/src/assist/grading/transcribe.py` | 直迁（多模态转录） |
| `src/grader.py`、`src/llm/evaluator.py` | `engine/src/assist/grading/evaluate.py` | 直迁，改造 prompt 绑定作业纸题目与 solution（合并收益点） |
| `src/report_generator.py` | `engine/src/assist/grading/report.py` | 直迁（MD/HTML/PNG） |
| `src/question_loader.py`、`ids_collector.py`、`browser_helper.py`、`config.py` | 对应合并到 `xuexitong/`、`config.py` | 精简 |
| `webui.py` + `webui/` | `engine/src/assist/serve.py`（后端协议参考） | 前端由 app/PWA 取代 |
| `test/`（学生作业图片、转录、评阅） | **绝不入库**（脱敏） | 本地保留为真实数据回放测试集，供开发比对 |
| `.env`、`config*.json`、`xuexitong-ids.json`、`state.json` | **绝不入库** | 模板/脱敏样例进 repo |

## 合并带来的新增（两旧项目没有的）

1. **数据契约统一**：一份"作业任务 JSON"同时驱动 作业纸生成 与 批阅——
   评阅时知道每题题干、参考答案、分层标签，prompt 精确定向；
   顶替作业（学生上传他不曾得到的题目）可当场给出高置信度警告。
2. **横版 A4 双题版式**（reportlab landscape + 两 frame）。
3. **网页题库 CRUD**（旧为手编 xlsx）。
4. **引擎本地 API（assist serve）** 让 PWA 前端驱动引擎。
5. **公告/通知发布**（学习通，含附件）。

## 旧项目数据资产整理建议

`_legacy/`（本工作区）内含原始项目与数据，仅作开发参考，永不进入 git。
在后续阶段建立 `fixtures/`（完全合成/脱敏的数据样例：示例题库、
假学生名单、合成手写图）用于测试与文档，避免真实学生数据泄漏。
