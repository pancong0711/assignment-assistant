# D134 需求单：Atopia 专用工作区（重命名 + 目录收拢）+ `summary` 批阅双轨（资料口径 / 保底口径）

> 日期：2026-10-31
> 状态：**实施中**
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

（实施后回填）

## 8. 验收对照

（实施后回填）
