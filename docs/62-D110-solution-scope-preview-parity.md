# D110 缺陷修复：跨章同号答案串味 / 误刷全库 / 置顶答案预览异常

> 日期：2026-10-28
> 状态：已实现并验证
> 关联：`docs/42-D89-pack-and-solution-versions.md`（答案版本库）、`docs/61-D109-...`（示意图/LaTeX）；`docs/63-D111-global-question-id-taskboard.md`（题号全局唯一）

## 1. 现象（用户反馈）

1. 题库中**同号但不同章节**的题，答案变成同一个；
2. 没点"全库生成"，却好像把**整个题库**都作答了；
3. 「置顶的参考答案」预览有问题：**文字截断**、**连续多行虚线**、**看不到示意图**。

## 2. 根因

### 2.1 答案文件只按 qid 命名 → 跨章同号互相覆盖（主因）

`files/solutions.py` 原实现：`kb/solutions/<qid>.json`。而题库 id 只保证**章内唯一**
（`c1` 在 chap04、chap05 都存在），于是两章的 `c1` 写进同一个 `c1.json`：

```
chap04/c1 写 → c1.json: [v1=第四章答案]
chap05/c1 写 → c1.json: [v1=第四章答案, v2=第五章答案(pinned)]
读 chap04/c1 → 拿到第五章答案 ✘
```

`docs/42 §4.2` 示例用的是 `chap04-1` 这种全局唯一 id，与真实数据不符，属设计假设错误。

### 2.2 空选择 = 整章/整库，且无任何确认

- `solve.list_targets(chap="", ids=[])` → 遍历**全部章节**；
- PWA 题号多选留空即"整章"，章节也不选就是**整库**；
- serve `/kb/ai-solve` 原样透传；CLI 同样。
→ 用户以为只答几题，实际整库刷了 AI 作答并**置顶为生效答案**。

### 2.3 预览：KaTeX 重渲染用 `textContent` 还原，抹掉全部标签

`lib/katexRender.ts` 的 `renderMathIn(el, force=true)`：

```ts
el.textContent = original     // ← 把"纯文本快照"写回元素
```

实测（Chromium）：`table 1→0`、`svg 1→0`，KaTeX 的 MathML+HTML 双份文本被拼成
`F=maF=maF=ma`。于是：**示意图消失**、表格塌成一行、文字看起来被**截断/重复**。

### 2.4 预览：每条答案续段都画一次顶部虚线

`.q-solution { border-top: 1px dashed }`，而答案跨格续写时**每格**都渲染一个
`.q-solution` → 出现**一串平行虚线**。

## 3. 修复

### 3.1 答案版本库改为「作用域」存储（`files/solutions.py`）

- 文件名 `<kb>__<chap>__<qid>.json`（`scope_id()`；缺 chap/kb 时逐级退化，保持旧路径兼容）；
- 全部读写函数新增 `kb=`/`chap=` 参数：`read_solutions` / `save_solutions` /
  `add_version` / `pin_version` / `remove_version` / `effective_solution`；
- **旧数据自动迁移**：首次按章节写入时，若命中的是旧 `<qid>.json`，把它合并过去并
  标记 `migratedTo`，读取时跳过——避免旧文件继续充当其它章节的兜底答案；
- 新增 `effective_by_key()`（`kb__chap__qid` 精确索引）；`effective_map()` 按 qid
  保留但跨章同号时标 `ambiguous=true`，前端不再盲用。

### 3.2 全链路带上作用域

| 位置 | 改动 |
|---|---|
| `paper/htmlfile.py` | 答案索引改 `(kb,chap,qid)`；`_resolved_ids` → `_resolved_items_ref` 返回三元组 |
| `paper/task.py` | 教师版 PDF 按 `_resolved_refs` 取答案 |
| `grading/flow.py` / `grading/inputs.py` | 批阅 prompt 的答案按作用域取 |
| `serve.py` | `POST /kb/solution`、`GET /kb/solutions/<qid>` 接受 `kb`/`chap`；批量索引新增 `effectiveByKey` |
| `cli.py` | `kb solution list/pin/rm` 新增 `--kb/--chap` |
| `stores/kb.ts` | 新增 `solIndexByKey`，`effectiveSolution(qid, fallback, scope)` 优先精确命中 |
| `lib/sheetHtml.ts` | `SolutionResolver` 增加 `scope` 参数，`expandPadItems` 传入 `item.kb/item.chap` |
| `lib/engineClient.ts` | `fetchKbSolutions` 带 `?kb=&chap=`；新增 `solutionScopeKey()` |
| `KbEditorView.vue` | 打开预览/置顶/删除版本均带当前 kind+chap |

### 3.3 防"误刷全库"

- CLI：`kb ai-solve` 在 **无 `--chap` 且无 `--ids`** 时必须显式 `--all`，否则报错退出；
- serve：同样情况下要求请求体 `all: true`，否则 **400**（不再默认整库）；
- PWA：空选择弹确认框，明确写出"将对整个题库/整章作答（并写回/置顶生效答案）"。

### 3.4 预览修复

- `katexRender.ts`：force 重渲染改用 **`innerHTML`** 还原，快照也存 `innerHTML`
  → 示意图/表格保留，不再出现重复文字；
- 虚线：只有一条答案的**首个**块加 `q-sol-first`（画虚线），续段用 `q-solution-cont`
  （不画线）。`sheetHtml.ts` 与 `assignment.html.j2` 同步。

## 4. 验证

| 项 | 结果 |
|---|---|
| engine pytest | **603 passed**（新增 `test_d110_scoped_solutions.py` 9 例） |
| app `vue-tsc -b` / `npm run build` | 0 error |
| app `npm run selfcheck` | 全绿（新增 `selfcheck-d110-solution-scope.mjs`） |
| Playwright（KaTeX） | 修复前 `table 1→0 / svg 1→0`；修复后 `table=1, svg=1`，结构完整 |
| CLI 端到端 | 两章同号 `c1` 各写各的答案；`sheet html` 中两章答案各出现 1 次、无串味 |
| 迁移 | 旧 `c1.json` 在按章写入后标记 `migratedTo`，其它章节读不到它 |

## 5. 注意 / 后续

- **已有旧数据**：若此前两章答案已被写进同一个 `<qid>.json`，该文件内容无法自动判定
  属于哪一章。系统会把它并入**首次按章写入的那一章**；其余章节需重新作答一次。
  可用 `GET /kb/solutions?raw=1` 或 `assist kb solution list` 检查残留。
- 若要全局唯一的题库 id（如 `chap04-c1`），属于数据层规范调整，另行立项。
