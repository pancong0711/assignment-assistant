# D125 缺陷修复：转录用了评阅段的 base_url/key（配置错配）+ 分步批阅

> 日期：2026-10-29
> 状态：**已执行完成（2026-10-29）**；验证见 §6
> 关联：`docs/05-D86`（两段式 provider）、`docs/32-D80`（批阅）、`docs/13`（D82-F 旧覆盖）

## 1. 现象

```
AI 批阅中：转录失败[陈蘇韩]（重试3次）：
LLM API 请求失败(status=400):
{"error":{"type":"server_error","message":"Upstream request failed: Model is unavailable."}}
```

但**同一个 provider/模型在 Playground 里可以正常回复**。

用户配置：

| 段 | provider | 模型 |
|---|---|---|
| 转录 | `aliyun-official` | `qwen3.7-flash` |
| 评阅 | `opencode-go` | `deepseek-v4.1-flash` |

## 2. 根因（已实测确认）

`grading/llm.py::_settings_from_workspace()`：

```python
ep = _prov.stage_endpoint(ws, use_stage)      # stage="" → use_stage 默认 "evaluation"
return {
    **ep,                                      # ← base_url / api_key 全部来自**评阅段**
    "transcription_model": <转录段模型名>,        # ← 只搬了模型名
    "evaluation_model":    <评阅段模型名>,
}
```

`LLMClient` 内部：

```python
def _step_base_key(self, step):
    cfg = self._step_cfg(step)                 # 查 llm.transcription（旧结构 D82-F）
    base = cfg.get("base_url") or self.base_url   # ← 空 → 用评阅段 base_url
    key  = cfg.get("api_key")  or self.api_key    # ← 空 → 用评阅段 key
    model = cfg.get("model") or (transcription_model if step=="transcription" else ...)
```

实测结果：

```
transcription 段应发往：base=https://aliyun…/v1  key=<aliyun key>  model=qwen3.7-flash
实际发出：            base=https://opencode…/v1 key=<opencode key>  model=qwen3.7-flash
                                            ↑ 错配 → "Model is unavailable"
```

**Playground 正常**是因为它只走 `evaluation` 段，base/model/key 三者配套。

### 2.1 本质：两套配置结构并存且只搬了一半

| 结构 | 用途 |
|---|---|
| `llm.stages.{transcription,evaluation}.{provider,model}` | **新**（D86 两段式，PWA 在用） |
| `llm.transcription.{base_url,api_key,model}` | **旧**（D82-F 覆盖） |

新结构的**模型名**被搬进了旧字段，但 provider 对应的 **base_url/api_key 没搬** → 错配。

## 3. 修复

### 3.1 每段一套完整 endpoint

`_settings_from_workspace()` 改为返回**两套完整配置**：

```python
{
  "transcription": {base_url, api_key, model, type, cmd, input_mode, output_mode, timeout_s},
  "evaluation":    {base_url, api_key, model, type, cmd, ...},
}
```

`_step_base_key(step)` **只读对应那一套**，不再回退到 `self.base_url/self.api_key`；
`type=command` 的 provider 也按段区分（`_request_via_command` 需按 step 取 cmd）。

### 3.2 兼容旧配置

- `llm.stages` 缺失 → 回落旧单层 `llm.base_url/api_key/model`（同段共用）；
- `llm.transcription`（D82-F 旧覆盖）仍生效，但**优先级低于** `llm.stages`。

### 3.3 报错可诊断

LLM 请求失败的报错追加：`（provider=…, base_url=…, model=…, step=…）`（key 绝不出现）。

### 3.4 确定性错误不重试

`400` / `Model is unavailable` / `invalid_request_error` 等 → **不重试**，立即失败。

### 3.5 分步批阅（PWA + CLI）

| 按钮 | 动作 | CLI |
|---|---|---|
| 🔍 测试配置 | 分别对**转录段**（1 张内置小图）与**评阅段**（纯文本）各发一次最小请求，返回所用 provider/model/base/耗时 | `assist llm test [--stage transcription\|evaluation]` |
| ① 仅转录 | 只跑 transcribe | `grade --steps transcribe`（`--rerun transcribe` 需已有产物） |
| ② 仅评阅 | 只跑 evaluate（要求转录存在） | `grade --steps evaluate` |
| ③ 转录+评阅 | 不含报告 | `grade --steps transcribe,evaluate` |
| ④ 完整（现「开始 AI 批阅」） | transcribe → evaluate → report | 默认 |

新增 `grade --steps <a,b,c>`（覆盖 taskpad 里 `grade.steps`）。

### 3.6 转录部分失败时中止

`_run_transcribe` 若失败数 > 0：
- 默认**中止**后续步骤（避免拿出残缺数据批阅），并给出"可加 --allow-partial 继续"；
- `--allow-partial` 显式允许继续，报告里标注缺失学生。

## 4. 验收标准

1. 转录请求发往**转录段自己的** `base_url/key/model`（两段 provider 不同也能正确分流）；
2. Playground 能通的模型，分步「仅转录」也能通；
3. 报错含 `provider/base_url/model/step`（无 key）；
4. `Model is unavailable` 不重试 3 次；
5. PWA 有「测试配置 / 仅转录 / 仅评阅 / 转录+评阅」；
6. 转录部分失败默认中止（`--allow-partial` 可继续）；
7. `command` 型 provider 按段取 cmd；
8. engine pytest / vue-tsc / build / selfcheck 全绿；脱敏通过。

## 5. 风险

| 风险 | 缓解 |
|---|---|
| 改动 `_settings_from_workspace` 影响所有批阅入口 | 保留旧结构回落 + 全量回归（706+ 用例） |
| 两段共用同一 provider 时行为变化 | 与旧行为一致（同 base/key） |
| `--steps` 与 `--rerun` 语义重叠 | `--steps` 指定本次跑哪些；`--rerun` 保留兼容 |

---

## 6. 实施记录（已完成）

### 6.1 落地内容

| 条目 | 实现 |
|---|---|
| **核心修复** | `_settings_from_workspace()` 返回**两段各自的完整 endpoint**（`transcription` / `evaluation`：base_url/api_key/model/provider/type/cmd/timeout_s）；新增 `_step_endpoint(step)`，`_step_base_key()` 只读对应那一套 |
| 报错可诊断 | 失败信息追加 `（step=…, provider=…, base_url=…, model=…）`，**绝不含 key** |
| 不重试确定性错误 | `400/401/403/404` 或 body 含 `Model is unavailable` → 立即失败 |
| command provider 按段 | `_request_via_command(..., endpoint=)` 用该段的 `cmd`/`timeout_s` |
| 分步批阅 | CLI `grade --steps transcribe[,evaluate][,report]`；serve 透传 `steps`；PWA 四个按钮 |
| 测试配置 | CLI `assist llm test [--stage both\|transcription\|evaluation]`；serve `POST /llm/test`；PWA「🔍 测试配置」按钮（转录段发 8×8 PNG 验证**多模态**能力） |
| 转录部分失败默认中止 | `GradingInputError`，提示可加 `--allow-partial`；`run_task(allow_partial=)` + CLI `--allow-partial` |

### 6.2 PWA 按钮（按用户方案）

```
[🔍 测试配置] [① 仅转录] [② 仅评阅] [③ 转录+评阅] [▶ ④ 完整批阅]
```

### 6.3 复审发现并修复

| # | 问题 | 说明 |
|---|---|---|
| **R1** | **D82-F 旧覆盖失效** | `llm.transcription: {model: X}` 这类旧覆盖被 `llm.stages` 覆盖掉了（既有行为被破坏）。改为存到 `_legacy_override` 独立键，`_step_endpoint` **优先**采用 → 实测 `OVERDIDE` 生效且不影响评阅段 |
| R2 | 旧单层配置回归 | 无 `providers/stages` 时两段共用平铺字段（已验证） |

### 6.4 验证

| 项 | 结果 |
|---|---|
| **核心回归** | 两段 provider 不同时：转录 → `aliyun.example/v1` + `KEY-ALIYUN` + `qwen3.7-flash`；评阅 → `opencode.example/v1` + `KEY-OPENCODE` + `deepseek-v4.1-flash` ✅ |
| 模拟错配报错 | `…（step=evaluation, provider=opencode-go, base_url=http://…:9302/v1, model=qwen3.7-flash）` —— 一眼看出"把 qwen 发到了 opencode 端点" |
| `assist llm test`（真实 HTTP mock） | 两段分别命中 9301/9302，`provider` 正确显示 |
| `POST /llm/test` | 同上（HTTP 端点验证） |
| 确定性错误 | 只调用 1 次（不重试 3 次） |
| D82-F 旧覆盖 | `OVERRIDE` 生效，评阅段不受影响 ✅ |
| 旧单层配置 | 两段共用，行为不变 ✅ |
| engine pytest | **718 passed**（新增 `test_d125_per_stage_endpoint.py` 12 例） |
| app `vue-tsc` / `build` | 0 error |
| app `npm run selfcheck` | **33 项全绿**（新增 `selfcheck-d125-per-stage-endpoint.mjs`） |
| 脱敏 / bat lint | 通过 |

### 6.5 教师操作指引

```
「AI 辅助批阅」→ ③ 任务
  🔍 测试配置   ← 先点这个，立刻看到两段各自的 provider/base_url/model
  ① 仅转录     ← 最慢最贵的一步单独跑，出错能马上定位
  ② 仅评阅     ← 转录产物已存在时，只重跑评阅
  ③ 转录+评阅  ← 不生成报告
  ④ 完整批阅   ← 转录 → 评阅 → 报告
```

CLI 等价：

```bash
assist llm test                              # 两段都测
assist llm test --stage transcription        # 只测转录（多模态）
assist grade --task ... --steps transcribe   # 仅转录
assist grade --task ... --steps evaluate     # 仅评阅
assist grade --task ... --allow-partial      # 部分转录失败仍继续（默认中止）
```
