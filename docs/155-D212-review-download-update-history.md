# D212 需求单：作业预览-学习通「重复下载」的覆盖 / 历史 / 孤儿清理

> 日期：2026-11-19
> 状态：**已完成（2026-11-19）**
> 关联：`docs/153-D210-preview-cache.md`、`docs/154-D211-dedupe-and-overwrite.md`
>
> 隐私：测试只用合成数据。

---

## 0. 背景与现状

「作业预览-学习通」重复下载同一份作业时，当前行为：

- 文件名确定：`<学生>_<班级>+<作业>_p<序号><扩展名>`；
- `mode=missing`（PWA 默认）：已存在的图**跳过**，只补缺失；
- `mode=full`：同名文件**覆盖**；
- `manifest(students.json)` 每次重写，是“当前最新”的唯一权威。

### 现有隐患（3 种会产生两份/残留）

| # | 场景 | 结果 |
|---|---|---|
| A | 扩展名变化（jpg ↔ png） | 同一张图出现 **两份**（`p01.jpg` + `p01.png`） |
| B | 图片数量变少（3 → 2） | `p03.jpg` 成为**孤儿**留在目录 |
| C | 学生/作业改名 | 旧文件名那一套成为孤儿 |

另外：重下不做内容哈希比较，无法判断“这次到底变了没有”。

## 1. 需求

### R1. 新增 `update` 模式（推荐默认）

| 模式 | 语义 |
|---|---|
| `missing` | 只补缺失（保持现有行为） |
| **`update`** | **覆盖变化内容 + 归档旧版 + 清理孤儿（新默认）** |
| `full` | 强制全量重下（同样归档） |
| `comments-only` | 只更新批语/分数，不动图片 |

### R2. 主目录只保留最新一份（原子写）

- 同一「班级 + 作业 + 学生 + 图序」= 同一份，重下即替换；
- 写临时文件 + `os.replace` 原子替换，避免半张图。

### R3. 旧版进 `.history/`，不在主目录留两份

```
pages/review/<classId>/<workId>/
  学生甲_班级+作业_p01.jpg          ← 始终最新
  students.json
  .history/20261119-234500/
      学生甲_班级+作业_p01.jpg       ← 被覆盖前的旧版
      _orphans/…                    ← 被清理的孤儿
```

### R4. 内容哈希去重（幂等）

- 新图与旧图 `sha256` 相同 → **不写、不归档**，计入 `unchanged`；
- 重复点下载几乎零成本，历史不膨胀。

### R5. 按 manifest 清理孤儿

- `update` / `full` 模式下，下载完成后按新 manifest 的引用集合校验目录；
- 不在集合内的本作业图片 → 移到 `.history/<ts>/_orphans/`（不直接删）；
- 同时解决 A/B/C 三种残留。

### R6. 回执与界面

回执新增统计：

```json
{"stats": {"new": 3, "updated": 2, "unchanged": 40, "archived": 2, "orphans": 1}}
```

PWA 显示：`新增 3 / 更新 2 / 未变 40 / 归档 2 / 清理孤儿 1`，并新增「🔄 更新（推荐）」按钮。

### R7. 历史保留

`.history/` 纳入清理策略（默认保留 30 天），避免无限增长。

## 2. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 同图重复下载（内容未变） | `unchanged` 增加，不产生历史 |
| 2 | 图内容变化 | 主目录为新图；旧图进 `.history/<ts>/`；`updated/archived` 增加 |
| 3 | 扩展名 jpg→png | 主目录只有 `.png`；旧 `.jpg` 进 `_orphans` |
| 4 | 图片 3 张变 2 张 | 第 3 张进 `_orphans`，主目录只剩 2 张 |
| 5 | `missing` 模式 | 行为不变（只补缺、不清孤儿） |
| 6 | 原子性 | 写文件用临时文件 + replace |
| 7 | 回执 | 含五类统计 |
| 8 | 回归 | 全量 pytest 通过 |

## 3. 范围

允许：`engine/src/assist/xxt/review_history.py`（新增）、
`engine/src/assist/xxt/review_download.py`、`engine/src/assist/xxt/cli.py`、
`engine/src/assist/serve.py`、`app/src/lib/engineClient.ts`、
`app/src/views/XxetongView.vue`、`app/package.json`、对应 tests、本文档与 README 索引。

不得改变“只读下载”约束（仍只放行 GET/HEAD/OPTIONS + 显式白名单 POST），
不得删除 manifest，不得影响批阅/报告链路。


---

## 4. 实施结果

### 新增模块

`engine/src/assist/xxt/review_history.py`：

| 函数 | 作用 |
|---|---|
| `sha256_bytes` / `file_sha256` | 内容哈希 |
| `atomic_write_bytes` | 临时文件 + `os.replace` 原子写 |
| `new_history_dir` | `.history/<YYYYmmdd-HHMMSS>`（同名自动加序号） |
| `archive_existing` | 旧文件移入历史目录 |
| `save_file` | 返回 `new / updated / unchanged`，并累加统计 |
| `manifest_keep_names` | 从 manifest 提取全部引用文件名 |
| `cleanup_orphans` | 孤儿移入 `.history/<ts>/_orphans/` |
| `prune_history` | 清理 30 天前历史目录 |

历史目录**按需创建**：内容全未变时不会留下空目录。

### 下载链路

- `--mode` 新增 `update` 并设为**默认**（`missing/full/comments-only` 保留）；
- `update`/`full` 走哈希+归档写入；`missing` 保持“已有就跳过”；
- 下载完成后按新 manifest 清理孤儿；
- manifest 与回执新增 `stats` / `orphans` / `historyDir`；
- CLI 额外输出 `__STATS__{json}` 单行标记供 PWA 展示。

### PWA

- 每个作业新增「🔄 更新（推荐）」按钮（`mode=update`）；
- 下载完成提示：`下载完成（新增 N / 更新 M / 未变 K / 归档 O / 清理孤儿 P）`。

## 5. 真机验证（真实学习通）

对象：`大学物理知识点拾遗 / 新建班级2 / 手动测试作业发布`（1 份作答）。

| 场景 | 统计 | 目录结果 |
|---|---|---|
| 首次下载 | `new=1` | 主目录 1 张图 + `students.json` |
| 再下载一次（内容未变） | `unchanged=1` | 无新文件、无空 `.history` |
| 本地改坏文件后再下载 | `updated=1, archived=1` | 主目录恢复为平台原图；改动版进 `.history/<ts>/` |
| 手工放入孤儿文件后再下载 | `orphans=1` | 孤儿移入 `.history/<ts>/_orphans/` |

## 6. 测试

`engine/tests/test_d212_review_update_history.py`（10 项）：
新增/未变/更新三态、原子写无残留 tmp、历史目录唯一、按需创建、
孤儿清理（含 manifest 不动、子目录忽略）、历史清理、keep 集合、源码契约。

全量 pytest：`1935 passed`；`selfcheck:d212` 通过；前端 build 通过。

## 7. 与旧行为对比

| 场景 | 旧行为 | 新行为（update） |
|---|---|---|
| 重复下载同一张图 | 重写（无变化感知） | `unchanged`，不写盘 |
| 图内容变了 | 直接覆盖，旧版丢失 | 旧版进 `.history/`，可回溯 |
| 扩展名变化 | 主目录两份 | 旧扩展名进 `_orphans` |
| 图片变少 | 孤儿残留 | 进 `_orphans` |
| 学生/作业改名 | 旧名残留 | 进 `_orphans` |
