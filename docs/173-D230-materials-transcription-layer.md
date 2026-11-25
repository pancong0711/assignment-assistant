# D230：课堂资料独立转写层（本地 OCR / 多模态）+ 转写结果可审查

> 日期：2026-11-25
> 状态：**已完成（2026-11-25）**
> 关联：`docs/172-D229`（识别诊断/抽取详情）、`docs/79`（课堂资料）、
> `docs/170-D227`（个性化作业纸分析主线）
>
> 隐私：转写文本保存在本地 workspace；不进入公共仓库。

---

## 0. 需求背景

教师反馈：

1. 当前「抽取完成」但 PDF 是扫描件，`chars=0`、只有页图，看不到任何文档内容；
2. 知识点识别直接吃 12 张页图，失败后既无法定位也无法核对模型读到了什么；
3. 希望区分：文件有没有文字层、是否只是页图、是否已 OCR/转写；
4. DOCX/PPT 的文字提取能力需要说明；
5. 需要独立转写步骤，而不是把“看图理解”和“抽知识点”绑在一次调用里。

核心判断：**抽取 ≠ OCR ≠ 知识点识别。** 原链路缺了可审查的“转写”中间层。

---

## 1. 设计原则

```text
① 抽取（确定性，不花钱）
   原件 → 文字层 / 页图 / 元数据 / 索引

② 转写（显式，可花钱，可重试）
   图片型资料 → 本地 OCR 或视觉模型 → transcript.json/.md

③ 知识点识别
   优先使用转写文本
   没有转写且只有页图时，才允许视觉直读兜底
```

- **转写与识别分离**：教师可先看转写，再决定是否识别；
- **逐文件 / 多选 / 全选**：沿用 D228 选择能力；
- **按页分批**：避免一次请求塞过多图片；
- **失败页可续跑**：已成功的页不重复调用；
- **结果可审计**：索引记录引擎、provider/model、页数、字数、失败页；
- **本地优先**：有 tesseract 时先本地 OCR，缺失/失败再走视觉模型。

---

## 2. 抽取层现状（回答“抽取的意义”）

| 类型 | 当前抽取结果 |
|---|---|
| md/txt | 文字 |
| DOCX | `python-docx` 正文段落 + 表格 |
| PPTX | `python-pptx` 逐页文本框文字 |
| PDF 文字版 | `pdftotext` 文字 + `pdftoppm` 页图 |
| PDF 扫描版 | 文字为空，但有逐页 PNG |
| 图片 | 直接作为图片资料 |

因此“抽取完成”表示**规范化中间产物已生成**，不保证一定得到文字。
对于扫描 PDF，原抽取结果就是 0 字 + N 张页图；D230 新增转写来补足这一步。

---

## 3. 转写数据

每文件生成：

```text
_extract/<文件>.transcript.json
_extract/<文件>.transcript.md
```

`transcript.json`：

```json
{
  "version": 1,
  "chap": "26C2",
  "file": "_source/plan/skjh_hb.pdf",
  "sourceSha256": "...",
  "engine": "mixed",
  "provider": "opencode-go",
  "model": "deepseek-v4.1-flash",
  "pages_total": 12,
  "pages": [
    {"page": 1, "image": "skjh_hb-1.png", "text": "...", "engine": "vision", "error": ""}
  ],
  "failedPages": [],
  "chars": 12345,
  "generatedAt": "2026-11-25 20:00:00"
}
```

索引 `索引.json` 的 source.extract 增加：

```json
{
  "transcript": {
    "engine": "vision",
    "provider": "...",
    "model": "...",
    "text_file": ".../skjh_hb.transcript.md",
    "chars": 12345,
    "pages": 12,
    "pages_total": 12,
    "failedPages": [],
    "generatedAt": "..."
  }
}
```

---

## 4. 引擎实现

`engine/src/assist/files/materials.py`：

- `transcribe_chap_file(...)`
  - `engine=auto`：tesseract 本地 OCR → 不足/失败页走视觉；
  - `engine=local`：只用 tesseract；
  - `engine=vision`：只用多模态；
  - 按 `pages_per_call` 分批；
  - 复用已有页转写，只补缺失页；
  - 写 transcript JSON + Markdown，并回写索引。
- `transcribe_materials(...)`
  - 按勾选文件批量执行；
  - 汇总成功/跳过/失败页。
- `read_source_text()`
  - **优先使用 transcript 文本**，无转写时回退原文字层。
- `source_selection_diagnostics()`
  - 返回 `transcriptFiles`、`needsTranscription`；纯页图无转写时给出明确建议。
- `extract_info()`
  - 返回转写引擎、页数、字数、失败页、提供者/模型和转写预览。

### 多模态分批

默认每批 4 页，要求模型严格输出：

```text
--- page N ---
...
```

批量失败时记录对应页，不阻断其他批；下次只重试缺失页。

---

## 5. CLI / API / PWA

### CLI

```bash
assist materials transcribe --chap 26C2 \
  --file _source/plan/skjh_hb.pdf \
  --engine auto \
  --provider opencode-go \
  --model deepseek-v4.1-flash
```

- `--engine auto|local|vision`
- `--pages-per-call 4`
- `--max-pages 60`
- `--force`

### serve

```text
POST /materials/transcribe
{
  "chap": "26C2",
  "files": ["_source/plan/skjh_hb.pdf"],
  "engine": "auto",
  "provider": "opencode-go",
  "model": "deepseek-v4.1-flash",
  "pagesPerCall": 4
}
```

### PWA

课堂资料页新增：

- 转写引擎下拉：自动（OCR→视觉）/ 仅本地 OCR / 仅 AI 视觉；
- 「📝 转写选中 N 个」按钮；
- 「强制重转写」；
- 文件列表显示：
  - `已转写 X/Y 页 · N 字 · engine`
  - `纯页图，未转写`
  - 失败页列表；
- 「🔍 抽取信息」弹窗显示转写文本预览与转写元数据；
- 「🔎 检查识别配置」在纯页图无转写时提示先转写；
- 实际使用模型处同时显示：
  - 知识点识别 provider/model；
  - 转写 provider/model。

---

## 6. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 文字版 PDF/DOCX/PPT | 已有足够文字层，转写默认跳过 |
| 2 | 扫描 PDF | 转写页图，生成 transcript |
| 3 | tesseract 可用 | 本地 OCR 优先，不花模型费用 |
| 4 | tesseract 不可用/效果为空 | auto 走视觉模型 |
| 5 | 12 页 PDF | 按批发送，不一次塞 12 图 |
| 6 | 某批失败 | 已成功页保留；重跑只补失败页 |
| 7 | 转写完成后识别 | 知识点识别使用 transcript 文本，不再直接看图 |
| 8 | 页面查看 | 可看到转写状态、字数、页数、失败页与全文预览 |

### 自动化

- 引擎新增：
  - 视觉转写生成 transcript；
  - `read_source_text` 优先 transcript；
  - 诊断从 `vision` 变为 `text`；
  - 部分失败后第二次只重试缺失页；
  - 知识点识别使用转写文本。
- 引擎全量 pytest：**2016 passed**；
- PWA `selfcheck-d230-materials-transcribe.mjs`；
- 前端 build + 全量 selfcheck 通过。

---

## 7. 当前边界

- DOCX/PPTX 的正文/表格/文本框文字可以抽取；
- 嵌入图片中的文字、复杂 SmartArt/OLE、公式对象仍可能需要页面渲染后再 OCR；
- 若某 PPTX 只有图片且没有文字、同时本机没有 officecli/LibreOffice 转 PDF，当前也可能没有页图可转写；
- tesseract 对公式和复杂版式精度有限，重要理科资料建议用 `auto/vision` 或人工核对；
- 转写调用可能产生模型费用，因此默认只在教师点击「转写选中」时执行，不自动偷偷跑。
