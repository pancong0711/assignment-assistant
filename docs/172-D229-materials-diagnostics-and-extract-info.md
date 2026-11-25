# D229：课堂资料识别诊断 + 单文件抽取详情

> 日期：2026-11-25
> 状态：**已完成（2026-11-25）**
> 关联：`docs/171-D228`（按文件抽取/识别）
>
> 隐私：只展示本地课堂资料；诊断信息不含 api_key。

---

## 0. 教师反馈

1. PWA 上失败信息太少，无法判断发生了什么；
2. 已升级最新版仍识别失败，怀疑「建议用模型」处 provider 用错；
3. 「抽取选中文件」显示完成，但页面上看不到到底抽出了哪些内容。

---

## 1. provider 的真实语义

默认（不显式选择 provider）确实走**评阅段 `evaluation`**：

```text
provider 空
  → providers.stage_endpoint(ws, "evaluation")
  → 使用评阅段的 provider / model / base_url / key
```

这条逻辑本身是正确的；问题在于页面此前只显示“跟随评阅段配置”，
教师无法看到具体是哪一个 provider、哪个 model、有没有 key。

D229 改进：

- 读取 `/llm/config` 的 `stages.evaluation`，页面明确显示：
  - `显式 provider / model`
  - 或 `评阅段 provider / model（跟随 evaluation）`
- 选择 provider 时若 `has_key=false`，页面直接黄字提醒；
- 识别失败时返回结构化诊断，而不是一行“失败”。

### 诊断字段

`/materials/suggest` 失败响应现在包含：

```json
{
  "ok": false,
  "error": "知识点识别配置未通过 / 知识点识别失败",
  "detail": "具体异常（已脱敏，含 status/provider/base_url/model）",
  "errorType": "LLMAPIError",
  "diagnostics": {
    "request": {"provider": "...", "model": "...", "files": ["..."]},
    "llm": {
      "requestedProvider": "...",
      "provider": "实际 provider",
      "model": "实际 model",
      "baseHost": "实际主机",
      "hasKey": true,
      "warnings": []
    },
    "source": {
      "selectedFiles": ["_source/..."],
      "chars": 12345,
      "imageCount": 0,
      "mode": "text",
      "warnings": []
    }
  }
}
```

新增**不调模型**的检查接口：

```text
GET /materials/suggest-diagnostics?chap=...&provider=...&model=...&file=...
```

PWA 新增「🔎 检查识别配置」按钮，可先检查：

- 实际 provider / model / host / key；
- 选中文件是否已抽取；
- 抽取文本字数；
- 页图数量与识别模式（text / vision）；
- 上下文过长、未抽取文件等警告。

识别诊断 JSON 可在页面直接查看并「复制诊断信息」。

---

## 2. 单文件抽取详情

新增：

```text
GET /materials/extract-info?chap=...&file=...
```

每个已抽取文件行新增「🔍 抽取信息」，弹窗展示：

- 抽取引擎（read-text / python-pptx / pdftotext / officecli / pdftoppm …）；
- 文本字数、幻灯片数、PDF 页数、页图/图片数；
- 文本缓存路径；
- **抽取文本预览**；
- 页图/图片清单及文件是否存在；
- 文本截断提示。

这样教师可以直接判断：

- PPT/PDF 到底有没有抽到文字；
- 是纯文本识别还是走了多模态页图；
- 文件是否抽取成功；
- 识别失败时是“没内容”还是“provider/model/API 问题”。

---

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 默认（provider 空） | 页面明确显示评阅段的 provider/model |
| 2 | 显式选择 provider | 页面显示该 provider 与模型；无 key 有警告 |
| 3 | 选中未抽取文件 | 前置检查失败并指出文件名 |
| 4 | 识别 API 失败 | 显示 error/detail/errorType/诊断 JSON |
| 5 | 点击「检查识别配置」 | 不调模型，返回 provider/source 诊断 |
| 6 | 点击「抽取信息」 | 看到文本预览、页图清单、引擎与字数 |
| 7 | 复制诊断信息 | 复制脱敏 JSON 供排查 |

### 自动化

- 引擎 `test_d131_materials.py`：**42 passed**
  - extract-info、source diagnostics、structured suggest failure、provider/files 透传；
- PWA `selfcheck-d229-materials-diagnostics.mjs`；
- D134 课堂资料上传/移除浏览器回归仍通过；
- 前端 build 通过。
