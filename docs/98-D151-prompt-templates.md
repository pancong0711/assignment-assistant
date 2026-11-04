# D151 需求单：提示词模板中心（5 类 system prompt 可改/可存/可删）

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/108-D108`（原 ai-solve 模板库）、`docs/78-D130`、`docs/12`

## 0. 问题

5 处 system prompt **硬编码**，教师无法调整：

| 文件 | 常量 | 用途 |
|---|---|---|
| `grading/evaluate.py` | `ANALYSIS_PROMPT` | 批阅 |
| `grading/prompts.py` | `TRANSCRIPTION_PROMPT` | 转录 |
| `grading/solve.py` | `SOLVE_SYSTEM_PROMPT` | AI 作答 |
| `grading/rubric.py` | `RUBRIC_PROMPT` | 评阅要点 |
| `grading/termnorm.py` | 术语归一 | 知识点归一 |

现有模板库（`prompts/ai-solve/`）只覆盖"作答要求"，不含 system prompt。

## 1. 设计

### 1.1 目录扩展

```
<ws>/prompts/
  ai-solve/        ← 已有：作答要求片段
  transcribe/      ← 新：转录 system prompt
  evaluate/        ← 新：批阅 system prompt
  solve/           ← 新：AI 作答 system prompt
  rubric/          ← 新：要点生成 system prompt
  termnorm/        ← 新：术语归一 system prompt
```

每个目录用**同一套** `files/prompts.py` 的 CRUD（`list/save/delete/set_default`）。

### 1.2 解析顺序

**选了模板 → 用模板；没选 → 用内置默认**（向后兼容，不选等于现状）。

### 1.3 安全门槛（教师要求）

| 类别 | 可编辑 | 额外要求 |
|---|---|---|
| solve / rubric / termnorm | ✅ 自由改 | — |
| **transcribe** | ✅ 可改 | 模板必须仍能产出**结构化 JSON**：保存时提示"改完请先跑一次试转写" |
| **evaluate** | ✅ 可改 | 内置默认**不可删**；保存时提示"改完请先跑一次试批阅" |

内置模板（每类至少一个 `builtin=True`）不可删除，可复制后修改。

## 2. 任务清单

| # | 内容 | 验收 |
|---|---|---|
| T1 | `prompts.py` 支持多 category（目录参数化） | 单测：各 category 独立 |
| T2 | 5 类内置默认模板（首次访问落盘） | 单测 |
| T3 | 各调用点支持"取模板 or 内置默认" | 单测：不选=现状 |
| T4 | CLI `prompt list/save/delete/use` 加 `--category` | CLI 测试 |
| T5 | serve `/prompts?category=` CRUD | 单测 |
| T6 | PWA 模板管理入口（题库AI+ 页） | 浏览器 |
| T7 | evaluate 的内置模板不可删 | 单测 |

## 3. 验收标准

1. 不选模板时行为**与改动前完全一致**（有测试锁定）；
2. 5 类都能列出/保存/另存/删除/设默认；
3. **evaluate 内置模板不可删**；transcribe/evaluate 保存时给出"先试跑"提示；
4. 模板改动**立即生效于下一次调用**；
5. pytest / build / selfcheck / 脱敏全绿。

## 4. 实施记录（2026-10-31 完成）

- `prompts.py`：`CATEGORIES` 六类（含原有 `ai-solve`），`prompts_dir/get_template/
  list_templates/save_template/delete_template/set_default/default_template` 全部支持 `category`；
- 新增 `system_prompt(ws, category, fallback)` 与 `system_prompt_env(category, fallback)`
  （后者供没有 `ws` 参数的旧函数用 `ASSIST_WORKSPACE`）；
- **不选模板 = 内置默认**（`text` 为空即回落），有测试锁定；
- 五处接入：`evaluate.analyze(ws=)` / `solve` / `rubric` / `transcribe` / `termnorm`；
- CLI `prompt list|save|delete|use --category`；serve `/prompts/templates`、`/prompts/save`；
- PWA「题库AI+」④ 区：类别下拉 + 模板选择 + 编辑 + 保存/另存/设默认/删除。

## 5. 验收对照

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 不选模板 = 与改动前一致 | ✅ | `test_empty_template_falls_back_to_builtin` |
| 2 | 六类可列出/保存/删除/设默认 | ✅ | `test_list_per_category` 等（11 项） |
| 3 | **各类互相隔离** | ✅ | `test_categories_are_isolated` |
| 4 | 内置模板不可删 | ✅ | `test_builtin_not_deletable` |
| 5 | 新建模板不自动抢默认（防误改全局） | ✅ | `test_new_template_does_not_steal_default` |
| 6 | pytest / build / selfcheck / 脱敏 | ✅ | 1241 passed · 0 error · 33/33 |

验证：pytest **1241 passed** · build 0 error · selfcheck **33/33** · 脱敏通过。
