# D120 任务需求单：workspace 根语义收口 + roster 自动落盘 + 目录错位迁移

> 日期：2026-10-29
> 状态：**已确认（2026-10-29 用户拍板）→ 执行中**
> 关联：`docs/69-D119`（批阅产物布局）、`docs/04`（数据契约）、`docs/05-D13`（workspace 引导）
> 触发：教师在「班级与标签」点「写回 workspace」后，roster 出现在 **`<ws>/kb/classes/<班级>/roster/`**，
> 而引擎只读 **`<ws>/<class_dir>/roster/roster.xlsx`** → AI 批阅报「名单 0 人」。

---

## 1. 问题

### 1.1 直接原因：目录句柄的语义被混用

```ts
// RosterView.vue
const dirHandle = computed(() => getKbDirHandle())     // ← 复用「题库目录」句柄
await roster.saveToDir(dirHandle)
//   → writeFileInDir(dirHandle, `classes/${cls}/roster/roster.xlsx`)
```

而 UI 上那个按钮写的是「连接**本地题库目录**（Chrome/Edge）」，教师自然选了 `<ws>/kb`。
于是：

| 操作 | 期望 | 实际 |
|---|---|---|
| roster 写回 | `<ws>/classes/<班级>/roster/roster.xlsx` | **`<ws>/kb/classes/<班级>/roster/roster.xlsx`** |
| kb 写回 | `<ws>/kb/<kind>.xlsx` | `<ws>/kb/<kind>.xlsx`（**恰好正确**，因为选了 kb/ 且代码写 `kb/...`? 见 §1.2） |

> 教师实测：`<ws>/kb/classes` **存在**，`<ws>/kb/kb` **不存在**。
> → 说明 kb 写回时句柄应是 `<ws>`（而不是 `<ws>/kb`），或路径前缀被正确抵消。
> **结论：同一句柄被两处按不同语义使用**（一处当 workspace 根、一处当 kb 根）。

### 1.2 这是同一根因的第三次出现

| # | 现象 | 共同根因 |
|---|---|---|
| 1 | 作答图/草稿落进仓库 `.scratch`（D119） | 路径根不唯一 |
| 2 | roster 只在 localStorage，引擎读不到 | 前后端数据契约缺失 |
| 3 | **roster 写进 `kb/classes/`** | **目录句柄语义模糊** |

**本质**：项目里没有一处权威的「我该写到哪个根」的定义，每个功能各自假设。

### 1.3 语义边界（教师拍板）

```
<workspace>/                       ← 唯一根，一切可写数据的锚点
├── kb/                            ← 只放题库/题目（xlsx、fig/、solutions/）
│     禁止出现：classes/、grading/、roster/
├── classes/<班级>/
│        ├── roster/roster.xlsx    ← 名单（含 tag）
│        └── grading/<taskId>/     ← 批阅成果（D119）
├── packs/
├── sheets/
└── .runtime/                      ← 引擎运行产物（可重建）
      └── xxt/pages/review/<class>/<work>/   ← 作答原件
```

| 目录 | 可重建？ | 丢了怎么办 |
|---|---|---|
| `kb/` | ❌ | 灾难（靠云同步/备份） |
| `classes/`（roster） | ❌ | 要重做分层 |
| `classes/`（grading） | ✅ | 重跑批阅 |
| `.runtime/` | ✅ | 重新下载/批阅 |

---

## 2. 目标

- **G1 根语义唯一**：前端只维护**一个**「workspace 根」句柄；所有写回用「完整相对路径」。
- **G2 roster 自动落盘**：保存/打 tag 即写 `<ws>/<class_dir>/roster/roster.xlsx`，不再依赖手动按钮。
- **G3 迁移错位目录**：把 `<ws>/kb/classes/**` 搬到 `<ws>/classes/**`（PWA 一键 + CLI 等价）。
- **G4 护栏**：选错目录（如选了 `kb/`）当场拒绝并提示；`kb/` 下出现 `classes/` 时体检告警。
- **G5 CLI 与 PWA 能力等价**（教师要求）：同一动作两端都能做。

---

## 3. 方案（已拍板：A 为主 + C 兜底）

### 3.1 A：单一「workspace 根」句柄

| 项 | 改动 |
|---|---|
| 句柄 | 统一存一个 `workspaceRootHandle`（IndexedDB 持久化），**不再有"kb 句柄"** |
| UI 文案 | 「连接 workspace 根目录（含 `kb/`、`classes/`）…」 |
| 校验 | 选中后检查：存在 `kb/` **或** `classes/`（任一即可）；否则提示「你选的是子目录，请选 workspace 根」 |
| 写回 | kb → `kb/<kind>.xlsx`；roster → `classes/<班级>/roster/roster.xlsx`；全部相对根 |

### 3.2 C：引擎兜底写盘（句柄不可用时）

新增引擎端点，**路径由后端权威决定**：

| 端点 | 作用 |
|---|---|
| `POST /roster/write` | `{classDir, students, sources?, ratios?}` → 写 `<ws>/<classDir>/roster/roster.xlsx` + `roster.json` |
| `GET /roster/read?classDir=` | 读回（PWA 丢失 localStorage 时可从磁盘恢复） |
| `POST /workspace/fix-layout` | 迁移错位目录（§3.3） |

**优先级**：ENGINE（在线）> FSA（有句柄）> 下载文件（兜底）。

### 3.3 目录错位迁移

| 旧位置 | 新位置 | 动作 |
|---|---|---|
| `<ws>/kb/classes/**` | `<ws>/classes/**` | 复制（不删源），冲突则跳过并告警 |
| `<ws>/kb/roster/**`（若存在） | `<ws>/classes/**` | 同上 |

命令：`assist workspace fix-layout [--apply]`；PWA 走 `POST /workspace/fix-layout`。

### 3.4 护栏

1. 写入前校验根目录（§3.1）；
2. 体检新增/增强检查项：
   - `workspace_layout`：`kb/` 下出现 `classes/`、`roster/`、`grading/` → **yellow + 一键修复**
   - `roster_persist`：localStorage 有 roster 但磁盘没有 → 提示「一键写盘」
3. parity 自检：前端写入路径 == 后端 `roster_file()` 路径（用测试锁死）。

---

## 4. PWA 上如何提供迁移（教师提问）

**放在「设置中心 → 环境体检」**，复用现有 `fix` 机制（当前仅支持 `type: 'install'`，本次**扩展**）：

| fix.type | PWA 行为 |
|---|---|
| `install`（现有） | 调 `/install/<item>` |
| **`api`（新增）** | 调 `fix.endpoint`（POST），并把返回摘要显示在体检日志区 |

体检项示例：

```
⚠ workspace 目录布局（yellow）
   检测到 kb/classes/（名单被写到了题库目录下），共 2 个班级
   [🔧 一键迁移到 classes/]
```

迁移动作本身**先演练后执行**：点击后先弹「将迁移 N 个班级 → 显示清单 → 确认」。

同时 **CLI 等价**：`assist workspace fix-layout [--apply]`（教师要求 CLI 能重复 PWA 功能）。

---

## 5. roster 自动落盘（G2）

| 时机 | 动作 |
|---|---|
| 保存班级 / 打 tag / 自动分层后 | **自动**写盘（ENGINE 优先 → FSA → 提示导出） |
| 页面加载 | 若磁盘有 roster 且 localStorage 为空 → **从磁盘恢复**（`GET /roster/read`） |
| 冲突（两边都有） | 以 `updatedAt` 较新者为准，并提示 |

> 这条同时解决「换浏览器/清缓存 = 数据全丢」的风险。

---

## 6. 验收标准

1. 保存/打 tag 后，`<ws>/<class_dir>/roster/roster.xlsx` **自动出现**（无需点按钮）；
2. 选错目录（选到 `kb/`）时当场被拒并给出正确指引；
3. `kb/` 下不再能产生 `classes/`；
4. 体检能检出 `<ws>/kb/classes/**` 并提供**一键迁移**；CLI 有等价命令；
5. 迁移**不删源**、幂等、有演练；
6. 清空 localStorage 后能从磁盘恢复 roster；
7. AI 批阅不再因「名单 0 人」失败（roster 已在正确位置）；
8. parity 自检锁住「前端写入路径 == 后端读取路径」；
9. engine pytest / vue-tsc / build / selfcheck 全绿；脱敏通过。

---

## 7. 待确认

| # | 问题 | 建议 |
|---|---|---|
| Q1 | 句柄校验条件 | ✅ **必须有 `kb/`**，否则拒绝并提示"你选的是子目录" |
| Q2 | roster 自动落盘频率 | ✅ **800ms debounce** |
| Q3 | 迁移冲突处理 | ✅ **不覆盖**，旧文件改名 `.old-<ts>` 留档 |
| Q4 | 修复顺序 | ✅ **先修代码 → 再迁移** |
| Q5 | 是否一并做作业纸写盘 | ✅ **做**（`<ws>/tasks/<padId>.taskpad.json`），消除"包在纸没"的悬空引用 |
| Q6 | 「导出全部本地数据」备份 | 下一轮（本轮不做） |
