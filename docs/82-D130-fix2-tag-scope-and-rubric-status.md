# D130-FIX2：刷新后 tag/AI 状态不显示 + 「参考答案带评阅要点」现状核查

> 日期：2026-10-30
> 关联：`docs/78-D130`（T5 评阅要点）、`docs/79`（材料）、`docs/81`（Assistopia）

## 1. 「AI 做参考答案时顺带记录评阅要点」——当前实际做法

### 1.1 结论：**目前是两条独立路径，尚未合并**

| 路径 | 命令 | 产出 | 会用规则摘要吗 |
|---|---|---|---|
| AI 作答（原路径） | `assist kb ai-solve` | 一段**纯解答文本**，写进答案版本库（默认置顶） | ❌ 完全不含要点 |
| AI 评阅要点 | `assist rules generate` | `【参考解答】+【评阅要点】+【示意图要求】+【知识点】`，写入答案版本库（**默认不置顶**） | ✅ 带该题型规则摘要 |

证据：
- `solve.SOLVE_SYSTEM_PROMPT` 里**没有任何**"要点/rubric"字样（检查返回 0）；
- `rubric.rubric_to_text()` 已实现"参考解答 + 要点 + 图 + 知识点"的合并文本；
- 但 `kb ai-solve` 调的是 `sol.add_version(ws, id, text=纯解答, ...)`，**没走** `rubric_to_text`。

### 1.2 也就是说

- 你原来说的"让 AI 做参考答案时**直接**把评阅要点记进参考答案"——
  **半实现了**：`rules generate` 能做到（且是带规则摘要的、更对的版本），
  但**教师日常用的「题库 AI 作答」按钮（ai-solve）不会顺带生成要点**，需要另外跑一次。
- 要点的文本形式已经存在且会被批阅使用（`expand_items` 取"生效答案"进 prompt），
  所以**置顶**后就等于"参考答案里带要点"。

### 1.3 建议（待你确认后实施）

把两条路径合并成一个动作（保留兼容）：
1. `kb ai-solve` 增加 `--with-rubric`：一次调用同时产出
   `【参考解答】+【评阅要点】+【知识点】`（复用 `rubric.build_rubric_prompt`，带题型规则摘要）；
2. PWA「题库 AI 作答」按钮加勾选项「同时生成评阅要点」；
3. 默认**仍不置顶要点版**（与 D130 验收 5 一致），由教师确认。

> 未在本轮实施：属于**功能变更**（改 AI 作答的产出契约），需要你拍板默认值。

## 2. 刷新后「逐生审核」tag / AI 状态不显示（已修复）

### 2.1 两个**独立**的根因（都已用测试复现）

**根因 A：tag 永远为空**
`/xxt/preview/students`（`xxt/preview.py:preview_students/parse_review_list`）
**根本不返回 `tag` 字段**，而 tag 是**本校名单**的概念（学习通列表页没有分层 tag）。
前端 `students[].tag = String(s.tag || '')` → 永远是空串。

**根因 B：AI 状态全空，但点开弹窗又有内容**
`packId` / `padId` **只来自下拉框**，刷新后为空。于是读草稿时 `taskId=''`
→ `read_drafts_normalized` 一条也读不到 → 「AI 状态」全显示"未跑"；
而弹窗另有"按姓名兜底"的取值逻辑 → 能看到内容。这与 D130-T12 的症状同源（**表与弹窗不同源**）。

实测：
```
A taskId=pack1 → ['张三']
B taskId=''    → []          ← 刷新后的真实情况
```

### 2.2 修法：都由**引擎**兜底，不要求教师先手选

| 修复 | 位置 |
|---|---|
| tag 按姓名 join 本校名单后随学生清单返回 | `serve.py` `/xxt/preview/students` |
| 学生清单带回 `draftScopes`（从磁盘反查含该 workId 草稿的批阅目录） | `grade_store.discover_draft_scopes()` |
| 读草稿接口在 `taskId` 为空时**自动用反查结果** | `serve.py` `/xxt/grade/drafts/*` |
| 前端一次读不到就按 `draftScopes` 再读一次 | `AiGradingPanel.loadStudents()` |
| **新增「🔄 读取状态」按钮** + 显示"这次读的是哪个批阅目录" | `AiGradingPanel.vue` |

顺带修的：
- `drafts_root()` 原先**无条件 mkdir**，`XXT_HOME` 只读时直接 `OSError` → 读草稿接口 500
  （现在读路径容忍只读，不再崩）；
- `altTaskId` 原先当单值用，现支持**逗号分隔多值**（前端一次带多个反查结果）。

### 2.3 验证

- 单元/接口：`tests/test_d130_fix2_tag_and_scope.py` **8 例**
  （含"不传 taskId 仍能读到草稿"、"只读 XXT_HOME 不 500"、"显式 taskId 仍优先"）；
- **真实浏览器**：`app/tests/run-d130-fix2-refresh-browser.sh`
  —— 挂载**真实面板**（不选作业包 = 刷新后的状态）+ 真实引擎 + 真实名单/草稿，
  断言 tag 列、AI 状态「已评阅」、AI 分、「读取状态」按钮均正常。
- 全量：engine pytest **962 passed**；build 0 error；selfcheck **24 项全绿**；脱敏通过。
