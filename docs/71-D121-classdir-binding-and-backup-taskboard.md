# D121 任务需求单：班级目录自动绑定 + 假目录根除 + 一键备份 + 上传清单

> 日期：2026-10-29
> 状态：**已确认（用户拍板）→ 执行中**
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
