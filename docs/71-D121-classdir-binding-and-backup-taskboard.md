# D121 任务需求单：班级目录自动绑定 + 假目录根除 + 一键备份 + 上传清单

> 日期：2026-10-29
> 状态：**已执行完成（2026-10-29）**；验证见 §7
> 关联：`docs/70-D120`（workspace 根语义/roster 落盘）、`docs/69-D119`（批阅产物布局）、`docs/04`（数据契约）
> 触发：`<ws>/classes/grading/`、`<ws>/grading/` 两个**假目录**；PWA 体检误报「1 个班级缺 roster.xlsx（grading）」

---

## 1. 问题

### 1.1 假目录的产生（已实测）

`flow.grading_dir()`：

```python
d = ws / task.get("class_dir", "classes") / "grading" / str(task.get("id", "task"))
```

| `class_dir` 值 | 结果 |
|---|---|
| `"classes/化工25"` | `<ws>/classes/化工25/grading/<task>/` ✅ 正确 |
| `"classes"`（解析失败回退） | `<ws>/classes/grading/<task>/` ❌ **假目录** |
| `""`（键存在但为空） | `<ws>/grading/<task>/` ❌ **假目录**（空串在 Path 拼接中塌掉） |

而 `class_dir` 的来源（`cli.py`）：

```python
class_dir = resolved.get("classDir") or str(task.get("class_dir") or "classes")
                                                          ↑ 解析不到就静默回退
```

### 1.2 为什么“解析不到”

系统有**两个**班级标识，必须靠对照表连接：

| 概念 | 例子 | 存在哪 |
|---|---|---|
| 学习通班级 id | `153248256` | 学习通服务器 |
| 本地班级目录 | `classes/化工25` | workspace 磁盘 |

对照表 = `settings.local.json` 的 `xxt.class_map`。

**关键事实（已查证）**：`classmap.set_class_dir()` **只有一个写入点**——手动「保存映射」。
**「提取班级 / 追加批次」流程完全不碰 classmap**，所以绝大多数教师从未建立过映射。

### 1.3 连带问题

| # | 问题 |
|---|---|
| A | `roster_persist` 把 `classes/` 下**所有**子目录当班级 → `grading` 被误判为「缺 roster 的班级」 |
| B | 用户困惑「保存映射」是什么意思——它本不该是常规操作 |
| C | 无「一键备份」，localStorage 数据（roster/kb/作业纸/作业包）清缓存即丢 |
| D | 上传学习通时 payload **现场拼装、不落盘** → 无法复现“上次上传了什么” |

---

## 2. 目标

- **G1 根除假目录**：`class_dir` 解析不到时**不回退、明确报错**并给出下一步动作。
- **G2 自动绑定**：提取班级时**自动**建立 classmap（唯一精确命中即可自动写），用户无需手填。
- **G3 正确识别班级**：`classes/` 下只认「含 `roster/` 的目录」为班级，保留名排除。
- **G4 清理入口**：CLI + PWA 都能清理假目录（列出内容后确认，绝不误删真实产物）。
- **G5 一键备份**：`assist backup` + PWA 按钮，覆盖 workspace 与浏览器数据。
- **G6 上传清单落盘**：`grading/<task>/upload/<workId>.json`，上传前写、上传后追加结果。

---

## 3. 方案

### 3.1 G1 解析不到 → 报错（已拍板）

不再 `or "classes"`。改为按场景给出**可执行**的报错：

| 场景 | 报错与动作 |
|---|---|
| 有**唯一精确**匹配的本地班级目录 | **自动写入映射**并继续（无需打扰用户） |
| 有多个候选 | 报错：「学习通班级 <id> 未绑定本地目录，候选：`classes/A`、`classes/B`；请在 AI 批阅页 ② 区选择其一并保存，或运行 `assist xxt class-map --course … --class … --dir …`」 |
| 无任何候选 | 报错：「本地没有班级目录：请先在「班级与标签」建班并导入名单，或重新提取该班级」 |
| 映射过但目录已删 | 报错：「关联的目录已不存在：`classes/xxx`；请重新关联或重新提取」 |
| `task.class_dir` 为空串 | 同「无候选」处理（**绝不**再拼出 `<ws>/grading/`） |

同时 `grading_dir()` 增加**兜底断言**：拼接结果必须落在 `<ws>/classes/` 之下，否则抛错。

### 3.2 G2 提取时自动绑定（已拍板）

在「提取班级 / 追加批次」流程中，拿到 `className` 后：

```
resolve_class_dir(ws, courseId, classId, className, auto_write=True)
```

判定规则（**D1 已拍板**）：
- 候选**唯一**且 `score >= 0.999`（完全相同）→ **自动写入**映射；
- 否则**不写**，收集到「待确认列表」。

**交互（D2 已拍板）**：提取**完成后统一提示**，不逐个弹窗：
```
本次提取 8 个班：5 个已自动关联，3 个需确认  [去确认]
```

「保存映射」入口**保留**（高级/纠错）。

### 3.3 G3 班级识别

```python
RESERVED_CLASS_DIR_NAMES = {"grading", "roster", "tasks", "packs", "_unassigned"}
def is_class_dir(p: Path) -> bool:
    return p.is_dir() and p.name not in RESERVED_CLASS_DIR_NAMES and (p / "roster").is_dir()
```

`roster_persist` 与 `list_class_candidates` 统一用它。

### 3.4 G4 清理假目录（已拍板）

新增 `assist workspace clean-junk [--apply]`：

| 目标 | 判定「可安全删」 |
|---|---|
| `<ws>/grading/**` | 顶层 grading（新布局永远是 `classes/<班级>/grading`） |
| `<ws>/classes/grading/**` | `classes/grading` 是保留名，非班级 |
| `<ws>/classes/roster/**` | 同上 |
| `<ws>/classes/_unassigned/**` | 同上 |

**安全**：默认演练；`--apply` 前打印每个目录的文件清单与大小；**任一目录含 `evaluations/`/`transcripts/`/`reports/` 真实产物则拒绝并告警**（需人工确认）。

PWA：体检项 `workspace_layout` 的 `fix.type='api'` 扩展现有按钮（同一端点，新增 `cleanJunk` 动作）。

### 3.5 G5 一键备份（D3 已拍板：**不含 `.runtime/`**）

`assist backup [--out <zip>] [--include-browser <json>]`

```
<zip>/
├── manifest.json        版本/时间/workspace/统计/校验
├── workspace/
│   ├── kb/  classes/  tasks/  packs/  sheets/
│   └── settings.local.json（**脱敏**：api_key 等替换为 "***"）
└── browser/             PWA 传入的 localStorage 导出
    ├── roster-classes.v2.json  kb.json  taskpads.json  packs.json  settings.json
```

- **不含** `.runtime/`（可重建，体积大）；
- 备份里 **必须脱敏**（密钥不入包）；
- PWA 设置中心新增「⬇ 一键备份」，先把 localStorage 打成一个 JSON 传给引擎。

### 3.6 G6 上传清单落盘

`<ws>/classes/<班级>/grading/<taskId>/upload/<workId>.json`：

```jsonc
{
  "workId": "...", "taskId": "...", "generatedAt": "...",
  "source": "evaluations|drafts",
  "items": [{ "student": "张三", "total_score": 88, "question_scores": [8,9], "comment": "..." }],
  "result": { "at": "...", "ok": true, "receipt": "..." }   // 上传后追加
}
```

**时机**：上传**前**写入（记录“即将发送什么”）→ 上传后写 `result`。失败也能复现输入。

---

## 4. 验收标准

1. `class_dir` 解析不到时**不再产生** `<ws>/grading/` 或 `<ws>/classes/grading/`；
2. 报错文案含**下一步动作**（关联/建班/重新提取）；
3. 提取班级后，唯一精确匹配的班级**自动**出现在 `class_map`（无需人工点「保存映射」）；
4. `roster_persist` 不再把 `grading` 当班级（体检不再误报）；
5. `assist workspace clean-junk` 可识别假目录；默认演练；含真实产物时**拒绝删**；
6. `assist backup` 产出 zip，**不含 `.runtime/`**，`settings.local.json` 中密钥已脱敏；
7. PWA 有「一键备份」按钮并能成功下载 zip；
8. 上传前生成 `upload/<workId>.json`，上传后追加 `result`；
9. engine pytest / vue-tsc / build / selfcheck 全绿；脱敏通过。

---

## 5. 风险

| 风险 | 缓解 |
|---|---|
| 改成「报错」后，原本能跑的流程会中断 | 报错给**一键修复指引**；自动绑定覆盖 99% 场景 |
| 自动匹配**错配**班级（比未配更危险） | 只允许 `score>=0.999` 精确匹配自动写；其余让人确认 |
| 清理命令误删真实批阅产物 | 默认演练 + 内容清单 + 含 `evaluations/transcripts/reports` 时拒绝 |
| 备份包体积过大 | 排除 `.runtime/`；`manifest` 记录各项统计 |
| 备份包泄漏密钥 | 强制脱敏，备份后自检 `api_key` 不存在 |

---

## 6. 实施记录（已完成）

### 6.1 落地内容

| 条目 | 实现 |
|---|---|
| **G1 不回退** | `classmap.resolve_or_raise()`：解析不到**抛 `ClassDirResolutionError`**（分级：无班级/有候选/映射目录已删，各给下一步动作）。`cli.py` 两处调用点改用它 |
| **G1' 目录越界断言** | `flow.grading_dir()` 拒绝 `class_dir` 为空或为 `"classes"`（旧实现正是这两个值造出假目录），并断言结果必须落在 `<ws>/classes/` 之下 |
| **G2 自动绑定** | `resolve_or_raise(auto_bind=True)`：**仅当归一后完全相同**（目录名或 roster 文件名）才自动写入映射。`GET /xxt/review/index` 顺手对所有作业班级执行，返回 `autoBound` / `needConfirm` 供 PWA 统一提示 |
| **G3 班级识别** | `is_class_dir()`：非保留名 + 含 `roster/`。`roster_persist` 用它 → 不再把 `classes/grading` 误报为缺 roster 的班级 |
| **G4 清理假目录** | `workspace_junk.py` + `assist workspace clean-junk [--apply]` + `POST /workspace/clean-junk`，PWA「🧹 清理假目录」按钮（演练→确认→执行） |
| **G5 一键备份** | `backup.py` + `assist workspace backup [--out] [--browser-json]` + `POST /workspace/backup` + `GET /workspace/backup/file`，PWA「💾 一键备份」按钮。**不含 `.runtime/`**、`settings.local.json` 递归脱敏、备份后 `verify_no_secrets()` 自检 |
| **G6 上传清单** | `write_upload_manifest()` → `grading/<taskId>/upload/<workId>.json`；`xxt grade-upload` 两个路径（drafts/evaluations）上传**前**落盘，上传后可追加 `result` |

### 6.2 复审发现并修复的 3 个问题

| # | 问题 | 说明 |
|---|---|---|
| **R1** | **clean-junk 会误删真实班级** | 若教师把班级命名为保留名（如 `classes/tasks`），会被当成假目录删除。改为 `_looks_like_real_class()`：含 `roster.xlsx/roster.json/task-package.json` 一律视为真实班级，**永不删** |
| **R2** | **上传清单膨胀** | `drafts_to_payloads()` 的 `images` 含报告 PNG 的 base64，原样落盘会让清单到 MB 级。改为只记元信息（`name`/`bytes`/`hasData`）——实测 400KB → **300 字节** |
| **R3** | **备份漏收水印/题图素材** | `collectBrowserData()` 最初只收 6 个键，漏了 `watermark.assets.v1`、`watermark.styles.v1`、`fig.assets.v1`（教师上传的**图片素材，丢了不可恢复**）。补齐并加自检：**store 里的键必须全部被收集**（仅排除瞬时状态） |

### 6.3 验证

| 项 | 结果 |
|---|---|
| 解析不到 | 抛可读错误，含"先在「班级与标签」建班 / 重新提取" |
| 自动绑定 | `classes/化工25` 与班级名"化工25"完全相同 → 自动写映射（`source=auto`） |
| 防误绑 | 有 `classes/化工2` 但班级名"化工25" → **不**自动绑定，报错要求人工确认 |
| 映射目录被删 | 明确报"关联的本地目录已不存在" |
| grading_dir | 空 / `"classes"` / `../outside` 全部被拒 |
| clean-junk | 顶层 `<ws>/grading` 可删；`classes/grading` 含 `evaluations/` → **保护**；真实班级撞保留名 → **保护** |
| 备份 | 不含 `.runtime/`；`api_key`/`token` → `***`；`verify_no_secrets()` 通过；含浏览器数据 |
| 上传清单 | 路径 `classes/…/grading/<task>/upload/<workId>.json`；追加 `result` 不丢 `items`；图片只存元信息 |
| 端到端（HTTP） | `GET /workspace/layout` 检出 2 个假目录 → `clean-junk` 演练 `deletable=1/protected=1` → 执行后顶层删掉、真实产物保留 → 备份 `secretCheck.ok=true` |
| engine pytest | **685 passed**（新增 `test_d121_classdir_binding_backup.py` 16 例） |
| app `vue-tsc` / `build` | 0 error |
| app `npm run selfcheck` | **31 项全绿**（新增 `selfcheck-d121-classdir-backup.mjs`） |
| 脱敏 / bat lint | 通过 |

### 6.4 教师操作指引

```bash
# ① 体检（PWA 设置中心 → 体检）
assist doctor

# ② 清理假目录（PWA 有「🧹 清理假目录」按钮）
assist workspace clean-junk            # 演练
assist workspace clean-junk --apply    # 含真实批阅产物的目录会自动跳过

# ③ 一键备份（PWA 有「💾 一键备份」按钮）
assist workspace backup                # → <ws>/backups/*.zip

# ④ 关联班级目录（现在多数情况会自动完成）
assist xxt class-map --list            # 看当前映射
assist xxt class-map --course <c> --class <k> --dir classes/<班级>   # 仅需手工时
```

---

## 8. 补充：迁移默认复制 / `--move` / 清理已迁移源（D122）

用户确认「一键迁移是复制不是 move」后，补齐配套能力。

### 8.1 行为约定

| 命令 | 行为 |
|---|---|
| `assist workspace fix-layout` | 演练 |
| `assist workspace fix-layout --apply` | **复制**（源保留，默认） |
| `assist workspace fix-layout --apply --move` | **移动**：复制成功并校验大小后才删源；随后**回收空目录** |
| `assist workspace clean-migrated [--apply]` | 清理「已迁移完成」的源；**sha256 一致**才删，否则保留并告警 |

PWA（设置中心）：
- 「workspace 目录布局」的 🔧 一键迁移 → 技能确认弹窗：**【确定】= 移动（删源）／【取消】= 复制（保留源）**；
- 新增「🧹 清理已迁移源」按钮（演练 → 确认 → 执行）。

### 8.2 安全设计

1. **不用 `shutil.move`**：先 `copy2` → 校验大小一致 → 才 `unlink` 源。任何一步失败都保留源。
2. `clean_migrated` 用 **sha256** 逐文件比对（不是只比大小），只有**全部一致**才把该源目录列为可删。
3. 空目录回收只 `rmdir` **空目录**，有内容一律保留。

### 8.3 复审发现并修复

| # | 问题 | 说明 |
|---|---|---|
| **R4** | `--move` 删了文件但**空目录残留** | 体检仍报 `violations=1`，用户误以为没迁移成功。改为 `--move` 后自底向上回收空目录（`prunedDirs`），实测 `violations` → **0**。加了"有内容则不删"的回归用例 |

### 8.4 验证

| 项 | 结果 |
|---|---|
| 默认复制 | 源保留 ✅ |
| `--move` | 源文件删除、空目录回收、`violations=0` ✅ |
| 非空目录 | `kb/classes` 里还有未迁移文件时**不删目录** ✅ |
| `clean-migrated` | 内容一致 → 可删；**改坏目标 → blocked 并保留源** ✅ |
| engine pytest | **691 passed**（D121 用例 16 → 22） |
| app selfcheck | 31 项全绿（补充 D122 哨兵） |
