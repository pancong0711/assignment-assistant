# D140 需求单：Atopia 独立选项卡 + 对话模式（Playground 保持一次性）

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/81-D132`（Atopia 分级/护栏/审计）、`docs/86-D136`（会话 id）、
> `docs/90`（Playground 定位）、`docs/12`

## 0. 动机

Atopia 是"让 AI 调用本项目工具"的先锋功能，但目前：

1. **藏在「AI 辅助批阅」页面底部**，与批阅动线混在一起；
2. **PWA 里只能手选工具 + 手填 JSON 参数**，没有对话；
3. 后端 `agent.run_session_auto()`（原生 tools + 自动降级）**早已写好**，
   却只有 CLI `assist atopia ask` 能用。

## 1. 分工定稿（教师拍板）

| 能力 | Playground | Atopia |
|---|---|---|
| 单次调用测模型/测连通性 | ✅ **保持现状** | — |
| 连续多轮对话 | ❌ **不做** | ✅ 做 |
| 管理对话（会话/历史） | ❌ 不做 | ✅ 做 |
| 调用本项目工具 | ❌ **不给**（无 Gate 通道） | ✅ 唯一入口 |

**为什么 Playground 不给工具**：Atopia 每次调用都要过 Gate
（L3 拒绝 / L2 教师确认 / 审计）。若让 Playground 也有工具能力，
就等于开了一条**没有 Gate 的旁路**——安全倒退。

## 2. 任务清单

### A. Atopia 独立选项卡

- 顶层导航新增「Atopia」页（与「AI 辅助批阅」平级）；
- 原 `AiGradingPanel` 底部内嵌的 `AtopiaPanel` **移除**（避免双入口）；
- 页面内含两个模式页签：**对话**（默认）/ **工具**（原手选执行）。

### B. 对话模式

| # | 内容 |
|---|---|
| B1 | serve `POST /atopia/ask`：入参 `{task, protocol?, maxTurns?, session?}`，跑 `run_session_auto` |
| B2 | **L2 二级确认**：会话执行中若模型请求 L2 工具，接口返回 `pendingConfirm`（含工具名+参数），前端弹窗；教师确认后带 `confirmed=true` 重入 |
| B3 | 多轮：前端保留 `messages[]` 展示（用户消息 / AI 思考与工具调用 / 工具结果 / 最终回答）；后端**同一会话复用 session_id**（D136 粒度口径） |
| B4 | 会话历史：`<ws>/atopia/sessions/<id>.jsonl` 追加；页面可列出最近会话并回看 |
| B5 | 无 Gate 旁路：全部经 `run_tool()`（与 CLI 同一 Gate） |

### C. Playground 说明

- 页面顶部加一行说明："这里只做**单次调用**测试；需要多轮对话 + 调用本项目工具，请到 **Atopia**。"

## 3. 安全要求（不放松）

1. 对话里模型请求的工具**只能**来自白名单（未登记直接拒绝）；
2. **L2 必须教师逐次确认**，且记录 `confirmed_by`；
3. **L3 永远不执行**（前端不给按钮、后端拒绝）；
4. 护栏（次数/L1 成本/超时）照旧生效，**失败与超时也计数**；
5. 会话历史只落 `<ws>/atopia/`（可整体删除，见 docs/83 T2）。

## 4. 验收标准

1. 导航出现「Atopia」页且原页面底部不再有内嵌面板（无双入口）；
2. Atopia 页可在「对话 / 工具」之间切换；
3. 对话可多轮：AI 请求工具 → 执行 → 继续 → 给出最终回答；
4. L2 工具在对话中**必须**弹窗确认，确认前不执行（查 journal 可证）；
5. L3 工具被拒绝且不执行；
6. 会话历史落盘并可在页面回看；
7. Playground 有明确分工说明；
8. pytest / build / selfcheck / 脱敏全绿。

## 5. 风险

| 风险 | 缓解 |
|---|---|
| 对话里 AI 连续调很多次工具，花光额度 | 护栏硬顶 + 显示本次已用次数 |
| L2 确认被"顺手点过" | 弹窗列出**工具名 + 完整参数**，默认不执行 |
| 会话历史含敏感内容 | 只落 `<ws>/atopia/`；journal 已有 500 字截断口径 |
| 对话模式让页面变复杂 | 默认「对话」，高级「工具」折叠到第二个页签 |

## 6. 实施记录（2026-10-31 完成）

### A. 独立选项卡

- `App.vue` 顶层导航新增 `Atopia`（位于「AI 辅助批阅」之后）；
- 新建 `views/AtopiaView.vue`，含两个页签：**💬 对话**（默认）/ **🧰 单一工具执行**；
- 移除 `AiGradingPanel` 底部内嵌的 `AtopiaPanel`（**无双入口**），
  只留一行指路提示。

### B. 对话模式

| 项 | 实现 |
|---|---|
| `POST /atopia/ask` | 入参 `{task, sessionId?, confirmed?, confirmedBy?, protocol?, maxTurns?, model?}` |
| 会话复用 | 前端传 `sessionId` → 后端 `client.set_session_id()`，多轮复用同一 id（D136 口径） |
| 协议 | 默认 `native`，provider 不支持时**自动降级** JSON 指令协议（响应带 `protocol/degraded`） |
| L2 确认 | 后端 `confirm` 回调在 PWA 场景**只能**在"本次请求已带 `confirmed=true`"时放行；否则该步被拒，响应带 `pendingConfirm{tool,args,reason}` → 前端弹窗 → 教师点确认后**重发** |
| 会话历史 | `<ws>/atopia/sessions/<sessionId>.jsonl` 追加；`GET /atopia/sessions[?id=]` 列出/回看 |
| 工具细节 | 前端可折叠查看每次工具调用（工具名/参数/成败/输出前 400 字） |

**为什么 L2 用"重发"而不是"阻塞等待"**：HTTP 请求线程里等教师点击会让连接挂住、
且无法跨进程恢复。改成"拒绝 + 返回待确认信息 + 前端确认后重发"更简单也更可审计
（第二次请求明确带 `confirmed=true` 与 `confirmed_by`）。

### C. Playground 说明

`PlaygroundPanel` 标题下加说明：只做单次调用、**不保存上下文**、
**不调用本项目工具**；要对话/用工具请去 Atopia。

## 7. 验收对照

| # | 标准（§4） | 结果 | 证据 |
|---|---|---|---|
| 1 | 导航出现 Atopia 页，原页面不再内嵌（无双入口） | ✅ | `App.vue` + 浏览器回归 |
| 2 | 可在「对话 / 工具」切换 | ✅ | `run-d140-atopia-chat-browser.sh` |
| 3 | 对话可多轮：AI 请求工具 → 执行 → 最终回答 | ✅ | `test_chat_runs_l0_tool_and_answers` |
| 4 | L2 在对话中必须确认，确认前不执行 | ✅ | `test_chat_l2_without_confirm_is_denied` / `test_chat_l2_with_confirm_executes` |
| 5 | L3 被拒绝且不执行 | ✅ | `test_chat_l3_never_runs` |
| 6 | 会话历史落盘且可回看 | ✅ | `test_session_history_files_under_atopia` + `GET /atopia/sessions` |
| 7 | Playground 有分工说明 | ✅ | `PlaygroundPanel` 说明段 |
| 8 | pytest / build / selfcheck / 脱敏 | ✅ | 1144 passed · 0 error · 29/29 · 通过 |

## 8. 已知限制

- 对话是**单次请求内**的多轮（`maxTurns` 默认 6）；没有做"长会话流式输出"；
- 前端**不把对话历史**存到本地存储（刷新后靠「会话历史」从引擎回看）；
  注意：localStorage 里另有 `atopia.provider` / `atopia.model`（D146 的选择记忆），
  那是**配置偏好**，不是对话历史；
- L2 确认**精确到"工具 + 参数"**（D147 修复）：一次请求只放行教师确认的那一次调用；
  若同一次会话里要调多个 L2 工具，**每个都会各自弹一次确认**。
