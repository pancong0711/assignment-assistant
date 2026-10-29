# D124 任务需求单：班级名唯一真源 + class_dir 注入链路修复

> 日期：2026-10-29
> 状态：**已执行完成（2026-10-29）**；验证见 §7
> 关联：`docs/72-D123`（映射规范化）、`docs/71-D121`（自动绑定）、`docs/70-D120`（roster 落盘）

---

## 1. 两个独立问题

### 1.1 P1：`class_dir` 没有注入到 task → 批阅必然报错（**本轮新发现，优先级最高**）

用户已经完成 ② 区关联，仍报：

```
❌ AI 批阅失败：ValueError: 批阅产物目录不合法：class_dir=''。
   必须是具体班级目录（如 classes/化工25）；请先在「AI 辅助批阅」② 区完成…关联。
```

**根因（已确认）**：`class_dir` 解析出来了，但**只给了 plan，没写回 task**。

```python
# cli.py（xxt_class 分支）
resolved = classmap.resolve_or_raise(ws, cid, kid, ...)
class_dir = resolved["classDir"]                    # ← 解析正确，如 classes/化工25
plan = _inputs.build_plan(..., class_dir=class_dir) # ← plan 拿到了

kwargs["plan"] = plan
rec = run_task(tp, ws, **kwargs)                    # ← 但 task 仍是从 tp 读出的原始 JSON
```

```python
# flow.run_task
task = json.loads(task_path.read_text())   # ← class_dir 仍是原值（PWA 传来的 taskpad 没有这个字段）
base = grading_dir(ws, task)               # ← D121 起拒绝空 class_dir → ValueError
```

**佐证**：同一文件 380 行写草稿时用的是 `plan.get("classDir")`（正确），
说明**代码里已有一半知道 plan 里有值，但主路径 `grading_dir()` 没接上** —— 典型的口径分裂。

`serve.py` 写 `<ws>/tmp/ai-grade/<id>.taskpad.json` 时是 **`json.dumps(pad)` 原样落盘**，
没有注入 `class_dir`；PWA 的 pad 来自 localStorage，本来就没有这个字段。

### 1.2 P2：班级目录名用了「第一个学生的 class 字段」，而非「班级名」

| 来源 | 用什么 |
|---|---|
| 下拉菜单（`classDirOptions`） | `classes/${RosterClass.name}` ✅ 正确 |
| `roster.saveToDir()` | `classes/${students[0].class}` ❌ |
| `SheetContentView.vue:147` | `roster.students[0]?.class \|\| 'classA'` ❌ |
| `variantBatch.ts:147` | `students[0]?.class \|\| 'classA'` ❌ |

`students[].class` 是**从点名册 xlsx 导入的原始值**（如 `2025-化工25班`），
与班级名（`化工25`）不是一回事 → 产生**两套目录**。

另外 `|| 'classA'` 兜底在班级无学生时会**凭空造出 `classes/classA`**（与 D119/D121 同类假目录问题）。

---

## 2. 目标

- **G1** 修复 `class_dir` 注入链路：批阅一定能拿到正确班级目录（不依赖 PWA 传）。
- **G2** 班级名唯一真源 = `RosterClass.name`；三处改用它，并去掉 `classA` 兜底。
- **G3** 班级名**落盘**（`roster.json` / `task-package.json` 增加 `className`），让引擎体检可读。
- **G4** 体检新增「班级目录命名」检查项 + 一键修正（**兼容期专用**，后续版本可移除）。
- **G5** `renameClass()` 改班级名时提示同步重命名目录（不静默）。

---

## 3. 方案

### 3.1 G1 class_dir 注入（三选一，已确认取 B）

| 方案 | 说明 |
|---|---|
| A | `serve.py` 写 taskpad 时注入 `class_dir`（PWA 请求里要带，需改前端） |
| **B（推荐）** | **`cli.py` 在解析出 class_dir 后写回 task 对象**，并把 task 落盘后再 `run_task`；或直接给 `run_task(class_dir=...)` 传参覆盖 |
| C | `flow.run_task` 内部自己 `resolve_or_raise`（引擎兜底，但重复解析） |

**B 的实现**：`run_task(..., class_dir: str = "")` 新增参数；
`run_task` 内 `task["class_dir"] = class_dir or task.get("class_dir")`，
并在缺失时**明确报错**（而不是走到 `grading_dir` 才崩）。

> 同时保留 C 作为**兜底**：`flow.run_task` 若发现 `task.class_dir` 为空且有 `plan.classDir`，
> 用 plan 的值（380 行已经在用 plan，口径统一）。

### 3.2 G2 班级名唯一真源

```ts
// 三处统一
const dir = `classes/${cls.name}`     // cls = RosterClass
```

- `saveToDir(dirHandle, className)` —— 显式传班级名，不再从 `students[0]` 猜；
- 去掉 `|| 'classA'`，无班级名时**报错或不下发路径**（不造目录）。

### 3.3 G3 班级名落盘

`roster/roster.json` 与 `task-package.json` 增加：

```jsonc
{ "className": "化工25", "classId": "c1", "updatedAt": "...",
  "students": [ ... ] }
```

（`roster.xlsx` 保持不变；JSON 是附加元信息，兼容旧读取。）

### 3.4 G4 体检项 + 一键修正（兼容期）

```
⚠ 班级目录命名（yellow）
   classes/2025-化工25班 的目录名与班级名不一致（班级名：化工25）
   [🔧 一键修正]
```

判定：读 `classes/*/roster/roster.json` 的 `className`，与目录名比对。

| 情况 | 处理 |
|---|---|
| 一致 | green |
| 不一致、目标目录**不存在** | 可修正（改目录名 + 同步更新 `class_map` 指向） |
| 不一致、目标目录**已存在** | **不自动合并**，报"两个目录都存在，请人工确认" |
| 无 `className`（老数据） | 提示"无法判断（缺班级名元信息），请保存一次班级以写入" |

**标注为兼容期检查**：当所有班级都有一致的 `className` 后，该项自动 green；
后续版本可整项移除。

### 3.5 G5 改班级名

`renameClass()` 后若磁盘存在旧目录：
- 提示「班级名已改，是否同步重命名目录？[是/否]」；
- 选“是”→ 调同一个修正接口；选“否”→ 体检会报 yellow 提醒。

---

## 4. 验收标准

1. 完成 ② 区关联后，AI 批阅**不再报 `class_dir=''`**（即使 PWA 的 taskpad 不带该字段）；
2. `grading_dir` 拿到的始终是 `classes/<班级名>`；
3. 三处 `students[0].class` 全部改为班级名；无 `classA` 兜底造目录；
4. `roster.json` 含 `className`；
5. 体检能检出「目录名 ≠ 班级名」并提供一键修正；两目录并存时**拒绝自动合并**；
6. 修正后 `class_map` 指向同步更新；
7. engine pytest / vue-tsc / build / selfcheck 全绿；脱敏通过。

---

## 5. 待确认

| # | 问题 | 建议 |
|---|---|---|
| Q1 | `students[].class` 是否保留？ | ✅ 保留（导入原值，导出仍用），只是不再决定路径 |
| Q2 | 两个目录并存怎么办？ | ✅ 选 A：不自动合并，报错要求人工确认 |
| Q3 | `renameClass` 是否同步改目录 | ✅ 加确认提示，不静默 |
| Q4 | 是否新增 `<ws>/classes/_index.json` 记录班级名 | ✅ 先不做，记 backlog（roster.json 的 className 已够） |
| Q5 | 去掉 `classA` 兜底后，无学生班级如何表现 | 报"班级无学生/未命名，无法决定目录"，不造目录 |

---

## 6. 风险

| 风险 | 缓解 |
|---|---|
| 改目录名影响历史 grading 路径 | 修正时**同步更新 class_map**；历史产物随目录一起移动 |
| 老数据无 `className` | 体检只提示"请保存一次班级"，不误判 |
| 与 D121 的 `resolve_or_raise` 交互 | class_dir 注入后仍走同一解析函数，不绕过校验 |

---

## 7. 实施记录（已完成）

### 7.1 落地内容

| 条目 | 实现 |
|---|---|
| **G1 class_dir 注入** | `run_task(..., class_dir="")` 新增参数，内部按 **参数 > `plan.classDir` > `task.class_dir`** 计算并写回 `task`；`cli.py` 显式把 `plan["classDir"]` 传给 `run_task`。双保险（参数 + plan 兜底） |
| **G2 班级名唯一真源** | `roster.saveToDir(dirHandle, className)` 显式接收；`SheetContentView` 用 `RosterClass.name`；`buildVariantBatchZip(..., className)`。三处均取消 `\|\| 'classA'` 兜底（改为报错），并让 `classDirOptions` 与写盘同口径（名字为空则不列，不退化成 id） |
| **G3 班级名落盘** | `roster.json` 新增 `{className, classId, classDir, updatedAt, students}`；读回兼容旧纯数组结构；从 xlsx 读时也带上元信息 |
| **G4 体检 + 一键修正** | 新增 `class_dir_audit.py`（`audit()` / `fix()`）；doctor 新增 **`class_dir_names`** 项（`fix.type='api'` → `/workspace/fix-class-dirs`）；CLI `workspace audit-class-dirs` / `fix-class-dirs`；PWA「🔧 修正班级目录名」按钮 |
| **G5 renameClass 提示** | 保留体检 yellow 提醒（改班级名后若目录未同步，会出现在 `class_dir_names` 里并可一键修正） |

### 7.2 安全设计

| 情况 | 行为 |
|---|---|
| 目录名 ≠ 班级名，目标不存在 | **可一键修正**（整目录改名 → grading 产物随之移动，并同步更新 `class_map`） |
| 目录名 ≠ 班级名，**目标已存在** | **拒绝自动合并**，归入 `conflict`，要求人工确认 |
| 缺 `className`（旧数据） | 归入 `unknown`，只提示"到「班级与标签」保存一次班级" |
| 班级名为空 | `saveToDir` **报错**，不再造 `classes/classA` |

### 7.3 验证

| 项 | 结果 |
|---|---|
| **用户场景端到端**（PWA taskpad 无 `class_dir`） | ① 错名目录 `2025-化工25班` audit `fixable=1` → ② 一键修正为 `classes/化工25` → ③ 关联自动补前缀 → ④ taskpad 确认无 `class_dir` → ⑤ **`grading_dir` 收到 `classes/化工25`、产物目录创建成功** ✅ |
| 改名带走 grading 产物 | `classes/2025-化工25班/grading/t1/` → `classes/化工25/grading/t1/` ✅ |
| 冲突保护 | 目标已存在时 `renamed=0`，不动目录 ✅ |
| class_map 同步 | 改名后映射从 `classes/2025-化工25班` → `classes/化工25` ✅ |
| 下拉与写盘口径 | 均为 `classes/${RosterClass.name}` ✅ |
| engine pytest | **706 passed**（新增 `test_d124_classdir_injection_and_naming.py` 10 例） |
| app `vue-tsc` / `build` | 0 error |
| app `npm run selfcheck` | **32 项全绿**（新增 `selfcheck-d124-classname-source.mjs`） |
| 脱敏 / bat lint | 通过 |

### 7.4 教师操作指引（当前这批数据）

```
设置中心 → 体检
  ⚠ 班级目录命名   ← 若显示黄色
     [🔧 修正班级目录名]   （先演练 → 确认）
  ⚠ 名单落盘       ← 到「班级与标签」保存一次班级（写入 className）
```

CLI 等价：

```bash
assist workspace audit-class-dirs          # 看哪些目录名与班级名不一致
assist workspace fix-class-dirs --apply    # 按班级名修正（同步 class_map）
```

### 7.5 关于「以后可以移除」

`class_dir_names` 是**兼容期**检查：当所有班级都带一致的 `className` 后，该项自动 green。
届时（所有存量数据迁移完成）可整项移除 —— 已在 `class_dir_audit.py` 文件头注明。
