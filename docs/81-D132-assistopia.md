# D132 需求单：Assistopia —— AI 调用本项目工具的安全工作区（P3）

> 日期：2026-10-30
> 状态：**P3-1 / P3-2 / T16 已完成；PWA 工作区界面待做**
> 关联：`docs/78-D130` §3.9（P3 T15–T18）、`docs/40-D88`（playground）、`docs/12`

## 0. 一句话

Assistopia（**assist + utopia**）让 AI 在本项目**自己的工具**上工作，但**每一步都受限、可审计、可复现**：
只读工具直接跑，写操作**必须教师二次确认**，危险操作**不开放**，用户扩展
`<ws>/extensions/` **升级永不覆盖**。

## 1. 为什么必须先定安全边界（而不是先做对话）

AI 调用本机工具的风险与"聊天"完全不同：

| 风险 | 例子 | 若不做护栏 |
|---|---|---|
| **误删** | 模型想"清理重复草稿"，误调 `migrate-grading-dir --apply` | 教师几个月批阅成果没了 |
| **静默改写** | 模型"帮老师整理知识点"，直接 `tag-knowledge --apply` 覆盖人工标注 | 数据被 AI 口径污染，且**无人察觉** |
| **成本失控** | 模型循环调用批量 API 5 万题 | 账单爆炸 |
| **不可复现** | 不知当时用了什么参数、什么版本的工具 | 出问题无法回溯，也无法复现 |

因此本单的第一交付物**不是**对话界面，而是：
**工具白名单 + 分级 + 审计 journal + 护栏**。LLM function calling（T16）放在最后接。

## 2. 工具分级（定稿）

| 级别 | 定义 | AI 权限 | 典型工具 |
|---|---|---|---|
| **L0 只读** | 不改任何文件 | ✅ 直接执行 | `kb stats`、`kb catalog`、`packs list`、`doctor --json`、`materials list`、`grade drafts`(读) |
| **L1 预览** | 只读但会**花 LLM 成本**（dry-run / 分析） | ✅ 直接执行（**计费护栏**） | `kb tag-knowledge --dry-run`、`kb check-knowledge`（只提议）、`materials suggest`、`llm test` |
| **L2 写入** | 改题库/答案/草稿/词表 | ⚠️ **必须教师二次确认**（逐次） | `kb write`、`kb tag-knowledge --apply`、`check-knowledge --apply`、`materials confirm`、`kb vocab add`、`rules set` |
| **L3 危险** | 迁移/删除/升级/越界写 | ❌ **不开放**（连提议都不允许） | `migrate-grading-dir --apply`、`engine update`、`workspace clean-migrated --apply`、任何 `rm`/删除 |

**判级原则（硬编码，不由配置放宽）**：
1. 只要命令含 `--apply` / `write` / `delete` / `rm` / `update` → **至少 L2**；
2. 只要命令会**移动/删除/覆盖**既有产物 → **L3**；
3. 工具注册表里**没有登记**的命令 → 视为 **L3**（默认拒绝，白名单而非黑名单）；
4. **L3 无法通过任何配置开通**（写死在代码里），这是最后一道闸。

## 3. 审计 journal（每次调用一行）

`<ws>/assistopia/journal.jsonl`：

```json
{"ts": "2026-10-30 12:00:00", "session": "s-xxxx", "tool": "kb stats",
 "level": "L0", "args": {"--kind": "problems"},
 "status": "ok", "ms": 128, "exit": 0,
 "stdout_head": "…前 500 字…", "stderr_head": "",
 "confirmed_by": "", "cost_note": ""}
```

- **stdout/stderr 只留前 500 字**（防 journal 爆掉，也防把大段学生作答写进日志）；
- L2 必须记 `confirmed_by`（教师确认动作的来源）；
- journal **只追加**，不提供"删除单行"API（可追溯性优先）。

## 4. 护栏（T17）

| 护栏 | 默认值 | 说明 |
|---|---|---|
| 单次会话调用上限 | 40 次 | 超出即停，提示"本次会话调用次数已达上限" |
| 单次调用超时 | 120 s | 超时 kill，记 `status=timeout` |
| 单次会话总时长 | 10 min | 防"一直跑" |
| L1 成本上限 | 30 次 | 会花 LLM 钱的调用单独计数 |
| 预算（可选） | 未设则不检查 | 配 `<ws>/assistopia/limits.json` 可覆盖默认 |

> 数值可配，但**不能配成"无限"**（上限有硬顶，如单会话 ≤ 200 次）。

## 5. 用户扩展隔离（T18，核心）

```
<ws>/extensions/                 ← 升级**永不触碰**
    tools/<name>.json            ← 自定义/覆盖工具登记（只能**降级**不能升级！）
    rules/grading-rules.json     ← 覆盖内置评阅规则
    knowledge-terms.json         ← 覆盖受控词表
```

**加载优先级**：内置默认 → `extensions/` 覆盖 → 生效。

**关键限制（安全）**：`extensions/` 里的工具登记**只能把级别调高（更严），不能调低**。
否则等于"用配置文件就能给 AI 开写权限"，护栏形同虚设。
例：内置 `kb tag-knowledge --dry-run` = L1；`extensions/tools/x.json` 可把它设为 L2
（更严），但**不能**设为 L0。

## 6. LLM function calling（T16，最后接）

- 本单**先做**工具层（注册表 + 执行器 + journal + 护栏），它们**不依赖** function calling；
- T16 再把工具层暴露成 `tools` 协议给模型（OpenAI 兼容 `tools` / `tool_choice`）；
- provider 不支持 `tools` 时**自动降级**为"模型输出 JSON 指令 → 我方校验并执行"，
  且降级路径**同样受分级/护栏约束**（不能因为是降级就绕过）。

## 7. 实施清单

| # | 任务 | 批次 |
|---|---|---|
| T15a | 工具注册表（名称/级别/说明/参数白名单）+ 分级判定 + L3 硬拒绝 | P3-1 |
| T15b | 执行器：调 CLI 子进程、超时、截断、写 journal | P3-1 |
| T17 | 护栏（调用数/时长/L1 成本/预算）+ L2 二次确认 token | P3-2 |
| T18 | `extensions/` 加载与"只能更严"约束 | P3-2 |
| T16 | function calling 接入（含降级路径） | P3-3 |
| T15c | PWA Assistopia 工作区（工具列表 + 执行 + 确认 + journal 查看） | P3-3 |

## 8. 验收标准

1. 注册表里**未登记**的命令一律拒绝（默认拒绝）；
2. L3 工具**无法**被任何配置开通（含 `extensions/`）；
3. L2 工具未经确认不得执行；确认记录进 journal 的 `confirmed_by`；
4. L0/L1 可直接执行，且每次调用都留 journal（含耗时/状态/前 500 字输出）；
5. 超出调用上限/超时 → 拒绝或 kill，并给出可读原因；
6. `extensions/` 覆盖生效，但**只能更严不能更松**（有测试锁定）；
7. 升级（引擎更新）**不触碰** `extensions/` 内任何文件；
8. pytest / build / selfcheck / 脱敏 全绿。

## 9. 风险

| 风险 | 缓解 |
|---|---|
| 模型组合出危险命令（如 `kb write --input /etc/passwd`） | 参数白名单 + 路径必须在 workspace 内 |
| 教师嫌确认麻烦，想"全部允许" | **不提供**该开关；只允许逐次确认 |
| journal 泄露隐私 | 只存前 500 字；敏感参数（api_key）**永久脱敏** |
| 扩展机制被用来提权 | 只能更严（§5） |
| 子进程逃逸 | 参数字典传参（不走 shell），cwd 固定 workspace |

## 10. 实施记录

### 10.1 P3-1：工具注册表 + 分级 + 执行器 + 审计（T15a/T15b，2026-10-30）

**新增** `engine/src/assist/assistopia/`：
- `registry.py`：27 个内置工具（L0 10 / L1 4 / L2 8 / L3 5）+ 分级 + 参数白名单
  + `build_argv`（列表传参）+ `extensions/` 覆盖加载（只升不降）
- `runner.py`：子进程执行（`python -m assist.cli <argv> -w <ws>`，cwd=workspace）、
  超时 kill、输出截断 500 字、逐次 journal
- `limits.py`：护栏 + **硬顶夹取**（`HARD_CAPS`，配置再大也压回）
- CLI：`assist assistopia tools | run | journal`

**关键安全决定（均已测试锁定）**

| 决策 | 理由 |
|---|---|
| **白名单**，未登记一律拒绝 | 命令名可拼出无限变体（`kb.write` / `kb  write`），按名猜测必有漏 |
| L3 **写死在代码**，`extensions/` 也无法降级 | 否则"改个配置文件就能给 AI 开删除权限" |
| 扩展**只能升不能降**，且**不能新增工具** | 新增工具 = 任意命令注入 |
| 参数名白名单 + 路径必须在 workspace 内 + 值不得含 `--` | 防 `--workspace /etc`、路径穿越、开关注入 |
| 失败/超时**也计入**调用次数 | 否则可用"失败循环"绕过上限 |
| journal 只存前 500 字 | 防爆量；也防把大段学生作答写进日志 |

**实施中修的 1 个测试自身缺陷**：mock 子进程用 `"python"` 而非 `sys.executable`
（本机 `python` 不在 PATH），导致 3 个测试假失败——是测试问题，已改。

**验证**：engine pytest **922 passed**（新增 `tests/test_d132_assistopia.py` 37 例）；
app build 0 error；selfcheck 22 项全绿；脱敏通过。

### 10.2 P3-2：扩展覆盖 + 护栏写接口 + 升级安全（T17/T18，2026-10-30 完成）

**新增** `assistopia/extensions.py`：
- `rules/grading-rules.json` 覆盖 → 经 `rules._apply_extensions` 叠加进 `read_rules`，
  因此**批阅/规则卡/要点生成全部自动生效**（无需各处改调用）；
- `knowledge-terms.json` 覆盖 → 按 term 合并进 `load_vocab`（扩展优先）；
- `snapshot()` / `assert_untouched()`：升级前后比对 extensions/ 文件 sha256，
  用于**证明**升级没碰用户扩展；
- `ensure()` **只新建不覆盖**（有测试锁死）。

**`limits.write_limits()`**：教师可调护栏，但**超硬顶直接拒绝**（不是夹住后不吭声），
并写 `assistopia/journal.jsonl`。

**CLI**：`assist assistopia limits [--set k=v]`、`assist assistopia extensions [--init]`。

**关键决定：算法名（`types.<kind>.mode`）不允许被扩展覆盖**——
改了会让"计分算法"与"提示词规则摘要"不一致，属于只读项（docs/78 §3.4）。

**实施中修的 1 个真实缺陷**：词表覆盖最初用 `p.parent.parent` 取 workspace 根，
但 `knowledge-terms.json` **直接在 `<ws>/` 下**，父目录才是根 → 扩展词表静默不生效。
已改 `p.parent`，测试锁定"扩展词表术语必须出现在 load_vocab 结果里"。

**验证**：engine pytest **936 passed**（新增 `tests/test_d132_assistopia_ext.py` 14 例）；
app build 0 error；selfcheck 22 项全绿；脱敏通过。

### 10.3 T16：LLM function calling 会话（2026-10-30 完成）

**新增** `assistopia/agent.py`：`run_session()` 多轮会话循环。

- 采用**JSON 指令协议**（`{"action":"tool"|"final", ...}`）而非先做原生 `tools`：
  本项目所有 LLM 客户端都是 `chat(system,user_text)` 单轮接口，JSON 指令**在所有
  provider 上都可用**，不需要为原生 tools 改造客户端；
- 每轮把「工具结果」回喂模型（否则多轮等于瞎跑）；
- **统一 Gate**：两条路径最终都调同一个 `runner.run_tool()`
  → L3 拒绝 / L2 二次确认 / 参数白名单 / 护栏**全部照旧生效**；
- 模型没按 JSON 回复 → 当**最终回答**，**不猜测意图执行工具**（防幻觉触发写操作）；
- 容忍 ```json 围栏与前后废话（`_parse_json_reply`）。

**CLI**：`assist assistopia ask "<任务>" [--yes] [--max-turns N]`
（`--yes` = 教师本人终端自动同意 L2，仍不做 L3，且逐次记账）。

**测试锁定的 6 条安全性质**（`tests/test_d132_assistopia_agent.py` 15 例）：
1. 模型请求 L3 → 拒绝，且**不写 journal**（压根没执行）；
2. 模型请求未登记工具 → 拒绝；
3. L2 无确认通道 → 拒绝；教师拒绝 → 拒绝；教师同意 → 执行且 journal 记 `confirmed_by`；
4. 扩展把 L0 提成 L2 后，会话里**同样**要求确认（提级不被绕过）；
5. 护栏超限 → 会话中止；
6. 非 JSON 回复 → 当回答，不执行任何工具。

**验证**：engine pytest **951 passed**；build 0 error；selfcheck 22 项全绿；脱敏通过。

### 10.4 待做

- **PWA Assistopia 工作区**：工具列表（按级别分组）/ 执行 / L2 二次确认 / journal 查看。
  引擎侧已全部就绪（`/assistopia/tools`、`/assistopia/run`、`/assistopia/journal` 尚需 expose）。
