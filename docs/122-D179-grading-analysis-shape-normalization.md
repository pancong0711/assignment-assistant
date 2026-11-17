# D179 需求单：评阅失败「sequence item 20: expected str instance, list found」

> 日期：2026-11-17
> 状态：**已完成（2026-11-17）**
> 关联：`docs/121-D178`（copyonly tag 等价别名 + 跳过可见）、
> `docs/119-D176`（逐题 kind 贯通）、`docs/120-D177`（评阅提示词唯一入口）
>
> 隐私：需求单中的学生姓名以「学生 A」代称；不得把真实姓名、图片、转写、
> API key 或 workspace 内容交给外部编码 agent。

---

## 0. 教师反馈

在 copyOnly 作业纸的 AI 批阅中，点击「转写+批阅」失败：

```text
转写+批阅失败：
12:43:19 [assist.grading.flow] [评阅] FAIL 学生A:
sequence item 20: expected str instance, list found
Error: 学生「学生A」评阅失败：
sequence item 20: expected str instance, list found
```

此前 D178 已修复 copyonly 学生的作业纸题目匹配与静默跳过问题；本次错误发生在
**题目已匹配、转写完成后，进入评阅结果组装阶段**，属于另一个独立缺陷。

---

## 1. 根因定位（已用最小用例复现）

### 1.1 直接崩溃点

`engine/src/assist/grading/evaluate.py` 的 `build_feedback_md()` 中：

```python
g = (analysis or result.get("analysis", {})).get("guidance", result.get("guidance", ""))
if g:
    lines += ["", "---", "## 整体思考", g]
...
return "\n".join(lines)
```

当模型返回的顶层 `guidance` 是**数组**（如 `["问题1", "问题2"]`）时，`g` 被原样
放进 `lines`，最后 `"\n".join(lines)` 抛：

```text
TypeError: sequence item 20: expected str instance, list found
```

已按「2 道题、每题 1 个 error、顶层 guidance 为数组」构造最小用例，**可稳定复现
同一句错误，且列表元素下标正好是 20**。

### 1.2 为什么 schema 没有拦住

- 评阅输出虽然声明了 `EVALUATION_SCHEMA`（`guidance: string`），但：
  1. provider 可能不支持 `json_schema`，`analyze()` 会回退到 `json_object`；
  2. `json_object` 只保证「是合法 JSON」，不保证字段类型；
  3. `parse_llm_json()` 当前只做 JSON 解析/LaTeX 修复，**没有按 schema 做后置类型校验**；
  4. 下游 `score_from_analysis()` 和 `build_feedback_md()` 默认信任字段类型。
- 因此模型只要把 `guidance`、`summary`、`evidence` 等标量字段偶尔输出成数组，
  就会在组装批语时崩溃。**不是 copyOnly 的计分规则算错**；copyOnly 只是本次
  实际触发该模型输出形态的场景。任何 tag、任何题型都存在同类风险。

### 1.3 影响面

- 在线逐生评阅：`evaluate_student()` → `build_feedback_md()`；
- 批量结果回灌：`build_result_from_analysis()` → `build_feedback_md()`；
- 同类的「本应是字符串、实际是数组」字段还可能影响报告展示与草稿批语：
  `guidance`、`summary`、`question_match.*`、`reasoning.note`、
  `errors[].description/evidence/why/step` 等。
- 本次崩溃发生时评阅结果未写出，教师侧表现为「整生失败、无分数、无批语」。

---

## 2. 修复目标

### 2.1 核心目标

在**评阅分析结果进入业务逻辑之前**增加唯一、可复用的类型归一化边界：
模型输出结构漂移时，尽量恢复为可读内容并继续批阅，而不是让单生整单失败。

### 2.2 非目标

- 不改动评分规则、题型判断、tag 匹配和提示词语义；
- 不因本次修复放宽 `evidence`/`confidence` 等严谨性要求；
- 不新增运行时依赖，不引入完整 JSON Schema 校验库；
- 不读取或上传真实学生数据到编码 agent / 外部服务；
- 不自动部署、不自动推送远端。

---

## 3. 实现要求

### R1. 新增统一的评阅结果归一化函数

建议位置：`engine/src/assist/grading/evaluate.py`（或 `prompts.py`，但必须
只有一个出口）。函数至少保证：

- 顶层必须是 `dict`；非 dict 时降级为空结果并告警；
- 标量字段必须是 `str`：
  - `guidance`、`summary`、`question_match.note/evidence/reason`；
  - `questions[].reasoning.note`；
  - `questions[].errors[].step/description/evidence/why/guidance`；
- 列表字段必须是 `list[str]`：
  - `strengths`、`weaknesses`、`correct_points`、`errors[].knowledge`、
    `knowledge_missing`；
- `questions`、`errors` 必须是「对象数组」，过滤掉非对象元素；
- 数字/布尔字段尽量保留原类型；无法判断时安全降级；
- 数组转字符串时**不得丢内容**，按可读顺序用 `；` 或换行拼接；
  dict 等复杂值用紧凑 JSON 字符串兜底；
- 修正时记录字段路径 warning，但**不得把学生原文或完整模型输出写进日志**。

### R2. 接入所有评阅入口

- `analyze()` 解析成功后立即归一化；或
- `evaluate_student()` 与 `build_result_from_analysis()` 在调用
  `score_from_analysis()` / `build_feedback_md()` 前统一归一化。
- 两条路径必须共用同一个函数，避免再次出现「在线正常、批量回灌崩溃」。

### R3. 批语组装增加最后一道防线

`build_feedback_md()` 是纯展示函数，不应因任意字段类型崩溃：

- 对进入 `lines` 的动态值统一 `_as_text(...)`；
- `guidance`、`summary`、`correct_points`、`deductions`、`thin_questions`、
  `strengths`、`low_items` 均走同一转换；
- 保留列表内容的可读顺序，不静默丢弃。

### R4. 可诊断性

- 评阅结果 JSON 增加最小诊断字段（例如
  `analysis_shape_fixes: ["guidance: list→str", ...]`），供教师排查；
- 不记录完整原始响应，不记录真实作答文本；
- 修复后若模型持续输出错误类型，仍应成功产出结果，同时日志给出可定位 warning。

### R5. 回归与边界

必须覆盖以下场景：

1. 顶层 `guidance` 为字符串数组 → 不抛错，批语中含全部问题；
2. `summary` 为数组、`strengths/weaknesses` 为字符串或数组 → 不抛错；
3. `errors[].evidence/why/guidance` 为数组 → 不抛错且内容保留；
4. `questions`/`errors` 含 `null`/字符串等脏元素 → 过滤后可继续；
5. 正常字符串输出行为不变；
6. `evaluate_student()` 端到端写出 `evaluations/<student>.json` 和 `.md`；
7. `build_result_from_analysis()` 批量回灌路径同样通过；
8. copyOnly 端到端仍能产出 `ai.score` + `ai.comment`（守住 D178 行为）。

---

## 4. 验收标准

| # | 标准 | 验证方式 |
|---|---|---|
| 1 | 复现用例不再抛 `sequence item 20` | 新增最小单测 |
| 2 | 含顶层 `guidance` 数组的评阅结果能正常写出分数/批语 | `evaluate_student()` 端到端单测 |
| 3 | 批量回灌路径同样不崩溃 | `build_result_from_analysis()` 单测 |
| 4 | 列表内容不丢，按顺序合并为可读文本 | 断言批语包含各数组元素 |
| 5 | 正常输出快照不回归 | 现有评阅/反馈测试全绿 |
| 6 | copyOnly 端到端不回归 | D178 测试 + 针对性回归 |
| 7 | 无新增依赖、无真实网络/学生数据 | 测试使用合成数据与 stub client |
| 8 | 全套回归 | `pytest`（当前基线 1620+）及项目 selfcheck |

---

## 5. 交给 opencode 的执行计划（已按此执行）

### 5.1 连接方式：service 直连，不走交互式 CLI

1. 使用本地 `opencode` service（HTTP/服务模式）提交任务，绑定
   **127.0.0.1 回环地址**，不得暴露公网；
2. service token/密码只从受控环境注入，不写入仓库、不写进需求单、不放进 prompt；
3. 每次任务使用独立 session，任务结束后显式关闭；
4. 先做健康检查与权限预检，确认 agent 实际工作目录、可写路径、可用命令；
5. 连接参数与原始会话日志不提交到 git。

### 5.2 工作区与权限边界

建议为本次修复创建独立 worktree：

```text
repo/.scratch/worktrees/D179/
  └─ 从当前 main HEAD 创建 fix/d179-analysis-shape 分支
```

权限按最小必要设置：

- **只读**：仓库 `docs/`、`engine/src/assist/grading/`、`engine/tests/`；
- **可写**：仅独立 worktree 内的 `engine/src/assist/grading/` 与
  `engine/tests/`；
- **禁止**：`~`、`.ssh`、`.git` 写操作、其它 Projects、真实 workspace、
  `settings.local.json`、题库/名单/图片/转写/成绩文件；
- **命令**：允许 `git status/diff/log`、`rg`、指定 pytest；`git commit`、
  安装依赖、网络请求、后台进程、`sudo`、删除文件等需人工确认或直接拒绝；
- **外部 agent 工具**：禁止读取环境变量和密钥；禁止 `curl/wget` 外部网络；
  禁止把学生 PII 或真实 API 响应放进任务上下文。

### 5.3 执行步骤（讨论通过后才启动）

1. 在隔离 worktree 中复现：新增失败测试，确认能触发
   `sequence item 20: expected str instance, list found`；
2. 实现统一归一化函数，并接入在线/批量两条评阅路径；
3. 加固 `build_feedback_md()` 的动态值转字符串；
4. 补 R5 全部边界测试，运行目标测试与全套 pytest；
5. 生成 diff、测试输出、风险说明；**不自动 commit/push**；
6. 由人工 review 后决定是否提交；如权限或行为异常，直接丢弃 worktree。

### 5.4 交接给 opencode 时必须附带

- 本需求单；
- 目标文件与明确验收测试；
- 禁止修改的模块/文件清单；
- 测试命令与预期基线；
- 权限配置和会话上限；
- 要求最终只返回：改动摘要、`git diff --stat`、测试结果、未解决问题；
- 明确「不得访问真实 workspace、不得发起真实 LLM 请求、不得提交」。

---

## 6. 实施结果（2026-11-17）

- 修改：`engine/src/assist/grading/evaluate.py`；
- 新增测试：`engine/tests/test_d179_analysis_shape_normalization.py`（13 项）；
- `analyze()` 返回后立即归一化，再进入 `_enrich_questions()`，顶层非 dict 也能优雅降级；
- 在线评阅与批量回灌共用 `_normalize_analysis_shape()`；
- `build_feedback_md()` 所有动态值经 `_as_text()` 输出；
- 验收：D179 目标测试 13 passed；D178 + 批阅相关回归 17 passed；
  全量 pytest 1631 passed / 2 skipped；
- 脱敏检查与启动脚本 lint 通过；未修改评分规则、tag 匹配、提示词语义和前端。
