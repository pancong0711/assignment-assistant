# D237：AI 建议知识点成功但被误判为失败

> 日期：2026-11-26
> 状态：已完成
> 关联：D236（完整错误展示）、D131（课堂资料知识点建议）

## 0. 现象

点击「② AI 建议知识点」后，页面显示：

```text
❌ 知识点识别失败
原因：引擎未返回 detail
HTTP 状态：200
```

完整诊断 JSON 中 `llm.ok=true`、`source.ok=true`，但没有 `error/detail`。

## 1. 根因

`materials.suggest_knowledge()` 成功时返回：

```json
{
  "version": 1,
  "chap": "26C2",
  "term_count": 12,
  "knowledge": []
}
```

**缺少 `ok: true`**。PWA 通过 `if (r?.ok)` 判断成功，于是把 HTTP 200 的
成功响应当成失败，并显示兜底的“知识点识别失败”。

模型调用本身可能已经成功，`知识点清单.ai.json` 也已写入。

## 2. 修复

- 引擎 `suggest_knowledge()` 成功返回值增加 `ok: true`；
- serve `/materials/suggest` 成功分支强制 `rep["ok"] = True`，
  兼容旧函数返回结构；
- PWA 增加向后兼容判断：旧引擎响应即使没有 `ok`，
  只要存在 `term_count` 或 `knowledge[]` 也按成功处理；
- 保留真正的失败路径 `ok:false + detail + errorType`，不会被这次兼容误判为成功。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 新引擎成功 | 返回 `ok:true` |
| 2 | 旧引擎成功但无 `ok` | PWA 按 `term_count/knowledge` 判成功 |
| 3 | 模型真实失败 | 返回 `ok:false`、`detail`、`errorType` |
| 4 | HTTP 200 成功 | 不再显示“知识点识别失败” |

自动化：

- `test_suggest_writes_ai_json_but_not_effective_md` 增加 `rep["ok"] is True`
- `test_serve_materials_suggest_passes_provider_and_files` 模拟旧版无 `ok`
  的成功返回，serve 必须补齐 `ok:true`
- PWA `npm run build` 通过
