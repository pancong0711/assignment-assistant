# skills/ — 给 AI agent 的操作规程

这些 Markdown **不是程序**，而是给 agent 读的"怎么做/不能怎么做"。程序本体在 `engine/`（`assist` CLI）。

## 先读这一页

1. **先探测能力**：运行 `assist doctor --json`，看 `capabilities.recommendedPath`：
   - `api` → 有 API key，直接跑 `assist grade`（程序调模型）
   - `command` → 有 `type=command` provider 或本机 agent CLI，跑 `assist grade`（程序回环调 CLI）
   - `subagent-or-manual` → 都没有，**停止并告知用户如何启用**，不要偷偷逐条做
2. **路径优先级**（详见 `batch-isolation.md`）：
   `type=command/本地端点` > `subagent` > `plan/collect`（兜底）> 逐条（**禁止**）
3. **核心纪律**：转录/批阅的**正文只落文件**，主会话只读 `batch-report.json`。

## 文件

| 文件 | 用途 |
|---|---|
| `transcribe.md` | 转录规程（逐生独立、多页合并、输出契约） |
| `evaluate.md` | 批阅规程（只吃文字、evidence/confidence、不自行算分） |
| `grade-orchestrate.md` | 两段式全流程编排 + 执行报告解读 |
| `batch-isolation.md` | 隔离原理、subagent 与兜底、禁止逐条 |
| `provider-setup.md` | 无 API key 时如何配置 `type=command` / 本地端点 |
| `providers-qwen.md` | **qwen CLI / QwenWork / WorkBuddy** 接入（含实测 adapter） |
| `qwenwork/<name>/SKILL.md` | **QwenWork 原生 skill**（`~/.qwenwork/skills/`） |
| `workbuddy/<name>/skill.yml` | **WorkBuddy 原生 skill**（skill.yml + run.py + README） |

## 安装到宿主（QwenWork / WorkBuddy）

```bash
python tools/skill_installer.py list            # 查看可装 skill 与宿主
python tools/skill_installer.py check           # 前置校验（assist 可用、LLM 能力、文件齐全）
python tools/skill_installer.py install --host qwenwork
python tools/skill_installer.py install --host workbuddy --dest <目录>
python tools/skill_installer.py verify  --host qwenwork
```
