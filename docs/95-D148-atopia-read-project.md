# D148 需求单：Atopia 通用只读文件能力（fs.ls / fs.read / fs.search）

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/81-D132`（工具白名单/分级）、`docs/86-D136`（会话头）、
> `docs/89-D140`（Atopia 对话）、`docs/12`

## 0. 教师反馈

> atopia 需要能够读我们整个项目的全部内容，包含各类文档。
> 当时让它看一道题的参考答案，它应该先找到这个文档、再打开文档查看，
> 为什么我们的工具设计里不是这样的？

## 1. 根因（设计缺口，不是 bug）

D132 的工具白名单是**"特定任务命令"**（`kb.stats` / `materials.show` / …），
**没有任何通用文件操作**：没有 `ls`、没有 `read`、没有搜索。

`materials.files` 只列 `materials/<chap>/_source/` 下的原件，**不是全项目**。

原因：D132 选了"白名单而非黑名单"——只登记确定安全的命令。
这个取舍保证了安全，代价是 **AI 只能做我们预先想到的事**，
无法"翻项目找文档"。

## 2. 设计

### 2.1 新增三个 **L0 只读** 工具

| 工具 | 作用 | 说明 |
|---|---|---|
| `fs.ls` | 列目录（名称/类型/大小） | workspace 内，深度受限 |
| `fs.read` | 读文本文件（分页/截断） | 默认前 200 行；二进制拒读 |
| `fs.search` | 按关键词搜文件内容 | 返回 `文件:行:摘要` |

### 2.2 安全约束（硬性）

1. **路径必须在 workspace 内**（复用 `registry.validate_args` 的 `path_in_ws`）；
2. **硬屏蔽敏感路径**（即使调用方是 AI、即使路径看起来正常）：
   - `settings.local.secrets.json` / `*.secrets.json`
   - `.runtime/**`（含浏览器数据、venv）
   - `atopia/limits.json`（护栏自我篡改）
   - `.git/**`
3. **只读**：三个工具都**不写任何文件**；
4. 大小/条数上限：`fs.read` ≤ 200 行或 64KB；`fs.search` ≤ 50 条；
5. 二进制文件（含 `\x00`）拒读并提示"这是二进制文件"；
6. 全部记 journal（工具名/参数/耗时）。

### 2.3 为什么这**不削弱** D132 的安全模型

- 仍是**白名单**（只登记这三个通用能力，不是"任意命令"）；
- 比"不给文件能力"多了"读"，但**读的范围被 workspace + 屏蔽清单硬限制**；
- **写**能力没有增加：`fs.*` 全为 L0，AI 仍然无法改任何文件；
- L3 口径完全不变。

## 3. 任务清单

| # | 内容 | 验收 |
|---|---|---|
| T1 | `fs.ls` / `fs.read` / `fs.search` CLI（只读） | CLI 测试 |
| T2 | 注册为 L0 工具（参数 `path`/`query` 走 `path_in_ws`） | 注册表测试 |
| T3 | 敏感路径屏蔽（secrets/.runtime/.git/limits） | 单测：读 secrets 被拒 |
| T4 | 二进制拒读；大小/条数截断 | 单测 |
| T5 | 端到端：AI 用 `fs.search` 找到答案文件再 `fs.read` | 单测（假 LLM） |
| T6 | 文档回填 | — |

## 4. 验收标准

1. AI 能列出 workspace 目录、读文本文件、按关键词搜索；
2. 读 `settings.local.secrets.json` → **被拒绝**；
3. 读 workspace 之外（`/etc/passwd`）→ **被拒绝**；
4. 读二进制（png）→ 明确提示，不返回乱码；
5. `fs.read` 超大文件被截断并说明；
6. 三个工具**都不能写**（无副作用，journal 可证）；
7. pytest / build / selfcheck / 脱敏全绿。

## 5. 风险

| 风险 | 缓解 |
|---|---|
| 读到密钥 | 硬屏蔽清单 + 单测锁定 |
| 读到无关学生隐私数据 | 只读且需 AI 主动指定路径；journal 可审计 |
| 大文件把上下文撑爆 | 行数/字节上限 + 截断提示 |
| 目录过大导致列举慢 | 深度/条数上限 |

## 6. 实施记录（2026-10-31 完成）

### 6.1 新增 `atopia/fsview.py`

`ls` / `read` / `search` 三个纯只读函数 + `_resolve_in_ws` 路径校验：

- workspace 边界（`resolve()` 后 `relative_to` 校验）；
- 硬屏蔽：`.runtime` / `.git` / `node_modules` / `__pycache__` / `.venv` 目录，
  以及 `*.secrets.json` / `limits.json` 文件；
- 二进制（含 NUL）拒读；
- 上限：列目录 300 项、读 200 行/64KB、搜索 50 条/单文件 2MB。

### 6.2 CLI + 工具注册

- `assist fs ls|read|search`
- 工具 `fs.ls` / `fs.read`（`path_in_ws`）、`fs.search`（`query` 位置参数）

### 6.3 顺带修了一个**真实缺陷**

`registry.build_argv()` 的占位符正则写成了双反斜杠：

```python
re.fullmatch(r"\\{(\\w+)\\}", tok)   # 匹配的是字面 `\{`，永远不命中
```

导致**所有用 `{name}` 占位符传参的工具**（`fs.search`、`kb.write` 等）参数传不进去，
报 "不知道如何传递参数"。已改为 `r"\{(\w+)\}"`。

（此类"正则多写一层反斜杠"的问题已是第二次出现，D136 的 `_SAFE_STR` 也是同一类。）

## 7. 验收对照

| # | 标准（§4） | 结果 | 证据 |
|---|---|---|---|
| 1 | 能列目录/读文件/搜关键词 | ✅ | `test_ls` / `test_read` / `test_search_finds_answer` |
| 2 | 读 secrets → 拒绝 | ✅ | `test_blocked_secrets` / `test_fs_read_via_runner_blocks_secrets` |
| 3 | 读 workspace 外 → 拒绝 | ✅ | `test_blocked_outside_workspace` / `test_fs_read_rejects_non_ws_path_arg` |
| 4 | 读二进制 → 明确提示 | ✅ | `test_binary_rejected` |
| 5 | 大文件截断并说明 | ✅ | `test_read_truncated` |
| 6 | 只读（无写能力） | ✅ | 三个函数均无写操作；L0 |
| 7 | pytest / build / selfcheck / 脱敏 | ✅ | 1204 passed |

## 8. 现在 AI 能做什么

教师：**"帮我找 chap04 第 1 题的参考答案"**

AI 现在可以：
1. `fs.search("chap04-01")` → 找到 `kb/solutions/chap04-01.json`
2. `fs.read("kb/solutions/chap04-01.json")` → 看到答案内容
3. 回答教师

这正是教师期望的"先找到文档、再打开查看"。
