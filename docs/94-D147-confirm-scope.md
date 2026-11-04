# D147 需求单：Atopia L2 确认必须精确到「工具 + 参数」（安全修复）

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/81-D132`（L2 必须教师逐次确认）、`docs/89-D140`（Atopia 对话）、`docs/12`

## 0. 问题（规划核查时发现）

D140 的「已知限制」里写着"L2 确认粒度是本次请求全部确认"。核查后发现
**这不是"限制"，是漏洞**：

`/atopia/ask` 的 `_confirm()` 只看 `confirmed is True`：

```python
def _confirm(tool_name, args):
    return conf_note if confirmed else ""
```

**实测复现**：教师为 `materials.confirm` 点了确认后，同一次请求里模型改请求
`kb.vocab.add` → **同样被自动放行并真的执行了**（journal 里两条都有）：

```
journal 里实际执行的工具: ['materials.confirm', 'kb.vocab.add']
```

这违背 D132 的核心设计：**L2 必须教师逐次确认**。
教师看到的弹窗写着 A，实际可能执行了 B。

## 1. 修复

### 1.1 后端

抽取 `serve.make_atopia_confirm()`（便于单测真实实现）：

| 情况 | 结果 |
|---|---|
| `confirmed=False` | 拒绝（返回空串） |
| 带 `confirmed` 但**没给 `confirmedTool`** | 拒绝（不允许"盲确认"） |
| 工具名与 `confirmedTool` 不一致 | 拒绝，并记 warning |
| 传了 `confirmedArgs` 但参数不一致 | 拒绝，并记 warning |
| 全部一致 | 放行，返回确认来源（记入 journal `confirmed_by`） |

兼容：老客户端只传 `confirmedTool` 不传 `confirmedArgs` → 仍按工具名放行。

### 1.2 前端

确认弹窗点「我确认执行」时，把**该次待确认的工具名与参数**随请求回传：

```ts
confirmedTool: confirming.value?.tool,
confirmedArgs: confirming.value?.args,
```

## 2. 验收

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 确认 A、模型请求 B → B 被拒绝 | ✅ | `test_serve_confirm_rejects_other_tool` |
| 2 | 带 confirmed 但没指明工具 → 拒绝 | ✅ | `test_serve_confirm_requires_tool_name` |
| 3 | 同名工具但参数不同 → 拒绝 | ✅ | `test_serve_confirm_rejects_arg_mismatch` |
| 4 | 工具+参数都一致 → 正常执行（不误伤） | ✅ | `test_confirm_matching_arguments_allowed` |
| 5 | 未确认 → 拒绝 | ✅ | `test_serve_confirm_without_flag` |
| 6 | 老客户端（只传工具名）仍可用 | ✅ | `test_serve_confirm_legacy_client_without_args` |
| 7 | 前端确实回传 confirmedTool/Args | ✅ | `AtopiaView.vue` + build |

验证：pytest **1178 passed** · build 0 error · selfcheck **32/32** · 脱敏通过。

## 3. 影响

- 一次会话若连续调用多个 L2 工具，**每个都会各自弹一次确认**（这才是 D132 的本意）；
- 不改变 L3 口径（仍然永远不执行）；
- 确认仍记 journal（`confirmed_by`），可审计。
