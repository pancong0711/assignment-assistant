# D90 任务需求单：LLM Playground（AI 辅助批阅选项卡内的大模型试验台）

> 日期：2026-10-16
> 状态：**P1–P5 全部完成**（2026-10-16）。验证：engine pytest 357 passed、PWA build+selfcheck、脱敏扫描全绿；真机实测待用户。
> 关联：`docs/39-D86-...`（provider/两段式/key 安全）、`docs/42-D89-...`（AI 集中选项卡）、
> `engine/src/assist/grading/llm.py`（chat / chat_with_images / batch_chat）、
> `engine/src/assist/grading/llm_batch.py`（provider batch API）。

## 1. 目标

在「AI 辅助批阅」选项卡内新增 **Playground**：单次调用大模型做试验——
把 **问题文本 + 图片 + 文档（pdf/docx/doc/文本）** 发给模型，呈现回复。
**不做多轮对话**（无 chat history 上下文）；支持 batch 发送（时效性不强）；
**问题与答案本地留档**，并提供**记录管理**（建文件夹/移动/删除）与**勾选查看**。

## 2. 功能范围

### 2.1 单次调用
- 输入：提问文本（必需）+ 可选附件（图片 / 文档）。
- 选 provider + 模型（复用 D86 已配置的 provider 列表；可填模型名）。
- 参数：temperature、max_tokens（可选，按缺省）。
- 输出：模型回复原文（Markdown/LaTeX 原样呈现）。
- **无对话上下文**：每次都是独立 system+user 单次请求。

### 2.2 附件与提取
- **图片**（png/jpg/webp/gif）→ base64 data-url（与 `chat_with_images` 同口径）。
- **文档**（pdf/docx/doc/txt/md）→ 先抽文本再拼进上下文：
  - pdf → `pypdf` 抽文本（已有依赖）；
  - docx → 解压 `word/document.xml` 抽 `<w:t>`（不引新依赖）；
  - doc（旧二进制）→ **不支持直接解析**：提示用户转 docx/pdf（或后续接 LibreOffice，标「待定」）；
  - txt/md/csv → 直读。
- 附件上传：PWA base64 → 引擎落 `<ws>/.runtime/playground/uploads/<ts>/`，与 notice-uploads 同模式。

### 2.3 Batch 发送
- 一组 question（每行一条 / 或「多问题」模式）→ 逐条独立调用（复用 `batch_chat` 受控并发）。
- **可选**走 provider batch API（`llm_batch.py`：build jsonl → submit/poll/download）；
  默认走并发普通调用（立即可得），provider batch 作为高级项。
- 每条结果同样落档。

### 2.4 本地留档 + 记录管理
- 落盘 `<ws>/playground/records/<id>.json`（工作区，便于长期维护/跨设备；不入库）。
- 结构：
  ```json
  { "id": "20261016-153000-ab12", "folder": "默认",
    "at": "2026-10-16 15:30:00",
    "provider": "aliyun", "model": "qwen-max", "temperature": 0.3,
    "question": "……", "attachments": ["uploads/…/a.pdf"],
    "answer": "……", "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    "mode": "single|batch", "batchGroup": "", "error": "" }
  ```
- **文件夹**：`<ws>/playground/folders.json`（列表）；记录用 `folder` 字段归属。
- 管理：新建文件夹、把记录**移动**到文件夹、**删除**（单条/批量/整夹）；**勾选查看**（多选 → 批量删除/移动；逐条点开看 Q/A）。
- 引擎离线时：记录可退回 localStorage（仅本浏览器），界面明确提示。

## 3. 端点 / CLI

| 类型 | 名称 | 说明 |
|---|---|---|
| serve | `POST /playground/ask` | 单次调用（返回 job_id，流式；与 ai-run 同机制） |
| serve | `POST /playground/batch` | 多问题（并发或 provider batch） |
| serve | `POST /playground/upload` | 附件 base64 → `<ws>/.runtime/playground/uploads/` |
| serve | `GET /playground/records` | 列出记录（含文件夹） |
| serve | `POST /playground/record` | 保存/删除/移动记录 |
| serve | `GET /playground/folders` / `POST /playground/folder` | 文件夹 CRUD |
| CLI | `assist playground ask --question --attach … --provider … [--model]` | 单次；默认写档 |
| CLI | `assist playground batch --questions-file …` | 批量 |
| CLI | `assist playground records list|move|rm` + `folders new|rm` | 记录管理 |

## 4. UI 位置

「AI 辅助批阅」选项卡 → 新增 **⑧ Playground** 区（与其他 AI 功能并列，符合 D89「AI 集中」）：
- 左：提问框 + 附件（拖入/选择）+ provider/模型/参数 + 「提问」/「批量」按钮；
- 右：回复区（Markdown/LaTeX 渲染，复用现有 KaTeX）；
- 下：**记录管理**（文件夹树 + 勾选列表 + 批量删除/移动 + 点开查看 Q/A）。

## 5. 安全（延续 D86/D87）

- 复用 provider/key 管理（key 掩码、secrets.json 0600、日志绝不记 key）；
- 附件只接受白名单扩展名；文件名 basename 清洗防路径穿越；落在 workspace 下；
- 记录落 workspace（不入库）；PWA 不缓存 key。

## 6. 分期实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| P1 | 引擎：`playground/` 模块（单次调用 + 附件抽文本 pdf/docx/txt + 落档） | `engine/src/assist/playground/`（ask/extract/store）+ 单测 | ✅ |
| P2 | 引擎：记录/文件夹 CRUD + batch（并发）+ provider batch 可选 | 同上 + `batch` + 单测 | ✅ |
| P3 | serve 端点（ask/batch/upload/records/folder）+ CLI `assist playground …` | `serve.py` + `cli.py` + 单测 | ✅ |
| P4 | PWA：⑧ Playground 区（提问/附件/回复）+ 记录管理（文件夹/勾选/移动/删除） | `PlaygroundPanel.vue`（挂 AiGradingPanel） + `engineClient.ts` + **provider/模型选择** | ✅ |
| P5 | 文档（docs/04/13/15/39/43）+ 验证 + 去敏 push | 文档 + CI | ✅ |

## 7. 待定项（可随时改）

- **D1**：旧版 `.doc` 是否要支持？（默认：提示转 docx/pdf，不引 LibreOffice）
- **D2**：batch 默认走「并发普通调用」（快）还是「provider batch API」（便宜但慢）？（默认：并发，batch API 为高级开关）
- **D3**：回复是否要「重新生成/编辑问题再问」？（默认：提供「复制到提问框再问」，不存对话树）
- **D4**：记录是否要导出（json/zip）？（默认：暂不做，后续可加）

## 8. 验收

- Playground 可发「问题 + 图片 + 文档」，拿到回复（文本正确渲染，含 LaTeX）；
- 无多轮上下文（每次独立）；
- batch 可一次发多条并逐条落档；
- 记录落 `<ws>/playground/records/`；可建文件夹、移动、删除（单条/批量）、勾选查看；
- 复用 provider/key 安全；附件/记录均在 workspace 内、白名单校验；
- engine pytest / PWA build+selfcheck / 脱敏扫描 全绿。
