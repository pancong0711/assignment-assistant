# D231：课堂资料模型选择下拉化 + 显式模型测试

> 日期：2026-11-25
> 状态：**已完成（2026-11-25）**
> 关联：`docs/172-D229`（识别诊断）、`docs/173-D230`（转写层）
>
> 隐私：模型测试不记录学生数据；仅发送固定探针文本/图片。

---

## 0. 反馈

1. 课堂资料的 provider/模型选择 UI 不如 AI 辅助批阅：模型只能手填；
2. 希望改为与 AI 辅助批阅一致：**下拉候选 + 可切自定义**；
3. 最新诊断中 provider、session header、转写文本都已就绪，但知识点识别仍可能失败，
   需要一个能直接验证 provider/model 的测试入口。

---

## 1. 最新诊断结论

教师提供：

```json
{
  "llm": {
    "provider": "opencode-go",
    "model": "deepseek-v4.1-flash",
    "basePath": "/inference/go/openai/v1",
    "hasKey": true,
    "headerNames": ["x-opencode-session"],
    "hasSessionHeader": true,
    "warnings": []
  },
  "source": {
    "chars": 832,
    "imageCount": 12,
    "mode": "text",
    "transcriptFiles": ["_source/plan/skjh_hb.pdf"],
    "needsTranscription": false
  }
}
```

说明：

- provider/model/key 基础配置存在；
- opencode-go 会话头已配置；
- 转写已完成，知识点识别会走**文本模式**；
- 因此“provider 没传”“session 头缺失”“仍直接把 12 张图塞给文本模型”这几种原因已被排除。

接下来需要看真正的 API 失败 `detail`，或直接跑模型探针测试。

---

## 2. 模型选择 UI

课堂资料页模型控件改为：

```text
provider 下拉
  ├─ （跟随评阅配置）
  └─ opencode-go / 其他 provider

模型下拉（来自 providers[].models[]）
  ├─ （默认模型）
  ├─ deepseek-v4.1-flash
  └─ ...
  [自定义] ←→ [用下拉]
```

- 默认走下拉；
- 点「自定义」切为输入框，可填写未记录的模型名；
- 自定义状态与选择一起存 localStorage；
- provider 切换后，若当前模型不在新 provider 的候选列表，自动清空为默认；
- 同时显示：
  - 知识点识别实际 provider/model（默认跟随 evaluation 段）；
  - 转写实际 provider/model（默认跟随 transcription 段）。

---

## 3. 显式模型测试

新增按钮：

```text
🧪 测试模型
```

行为：

- 若页面已显式选择 provider/model：用该 provider/model；
- 若未显式选择：分别测试 transcription / evaluation 两段的默认配置；
- 两次真实探针：
  1. 文本探针：`只回复两个字：收到。`
  2. 多模态探针：发送 128×128 双色图，问图片主要颜色；
- 返回逐段：
  - provider / model / base_url；
  - 成功耗时与回复；
  - 失败原文（截断到可读长度）。

`/llm/test` 已扩展支持显式 `provider/model`：

```json
{"stage":"both","provider":"opencode-go","model":"deepseek-v4.1-flash"}
```

这样可以区分：

- provider 本身不可用；
- 文本请求可用，但图片请求不可用；
- 模型名不支持；
- session/路由/鉴权错误；
- 知识点识别 prompt/解析层面的问题。

---

## 4. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | provider 有 models[] | 模型显示为下拉候选 |
| 2 | 点「自定义」 | 切为输入框，可填任意模型名 |
| 3 | 点「用下拉」 | 切回候选列表 |
| 4 | 切换 provider | 不兼容的旧模型清空，避免错配 |
| 5 | 测试显式 provider/model | 文本与多模态探针都使用该配置 |
| 6 | 探针失败 | 显示 provider/model/base_url/error 原文 |
| 7 | 转写/识别模型来源 | 页面分别显示 evaluation 与 transcription 实际配置 |

### 自动化

- PWA `selfcheck-d231-materials-model-picker.mjs`；
- 前端 build + selfcheck 全绿；
- 引擎全量 pytest 仍通过。
