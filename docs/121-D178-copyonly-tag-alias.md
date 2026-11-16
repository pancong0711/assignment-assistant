# D178 需求单：tag=copyonly 的学生「批阅后没有分数和批语」

> 日期：2026-11-16
> 状态：**已完成**
> 关联：`docs/119-D176`（题目类型贯通）、`docs/116-D171`（评阅落草稿）

## 0. 教师反馈

> 学生 tag 为 copyonly 的不能使用 AI 批阅。逐生批阅里点击「批阅」和「转写+批阅」，
> 都执行了操作，但是没有看到分数和批语。

---

## 1. 根因（端到端复现，两处叠加）

### 1.1 tag 匹配是**逐字精确**的，没有等价别名
`copyonly / copysp / copys / punish` 在**评阅规则**里都被归一到「抄写(copy)」：

```python
# grading/rules.py
_KIND_ALIASES = {"copys": "copy", "copyonly": "copy", "copysp": "copy", "punish": "copy"}
```

但 **tag 匹配**（`paper/pack._norm_tag` → `pick_pad_for_tag`）只做
「去空白 / 全半角 / 小写」，**没有别名**。于是：

```
学生 tag = copyonly，作业纸 target_tag = copy
  → 匹配失败 → 该生 questions = 0
  → _run_evaluate 跳过（"没有可用的作业纸题目"）
  → 无 evaluations/*.json → 无草稿 → 界面没有分数也没有批语
```

实测（真实 roster + taskpad + pack）：

| 作业纸 target_tag | 学生 tag | 修复前题目数 |
|---|---|---|
| `copyonly` | `copyonly` | 1 |
| `copy` | `copyonly` | **0** ← 教师踩的坑 |
| `copyonly` | `copy` | **0** |

### 1.2 跳过是"静默"的：任务仍以 done 结束
`_run_evaluate` 跳过后只写日志/诊断/journal，`run_task` 照常返回 `status=done`
→ CLI 打印「完成」→ PWA `pollJob` 显示「✅ 完成」。
教师看到"都执行了操作"，却完全不知道评阅被跳过。

---

## 2. 修复

### 2.1 tag 等价别名（根因）
- `paper/pack.py` 新增 `_TAG_ALIASES` + `_alias_tag()`，
  `pick_pad_for_tag()` 改为：**精确匹配 → 等价 tag 匹配 → 显式兜底作业纸**；
- `grading/inputs.build_plan._pad_for()` 同样加等价兜底；
- **仍严格限制在包内**（D127 红线：绝不回退到包外/全库作业纸），
  且精确匹配永远优先（包内同时存在 copy 与 copyonly 时不会误选）。
- 不相关 tag（如 `qa`）不会被误匹配。

### 2.2 跳过必须可见
- `_run_evaluate` 记录 `skipped` 原因；
- **逐生补批**（只点名 1 人）且一人未产出 → 抛 `GradingInputError`，
  CLI 转成可读业务错误 → PWA 显示「❌ 批阅失败：学生「张三」没有可用的作业纸题目…」；
- **整班批阅**不阻断，但把 `evaluate_skipped` 写进 run 汇总，
  CLI 额外打印：
  ```
  ⚠ 有 N 名学生未完成评阅（未产出分数/批语）：
    · 学生「李四」没有可用的作业纸题目…
  ```

---

## 3. 验收

| # | 标准 | 验证 |
|---|---|---|
| 1 | `copyonly`↔`copy`↔`copysp` 四种组合都能匹配到作业纸与题目 | `test_copy_tag_aliases_match` |
| 2 | `pick_pad_for_tag` 大小写归一 + 不误匹配无关 tag | `test_pick_pad_for_tag_uses_alias` |
| 3 | 等价兜底**不越出作业包** | `test_alias_never_leaves_the_pack` |
| 4 | copyonly 学生端到端产出 `ai.score` + `ai.comment`（草稿） | `test_copyonly_student_gets_score_and_comment` |
| 5 | 逐生补批被跳过 → 抛可读错误（不再假成功） | `test_single_student_skip_raises_readable_error` |
| 6 | 四道门 | pytest **1620** |

### 3.1 排障时同时修掉的测试污染
`flow.evaluate_student` 就是 `evaluate.evaluate_student` 本体，其 `__globals__`
即 evaluate 模块字典。测试里对同一 key 同时 `monkeypatch.setattr` + `setitem`，
恢复顺序错乱会让假 `analyze` 残留到后续用例（表现为 `test_grading` 的分数变成 40）。
现统一只 patch 一次，并加注释说明。
