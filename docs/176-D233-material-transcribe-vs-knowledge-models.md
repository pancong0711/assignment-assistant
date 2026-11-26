# D233：转写模型与知识点识别模型分开设置 + 识别依据核查

> 日期：2026-11-25
> 状态：**已完成（2026-11-25）**
> 关联：`docs/173-D230`（转写层）、`docs/174-D231`（模型下拉/测试）、
> `docs/175-D232`（转写提示词）
>
> 隐私：无学生数据；只调整课堂资料模型配置与识别依据展示。

---

## 0. 教师问题

1. 课堂资料里的「转写」和「AI 建议知识点」用的是同一个模型设置吗？
2. 能否在 PWA 里分别设置？
3. AI 建议知识点是基于转写/抽取内容，还是又把文档从头识别一遍？

---

## 1. 原逻辑

此前 PWA 只有一个 provider/model 选择，同时传给：

- `/materials/transcribe`
- `/materials/suggest`

默认行为：

- 未显式选择 provider 时：
  - 转写跟随 `transcription` 段；
  - 知识点识别跟随 `evaluation` 段。
- 一旦显式选择 provider/model，两边共用同一个显式模型。

因此默认阶段不同，但**显式覆盖时不能分别设置**。

---

## 2. 新逻辑：两套模型设置

PWA 课堂资料页现在有两个独立控件：

```text
转写模型
  provider：跟随 transcription 段 / 显式 provider
  model：该 provider 的候选下拉 / 自定义

识别模型
  provider：跟随 evaluation 段 / 显式 provider
  model：该 provider 的候选下拉 / 自定义
```

- 两套选择分别存 localStorage：
  - `assignment-assistant.materials.transcribeModel.v1`
  - `assignment-assistant.materials.suggestModel.v1`
- 转写请求只使用「转写模型」；
- 知识点识别请求只使用「识别模型」；
- 两套都保留下拉候选 + 自定义输入；
- 分别提供：
  - `🧪 测试转写模型`：多模态探针；
  - `🧪 测试识别模型`：文本探针。

兼容旧版：若旧版只有一个保存值，会先同时复制到两套设置，之后可分别修改。

---

## 3. 知识点识别的依据

`Suggest_knowledge` 的读取顺序：

```text
① 独立转写文本 transcript
      ↓ 没有
② 抽取出的原始文字层 text_file
      ↓ 没有
③ 页图 → 视觉直读兜底
```

当前实现：

- `read_source_text()` **优先读取 `extract.transcript.text_file`**；
- 如果存在转写文件，`use_vision` 强制为 false；
- 不会重新 OCR，也不会重新做一遍转写；
- 只有完全没有转写、也没有文字层时，才把页图送给视觉模型。

识别结果新增：

```json
"source": {
  "mode": "text",
  "basis": "transcript",
  "transcriptFiles": ["_source/plan/a.pdf"],
  "chars": 832,
  "imageCount": 12
}
```

`basis` 取值：

| 值 | 含义 |
|---|---|
| `transcript` | 使用独立转写文本 |
| `text_layer` | 使用抽取出的原始文字层 |
| `vision` | 无转写/无文字，直接视觉直读 |
| `none` | 无可用内容 |

PWA 的「检查识别配置」会明确显示：

```text
知识点识别将基于：转写文本 / 原文文字层 / 视觉直读
```

「AI 建议知识点」确认框也明确说明：

```text
不会重新 OCR/转写；只有完全无转写和文字层时才走视觉直读。
```

---

## 4. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 转写选择 A 模型 | 只影响转写 |
| 2 | 识别选择 B 模型 | 只影响知识点建议 |
| 3 | 两套都选显式 provider/model | 各自请求使用各自配置 |
| 4 | 页面刷新 | 两套选择分别恢复 |
| 5 | 已有 transcript | 识别基于 transcript，不再看图/重转写 |
| 6 | 无 transcript 但有文字层 | 识别基于 text_layer |
| 7 | 两者都没有 | 才回退 vision |
| 8 | 诊断/结果 | 显示 basis 与来源文件 |

### 自动化

- 引擎 `test_d131_materials.py`：**48 passed**
  - transcript 优先、basis=transcript、有转写时不走 vision；
- PWA `selfcheck-d233-material-model-separation.mjs`；
- 前端 build / selfcheck 全绿。
