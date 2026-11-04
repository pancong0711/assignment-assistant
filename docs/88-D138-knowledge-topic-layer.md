# D138 需求单：知识点两层分类（章节 + 主题），**不做 parent/child**

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/85-D135-knowledge-hierarchy`（方案 B 被采纳）、`docs/78-D130`（词表）、
> `docs/84-D135`（趋势报告受益）、`docs/12`

## 0. 决策（教师拍板）

在 `docs/85` 的四种方案中选 **B：两层固定分类**，且**先不做 `parent/child` 字段**。

```
chapter（章，如 chap04）  →  topic（主题，如 碰撞问题）  →  term（知识点，如 完全弹性碰撞）
```

- `chapter` **已存在**（来源：题库章节名），本轮不改语义；
- 新增 `topic`：**一层**，字符串，用于把同章内分散的术语归成"块"；
- **明确不做**：`parent` 字段、任意深度 DAG、多父。

## 1. 为什么选 B（而不是 A/C）

| 理由 | 说明 |
|---|---|
| 教师已按**章节**组织一切 | 题库 sheet、`materials/<chap>/`、`summary` 批阅依据全是章维度 |
| 报告最需要的分组是"块"而不是"树" | 教师报告/趋势报告要的是"这几个术语同属一块内容" |
| 不加 parent 就没有环检测/多父/渲染递归 | 复杂度最低，且够用 |

## 2. 数据模型

### 2.1 词表 `<ws>/knowledge-terms.json`

```jsonc
{"version": 1,
 "terms": [
   {"term": "完全弹性碰撞", "aliases": ["弹性碰撞"],
    "chapter": "chap04",          // 已有：来自题库章节
    "topic": "碰撞问题",           // 新增：同章内的"块"
    "source": "human|ai|kb", "count": 3}
 ]}
```

- `topic` 可选；缺失时按**章节**归组（报告仍能分组，只是粒度粗一档）；
- 不清空/不覆盖教师已填的 `topic`（与 `aliases` 同口径）。

### 2.2 资料清单 `materials/<chap>/知识点清单.md`

渲染时按 topic 分节：

```markdown
## 核心知识点（必考）
### 碰撞问题
- **完全弹性碰撞**（别名：弹性碰撞） —— _第1页_
### 动量定理
- **动量守恒** —— _第1页_
```

> 无 topic 的术语归入 `### 其他`（**不丢**，只是排最后）。

### 2.3 AI 抽取

`materials suggest` 的 prompt 增加要求：每条知识点给 `topic`（同章内的"块"，
如"碰撞问题""动量定理"），**必须**从资料原文归纳，不得编造；
提示词明确"topic 是**同章内**的归类，不要写成章名"。

## 3. 任务清单

| # | 内容 | 验收 |
|---|---|---|
| T1 | 词表支持 `topic` 读写；`set-topic` CLI（L2 需确认）；不清空已有值 | 单测 |
| T2 | `materials suggest` 产出 `topic`；`render_knowledge_md` 按 topic 分节 | 单测（含"无 topic 归入其他"） |
| T3 | `knowledge_terms()` 兼容新 md（按 `###` 分节也能取到术语） | 单测（回归：旧 md 仍可读） |
| T4 | 教师报告 / 趋势报告按 **chaptopic** 分组展示（无 topic 时退回按章） | 单测 + 浏览器 |
| T5 | PWA：资料页展示 topic 分组；报告卡按 topic 分组 | build + 浏览器 |
| T6 | 文档回填 | — |

## 4. 验收标准

1. 词表条目可带 `topic` 并落盘；未带的条目不报错（兼容旧数据）；
2. `render_knowledge_md` 有 topic 时按 `###` 分节，无 topic 归入「其他」；
3. **旧格式 md（无 ### 分节）仍能被 `knowledge_terms()` 正确读取**（向后兼容）；
4. 教师报告按 topic 分组展示；无 topic 时退化为按章，**不报错**；
5. 趋势报告同样可按 topic 分组；
6. pytest / build / selfcheck / 脱敏 全绿。

## 5. 风险

| 风险 | 缓解 |
|---|---|
| 已有 md 被重排导致 diff 很大 | 只在**重新确认**时按新格式渲染；旧文件不动 |
| `knowledge_terms()` 解析新 md 漏术语 | 专门回归测试；`###` 小节内 `- ` 行照常解析 |
| AI 编造 topic | prompt 明确"必须来自资料原文"；topic 只影响分组，不影响扣分 |
| topic 归类不一致（同术语不同 topic） | 词表以 term 为键，同 term 只保留一个 topic |

## 6. 实施记录（2026-10-31 完成）

### T1 词表（`grading/vocab.py`）

- `save_vocab` 保留 `topic` 字段；`add_term(topic=, chapter=)` **只在显式传入时改**
  （`None` = 保持原值，与 aliases 同口径，避免误清空教师归类）；
- CLI `kb vocab add --topic/--chapter`、新增 `kb vocab set-topic`；
- 工具注册 `kb.vocab.set-topic`（L2，需教师确认）。

### T2 抽取与渲染（`files/materials.py`）

- `KNOWN_PROMPT` 要求每个术语给 `topic`（**明确"不要写成章名"、"只能从资料归纳"**）；
- `suggest_knowledge` 保留 `topic`；
- `render_knowledge_md` 按 `topic` 分节：`## 核心知识点` 下再分 `### 主题`；
  无 topic 的条目归入 `### 其他` 并**排在最后**（不丢）；
  **整份都没有 topic 时保持旧格式**（无 `###`），旧文件/旧数据零影响。

### T3 解析（向后兼容）

- `knowledge_terms()` 同时支持新旧格式；`## 逻辑关系` 段内的 `- A → B` **不再**被误当术语；
- 新增 `knowledge_topics()` → `{主题: [术语]}`；旧格式全部归 `"其他"`。

### T4 报告按主题分组

- `teacher_report`：`analyze(topics=)` 附 `topic` 并产出 `byTopic`；
  `render_md` 有主题时按 `### 📚 主题` 分块；**无主题时与 D126-B 完全一致**；
  新增 `load_topic_map(ws, chaps)` 从各章生效清单汇总映射；
- `trend`：同样附 `topic` 与 `byTopic`；**只有 ≥2 个主题时才分组**
  （单组多一层标题没有信息量）。

### T5 PWA

- `/materials/knowledge` 增加 `topics`；资料页按主题分组展示术语；
- 教师报告卡有 `byTopic` 时按主题分表展示，否则退回扁平表。

### 测试

- `test_d138_knowledge_topic.py`（19 项）：词表 topic 读写/不清空/可显式清除、
  旧词表兼容、渲染分组/无 topic 旧格式、解析新旧格式、报告与趋势分组、
  单主题不分级、工具级别；
- `run-d126b-d131-pages-browser.sh` 扩展：真实浏览器断言教师报告出现 `📚 主题`。

## 7. 验收对照

| # | 标准（§4） | 结果 | 证据 |
|---|---|---|---|
| 1 | 词表可带 topic 落盘；未带的兼容 | ✅ | `test_add_term_with_topic` / `test_old_vocab_without_topic_loads` |
| 2 | 有 topic 按 `###` 分节，无 topic 归「其他」 | ✅ | `test_render_groups_by_topic` |
| 3 | **旧格式 md 仍能正确解析** | ✅ | `test_knowledge_terms_old_format` / `test_knowledge_topics_old_format_falls_back_to_other` |
| 4 | 教师报告按 topic 分组；无 topic 不报错 | ✅ | `test_teacher_report_groups_by_topic` / `test_teacher_report_flat_when_no_topics` |
| 5 | 趋势报告同样可分组 | ✅ | `test_trend_groups_by_topic` / `test_trend_single_topic_stays_flat` |
| 6 | pytest / build / selfcheck / 脱敏 | ✅ | 1132 passed · 0 error · 28/28 · 通过 |

## 8. 明确不做

- `parent` / `child` 字段（教师明确要求先不做）；
- 任意深度 DAG、多父；
- 任何因分类而改变的**扣分**逻辑（分类只影响展示与分组统计）。
