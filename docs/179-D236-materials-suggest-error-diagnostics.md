# D236：AI 建议知识点失败时显示完整错误

> 日期：2026-11-26
> 状态：已完成
> 关联：D229（识别诊断）、D233（识别依据）

## 0. 教师问题

点击「② AI 建议知识点」后页面只显示“知识点识别失败”，看不到 HTTP 状态、
上游模型响应、错误类型或请求诊断，无法定位是配置、网络、限流还是模型返回格式问题。

## 1. 原因

引擎 `/materials/suggest` 在多数异常路径已经返回
`error / detail / errorType / diagnostics`，但前端存在两个问题：

1. 失败信息只拼进单行状态文本，长错误和原始响应不显眼；
2. 若请求在到达引擎前失败，或代理/网关返回非 JSON，前端只得到 HTTP 状态，
   原响应体被 `res.json().catch(() => ({}))` 丢弃。

## 2. 修复

### PWA

- `suggestMaterials()` 改为先读响应原文，再尝试解析 JSON；
- 非 JSON 错误响应也返回：
  - `httpStatus`
  - `rawResponse`
  - 可读 `detail`
- AI 建议失败时新增红色「完整错误信息」面板，展示：
  - `errorType` / HTTP 状态；
  - 引擎返回的 `detail`；
  - 可展开的原始响应；
  - 可展开的本次诊断 JSON。
- “复制诊断信息”现在也会包含错误、HTTP 状态与请求参数。

### 引擎

现有结构化错误响应保持不变；前端不会再丢弃其中的字段。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | LLM API 返回 400/500 | 页面显示 HTTP 状态、上游响应和 provider/model |
| 2 | 引擎返回非 JSON | 页面显示 HTTP 状态与响应原文 |
| 3 | 网络异常 | 页面显示 ClientError 与异常消息 |
| 4 | 配置检查失败 | 保留 diagnostics 中的 llm/source/request |
| 5 | 复制诊断 | 复制包含完整错误字段的 JSON |

自动化：PWA `npm run build` 通过；引擎原有
`test_serve_suggest_failure_returns_structured_diagnostics` 覆盖结构化错误返回。
