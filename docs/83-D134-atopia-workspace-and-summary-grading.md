# D134 需求单：Atopia 专用工作区（重命名 + 目录收拢）+ `summary` 批阅双轨（资料口径 / 保底口径）

> 日期：2026-10-31
> 状态：**已完成（T1–T6）**
> 关联：`docs/81-D132-assistopia`（本单 T1 是其更名与目录演进）、
> `docs/79-D131-materials-and-summary-grading`（本单 T4/T5 补其缺口）、
> `docs/78-D130-source-aware-grading-rules`、`docs/12`

## 0. 一句话

1. **更名**：`assistopia` → `atopia`（代码/CLI/HTTP/目录），旧名保留兼容别名；
2. **目录**：把散在 workspace 根的 Atopia 状态（`assistopia/`、`extensions/`）收进
   **`<ws>/atopia/`** 一个专用文件夹，**可整体删除且引擎照常工作**；
3. **`summary` 双轨**：有教师确认的课堂资料 → 走「资料口径」；没有 → 走
   **不依赖资料的「保底口径」**（知识点总结 / 公式推导 / 示意图 / 长度四维），
   且**降级必须可见**（`summary_basis`）；
4. **资料上传入口**：PWA 可上传到 `materials/<chap>/_source/`，新增
   `materials.files`（L0）/ `materials.remove`（L2，移入回收站不真删）工具。

## 1. 为什么 `materials/` 不能当 Atopia 工作空间（决策依据）

| 维度 | `materials/<chap>/` | Atopia 工作区状态 |
|---|---|---|
| 内容 | 教师上传的**原始教学资料** | 引擎运行产物（护栏/journal）+ 教师写给 Atopia 的**配置** |
| 谁能写 | **只有教师**（AI 一律只读，D131 三条硬规则第 1 条） | 引擎（AI 只能经 Gate 写 journal/limits 的受限字段） |
| 丢了会怎样 | **不可恢复**（唯一真源） | 可重建（回默认值） |
| 组织维度 | 按**章节**（与题库 sheet 对齐） | **全局**，与章节无关 |
| 被谁消费 | `summary` 批阅（**不依赖 Atopia**） | 只有 Atopia 与「扩展层」消费 |

→ 二者是 **输入 → 工作台** 的关系，不是包含关系。把 AI 的写入区与教师原件的保险箱
放在同一父目录，等于重演 D120「不同语义混一个目录」的事故。

**同时确立可验证的硬性质（T2 验收）**：

> 把 `<ws>/atopia/` **整个删掉**后：引擎能启动、评阅能跑、护栏回默认、工具回内置级别、
> 扩展不生效；**不得报错**，且**不得**影响 `materials/` 与 `<ws>/grading-rules.json`。

推论（写死在设计里）：
- `<ws>/grading-rules.json`（规则**本体**）**留在根目录**，不进 `atopia/`；
- `atopia/extensions/rules/*.json`（规则**扩展层**）才进 `atopia/`。

## 2. `extensions/` 为什么归 `atopia/`

先把事实说清（已核查代码）：**`extensions/` 不是 Atopia 生成的**，而是
**教师写给 Atopia 的配置**；`extensions.py` 只有读取 API，AI **没有任何写入口**。

归入 `atopia/` 的依据是「**只对 Atopia 有意义**」（消费方唯一），而不是「谁生成」：

| 路径 | 消费方 | 归属 |
|---|---|---|
| `extensions/tools/*.json` | 只有 Atopia 工具分级器 | ✅ `atopia/` |
| `extensions/rules/grading-rules.json` | Atopia 扩展加载（覆盖根规则本体） | ✅ `atopia/` |
| `extensions/knowledge-terms.json` | Atopia 扩展加载（覆盖词表） | ✅ `atopia/` |
| `grading-rules.json` | **评阅本体** | ❌ 留根 |
| `materials/` | **`summary` 批阅** | ❌ 留根 |

## 3. 目标目录布局

```
<ws>/atopia/                     # Atopia 专用工作区（**可整体删除**，删后回内置默认）
  limits.json                    # 护栏（原 <ws>/assistopia/limits.json）
  journal.jsonl                  # 审计日志（原 <ws>/assistopia/journal.jsonl）
  extensions/                    # 教师写给 Atopia 的配置（AI 只读）
    tools/*.json                 #   工具级别（只能升不能降、不能新增工具）
    rules/grading-rules.json     #   规则扩展层（不得改 types.<kind>.mode）
    knowledge-terms.json         #   词表覆盖

<ws>/grading-rules.json          # 规则本体（不进 atopia/）
<ws>/materials/<chap>/           # 教师原件（不进 atopia/；AI 只读）
  _source/  索引.json  _extract/  知识点清单.md  知识点清单.ai.json
  _source/_trash/                # D134 新增：remove 的回收站（不真删）
```

## 4. 任务清单

### T1 重命名 `assistopia` → `atopia`（纯机械，单独 commit）

| # | 内容 | 验收 |
|---|---|---|
| T1a | 包 `assist/assistopia/` → `assist/atopia/`；全量标识符替换 | `grep -r "assistopia" engine/src` 仅剩兼容别名 |
| T1b | CLI：`assist atopia ...` 为主，`assist assistopia ...` **保留隐藏别名** | 两个命令都能跑 |
| T1c | HTTP：`/atopia/*` 为主，`/assistopia/*` **保留转发**并回 `deprecated` 提示 | 旧路由仍 200 |
| T1d | 前端：`AssistopiaPanel.vue` → `AtopiaPanel.vue`，`/atopia/tools` 等 | build 通过 |
| T1e | 测试文件名/内容同步改名 | pytest 全绿 |

### T2 `atopia/` 目录收拢 + 幂等迁移

| # | 内容 | 验收 |
|---|---|---|
| T2a | `atopia_root(ws)`；`limits.json`、`journal.jsonl` 落到 `<ws>/atopia/` | 路径测试 |
| T2b | `extensions/` 落到 `<ws>/atopia/extensions/` | 覆盖加载仍生效 |
| T2c | 启动/首次访问时**幂等迁移**：`<ws>/assistopia/`→`<ws>/atopia/`、`<ws>/extensions/`→`<ws>/atopia/extensions/`；冲突时**新目录优先，旧的改名 `.bak-<ts>`**，并写 journal | 迁移测试（含冲突） |
| T2d | **删除即回默认**测试：删掉 `atopia/` 后引擎可用、评阅可用、护栏默认、扩展不生效、`materials/` 与 `grading-rules.json` 不受影响 | 专项测试 |
| T2e | `assist atopia reset [--keep extensions]`（**L3，不开放给 AI**） | CLI + 权限测试 |

### T3 资料上传入口（PWA）+ 文件管理工具

| # | 内容 | 验收 |
|---|---|---|
| T3a | `POST /materials/upload`（base64，同项目既有上传范式）→ `_source/<原名>`；扩展名白名单 `.pptx .ppt .pdf .docx .png .jpg .jpeg .md .txt`；**同名不覆盖**（自动 `-2`）；≤20MB | 接口测试 |
| T3b | `assist materials files --chap X`：列 `_source/` 文件名/大小/时间/sha + 回收站 | CLI 测试 |
| T3c | `assist materials remove --chap X --file Y` → **移入 `_source/_trash/`**（不真删） | CLI 测试 |
| T3d | 注册工具：`materials.files`（L0）、`materials.remove`（L2） | 注册表测试 |
| T3e | PWA `MaterialsView.vue`：上传按钮 + 文件列表 + 「移除（进回收站）」需确认 | build + 浏览器回归 |

### T4 `summary` 保底口径（**不依赖资料**）

新增 `<ws>/grading-rules.json` → `types.summary.fallback`：

```json
"fallback": {
  "enabled": true,
  "minChars": 150,
  "minCharsDeduct": 5,
  "requireKnowledgeSummary": true,
  "requireFormulaOrDerivation": true,
  "requireDiagram": "if_question_has",
  "missingItemDeduct": 0
}
```

口径：
- 四维判定 `covered{}`：`知识点总结` / `公式或推导` / `示意图` / `回答长度`；
- **保底模式下缺项不扣分**（怕误伤），只有「**过简**」按 `minCharsDeduct` 扣；
- 模型需返回 `summary_basis`：`"materials"` | `"heuristic"`；
- **有资料时保底口径不叠加**（资料口径优先，避免双重扣分）。

### T5 `summary` 资料口径要点生成

| # | 内容 | 验收 |
|---|---|---|
| T5a | `rubric_enabled(ws,"summary")` → **仅当**本章有已确认 `知识点清单.md` 时为 true | 单测 |
| T5b | summary 要点 prompt：生成「本章应总结的内容清单」而非评分要点 | prompt 断言 |
| T5c | 无资料时 `rules generate --kind summary` 明确提示「先去整理资料」，不静默产出 | CLI 测试 |

### T6 文档与回归

- 回填本文 §7 实施记录、§8 验收对照；
- `docs/12-backlog.md` 登记 D134；
- `README.md` 增补 docs/83；
- 全量：pytest / build / selfcheck / 脱敏。

## 5. 验收标准

1. 包/CLI/HTTP/前端全部以 `atopia` 为主名，旧名 `assistopia` 仍可用（别名/转发）；
2. `<ws>/atopia/` 存在时承载 `limits.json`、`journal.jsonl`、`extensions/`；
3. **删除 `<ws>/atopia/` 后引擎零报错、评阅照常、护栏回默认、扩展不生效**；
4. 旧目录自动迁移幂等，冲突不静默合并（旧的留 `.bak-<ts>`）；
5. `materials/` 与 `grading-rules.json` **不在** `atopia/` 内（防「删 Atopia 连评阅/原件一起没」）；
6. 资料可经 PWA 上传到 `_source/`，同名不覆盖；`remove` 只进 `_source/_trash/`；
7. `summary` 无资料时走保底口径：四维判定 + 过简扣分，结果带 `summary_basis="heuristic"`；
8. `summary` 有资料时走资料口径，`summary_basis="materials"`，**不再叠加**保底扣分；
9. pytest / build / selfcheck / 脱敏 全绿。

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 改名遗漏导致静默 ImportError | 保留 `assistopia` 兼容 shim + `grep` 检查 + 全量 pytest |
| 迁移半途失败留下脏状态 | 迁移**幂等**，先 copy 后删除，失败时不动原目录 |
| 把规则本体搬进 `atopia/`（后续误改） | §1 硬性质 + T2d 删除测试永久锁定 |
| 保底口径误伤（没资料就重扣） | 保底模式缺项**不扣分**，只扣「过简」；且 `summary_basis` 可见 |
| 上传带来任意文件写入 | 扩展名白名单 + 限定 `_source/` + 同名不覆盖 + 大小上限 |

## 7. 实施记录

### 7.1 T1 重命名（commit `42341bc`）

- 包 `assist/assistopia/` → `assist/atopia/`；全量标识符替换（53 处 .py）。
- **CLI**：主名 `assist atopia`；`assist assistopia ...` 由 `_alias_assistopia_argv()`
  在 `main()` 里把第一个子命令改写为 `atopia`（旧名永久可用，成本≈0）。
- **HTTP**：主路由 `/atopia/*`；`_rewrite_legacy_atopia()` 在 `do_GET`/`do_POST`
  入口把 `/assistopia/*` 前缀改写成 `/atopia/*`（只认前缀，不误伤含该词的资源路径）。
- **前端**：`AssistopiaPanel.vue` → `AtopiaPanel.vue`，`engineClient` 接口同步。
- 兼容测试：`test_d134_atopia_rename.py`（5 项，含"旧包名必须不可导入"）。

**踩坑**：改名前 `assist.assistopia` 若与新包并存会出现"改了一套、跑的是另一套"的
幽灵模块；因此专门加断言锁死旧包名不可 import。

### 7.2 T2 `atopia/` 工作区（commit `cf69406`）

- 新增 `atopia/paths.py` 作为**唯一路径出口**：`atopia_root` / `limits_path` /
  `journal_path` / `extensions_dir` / `migrate_legacy` / `ensure_migrated` / `reset`。
- `limits.json`、`journal.jsonl`、`extensions/` 全部落到 `<ws>/atopia/`。
- **幂等迁移**：`<ws>/assistopia/`、`<ws>/extensions/` → `<ws>/atopia/`；
  冲突时**新目录优先**、旧的改名 `.bak-<ts>`（**不静默合并**——配置静默合并最危险）；
  迁移动作本身写 journal。触发点：CLI `_setup()`、serve `_ws()`（进程内各一次）。
- 新增 `assist atopia migrate` / `assist atopia reset [--keep-extensions]`；
  `reset` 属 **L3，不注册为 AI 工具**。
- **修复既有缺陷**：`rules.read_rules` 在规则文件不存在、刚落盘默认时**直接 return**，
  跳过了 `_apply_extensions` → **新建 workspace 上扩展静默失效**。已改为落盘后仍叠加。

**关键设计**：`grading-rules.json`（规则本体）与 `materials/`（教师原件）**不进**
`atopia/`。用 `test_delete_atopia_restores_defaults` 与
`test_delete_atopia_grading_rules_still_work` 永久锁定"删掉 Atopia 后评阅照常、
原件不受影响"。

### 7.3 T3 上传与文件管理（commit `a831f82`）

- `materials.save_uploads()`：base64 → `_source/`；扩展名白名单
  （`.pptx .ppt .pdf .docx .doc .png .jpg .jpeg .md .txt .markdown`）、
  单文件 ≤20MB、一次 ≤20 个、文件名清洗（`Path(name).name` 防 `../` 写出）、
  **同名不覆盖**（自动 `-2`、`-3`）。
- `materials.files_of()` / `remove_source()`；`remove` **移入 `_source/_trash/`，不真删**
  （教师原件是唯一真源，误删不可恢复）。
- CLI `materials files|remove`；工具 `materials.files`(L0) / `materials.remove`(L2)。
- PWA：上传按钮（前端同样按白名单预筛，给出"已拒绝/已改名"提示）、文件表格、
  移除二次确认弹窗（确认后经 `/atopia/run`，`confirmed_by=teacher:pwa`）。
- serve：`POST /materials/upload`、`GET /materials/files`。

**踩坑两处**：
1. 上传分支最初被误放进 **GET** 分支（锚点选错）→ 前端收到 `not found`。
2. 前端传的 `file` 是 `_source/<名>`，而 CLI 期望**相对 `_source/`** 的名字 → 移除 400。
   已在前端 `slice('_source/'.length)` 对齐，并保留引擎侧"必须位于 `_source/` 内"的校验。

**顺带修复真实缺陷**：`registry._SAFE_STR` / `_INT_RE` 写成了**双反斜杠字面量**
（`"^[^\\x00-\\x1f]"`），实际匹配的是字面反斜杠 + `x00`，导致
**所有 `"str"` 类型工具参数都被误拒**。此前没暴露是因为既有测试没真正触发该分支。

### 7.4 T4 summary 保底口径（commit `6442d47`）

- `rules.DEFAULT_RULES.types.summary.fallback`：
  `minChars=150 / minCharsDeduct=5 / requireKnowledgeSummary=true /
  requireFormulaOrDerivation=true / requireDiagram="if_question_has" /
  missingItemDeduct=0`。
- `prompts.summary_fallback_block()`：要求模型回 `summary_basis="heuristic"`、
  `knowledge_missing=[]`（**禁止编造**本章知识点）、只判四件事。
- `evaluate._q_deduction`：`summary_basis != "materials"` 时 **缺项不扣分**，
  只扣"总结过于简略"；字数**以转写原文重算**（不信模型自报 `answer_chars`）。
- `build_feedback_md`：heuristic 时给学生报告加"关于总结题"说明（**降级可见**）。
- `evaluate._aggregate_summary_meta()`：两条评阅路径共用（见下）。

### 7.5 T5 summary 资料口径（同 commit）

- `rubric_enabled(ws, kind, chap="")`：`summary` **仅当**本章有已确认
  `知识点清单.md` 时才为 True——否则生成本章要点等于让模型编造依据。
- 有资料时 prompt 要求 `summary_basis="materials"`，且**不叠加**保底口径（避免双重扣分）。
- `rules generate --kind summary` 无资料时输出 `howTo`（materials 四步）而非静默产出；
  未给 `--chap` 直接报错。
- `kb ai-solve --with-rubric` 在 summary 上同口径跳过要点（两个入口一致）。

**顺带修复**：`build_result_from_analysis()`（batch 回灌）此前**不带** `feedback_md`
与 summary 元数据，与 `evaluate_student()` 口径不一致 → 抽出公共函数共用。

## 8. 验收对照

| # | 验收标准（§5） | 结果 | 证据 |
|---|---|---|---|
| 1 | 包/CLI/HTTP/前端以 `atopia` 为主名，旧名仍可用 | ✅ | `test_d134_atopia_rename.py`（5 项） |
| 2 | `<ws>/atopia/` 承载 limits/journal/extensions | ✅ | `test_paths_all_under_atopia` |
| 3 | **删除 `atopia/` 后零报错、评阅照常、护栏回默认、扩展不生效** | ✅ | `test_delete_atopia_restores_defaults` / `test_delete_atopia_grading_rules_still_work` |
| 4 | 旧目录自动迁移幂等，冲突不静默合并（旧的 `.bak-<ts>`） | ✅ | `test_migrate_*`（5 项） |
| 5 | `materials/` 与 `grading-rules.json` **不在** `atopia/` 内 | ✅ | `test_rules_and_materials_not_inside_atopia` |
| 6 | PWA 可上传到 `_source/`，同名不覆盖；remove 只进回收站 | ✅ | `test_d134_materials_upload.py`（19 项）+ `run-d134-materials-upload-browser.sh` |
| 7 | 无资料走保底口径，`summary_basis="heuristic"` | ✅ | `test_prompt_without_materials_uses_fallback` 等 |
| 8 | 有资料走资料口径，`="materials"`，不叠加保底扣分 | ✅ | `test_materials_basis_still_deducts_missing_items` |
| 9 | pytest / build / selfcheck / 脱敏 全绿 | ✅ | 1030 passed · build 0 error · selfcheck 25/25 · 脱敏通过 |

## 9. 已知限制

- 迁移只在 CLI `_setup()` 与 serve `_ws()` 触发；**直接 import 库函数**的场景
  （如测试/脚本）不会自动迁移，需显式调 `paths.ensure_migrated(ws)`。
- `materials.remove` 只把文件移入回收站，**没有"从回收站恢复"的 CLI/PWA 入口**
  （可手工移回；如需可后续加 `materials restore`）。
- 上传不收 `.zip`（压缩包可塞任意内容，先不做）。
- summary 保底口径**不判断漏了哪个知识点**（这是刻意的：无依据即无资格判）。
