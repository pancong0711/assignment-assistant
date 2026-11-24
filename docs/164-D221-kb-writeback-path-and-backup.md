# D221：题库写回落到 `kb/kb/` + 覆盖前无备份

> 日期：2026-11-23
> 状态：**已完成（2026-11-23）**
> 关联：`docs/163-D220`（题库编辑器输入失焦）
>
> 隐私：无学生数据。

---

## 0. 现场

1. 写回后文件出现在 `kb/kb/problems.xlsx`（多了一层 `kb`）；
2. 覆盖旧 xlsx 前没有备份。

## 1. 根因

### A. 连接目录的语义与写入路径不一致

- 按钮文案是「连接本地**题库目录**」→ 教师自然会选 `…/workspace/kb`；
- 但写入代码固定拼 `kb/<kind>.xlsx`：

```ts
await writeFileInDir(dirHandle, `kb/${kind}.xlsx`, bin)
```

→ 连的是 `kb/` 时，结果就是 `kb/kb/problems.xlsx`。

### B. 两条写回路径的备份能力不一致

| 路径 | 写前备份 |
|---|---|
| 引擎在线：`POST /kb/write`（openpyxl 保样式） | ✅ `kb/.history/<ts>/` 快照（已有） |
| 引擎离线：File System Access 原地写 | ❌ 无（覆盖即丢失） |

## 2. 修复

### R1. 写回路径**自动识别**（不再写进 kb/kb）

新增纯函数 `app/src/lib/kbLayout.ts`：

```ts
resolveKbWriteTarget(dirName, rootEntries, kind)
// 目录名是 kb，或根下已有 <kind>.xlsx  → 认为连的是 kb 目录 → 写 <kind>.xlsx
// 否则                                → 认为连的是 workspace 根 → 写 kb/<kind>.xlsx
```

- 连接目录后立即调用 `listDirEntryNames()` 读取一级条目并判定；
- 状态栏明确显示识别结果：
  - `已连接目录 X（识别为 kb 目录，写回 <目录>/<kind>.xlsx）`
  - `已连接目录 X（识别为 workspace 根，写回 <目录>/kb/<kind>.xlsx）`

### R2. 覆盖前自动备份（两条路径一致）

File System Access 路径现在会：

1. 读取目标旧文件（若存在）；
2. 写入 `…/.history/<YYYYMMDD-HHMMSS>/<kind>.xlsx`（与引擎 `kb/.history/<ts>/` 同口径）；
3. 再写新文件；
4. 返回文案里注明备份位置；备份失败也会提示但**继续写回**。

### R3. 历史误写提示

连接目录时检测 `<dir>/kb/kb`（以及 `kb` 目录下的 `kb/` 子目录），
状态栏给出提示：确认内容后把 `kb/kb` 里的文件合并到 `kb/` 再删除该子目录。

### R4. 文案澄清

- 按钮改为「连接 workspace/kb 目录（自动识别）…」；
- 写回按钮显示 `<kind>.xlsx`，tooltip 说明会自动识别且覆盖前备份。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 连 workspace 根（含 `kb/`） | 写 `kb/<kind>.xlsx` |
| 2 | 连 `kb` 目录本身 | 写 `<kind>.xlsx`，**不再出现 kb/kb** |
| 3 | 目录名非 kb，但根下已有 `<kind>.xlsx` | 按 kb 目录处理 |
| 4 | 空 workspace | 写 `kb/<kind>.xlsx` |
| 5 | 覆盖已有文件 | 旧文件先进 `.history/<ts>/` |
| 6 | 检测到 kb/kb | 状态栏提示合并/删除 |
| 7 | 回归 | build + selfcheck 通过 |

## 4. 测试

`app/tests/selfcheck-d221-kb-writeback-layout.mjs`：

- 行为：`resolveKbWriteTarget` 四种目录形态、`historyStamp` 格式、
  `historyBackupPath` 两种场景、`nestedKbWarning`；
- 契约：store 使用识别结果 + 写前备份（`readFileInDir` → `writeFileInDir`）。

## 5. 已有多余 `kb/kb` 怎么处理

1. 打开 `…/workspace/kb/kb/`，确认是不是你要的最新版本；
2. 把需要的 xlsx 复制到 `…/workspace/kb/`（覆盖前建议先备份）；
3. 删除 `…/workspace/kb/kb/` 整个子目录；
4. 重新连接目录（选 `workspace` 根或 `kb` 均可），状态栏应显示正确识别结果。
