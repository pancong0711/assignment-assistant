# D166 需求单：LaTeX 转义根因修复 + 知识点 JSON 化（预览 / AI 再整理）

> 日期：2026-11-05
> 状态：**已完成**
> 关联：`docs/42-D89`（答案版本库）、`docs/78-D130`（知识点标注）、`docs/105-D162`（LaTeX 裸换行）、
> `docs/110-D167`（2508 整合评估）、`docs/12`

## 0. 教师反馈（原话要点）

> qa 题库的参考答案仍然出现 `\f`、`\v`、`\t` 等转义失败，但 problem 题库的参考答案没有类似问题。
> 一个 qa 题库参考答案的 latex 语法例子：
> `$e=1.602\        imes10^{-19}$`、`$$\vec{F}=\rac{1}{4\pi\varepsilon_0}...$$`、`$-\
abla V$`

> 知识点没有在题库编辑器看到，我们原本应该是知识点写到 json 里，跟参考答案一样，
> 但现在可以预览参考答案却不能预览知识点。另，知识点清单似乎没有看到，是受控词表吗？
> ai 的再整理按键有没有设计？

> 1、latex 语法输出和转义都按照 problem 里面的做法是否合理？……
> 2、related 预览与参考答案预览原理类似，都将相关内容记入 json 而不是 xlsx，是不是？
> 3、知识点被看见和整理都需要完成。

---

## 1. 根因分析（实测确认，不是推断）

### 1.1 三条不同的坏法（同一次 `parse_llm_json`）

| # | 教师观察到的 | 实际发生 | 触发条件 |
|---|---|---|---|
| A | `1.602\        imes10^{-19}` | `\times` 的 `\t` 被当制表符 → `TAB` + 8 个空格 + `imes` | 模型写**单**反斜杠 + 缩进对齐 |
| B | `\rac{1}{4\pi...}` | `\frac` 的 `\f` 被当换页符 → `FF` + `rac` | 模型写**单**反斜杠 |
| C | `-\
abla V` 显示成真换行 | `\nabla` 的 `\n` 被当换行符 | 模型写**单**反斜杠 |

`_fix_latex_in_json` 的识别图案是 `\\[fbtrn](rac|eta|...)`——**要求控制符后紧跟已知尾巴**。
场景 A 里 `\t` 后面是 **8 个空格**再 `imes`，**图案对不上 → 修复完全不触发**：

```
_looks_like_eaten_latex('{"a": "1.602\\        imes10^{-19}"}')  →  False
parse_llm_json(...)  →  '1.602\\        imes10^{-19}'   ← 原样带垃圾
```

### 1.2 🔴 更严重：函数会**主动弄坏**合格的输出

当模型**完全遵守**现有提示词（JSON 里写两个反斜杠）时：

```
输入（模型守规矩）         json.loads 正确结果      parse_llm_json 实际
"\frac{1}{2}"     →     \frac{1}{2}        →     \\ + 换页符 + rac    ❌
"\times10^{-19}"  →     \times10^{-19}     →     \\ + 制表符 + imes   ❌
"\beta"           →     \beta              →     \\ + 退格符 + eta    ❌
```

**根因**：`_looks_like_eaten_latex` 在**原始 JSON 文本**上匹配。守规矩时文本里是 `\\frac`，
正则 `\\`（一个反斜杠）+ `f` + `rac` **正好命中** → 把合法 `\\` 当"被吃掉的 `\`"再补一个 → `\\\f`。
`\\` 是合法转义，`json.loads` 不报错 → **静默产出坏数据**。

**为什么 1298 个测试全绿也没发现**：`test_d148_latex_json_escape.py` 全部用**单**反斜杠构造输入，
从未覆盖"模型守规矩"这一态。

### 1.3 为什么 problem 参考答案没出事

**不是 prompt 更好，而是它不经过 JSON**：

| | problem 参考答案 | QA / summary 参考答案 |
|---|---|---|
| 生成 | `SOLVE_SYSTEM_PROMPT` | `RUBRIC_PROMPT` |
| 输出格式 | **纯文本** | **JSON**（`RUBRIC_SCHEMA`：解答+要点+知识点+示意图） |
| 转义风险 | **零**（无 JSON 层） | 每一步都可能坏 |

problem 历史修的是**内容质量**，QA 的问题是**编码层**，两个维度。

### 1.4 不能"让 QA 也走纯文本"

`RUBRIC_PROMPT` 一次产出四个字段。改纯文本要么再调一次模型（成本翻倍、口径可能不一致），
要么正则切【评阅要点】【知识点】（不可靠）。且 `rubric_to_text / apply_related / teacher_report`
已在读 `rub.get("knowledge")`。**退化成文本解析正确率只会更低。**

### 1.5 知识点为什么"看不见"

| # | 断点 | 位置 |
|---|---|---|
| 1 | AI 作答**默认不写**知识点，除非单独勾「同时标注知识点」 | `solve.py:185` `if with_rubric and apply and tag_knowledge:` |
| 2 | 写进 xlsx 后**前端不刷新**，需手动点「🔄 从引擎重载题库」 | `KbEditorView.vue` |
| 3 | `related` 列**无预览**，只有被 ellipsis 截断的 input | `KbEditorView.vue:404` |
| 4 | 答案里那段 `【知识点】…` 是**版本库文本**，不是 `related` 注解 | `rubric_to_text()` |

另需澄清（教师疑问）：**知识点清单 ≠ 受控词表**。
- 题目级 `related` 列 = 这题考哪些概念；
- 章级 `materials/<特征名>/知识点清单.md` = 课堂资料（summary 批阅依据）；
- 受控词表 `knowledge-terms.json` = 术语规范（AI 标注时**优先从中选**，但写进 `related` 是自由文本，**不做强制**）。

---

## 2. 修复设计

### 2.1 转义：保留结构化输出，把"防转义"做正确

**三层防护（顺序不可换）**：

| 层 | 位置 | 作用 |
|---|---|---|
| L1 预防 | `RUBRIC_PROMPT` / 各类 prompt | 明确给出**坏例子→好例子**（把"`\times` 会变成制表符+空格+imes"写进去） |
| L2 解析 | `parse_llm_json` | 修 `_looks_like_eaten_latex` 的**误判**（只认单个反斜杠） |
| L3 后置净化 | 新增 `_sanitize_latex(text)` | 对**已解析出**的字符串还原残余坏形态 |

**L3 为什么最可靠**：此时双反斜杠已变单反斜杠，边界清晰，不用猜 JSON 文本。

**`_sanitize_latex` 规则**（只动能对上已知 LaTeX 命令的图案，其余一律不动）：

1. `\\` + 空白* + 命令尾巴（`imes/rac/eta/heta/...`）→ `\` + 尾巴；
2. 控制符（`\x0c \x08 \x0b \t \r \n`）+ 空白* + 命令尾巴 → `\` + 尾巴；
3. `\` + 控制符 + 空白 + 字母 → 按已知命令表还原。

**必须不误伤**：真换行 `第一行\n第二行`、真缩进、英文句子。
判定原则：**只有尾巴在 LaTeX 命令白名单里**才还原，白名单外一律保留。

### 2.2 知识点 JSON 化（与参考答案同构）

**仿照 D89-N3 答案版本库**：

| | 参考答案（现有） | 知识点（本次） |
|---|---|---|
| 权威位置 | `kb/solutions/<kb>__<chap>__<qid>.json` | `kb/knowledge-meta.json`（**已有 sidecar，扩展**） |
| xlsx 里的 | `solution` 列 = 摘要 | `related` 列 = 速查（**保留**，兼容 Excel） |
| 版本 | 多版本 + 置顶 | **新增 `versions[]`**（AI 再整理可追溯） |
| 读取 | `GET /kb/solutions/<qid>` | **新增 `GET /kb/related/<qid>`** |

`knowledge-meta.json` 每条扩展为：

```json
{
  "qa__chap01__c1": {
    "related": "库仑定律,电场强度",
    "versions": [{"id":"v1","terms":["库仑定律"],"source":"ai","model":"…","at":"…","note":"AI 标注"}],
    "suggested": "AI 建议原文（未采纳）",
    "pinned_by": "human",
    "vocabHits": ["库仑定律"],
    "vocabMisses": ["电场强度叠加原理"],
    "updatedAt": "..."
  }
}
```

### 2.3 AI 再整理（"整理"）

```
选中范围（整章 / 勾选题号）
  → 读 related + knowledge-meta + 受控词表
  → 跳过 pinned_by=human（除非勾「强制」）
  → 一次 LLM 调用：每题的合并/拆分/归一建议
  → 前端 diff 表（旧 → 新，标出合并/新增/删除/词表外）
  → 教师逐题勾选 + 「全部应用」→ 写 versions[]（自动快照）
```

三条口径（教师确认过，见 §5）：`pinned_by=human` 默认跳过；词表术语优先，词表外标「词表外」；**不自动改**答案文本里的【知识点】行。

### 2.4 顺带修复：`write_xlsx` 表头污染

`write_xlsx` 把表头写成 `solution（摘要，完整答案见 kb/solutions/<id>.json）`，
而 `read_xlsx` 按 `solution` 匹配 → **新建题库读回时 `solution` 列消失**（实测 `'solution' in row == False`）。

影响面：`write_chapters_preserving`（`apply_related` 走这条）**不受影响**（它按标准列名映射）；
仅 `write_xlsx` 影响新库创建/`kb write` 全量重建。**修复 = 表头写标准列名 `solution`，注释另放批注**。

---

## 3. 任务清单

| # | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T1 | `_looks_like_eaten_latex` 修误判（只认单个反斜杠） | — | 双反斜杠输入不被改坏 |
| T2 | 新增 `_sanitize_latex`，接入 `parse_llm_json` | T1 | 教师样例三条全部还原 |
| T3 | 四态测试矩阵（双反斜杠/单反斜杠/控制符/裸换行 × N 命令） | T2 | 矩阵全绿 + 反例不误伤 |
| T4 | prompt 加坏例→好例（`RUBRIC_PROMPT` 等） | — | 含"制表符"字样 |
| T5 | `write_xlsx` 表头修复 | — | 建新库读回含 `solution` |
| T6 | `knowledge-meta` 扩展 `versions/related/vocabHits` | — | 单测 |
| T7 | `GET /kb/related/<qid>` + `POST /kb/related/apply` | T6 | 单测 |
| T8 | 编辑器 `related` 列 🔍 预览弹窗（版本 + 来源 + 词表命中） | T7 | 浏览器 |
| T9 | AI 作答默认勾选「同时标注知识点」 | T6 | 浏览器 |
| T10 | AI 再整理：后端 `kb/related/tidy` + diff 预览 + 逐题勾选 | T7 | 单测 + 浏览器 |
| T11 | 四道门 | 全部 | pytest / build / selfcheck / 脱敏 |

---

## 4. 实施记录（2026-11-05 完成）

### 4.1 转义（T1–T4）

**新增三层防护**（`grading/transcribe.py`）：

| 层 | 函数 | 作用 |
|---|---|---|
| L2 | `_odd_backslash_positions()` + `_fix_latex_in_json()` | 判断反斜杠**是否成对**：`\\frac`（守规矩）不动，`\frac`（偷懒）才转义 |
| L3 | `_sanitize_latex_text()` / `_sanitize_latex()` | 对**已解析出**的字符串还原，覆盖 4 种坏形态 |
| L1 | `RUBRIC_PROMPT` | 写明「坏法 → 后果」（制表符/换页符/换行），不只说"用双反斜杠" |

**4 种坏形态**（`_eaten_patterns()`）：

1. 双反斜杠 + 空白* + 尾巴（过度修复的产物）
2. 控制符（`\x0c \x08 \t \x0b \n \r`）+ 空白* + 尾巴
3. 反斜杠 + 控制符 + 空白* + 尾巴
4. 反斜杠 + **字面量字母** + **至少一个空白** + 尾巴

> 形态 4 必须要求 `\s+`（至少一个空白）：写成 `\s*` 会把**正确的** `\frac` 改成 `\f rac`（调试中踩过）。

**调试中发现的三个陷阱**（均已加注释防复发）：

1. `(?<!\\)` 断言过严：偷懒时 `\,\t` 前也是反斜杠 → 改用「奇偶配对」判断；
2. `re.sub` 替换串写 `"\\" + head` 会被当成转义（`\f` → 换页符）→ 必须写 `"\\\\"`；
3. `_sanitize_latex_text` 的快速跳过只看控制符，漏掉「反斜杠+字母」形态 → 加反斜杠判断。

**验证**：`test_d166_latex_escape.py` **43 项**，含
「双反斜杠 / 单反斜杠 / 控制符+空格」三态 × 10 条命令矩阵，
以及**反例**（真换行、真制表符、普通英文含 `times`/`rac` 单词）不误伤。

### 4.2 知识点 JSON 化（T6–T9）

**后端**（`grading/rubric.py`）：

- `add_related_version()`：每次写入追加 `versions[]`（`source/model/at/note`），不覆盖历史；
- `get_related()`：一次返回 `related/terms/versions/suggested/pinned_by/vocabHits/vocabMisses/fromKbFallback`；
- `apply_related()` 写 xlsx 的同时**自动留版本**；
- `knowledge-meta.json` 每条扩展为 `{related, versions[], vocabHits, vocabMisses, pinned_by, pinnedVersion}`。

**接口**：

| 路由 | 方法 | 说明 |
|---|---|---|
| `/kb/related/<qid>?kb=&chap=&fallback=` | GET | 知识点完整视图（无版本时回落 xlsx 旧列） |
| `/kb/related/apply` | POST | 写入知识点（追加版本 + 快照） |
| `/kb/related/tidy` | POST | AI 再整理（**只出建议**） |
| `/kb/related/tidy/apply` | POST | 写入教师勾选的结果 |

> ⚠️ 调试踩坑：四个路由最初全塞进了 `do_GET`，导致 POST 一律 404。
> 已把三个 POST 移入 `do_POST`，`/kb/related/<qid>` 留在 `do_GET`。

**前端**：

- `KbEditorView.vue`：`related` 列加 🔍 → 「知识点」弹窗（爆发词表命中/词表外 + 历史版本 + 编辑写回）；
- `KbAiSolvePanel.vue`：「同时标注知识点」**默认勾选**（此前默认关，教师看不到知识点）。

### 4.3 AI 再整理（T10）

**新增** `grading/related_tidy.py`：

- `collect_targets()`：按 kind/chap/ids 挑题，`pinned_by=human` **默认跳过**（`force` 可强制）；
- `build_tidy_prompt()`：带受控词表 + 6 条整理规则（同义合并/词表优先/保留原意/粒度一致/去重/数量合理）；
- `build_diff()`：算 `before/after/added/removed`（供前端逐题核对）；
- `tidy_related()`：**只产出建议，不落盘**；
- `apply_tidy()`：教师勾选后写回（走 `apply_related`，自动快照 + 版本）。

**前端**（`KnowledgeView.vue` 新「①-B AI 再整理知识点」卡）：
生成建议 → 表格显示「整理前 / 整理后（删除项划线）/ 说明」→ 默认勾选**有变化**的题 → 逐题取消勾选 → 写入。

### 4.4 顺带修复（T5）

`write_xlsx` 把 `solution` 表头写成带注释的长字符串（`solution（摘要，…）`），
而 `read_xlsx` 按 `solution` 匹配 → **新建题库读回时该列消失**。
改为：表头写标准列名，说明改放单元格批注。

## 5. 验收对照

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 模型守规矩（双反斜杠）不被弄坏 | ✅ | `test_correct_output_is_not_broken` |
| 2 | 偷懒（单反斜杠）能还原 | ✅ | `test_single_backslash_recovered` |
| 3 | 控制符+空格（教师样例）能还原 | ✅ | `test_control_char_then_spaces_recovered` |
| 4 | 真换行/真制表符不误伤 | ✅ | `test_real_newline_and_tab_preserved` |
| 5 | 普通英文（含 times/rac）不误伤 | ✅ | `test_plain_text_untouched` |
| 6 | 提示词有具体坏例→后果 | ✅ | `test_rubric_prompt_gives_concrete_bad_examples` |
| 7 | `write_xlsx` 表头不污染 | ✅ | `test_write_xlsx_header_is_standard` |
| 8 | 知识点可预览 + 版本可追溯 | ✅ | `test_add_version_appends_not_overwrites` |
| 9 | 无版本时回落 xlsx 旧列 | ✅ | `test_get_related_falls_back_to_kb_column` |
| 10 | 词表命中/外分开标出 | ✅ | `test_vocab_hits_and_misses` |
| 11 | 再整理跳过教师锁定、只出建议 | ✅ | `test_tidy_skips_human_pinned` / `test_tidy_produces_suggestions_without_writing` |
| 12 | 再整理可写回且保留历史 | ✅ | `test_apply_tidy_writes_version_and_keeps_history` |
| 13 | 四道门 | ✅ | **1354 passed** · build 0 error · selfcheck **35/35** · 脱敏通过 |
| 14 | 浏览器回归（真实组件） | ✅ | `run-d148-knowledge-browser.sh` 含 `hasTidy`/`hasTidyBtn` |

## 5. 教师已拍板口径（2026-11-05）

1. 转义：**不做**"让 QA 走纯文本"，保留结构化，三层防护；
2. `write_xlsx` 表头 bug：一并修；
3. 知识点 json 化：权威进 `knowledge-meta.json`，xlsx `related` 保留速查；
4. 2508 整合：本轮**只写文档**，不动代码（见 `docs/110`）。
