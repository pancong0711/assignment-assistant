# D106 任务需求单：转录图片分段压缩 + 转录 SVG 重绘（默认关）

> 日期：2026-10-25
> 状态：**实施中**
> 关联：`docs/57-D105`（md+html 答案）、`docs/51-D98`（两段式隔离）、`docs/39-D86`（AI 批阅）

## 1. 问题

`llm.py:301` 直接把原图 base64 送模型，**无压缩、无体积检查**：

```python
b64 = base64.b64encode(path.read_bytes()).decode("utf-8")   # 原样发送
```

手机照片 3~8MB，base64 后 +33% → 单张 4~10MB，导致：请求体超限（413）、
视觉 token 浪费、批量慢。

## 2. 分段压缩策略（用户拍板）

| 原始长边 / 体积 | 处理 | 理由 |
|---|---|---|
| 长边 ≤ 2000px **且** ≤ 2MB | **原样发送** | 已足够清晰，无损 |
| 2MB ~ 8MB | 等比缩到**长边 2000px**，JPEG q88 | 保留细节 |
| > 8MB | 等比缩到**长边 1600px**，JPEG q85 | 2MB 内可辨小字 |
| 手绘线稿（PNG 且体积可接受） | 保持 PNG | 线条更清晰 |

**识图底线（常识区间）**：长边 ≥1280px、短边 ≥900px、体积 ≥300KB；
低于 120 DPI 等价时手写小字不可辨。

**必须保留原图**：压缩只作用于「送去模型的副本」，原文件不动（复核/归档）。
在 `transcript.json` 记录 `{orig_bytes, sent_bytes, sent_side, strategy}`。

## 3. PWA 提供「原图 / 压缩」选择（便于对比转录效果）

- 设置项 `transcription.imageMode = 'auto' | 'original'`
  - `auto`（默认）：按 §2 分段压缩
  - `original`：原图直发（老行为，用于对比测试）
- UI 位置：AI 批阅面板「转录设置」区，带说明文字。

## 4. 转录 SVG 重绘（默认关）

- 设置项 `transcription.svgRedraw = false`（默认关）；
- 开启后 `TRANSCRIPTION_PROMPT` 追加指令：
  > 「学生手绘图请用内联 `<svg>` 重绘：黑白线稿、`viewBox` 定宽 ≤ 200×150、
  > 最多 20 个图元、不引用外部资源；无法可靠重绘时改用文字描述 `[手绘图表：…]`。」
- UI 旁**明确说明含义**：
  > 「让 AI 用手绘线稿重绘学生的示意图（SVG）。仅建议几何/受力题开启：
  > 会增加耗时与输出 token，且 AI 可能画得不准确，请人工核对。」

## 5. 任务分解

| # | 任务 | 文件 |
|---|---|---|
| T1 | `compress_for_model(path, mode)`：分段策略 + 返回策略元数据 | `engine/src/assist/grading/imageprep.py`（新增） |
| T2 | `chat_with_images` 使用压缩副本；记录元数据 | `grading/llm.py` |
| T3 | `transcripts/*.json` 增 `image_info[]` | `grading/transcribe.py` |
| T4 | 设置项 `imageMode` / `svgRedraw`（workspace settings + PWA） | `workspace.py`、`AiGradingPanel.vue` |
| T5 | prompt 追加 SVG 重绘指令（仅开启时） | `grading/prompts.py` |
| T6 | 测试：策略分档、原图保留、元数据、prompt 开关 | `engine/tests/` |

## 6. 回滚

`imageMode='original'` + `svgRedraw=false` = 完全回到旧行为。

---

## 7. 实施记录（待填）

## 7. 实施记录（2026-10-25）

### 7.1 完成项

| # | 内容 | 文件 |
|---|---|---|
| T1 | `compress_for_model(path, mode)`：分段策略 + 元数据 + 原图不变 + 解码失败兜底 | `grading/imageprep.py`（新增） |
| T2 | `chat_with_images` 改用压缩副本；`LLMClient.image_mode`（读 `ASSIST_IMAGE_MODE`） | `grading/llm.py` |
| T3 | `transcripts/*.json` 增 `image_info[]`（strategy/orig_bytes/sent_bytes/sent_side） | `grading/transcribe.py` |
| T4 | serve 透传 `imageMode`/`svgRedraw` → 环境变量；PWA 设置区 | `serve.py`、`AiGradingPanel.vue` |
| T5 | `transcription_prompt(svg_redraw)` + `_system_prompt()`（默认关） | `grading/prompts.py`、`transcribe.py` |

### 7.2 实测压缩效果

| 输入 | 输出 | 策略 |
|---|---|---|
| 800×600 JPEG（8KB） | 原样 8KB | `passthrough` |
| 4000×3000 JPEG（188KB） | 18KB（长边 2000） | `jpeg-q88` |
| `mode='original'` | 原样 188KB | `original` |

### 7.3 UI 说明（用户要求"讲清楚 SVG 重绘含义"）

面板内明确说明：SVG 重绘 = 让 AI 用内联 `<svg>`（黑白线稿、≤20 图元）
重画学生的示意图/受力图/电路图；**仅建议几何/受力/电路类开启**；
会增加耗时与输出 token，且**可能画不准确，需人工核对**。

### 7.4 验证

engine pytest 新增 **9 例**（分档/passthrough/original 不改原图/PNG 线稿/元数据/解码失败/prompt 开关/env）。
