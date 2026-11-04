# D161 需求单：翻译题随机种子（新建时随机、记进作业纸、可重抽）

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/46-D93`（translation 合成题）、`docs/12`

## 0. 问题

翻译题的抽取用 `random_seed` 做确定性随机，但**新建作业纸时从不写这个字段**
→ 永远取 0 → **每次抽到同一道翻译题**。

CLI 侧更弱：`sheet make` 没有任何 `--seed` 选项，也从不生成种子。

## 1. 设计

### 1.1 生成时机（关键）

| 场景 | `random_seed` |
|---|---|
| **新建**作业纸 | 自动取**当前时间戳**（`Date.now() % 2^31`） |
| 已存作业纸再次生成 | **用已存的值**（不变） |
| 教师点「🎲 换一题」 | 生成新时间戳并写回 |

**为什么不在每次生成时取当前时间**：那样同一份作业纸每次打印的翻译题都不同，
学生手里的与教师手里的对不上。种子必须**固定在作业纸里**，只在"新建/重抽"时变。

### 1.2 保留可复现性

```
随机生成一次 → 记进 <ws>/tasks/<padId>.taskpad.json 的 random_seed
            → 之后任何时候重出都是同一道（可核对、可复现）
```

存储**复用已有文件**（`packs/*.pack.json` / `tasks/*.taskpad.json`），不新建文件。

### 1.3 入口

| 能力 | PWA | CLI |
|---|---|---|
| 新建时自动随机 | ✅ | ✅（无种子则生成并写回） |
| 记住种子 | ✅ taskpad.json | ✅ 同一文件 |
| 手动换种子 | 🎲「换一题」按钮 | `--reseed` |
| 指定种子 | — | `--seed <int>` |

## 2. 任务清单

| # | 内容 | 验收 |
|---|---|---|
| T1 | PWA 新建作业纸时写入时间戳种子 | 单测（两次新建不同） |
| T2 | PWA 作业纸设计页加「🎲 换一题」 | 浏览器 |
| T3 | CLI `sheet make` 支持 `--seed` / `--reseed`，无种子时生成并写回 | CLI 测试 |
| T4 | 已存种子不被覆盖 | 单测 |
| T5 | 文档 | — |

## 3. 验收标准

1. 新建两份作业纸，`random_seed` **不同**（不会永远抽同一题）；
2. 同一份作业纸重复生成，**抽到同一道题**（可复现）；
3. 点「🎲 换一题」后种子改变、题目改变，且写回 JSON；
4. CLI 与 PWA 行为一致（同种子 → 同题）；
5. pytest / build / selfcheck / 脱敏全绿。

## 4. 实施记录（2026-10-31 完成）

### 4.1 PWA

- `taskpad.makeRandomSeed()`：`Date.now() % 2147483647`（与引擎 `seed_index` 同量级）；
- `emptyTaskpad()` 写入 `random_seed` —— **新建作业纸的唯一入口**，天然覆盖
  "新建 / 另存为新作业纸"；
- 作业纸设计页新增 **「🎲 换一题」**：生成新种子（保存后写回 taskpad.json）。

### 4.2 CLI

- `paper.task.ensure_random_seed(task, task_path, reseed=, seed=)`：
  - `--seed N` → 用 N；
  - `--reseed` → 新时间戳种子；
  - 已有且未要求重抽 → **不变**（可复现）；
  - 没有 → 生成并**写回 taskpad.json**；
- `sheets_from_task(..., reseed=, seed=)` 入口调用它；
- CLI `sheet make --seed N | --reseed`。

### 4.3 存储

复用**已有**文件，不新建：
- 作业包 `<ws>/packs/<id>.pack.json`
- 作业纸 `<ws>/tasks/<padId>.taskpad.json`（`random_seed` 字段早已预留）

## 5. 验收对照

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 新建两份作业纸种子不同 | ✅ | `test_two_new_pads_get_different_seeds` |
| 2 | 同一份重复生成抽到同一道题 | ✅ | `test_existing_seed_kept` / `test_same_seed_same_translation` |
| 3 | 「🎲 换一题」改变种子并写回 | ✅ | `test_reseed_changes_seed` / PWA 按钮 |
| 4 | CLI 与 PWA 同口径（同种子同题） | ✅ | `test_explicit_seed_wins` + 共用 `seed_index` |
| 5 | 种子落盘、可复现 | ✅ | `test_writes_back_to_file` / `test_seed_is_stable_across_reloads` |
| 6 | pytest / build / selfcheck / 脱敏 | ✅ | 1264 passed · 0 error · 33/33 |
