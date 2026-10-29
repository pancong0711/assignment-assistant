# D119 任务需求单：批阅产物目录重构（作答原件 / 批阅成果分离）+ 跨工作区串数据治理

> 日期：2026-10-28
> 状态：**需求单（待确认 → 执行）**
> 关联：`docs/68-D118`（缺图报错）、`docs/16`（学习通下载）、`docs/05-D86`（批阅流程）、`docs/04`（数据契约）
> 用户原话：作答图就按「作业预览-学习通」下载的地方；后面 AI 批阅/人工批阅/人工审核都指向这个文件夹找作答原件，
> 而通过 app 完成的批阅/审核修改放到新文件夹 —— 这样管理更合理；跨工作区串数据的隐患要排查。

---

## 1. 现状盘点（代码事实）

### 1.1 目录：5 个位置、2 个根，口径不统一

| # | 内容 | 路径 | 根由谁决定 |
|---|---|---|---|
| 1 | **作答原件**（下载） | `<XXT_HOME>/pages/review/<classId>/<workId>/*.jpg` + `students.json` | `xxt_home()` |
| 2 | **AI 批阅产物** | `<ws>/<class_dir>/grading/<taskId>/{transcripts,evaluations,reports,images,journal.jsonl}` | **serve 的 ws** |
| 3 | **批阅草稿**（人工改分/批语） | `<XXT_HOME>/grade-drafts/<classId>/<workId>.json` | `xxt_home()` |
| 4 | **报告 PNG/MD** | 汇入 #2 的 `reports/` | serve 的 ws |
| 5 | **作业包临时落盘** | `<ws>/tmp/ai-grade/*.taskpad.json` | serve 的 ws |

**问题**：同一件事的数据被拆在 `/` 与 `xxt_home()` 两组根下，且 `xxt_home()` 与 `<ws>` **不是同一个地方**。

### 1.2 已确认的两个跨工作区串数据隐患

#### 隐患 A：`xxt_home()` 优先返回**仓库里的 `.scratch/`**

`xxt/session.py`：

```python
priority: XXT_HOME > (repo_root/.scratch 若存在 xxt-storage.json) > <ws>/.runtime/xxt
```

实测（本机）：

```
find_workspace(None) → /home/bot2603/assignment-assistant-workspace
serve._ws()          → /home/bot2603/assignment-assistant-workspace
xxt_home()           → <repo>/.scratch        ← 仓库目录，不是 workspace！
```

**后果**：下载的作答图、批阅草稿全部落在**代码仓库**里，而不是教师 workspace。
- 换 workspace 不换数据（串数据）；
- 仓库目录可能被清理/被 gitignore 忽略、或误删；
- 也是"我上一轮查的目录和你实际的不一样"的直接原因。

> 这条是**开发期便利**（`.scratch` 方便调试），但它对**普通教师**也会生效（只要那个文件存在）。
> 而分发包里不会有 `.scratch`，所以**开发机与教师机行为不一致**，更难排查。

#### 隐患 B：`find_workspace(None)` 与 serve 的 ws 可能不同

`review_dir_for()` / `drafts_root()` 内部都走 `xxt_home()` → `find_workspace(None)`，
**不看 serve 当前使用的 workspace**。

实测（把 serve ws 指到 `/tmp/WS_A`）：

```
serve._ws()          → /tmp/WS_A
xxt_home()           → <repo>/.scratch     ← 完全没变
```

**后果**：在 A workspace 下载、切到 B workspace 批阅时，仍读 A 的图/草稿 —— 静默错配数据。

### 1.3 fallback 造成的"绕"

`flow._run_transcribe`：

```python
plan_groups = _plan_student_images(ctx) if plan else {}
if plan_groups:  ... 
else:
    images_dir = ctx["images_dir"]      # 默认 <ws>/<class>/grading/<task>/images
    groups = group_images(images_dir)   # ← 该目录无任何写入方，必然不存在
```

`<ws>/<class>/grading/<task>/images` **从来没有任何代码写入**，只作为 `grade --images` 手工批阅的默认值存在。
于是"0 人有图"就掉进这个不存在目录 → D118 那个 `WinError 3`。

**绕的根源**：`images` 这个字段在不同语境下代表两件事 ——
「下载来的作答原件目录」与「手工批阅的本地图片目录」，被同一个 fallback 混用了。

---

## 2. 目标设计（用户提出 + 本方案细化）

### 2.1 一句话

> **作答原件只读、集中一处；批阅成果可写、按"作业纸"归属单独一处。**

### 2.2 目录结构

```
<workspace>/
├── .runtime/xxt/                     # XXT_HOME（登录态、二维码、页面存档）
│   └── pages/review/<classId>/<workId>/
│        ├── students.json            # 下载回执：姓名/图名/批语
│        └── *.jpg                    # ★ 作答原件（只读，唯一真源）
│
└── <class_dir>/grading/<taskId>/     # ★ 批阅成果（全部可写、可重跑覆盖）
     ├── plans/plan.json              # 批阅任务清单
     ├── transcripts/<student>.json   # 转录
     ├── evaluations/<student>.json   # 评分
     ├── reports/                     # 报告 MD/HTML/PNG
     ├── drafts/                      # ★ 人工/AI 批阅草稿（原 grade-drafts/）
     ├── images/                      # 仅 --images 手工批阅时使用（可选）
     └── journal.jsonl                # 运行记录
```

### 2.3 三条铁律

| # | 规则 |
|---|---|
| L1 | **作答原件只读**：AI 批阅/人工批阅/人工审核都从 `pages/review/<class>/<work>/` 读图，**绝不写回** |
| L2 | **批阅成果可写**：AI 批阅、人工改分、逐生审核修订全部写进 `<class_dir>/grading/<task>/`，与该作业一一对应 |
| L3 | **口径唯一**：所有路径都由 **serve 当前 workspace** 推导，不再读"仓库 `.scratch`"或 `find_workspace(None)` |

### 2.4 关键改动点

| # | 改动 | 说明 |
|---|---|---|
| T1 | `xxt_home()` 去掉"仓库 `.scratch` 优先" | 改为 `XXT_HOME` > `<ws>/.runtime/xxt`；`.scratch` 仅在**显式** `ASSIST_DEV_SCRATCH=1` 时启用 |
| T2 | `xxt_home()` 接受显式 `ws` 参数 | serve 显式传 `self.ws`；CLI 传 `-w`；杜绝隐式 `find_workspace(None)` |
| T3 | 草稿目录迁入 grading | `grade-drafts/<class>/<work>.json` → `<class_dir>/grading/<taskId>/drafts/<work>.json`（**需迁移脚本**） |
| T4 | 删掉 `grading/<task>/images` 默认 fallback | 只有显式 `--images` 时才用它；plan 模式 0 人图 → D118 的可读错误（已实现） |
| T5 | 错误文案显示**真实**下载路径 | 现在写的是 `<workspace>/grading/.../images/`，**是错的**；应为 `<XXT_HOME>/pages/review/<class>/<work>/` |
| T6 | 提供 `assist doctor` 检查项 | 检测"是否命中仓库 .scratch""草稿与图是否同 workspace""旧目录残留" |

---

## 3. 迁移与兼容

### 3.1 需要迁移的旧数据

| 旧位置 | 新位置 | 迁移方式 |
|---|---|---|
| `<repo>/.scratch/pages/review/**` | `<ws>/.runtime/xxt/pages/review/**` | 一次性 `assist xxt migrate-home --from <old> --to <ws>` |
| `<XXT_HOME>/grade-drafts/<class>/<work>.json` | `<class_dir>/grading/<task>/drafts/` | 需 class→class_dir 映射；无法映射时**保留原地并告警**（不静默丢） |
| `<ws>/<class>/grading/<task>/images/` | 不动（本就空） | 仅提示可删 |

### 3.2 兼容策略

- 读：**新路径优先 → 旧路径回落 → 仍无则明确提示"旧数据在哪、如何迁移"**（三态可诊断）；
- 写：**只写新路径**；
- 提供 `--legacy-read/--no-legacy-read` 开关（默认开、可关以验证迁移彻底）。

---

## 4. 验收标准

1. 所有批阅路径只依赖 **serve 当前 workspace**；把 ws 指到新目录后，下载/批阅/草稿全部跟随；
2. 仓库 `.scratch` 在**非显式开启**时不参与任何读写；
3. AI 批阅 / 人工批阅 / 逐生审核 / 报告 **全部读同一份作答原件**（`pages/review/<class>/<work>/`）；
4. 所有 app 侧修改（草稿/报告/转录）**全部写入** `<class_dir>/grading/<task>/`，与作答原件物理隔离；
5. 缺图时报错文案给出**真实**下载路径 + 下一步操作；
6. `assist doctor` 能查出"仓库 .scratch 被误用""草稿与图不同源""旧目录残留"；
7. 迁移脚本可重复执行（幂等），有 `--dry-run`；
8. engine pytest / vue-tsc / build / selfcheck 全绿；脱敏通过。

---

## 5. 待确认问题

### Q1 草稿归属：按 `work` 还是按 `task`（作业纸）？
- 方案 A（推荐）：`<class_dir>/grading/<taskId>/drafts/<workId>.json` —— 一次"作业纸 × 学习通作业"一份草稿，语义最准；
- 方案 B：`<class_dir>/grading/_drafts/<workId>.json` —— 不绑 task，换作业纸仍复用同一份人工批语。
> 差别：同一份学习通作业用两张不同作业纸批阅时，A 各存一份，B 共用一份。你希望哪种？

### Q2 旧数据迁移是否自动执行？
- 方案 A（推荐）：**只检测+提示**，由教师显式运行迁移命令（安全）；
- 方案 B：启动时自动迁移（省事，但有覆盖风险）。

### Q3 作答原件是否允许"重新下载覆盖"？
现状 `review-download` 有 `--mode full|missing|comments-only`。
- 方案 A（推荐）：保持现状（默认 `missing` 只补缺失，不覆盖已有原件）；
- 方案 B：一律可覆盖。

### Q4 `--images` 手工批阅的语义要不要保留？
你提到"手工批阅必要，但图片目录应该已存在"。
- 方案 A（推荐）：保留，但**仅当显式传 `--images`** 时生效，且该目录必须已存在（不存在→可读报错）；
- 方案 B：彻底删除该入口，手工批阅也强制走 `pages/review/`。
> 我倾向 A：留一个"外部图片目录"入口应对特殊情况（如教师自己扫描的作业）。

### Q5 报告的最终归属
报告现在混在 `grading/<task>/reports/`。
- 方案 A（推荐）：保持（同一任务的产物聚在一起，便于整体删除/重跑）；
- 方案 B：另设 `reports/` 顶层目录，跨任务汇总。

---

## 6. 直接影响（会修的已知缺陷）

| # | 缺陷 | 关联 |
|---|---|---|
| 1 | D118 报错文案给出**错误**目录（`<ws>/grading/<task>/images`） | T5 |
| 2 | 开发机与教师机 `xxt_home()` 行为不一致 | T1/T2 |
| 3 | 切换 workspace 后仍读旧数据 | T2/T6 |

## 7. 风险

| 风险 | 缓解 |
|---|---|
| 迁移丢数据 | 先 `--dry-run`、迁移前自动快照、旧目录**保留不删** |
| 教师机已有 `.runtime/xxt` 与仓库 `.scratch` 并存 | 检测到并存时**告警并要求显式选择**，不自动合并 |
| 改动面大（下载/批阅/审核/报告/doctor） | 分阶段：T1+T2（口径）→ T3（草稿迁移）→ T4+T5（fallback/文案）→ T6（doctor） |
