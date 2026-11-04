# D146 需求单：Atopia 对话支持选择 provider / 模型

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/89-D140`（Atopia 对话）、`docs/74-D125`（两段式 endpoint）、
> `docs/92-D145`（provider 请求头）、`docs/12`

## 0. 问题

Atopia 对话**无法选 provider/模型**：`/atopia/ask` 只接受 `model`，
provider 固定取「评阅段」配置。

后果：
- 想用另一个 provider（如便宜的快模型）跑 Atopia 做不到；
- 各 provider 的 `headers`（如 opencode-go 的会话头）只能靠**评阅段恰好配了它**才生效；
- 与 Playground 的心智不一致（那边能选）。

## 1. 设计

### 1.1 后端

`POST /atopia/ask` 新增 `provider` 字段：

- **指定 `provider`** → 用该 provider 的 base_url/key/headers/user_agent 构造 client
  （**与 Playground 完全同一套逻辑**，避免两处口径漂移）；
- **未指定** → 沿用现状（「评阅段」配置），**行为不变**（向后兼容）；
- 模型：`model` 为空时用该 provider 的默认（`models[0]`）或评阅段模型；
- 校验：provider 不存在 / 没配 key → 400 可读错误；
- **会话 id 仍由引擎自动生成**（D141），前端不掺和。

### 1.2 前端（Atopia 对话页）

对话区顶部一行：

```
provider：[（评阅段配置） ▾]   模型：[（默认） ▾] / [自定义输入]
```

- provider 列表来自 `/llm/config`；
- 选定 provider 后，模型下拉列出它的 `models[]`（与 Playground 同源）；
- 切换 provider 时**提示**：会话中途换 provider 会新建 session（避免串缓存）；
- 选择结果**记住**（localStorage），下次打开沿用。

### 1.3 与 Playground 的关系（分工不变）

| | Playground | Atopia |
|---|---|---|
| 用途 | 单次测模型 | 多轮 + 调工具 |
| 能否选 provider/模型 | ✅ | ✅（本次补上） |
| 能否调工具 | ❌ | ✅ |

## 2. 任务清单

| # | 内容 | 验收 |
|---|---|---|
| T1 | serve `/atopia/ask` 接受 `provider`，复用 Playground 的构造逻辑 | 单测：指定 provider 时用它的 base_url |
| T2 | provider 不存在/无 key → 400 可读错误 | 单测 |
| T3 | 未指定 provider → 行为与现状一致 | 单测（回归） |
| T4 | Atopia 页加 provider/model 选择器 | 浏览器 |
| T5 | localStorage 记住选择；切 provider 提示会新建会话 | 浏览器 |
| T6 | 文档回填 | — |

## 3. 安全

- 只能选**已登记**的 provider（`providers.get_provider`），不接受任意 base_url；
- 该 provider 的 `headers` 白名单校验照旧（`validate_headers`）；
- 工具调用仍全部经 `run_tool()` 同一 Gate（与 D140 一致，不因换 provider 而放松）；
- 模型名只影响"用哪个模型"，不影响权限。

## 4. 验收标准

1. Atopia 对话可选 provider 与模型，选择后 `/atopia/ask` 带上 `provider`；
2. 指定 opencode-go 时，请求**使用它的 base_url 与 headers**（含会话头）；
3. 不选 provider → 与改动前完全一致（「评阅段」配置）；
4. 选不存在的 provider → 明确报错，不静默回落；
5. 选择被记住（刷新后仍在）；
6. 切 provider 时提示"将新建会话"；
7. pytest / build / selfcheck / 脱敏全绿。

## 5. 风险

| 风险 | 缓解 |
|---|---|
| Atopia 与 Playground 各写一套构造逻辑 → 口径漂移 | **抽公共函数**，两边都调它 |
| 会话中途换 provider 导致缓存/上下文错乱 | 切 provider 时**新建 session id** 并提示 |
| 选了无 key 的 provider，报错难懂 | 服务端预检并给可读错误 |

## 6. 实施记录（2026-10-31 完成）

### 6.1 抽公共函数（防止两处口径漂移）

新增 `grading/llm.py: build_client_for(ws, provider, model, session_prefix=)`：

- 指定 provider → 用其 base_url / key / **headers / user_agent**；
- 未指定 → 沿用「评阅段」endpoint（改动前行为）；
- 自动分配会话 id（`<prefix>-<hex>`）；
- provider 不存在 / 无 key → `LLMConfigError`（可读，不静默回落）。

**Playground 与 Atopia 现在都调它**，不再各写一套。

### 6.2 后端

`POST /atopia/ask` 新增 `provider` 字段（`model` 原本已有）。

### 6.3 前端

对话页顶部一行选择器：

```
provider：[（评阅段配置）▾]  模型：[（默认）▾] / [自定义输入]
```

- provider 列表来自 `/llm/config`（与 Playground 同源）；
- 选定 provider 后模型下拉列出它的 `models[]`，也支持自定义输入；
- 选择记在 `localStorage`（`atopia.provider` / `atopia.model`）；
- **切换 provider 时自动新建会话**并提示——否则上下文与 prompt 缓存会错位。

## 7. 验收对照

| # | 标准（§4） | 结果 | 证据 |
|---|---|---|---|
| 1 | 可选 provider/模型，请求带上 `provider` | ✅ | 浏览器 `providerOptions` + `askAtopia` payload |
| 2 | 选 opencode-go 时用它的 base_url 与 headers（含会话头） | ✅ | `test_pick_provider_uses_its_base_and_headers` |
| 3 | 不选 → 与改动前一致 | ✅ | `test_default_uses_evaluation_stage` |
| 4 | 选不存在的 provider → 明确报错不回落 | ✅ | `test_unknown_provider_raises` |
| 5 | 选择被记住 | ✅ | 浏览器 `providerRemembered` |
| 6 | 切 provider 提示新建会话 | ✅ | `onProviderChange()` |
| 7 | pytest / build / selfcheck / 脱敏 | ✅ | 1170 passed · 0 error · 32/32 · 通过 |

## 8. 效果

现在 Atopia 可以：

- 用「评阅段配置」跑（默认，行为不变）；
- 或**指定任意已登记 provider + 模型**；
- 选了 opencode-go 就会自动带上 `x-opencode-session`（D136/D145 配的那套），
  **不再依赖"评阅段恰好配了它"**。
