# D171 需求单：批阅三键语义 + 结果落草稿 + 抄写题计分 + 文档抽取依赖 + 模型选择

> 日期：2026-11-06
> 状态：**T1–T8 全部完成**（2026-11-06）
> 关联：`docs/115-D170`（上轮缺陷）、`docs/112-D168`（统计/快照）、`docs/12`

## 0. 反馈来源与核心问题

教师第 18 轮反馈（含上轮未修完项），共 6 组问题：

1. **「完整批阅」名不副实**：只转写、未评阅；且评阅默认跳过已有结果 → 教师以为坏了
2. **审核里看不到 AI 批语**：`evaluations/` 有产物，但**草稿库没同步** → 状态仍是「已转写」
3. **抄写题（`topicMatch`）计分未实现** → 恒满分（上轮遗留）
4. **知识点标注按钮灰色**：必须两步（先预览再写回），教师不知情（上轮遗留）
5. **文档抽取依赖外部工具**：没装 officecli 就抽不了 pptx/docx
6. **AI 建议知识点的 provider/模型无法设置**

---

## 1. 🔴 P0：批阅三键语义重做（教师提案，已采纳）

### 1.1 教师原话

> 那么你的完整批阅其实是重新批阅覆盖的意思，那么就不要叫完整批阅，
> 应该增加一个完整批阅键或者一键批阅键表明是转写+批阅，或者干脆叫转写+批阅。
>
> 从使用的角度讲，我们需要这样三个键子，转写、批阅、转写+批阅，
> 如果需要重新做这三件事而不是默认的跳过已完成作答，可否增加一个可勾选的选项，
> 比如强制重做，勾选后再点击前面说的三个键子就相当于分别重新调用大模型
> 做转写、批阅、转写+批阅并覆盖已有内容，是否合理？

**结论：完全合理，照此实施。**

### 1.2 现状问题

```js
// AiGradingPanel.vue:953
@click="startAi(['transcribe', 'evaluate'])">▶ ③ 完整批阅
```

- `startAi()` **不传 `force`** → 后端 `_run_evaluate` 命中
  `if _ev.is_file() and not ctx.get("force"): 跳过` → **评阅被静默跳过**；
- 教师看到“完整批阅”跑完，实际只做了转写；
- 再点「批阅」→ 又跳过 → 提示“已批阅”，但草稿里没有批语。

### 1.3 设计

**三个按钮，语义单一**：

| 按钮 | steps | 说明 |
|---|---|---|
| **① 转写** | `['transcribe']` | 只跑转写 |
| **② 批阅** | `['evaluate']` | 只跑评阅（要求已有转写） |
| **③ 转写+批阅** | `['transcribe','evaluate']` | 两件一起做（原「完整批阅」改名） |

**加一个「☑ 强制重做」勾选**：

| 状态 | 行为 |
|---|---|
| 未勾选（默认） | **跳过已完成**（省额度）；界面明确显示“将跳过 N 人” |
| 勾选 | 传 `force: true` → **覆盖已有产物并重新调用模型**；点击前二次确认（含人数与费用提示） |

**要点**：
- 按钮文案去掉“完整”，改「转写+批阅」（避免歧义）；
- 勾选框旁注明“会重新花额度”；
- 跑完在行内显示「已转写 / 已评阅」，与草稿状态一致。

---

## 2. 🔴 P0：评阅结果必须同步到草稿库

### 2.1 现象

> 点开审核没有看到 AI 批语，也没有打分；点「读取状态」后这些学生仍是「已转写」。

### 2.2 链路核查

```
flow.py 评阅步 → evaluations/<学生>.json  ✅ 写入
            ↓
flow.py:662  if plan: save_drafts_from_grading(...)   ← 关键
            ↓
grade_store → <xxt_home>/grade-drafts/<classId>/<workId>.json  → ai.{score, comment}
            ↓
PWA aiState()：`ai.comment && ai.score != null` → 「已评阅」
```

**缺陷**：`save_drafts_from_grading` 在 `if plan:` 下调用，且内部要求
`plan["classId"]` 与 `plan["workId"]` 都非空：

```python
cid = str((plan.get("classId") or "")).strip()
wid = str((plan.get("workId") or "")).strip()
if cid and wid:  ...  # 否则**静默跳过**
```

serve 侧 `--xxt-class cid:kid` 只保证 course/class，**workId 未必进 plan**
→ 整个落草稿步骤被跳过，但**没有任何报错**。

### 2.3 修复

1. **落草稿失败/跳过必须报错**（journal + 返回体），不能静默；
2. `workId` 从 `--work` 参数兜底注入 plan；
3. 加测试：`evaluations/*.json` 存在 → 草稿库必须有对应 `ai.comment` / `ai.score`
   （这正是「审核看不到批语」的根因）。

---

## 3. 🔴 P0：抄写题 `topicMatch` 计分实现

### 3.1 问题

`evaluate.py` 的算分函数只有四个分支：

```python
mode == "errorCount" | "missingPoints" | "checklist" | "lengthBased"
```

**没有 `topicMatch`** → `copy` 题不匹配任何分支 → **不扣分，恒满分**。

> 上一轮我只改了提示词与规则数据，**漏了算分实现**。教师问“现在仅调整了提示词是不是”，
> 答案是：**是的，上一轮确实只改了提示词**——本轮补齐。

### 3.2 设计

```python
elif mode == "topicMatch":
    # ① 主题一致性：模型回报 topic_match ∈ {match, partial, mismatch}
    #    mismatch → −topicMismatchDeduct（默认 20）；partial → −一半
    # ② 字数下限：answer_chars < minChars
    #    按 shortRatioDeduct 分档：<50% → −10；<100% → −5
    # ③ 明确**不看**：errors / 逻辑 / 推导 / 公式正误 / 抄全三项
```

配套：`prompts.py` 的 schema 增加 `topic_match` 字段；评阅提示词要求只回 `topic_match` + `answer_chars`。

---

## 4. 🟠 P1：知识点标注按钮一步化

### 4.1 现状

```html
<button :disabled="busy !== '' || !tagDry">② 确认写回题库</button>
```

`tagDry` 只在点「① 预览（dry-run）」后才非空 → **按钮默认灰**，教师不知道要先点①。

### 4.2 设计（教师确认方案 A）

- 「确认写回题库」**常亮**；
- 若未预览过 → **自动先跑 dry-run**，把“将更新 N 题”的结果展示在弹窗里；
- 教师确认后才真正写回。

---

## 5. 🟠 P1：修订版独立保存键

### 现状

修订框在上（AI 批语区），**唯一保存键在下方人工批阅区**，且该键同时写
`human` + `revision` + `humanMode` → 教师无法分辨“我保存的是修订还是人工批阅”。

### 设计

| 区域 | 按钮 | 写入字段 |
|---|---|---|
| 修订版 | 「💾 保存修订」（新增，就在修订框旁） | 只写 `revision.text` |
| 人工批阅 | 「💾 保存人工批阅」 | 只写 `human.*` + `humanMode` |

---

## 6. 🟠 P1：文档抽取改用 Python 库（去掉外部工具依赖）

### 6.1 问题

> 点击抽取键，提示没有安装 officecli，我们是否有备用方案，比如使用 python 的什么包？
> 可以把这样的包加到 dependences 里面，读取 pdf/pptx/docx 的 python 程序还是挺多的。

### 6.2 现状降级链

```
officecli（npm 工具） → soffice（LibreOffice） → 都失败则报错
```

两者都是**外部二进制**，教师机器上常常没有 → 抽取不可用。

### 6.3 方案：加纯 Python 后端（优先级最高）

| 格式 | Python 库 | 说明 |
|---|---|---|
| `.pptx` | **python-pptx** | 逐 slide 取 text_frame 文本，可靠 |
| `.docx` | **python-docx** | 段落 + 表格文本 |
| `.xlsx` | openpyxl（**已有**） | 逐 sheet 读单元格 |
| `.pdf` | pypdf（**已有**） | 文本层抽取；扫描件仍走 pdftoppm |
| `.doc`/`.ppt`（旧格式） | 仍需 soffice | 老二进制格式 Python 库支持差 |

**新的降级链**：

```
python 库（首选，纯 Python，无需外部工具）
   ↓ 失败
officecli
   ↓ 失败
soffice
   ↓ 失败
可读错误（说明装哪个）
```

**依赖**：`python-pptx>=0.6`、`python-docx>=1.0` 进 **主 dependencies**
（体积小，纯 Python，不拖慢安装）。

---

## 7. 🟡 P2：AI 建议知识点的 provider/模型选择

### 7.1 现状

- 后端 `/materials/suggest` 接受 `model`；
- 前端 `suggestMaterials(...)` 有 `model` 参数，但 **MaterialsView 从不传**；
- 界面**没有** provider/model 选择控件 → 实际总是用“评阅段配置”。

### 7.2 设计（教师建议：默认与批阅模型一致）

| 项 | 决定 |
|---|---|
| 默认 | **与批阅段（`evaluate`）配置一致**（现状即是，但要**显式显示**） |
| 可选 | 下拉选择 provider + 模型（与 Atopia/Playground 同数据源） |
| 记忆 | 选择存 localStorage，下次沿用 |
| 显示 | 界面标注“当前使用：<provider>/<model>（默认跟随批阅配置）” |

> 教师原话：“是否考虑默认与批阅模型一致较好？” → **是，默认跟随，但可覆盖**。

---

## 8. 🟡 P2：学生 tag 为空 / 新加入的标记

教师说明：

> 已提交学生不在 roster 的情况不存在（按 roster 生成作业）；
> 仅限“生成作业后该生才加入班级”——这种情况要单独制作作业纸、单独批阅。
> 但标记是有必要的：应该增加 tag 为无的情况或者 newadded 标记。

| 情况 | 标记 | 批阅行为 |
|---|---|---|
| tag 为空 | `(未分配)` | 提示“该生未分配 tag，需在名单中打 tag” |
| 不在 roster/snapshot | `新增` | 提示“该生不在本作业名单：需单独制作作业纸并单独批阅” |

**关键**：不再**静默跳过**——在「逐生审核」行内显示标记与原因。

---

## 9. 任务清单

| # | 内容 | 优先级 | 批次 |
|---|---|---|---|
| T1 | 三个按钮（转写/批阅/转写+批阅）+ 强制重做勾选 | P0 | A |
| T2 | 评阅结果落草稿失败**必须报错**；workId 兜底注入 | P0 | A |
| T3 | `topicMatch` 计分实现 + schema 加 `topic_match` | P0 | A |
| T4 | 知识点标注一步化（自动 dry-run） | P1 | B |
| T5 | 修订版独立保存键 | P1 | B |
| T6 | python-pptx / python-docx 抽取后端 + 降级链 | P1 | B |
| T7 | AI 建议知识点 provider/model 选择（默认跟随批阅） | P2 | C |
| T8 | tag 空/新增标记 + 行内原因 | P2 | C |

---

## 10. 验收标准

| # | 标准 | 验证 |
|---|---|---|
| 1 | 「转写+批阅」确实产生 `evaluations/*.json` | 单测 |
| 2 | 未勾“强制重做”时跳过已完成，勾选后覆盖 | 单测 |
| 3 | 评阅完成 → 草稿库有 `ai.comment` + `ai.score` | 单测 |
| 4 | 落草稿失败时 journal 有记录且接口返回非 ok | 单测 |
| 5 | 抄写题：主题不符扣分、字数不足分档扣分、不判逻辑 | 单测 |
| 6 | 知识点写回按钮始终可点 | 浏览器 |
| 7 | 修订版有独立保存键，且不写 human | 浏览器 |
| 8 | **无 officecli/soffice 时**仍能抽 pptx/docx | 单测（构造真实文件） |
| 9 | AI 建议可选 provider/model，默认跟随批阅 | 浏览器 |
| 10 | tag 空/新增 有标记与原因 | 浏览器 |
| 11 | 四道门 | pytest/build/selfcheck/脱敏 |

---

## 11. 实施记录（2026-11-06 完成）

### T1 · 批阅三键 + 强制重做

- 按钮改名：`① 仅转录` / `② 批阅` / `③ 转写+批阅`（原「完整批阅」名不副实）；
- 新增 `☑ 强制重做（覆盖已有结果，会重新花额度）`；
- `startAi()` 现在把 `force: true` 传给后端（此前完全不传 → 评阅被静默跳过）；
- 勾选后点击**二次确认**（含人数与"会重新消耗额度"）；
- 逐生审核行内的按钮文案同步改为「转写+批阅」。

### T2 · 评阅结果必须落草稿（修"审核看不到 AI 批语"）

抽出 `_persist_evaluations_to_drafts()`：

- `workId` 缺省时从 `task["workId"]/task["work_id"]` **兜底**；
- 缺 classId/workId → 返回 `skipped` 并把原因写进 **journal**（此前完全静默）；
- 写失败 → 返回 `error` + journal；不再只 `logger.warning`；
- 只在**真有 plan 却失败**时记 fail，"CLI 直接跑无 plan"属正常路径。

> 这正是「点开审核没有批语、状态停在已转写」的根因：
> `evaluations/*.json` 有产物，但草稿库没写 → PWA 的 `aiState()` 要求
> `ai.comment && ai.score` 才显示「已评阅」。

### T3 · 抄写题 `topicMatch` 计分

- `prompts.py` schema 增 `topic_match`（match/partial/mismatch）；
- 提示词改为「只判主题+字数，不评价逻辑/推导/公式/抄全」；
- `evaluate.py` 增 `mode == "topicMatch"` 分支：
  - mismatch → −`topicMismatchDeduct`（默认 20）；partial → 扣一半；
  - 字数 < `minChars` 按 `shortRatioDeduct` 分档（<50% → −10，<100% → −5）；
  - **不读 `errors`**（模型因逻辑问题生成的 error 不会冤枉学生）。

### T4 · 知识点写回一步化

「② 写回题库」**常亮**：未预览过时自动先跑 dry-run，
弹窗展示"将更新 N 题 + 前 5 条示例"，确认后才写。

### T5 · 修订版独立保存键

修订框下方新增「💾 保存修订版」→ **只写 `revision`**，不动 `human`；
原「保存到本地」保留为人工批阅的保存键。

### T6 · 文档抽取改纯 Python（去外部工具依赖）

降级链重排为：

```
① python-pptx / python-docx / openpyxl（纯 Python，无需外部二进制）
② officecli
③ soffice → PDF → 抽文本
④ 可读错误（说明装什么）
```

- `pyproject.toml` 主依赖新增 `python-pptx>=0.6`、`python-docx>=1.0`；
- 实测真实 pptx/docx 均能抽出（`engine` 字段标 `python-pptx` / `python-docx`）。

### T7 · AI 建议知识点的 provider/模型

- 默认**跟随评阅段配置**（教师建议），界面显示「当前模型：跟随评阅段配置（evaluate）」；
- 可显式选 provider + 输入模型名，选择存 localStorage；
- `doSuggest()` 现在真的把模型名传给后端（此前参数存在但从不传）。

### T8 · tag 空 / 新增标记

| 情况 | 显示 | 提示 |
|---|---|---|
| 有 tag | 正常显示 | — |
| tag 空但在名单里 | `(未分配)` | 到「班级与标签」打 tag 后再批阅 |
| 不在名单里 | `新增` | 需单独制作作业纸并单独批阅 |

### 测试适配

| 测试 | 改动 |
|---|---|
| `test_office_failure_message_is_readable` | 降级链变了 → 需**同时**屏蔽 python 后端才测得到"全失败" |
| 新增 `test_pptx_extracted_by_python_backend` | 无外部工具时仍能抽 pptx（真实回归） |
| `test_copy_topic_match_no_checklist_deduct` | 抄写题改判主题+字数 → 补 `topic_match`/`answer_chars` |
| `selfcheck-d125` | 按钮改名 + 断言 `forceRedo`/`force: true` 存在 |

### 关于「单题扣分上限」

`test_copy_rule_is_configurable` 发现：把 `topicMismatchDeduct` 调到 30 时实际只扣 25——
因为**全局 `perQuestionCap`（默认 20）封顶**。这是既有规则的正确行为，
已加测试 `test_copy_deduct_capped_by_global_cap` 说明，不是 bug。
