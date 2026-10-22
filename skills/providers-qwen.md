# QwenWork / WorkBuddy / qwen CLI 接入指南

> 调研日期：2026-10-18。以下**均来自官方文档实测抓取**（可复现）：
> - QwenWork: `docs.qwenwork.ai`（`llms.txt` 索引）
> - WorkBuddy: `www.workbuddy.ai`（`llms.txt`）
> - qwen CLI: 本机 `qwen 0.13.2` 实测

## 0. 先说结论（很重要）

| 产品 | 形态 | 能否被 `assist` 当 LLM 后端 | 我们能做什么 |
|---|---|---|---|
| **qwen CLI** | 命令行 | ✅ **可以**（`type=command`） | 已提供实测 adapter |
| **QwenWork** | 桌面/网页 GUI agent（阿里） | ❌ 无 CLI/API 入口 | 用它的 **Skills** 机制装我们的 SKILL.md |
| **WorkBuddy** | 桌面 GUI agent（腾讯，CodeBuddy 团队） | ❌ 无 CLI/API 入口 | 用它的 **skill.yml** 机制装我们的 skill |

**关键认知**：QwenWork / WorkBuddy 是"AI agent 桌面应用"，**不提供命令行接口**，
因此**不能**作为 `assist llm provider --type command` 的后端。
正确做法是**把我们的规程装成它们的原生 Skill**，让其在会话里调用本机 `assist` CLI。

## 1. qwen CLI（唯一可直接回环的）

实测（`qwen --help` / `qwen -p ... -o json`）：
- 非交互：`qwen -p "<prompt>"`；
- `-m/--model`、`--system-prompt`；
- **`-o/--output-format json`** → stdout 为 JSON 数组，结果项：
  ```json
  [{"type":"result","is_error":false,"result":"答案","usage":{"input_tokens":12,"output_tokens":34}}]
  ```
- **无图片参数**（help 无 image/attach）→ 多模态需另想办法。

### 配置
```bash
assist llm provider --action set --name qwen --type command \
  --cmd python3 --cmd "$PWD/tools/adapters/agent_adapter_qwen.py" \
  --output-mode stdout-json --timeout 600 --no-supports-images
assist llm provider --action stage --stage evaluation --name qwen
# 转录如需读图，把 transcription 段指到 type=api 的视觉模型
assist doctor --json   # 若转录仍指向 qwen，会告警 transcription_command_no_images
```

## 2. QwenWork（阿里，GUI agent）

**官方事实**（`docs.qwenwork.ai/desktop/skills.md`）：
- Skill = 一个文件夹，内含 **`SKILL.md`**，放在 **`~/.qwenwork/skills/`**；
- `SKILL.md` 用自然语言描述"名称、触发条件、执行步骤"，无需写代码；
- 也支持通过 **Extensions → Skills → Install Skill** 上传；
- 支持 **Hooks**（`~/.qwenwork/settings.json`），可拦截 Bash 命令。

**因此**：QwenWork 不能当 `assist` 的 LLM 后端，但它能**运行我们的 skill 并调用 `assist` CLI**。

### 安装我们的 skill（推荐用安装器）
```bash
python tools/skill_installer.py check                     # 前置校验（assist/能力/文件齐全）
python tools/skill_installer.py install --host qwenwork   # → ~/.qwenwork/skills/
python tools/skill_installer.py verify  --host qwenwork   # 校验安装完整性
```
> 也可手动：`mkdir -p ~/.qwenwork/skills && cp -r skills/qwenwork/assignment-grading ~/.qwenwork/skills/`，
> 或在 QwenWork 界面 → Extensions → Skills → Install Skill 上传 `SKILL.md`。
安装后在 QwenWork 会话里说"帮我批阅这批作业"，会自动触发该 skill。

### 前置
QwenWork 需要能执行本机命令（`assist` 已安装且 `assist doctor --json` 有可用 provider）。

## 3. WorkBuddy（腾讯，GUI agent）

**官方事实**（`www.workbuddy.ai` 文档）：
- 是桌面 AI agent（Windows/macOS），支持**多任务并行**、本地文件操作、Skills、MCP；
- Skill 结构：**`skill.yml`（元数据/配置）+ 实现文件（脚本/工具）+ README**；
- 有 Skill Marketplace，也可自定义（"Ask it to create a skill"）。

**因此**：同样不能当 `assist` 的 LLM 后端；但能装载我们的 skill 调用 `assist`。

### 安装
```bash
# 官方未公开固定 skills 目录 → 必须指定 --dest
python tools/skill_installer.py install --host workbuddy --dest <WorkBuddy skills 目录>
python tools/skill_installer.py verify  --host workbuddy --dest <WorkBuddy skills 目录>
```
或在 WorkBuddy 里说“安装这个 skill：<本地路径>”（会读取 `skill.yml` 与 `run.py`）。
`skill.yml` 的 `entry: run.py` 会调用 `assist grade ...`，并在执行前跑 `assist doctor --json` 检查能力。

## 4. 三者的组合建议

- **有 API key**：`assist` 直接用 `type=api`（转录用视觉模型、评阅用文本模型）；
- **只有 qwen CLI**：转录走 API 视觉模型（或无图时走 qwen），评阅走 `type=command`；
- **只有 QwenWork / WorkBuddy**：装我们的 skill，让它们在主会话里调用 `assist`；
  但注意——**它们的会话也是长上下文**，所以 skill 里已强制"正文落文件、只读报告"。

## 5. 排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `assist doctor` 报 `transcription_command_no_images` | 转录段用了不支持图片的 command provider | 转录段改 `type=api` 视觉模型 |
| QwenWork 未触发 skill | 未放对目录/未安装 | 确认 `~/.qwenwork/skills/<name>/SKILL.md` 存在 |
| WorkBuddy skill 执行失败 | `assist` 不在 PATH 或未配置 provider | 先 `assist doctor --json` |
| qwen 报 `No auth type is selected` | 未登录 | 先终端 `qwen` 登录 |
