# D136 需求单：opencode-go 会话语义请求头（`x-opencode-session`）+ provider 级自定义请求头

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/74-D125`（两段式 endpoint）、`docs/51-D98`（provider/provider_command）、`docs/12`

## 0. 现象

使用 PWA Playground 时（把 base_url 从 `https://opencode.ai/inference/openai/v1`
改为 `https://opencode.ai/inference/go/openai/v1`，其余不变）报：

```
LLM API 请求失败(status=400): {"type":"error","error":{"type":"MissingSessionID",
"message":"Request is missing x-opencode-session and cannot be routed efficiently."}}
（step=evaluation, provider=-, base_url=https://opencode.ai/inference/go/openai/v1）
```

## 1. 根因（已实测确认，不是配置改错）

opencode 官方文档（`/v2/docs/console/go/`）对 Go 套餐的客户端要求：

> 1. **Identify itself with its own user agent**（如 `my-coding-agent/1.0`），
>    **不要**用通用 SDK/HTTP 库名；
> 2. **Send a stable session ID in `x-opencode-session` for each conversation**
>    so we can optimize routing and prompt caching.

实测（curl 对照）：

| 请求 | 结果 |
|---|---|
| `/inference/go/openai/v1` + 无 session 头 | ❌ `MissingSessionID` |
| `/inference/go/openai/v1` + `x-opencode-session: <任意>` | ✅ 通过（进到下一层鉴权/模型校验） |
| `/inference/openai/v1`（无 `/go`） | 普通路由，不要求该头 |
| **旧 `/zen/go/v1`** | ❌ **同样报错** |

→ **这是服务端对 go 路由新增的要求**，与"改 URL"无关；
换回非 `/go` 路由会用充值 token（用户明确不考虑：不划算）。

代码侧现状（`grading/llm.py`）：

```python
headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
```

- **没有** `x-opencode-session`；
- **没有** user-agent（httpx 默认 `python-httpx/x`，正是官方点名要避免的通用库名）；
- 因此 `/go` 路由下**所有** LLM 调用都会失败（转录/评阅/要点/Atopia/批量），
  不止 Playground。

## 2. 关键语义：session 必须"按对话稳定"，不是"每次新"也不是"全局固定"

官方用词是 **stable session ID for each conversation**：

- **同一对话内多轮** → **复用同一个 id**（否则 prompt 缓存全失效，白丢 go 套餐的省钱优势）；
- **不同对话之间** → **应当不同**（否则路由把无关请求归成一坨，且"监控滥用"口径下不安全）。

### 粒度口径（定稿）

| 调用场景 | session 取值 |
|---|---|
| 单次调用（一道题的转录 / 一次评阅 / 一次要点生成） | **每次新建**一个 id |
| 多轮对话（Atopia 会话、Playground 多轮） | **整个会话复用**一个 id |
| 批量任务（一次批阅 N 份作业） | **每份作业**一个 id（不按题再拆） |

## 3. 设计

### 3.1 provider 级自定义请求头（不是全局开关）

```jsonc
"llm": { "providers": [
  { "name": "opencode-go",
    "base_url": "https://opencode.ai/inference/go/openai/v1",
    "headers": { "x-opencode-session": "{session}" },   // 新增（可选）
    "user_agent": "assignment-assistant/0.1.0"          // 新增（可选）
  } ] }
```

**安全红线**（与 D132「扩展不能提权」同一条原则）：

- 只允许 `x-*` 自定义头与 `user-agent`；
- **禁止**配置 `Authorization` / `Host` / `Cookie` / `Content-Length` 等
  （否则改配置文件即可劫持鉴权/指向别的服务）；
- 值不得含控制字符；长度受限。

### 3.2 session 注入：显式配置，缺失即报可读错误

- `LLMClient` 新增 `session_id` 属性（默认 `None` = 不发该头）；
- 配置里出现 `{session}` 占位时，**必须**有 session id，否则抛
  `LLMConfigError`（可读提示：opencode-go 需要 `x-opencode-session`）；
- **不自动**给 opencode 域名补默认值（配置错了要报出来，不要隐藏）。

> 说明：`user_agent` 默认 `assignment-assistant/<版本>`（满足官方"不要用通用库名"）；
> 只有 provider 显式配置时才附加自定义 headers，其它 provider **完全不受影响**。

### 3.3 顺带修复两个提示缺陷

1. **`provider=-`**：`_step_endpoint()` 从 `_step_cfg()` 取 `provider`，
   而该结构里**没有**这个字段 → 恒为空。改为回落到 `self.provider`
   （由 `stage_endpoint()` 填进来），报错信息才看得出真实 provider。
2. **错误分类**：识别响应体 `error.type`（如 `MissingSessionID`）并给出可操作提示，
   而不是只把 JSON 原样抛出。

## 4. 任务清单

| # | 内容 | 验收 |
|---|---|---|
| T1 | `providers` 支持 `headers` / `user_agent`；白名单校验（禁止 Authorization 等） | 单测：允许 x-* / 拒绝 Authorization |
| T2 | `LLMClient` 支持 `session_id` + `{session}` 占位替换；缺失报 `LLMConfigError` | 单测 |
| T3 | user-agent 默认 `assignment-assistant/<ver>`，可被 provider 覆盖 | 单测（读实际发出的 header） |
| T4 | 修 `provider=-`（回落 `self.provider`） | 单测：错误信息含真实 provider |
| T5 | 语义化错误提示（`MissingSessionID` → 明确指引） | 单测 |
| T6 | playground / Atopia / 批阅按 §2 粒度传 session | 单测 |
| T7 | 文档：新增本需求单、更新 README / backlog / 设置说明 | — |

## 5. 验收标准

1. provider 配了 `headers: {"x-opencode-session": "{session}"}` 且传入 session →
   实际请求**带**该头，且值 = 传入的 session；
2. provider 配了占位但**没**传 session → 抛 `LLMConfigError`（可读），**不发请求**；
3. 其它 provider（不配 headers）→ 请求头**与改动前完全一致**（有测试锁定）；
4. 配置 `Authorization` / `Host` 等 → 被拒绝（并且不静默忽略，要报错）；
5. user-agent 不再是 `python-httpx/*`（默认带 `assignment-assistant/`）；
6. 报错信息里的 `provider` 是**真实名字**（不再是 `-`）；
7. `MissingSessionID` 报错给出"需要 x-opencode-session"的可操作提示；
8. pytest / build / selfcheck / 脱敏 全绿。

## 6. 风险

| 风险 | 缓解 |
|---|---|
| 全用固定 session → prompt 缓存失效/路由错乱 | §2 粒度口径（按对话稳定）+ 单测 |
| 每次新 session → 丢掉缓存收益 | 多轮场景由调用方复用同一 id |
| 允许任意 header → 配置即提权 | §3.1 白名单（只 `x-*` 与 `user-agent`） |
| 自动给 opencode 补默认值 → 隐藏"忘配" | 显式配置，缺失即报错 |
| 改动碰公共鉴权层，影响所有 provider | 无配置时请求头**逐字节不变**（测试锁定） |

## 7. 实施记录（2026-10-31 完成）

### 7.1 T1 provider 级请求头（`grading/providers.py`）

- 新增 `validate_headers()`：只允许 `x-*` 与 `user-agent`；
  **显式拒绝** `Authorization` / `Host` / `Cookie` / `Content-Type` / `x-api-key` /
  `Proxy-Authorization` 等（即使写成 `X-...` 也拦）；
- 值 ≤512 字符、不含控制字符；
- `save_provider(headers=...)` 非法时**整单失败**（不静默丢弃，否则教师以为配好了）；
- `list_providers()` / `stage_endpoint()` 均返回 `headers` 与 `user_agent`。

### 7.2 T2/T3 `LLMClient`（`grading/llm.py`）

- 新增 `session_id` + `set_session_id()`；`{session}` 占位替换；
  配了占位却没传 session → `LLMConfigError`（**不发请求**）；
- 新增 `_headers_for()`：鉴权 + `User-Agent` + provider 自定义头；
- 默认 UA = `assignment-assistant/<版本>`（官方要求"用自己的 UA，不要通用库名"）；
- **无 headers 配置的 provider，请求头只多一个 User-Agent**，其余逐字节不变（测试锁定）。

### 7.3 T4 修 `provider=-`

`_step_endpoint()` 里 `provider` 取自 `_step_cfg()`，而该结构**没有**这个字段 → 恒为 `-`。
改为回落到 `self.provider`（`stage_endpoint()` 填进来）。

### 7.4 T5 语义化错误提示

新增 `_error_hint()`：读响应体 `error.type`，对
`MissingSessionID` / `Model is unavailable` 给出可操作提示
（body 原文仍保留，只在后面追加"【怎么办】"）。

### 7.5 T6 会话粒度（docs/86 §2 落地）

| 场景 | 实现 |
|---|---|
| Playground | `_client()` 生成 `playground-<hex>`，一次会话内多轮复用 |
| Atopia 会话 | `_ensure_session_id()` 生成 `atopia-<hex>`；调用方已设则不动 |
| 批阅（转录/评阅） | `_session_per_student()`：单份用 `grade-<学生>`，多份用 `grade-batch<N>` |

### 7.6 配置方法（给教师）

```bash
assist llm provider --action set --name opencode-go \
  --base-url "https://opencode.ai/inference/go/openai/v1" \
  --api-key "sk-..." \
  --header 'x-opencode-session={session}' \
  --user-agent assignment-assistant/0.4.0
```

然后正常把 `transcription` / `evaluation` 两段指到该 provider 即可。
**其它 provider 不需要配任何 headers**，行为与以前完全一致。

## 8. 验收对照

| # | 标准（§5） | 结果 | 证据 |
|---|---|---|---|
| 1 | 配 headers + 传 session → 请求带该头且值正确 | ✅ | `test_request_sends_session_header` |
| 2 | 配占位但无 session → `LLMConfigError` 且**不发请求** | ✅ | `test_missing_session_does_not_send_request` |
| 3 | 其它 provider 请求头与改动前一致 | ✅ | `test_plain_provider_headers_unchanged` |
| 4 | 配置 Authorization/Host 等被拒 | ✅ | `test_rejects_sensitive_headers`（6 例）+ CLI 测试 |
| 5 | UA 不再是 `python-httpx/*` | ✅ | `test_default_user_agent_is_not_httpx` |
| 6 | 报错含真实 provider | ✅ | `test_error_message_has_real_provider` |
| 7 | `MissingSessionID` 给出可操作提示 | ✅ | `test_error_hint_for_missing_session` |
| 8 | pytest / build / selfcheck / 脱敏 | ✅ | 1102 passed · 0 error · 27/27 · 通过 |

## 9. 已知限制

- session id **由调用方决定**，引擎不校验"是否真的是同一个对话"；
  若上层错误地给不同对话复用同一 id，只会影响缓存效率，不影响正确性；
- PWA 设置页**只读展示** `headers`/`user_agent`，不提供编辑框：
  请求头直接决定鉴权与路由，配置入口刻意保留在 CLI（避免误填造成难排查的故障）；
- 未实现"自动探测 provider 是否需要 session 头"——显式配置、缺失即报错，
  行为可预测（不做隐式魔法）。

---

## 10. D139 补记：修复「配了 provider 却没分配 stage → 静默回落」

### 现象

教师已保存 provider（含 `headers: {"x-opencode-session": "{session}"}`），
但请求仍报 `MissingSessionID`，且报错里的 `base_url` 与配置对不上。

### 根因（实测复现）

`_settings_from_workspace()` 里：**有 provider 但 `llm.stages` 为空**时，
会静默回落到 `load_llm_settings()`（读平铺 `base_url/api_key`）→
`LLMClient` 从未拿到 provider 对象 → `headers` **完全被绕过**。

| 配置状态 | 实际发出的请求头 |
|---|---|
| 只保存 provider，未分配 stage | `Authorization/Content-Type/User-Agent`（**无 session 头**），端点回落到旧平铺配置 |
| 两段都指向该 provider | 以上 + `x-opencode-session` ✅ |

### 修复

1. 有 provider 但**没有任何一段分配 provider** → 抛 `LLMConfigError`，
   明确提示去「① LLM 设置」分配两段（含 CLI 等价命令）；
2. `_settings_from_workspace` 的 `except Exception: pass` 改为**配置类错误向上抛**
   （其它异常仍可回落，避免误伤）；
3. **没有任何 provider** 时旧单层配置路径保持可用（有测试锁定）。

> 教训：**"看起来配好了但没生效"比"直接报错"危险得多**——
> 它会把配置问题伪装成服务端问题，浪费大量排查时间。

## 11. D139 补记：`failed: 1` 提示吞掉原因

`kb ai-solve` 前端**无条件**显示"作答并写回完成"，且只截取日志最后两行，
把 `results[].error` 截掉了 → 教师只看到 `"failed": 1`。

已改为：解析日志里的 `failed` 与 `error`，失败时显示
`❌ 有 N 题作答失败（未写回）：<原因>`，并提示"已成功的题已写回"。
