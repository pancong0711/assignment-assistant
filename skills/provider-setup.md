# 无 API key 时：把 agent/套餐当 LLM 后端

## 先探测
```bash
assist doctor --json    # 看 capabilities.command / agentCli
```

## 方式 A：本地 OpenAI 兼容端点（最省事）
若你的套餐/客户端暴露了本地 `.../v1`：
```bash
assist llm provider --action set --name local --base-url http://127.0.0.1:PORT/v1 --api-key dummy
assist llm provider --action stage --stage transcription --name local
assist llm provider --action stage --stage evaluation   --name local
```

## 方式 B：agent CLI 回环（type=command）
程序用**子进程**调用 agent CLI（每次新进程=隔离）：
```bash
assist llm provider --action set --name local --type command \
  --cmd opencode --cmd run --cmd --model --cmd '{model}' \
  --output-mode stdout-json --timeout 300
assist llm provider --action stage --stage transcription --name local
assist llm provider --action stage --stage evaluation   --name local
```
契约（固定）：stdin 收 JSON `{id,prompt,system,model,images[],temperature,max_tokens}`；
stdout 出 `{"text": "..."}`（或 `stdout-text`）。`{model}` 缺省时不传 → 用 agent 当前模型。

## 方式 C：只有 subagent
不用配置 provider；按 `batch-isolation.md` 用 subagent 执行，程序只做 plan/collect 与算分。

## 验证
```bash
assist playground ask -q "你好"     # 走当前 evaluation 段 provider
```
返回正常即配置成功。


## 具体客户端

- Qwen 系（qwen / qwenwork / workbuddy）：见 `providers-qwen.md`（含可复用 adapter）。
