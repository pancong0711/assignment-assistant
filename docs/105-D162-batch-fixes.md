# D162 需求单：一批问题修复（LaTeX 裸换行 / 标注不可见 / 章节下拉 / 种子往返 / 包计数 / 翻译换行）

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/104-D161`（种子）、`docs/103-D156-D160`（批阅质量）、`docs/12`

## 0. 教师反馈（9 条，逐条给结论）

| # | 反馈 | 结论 |
|---|---|---|
| 1 | 课堂资料没有上传键 | **有**（在选中章节后的「原件」区）；疑似没选中章节时看不到 → 加提示 |
| 2 | Atopia 能否分析文档并提取整合 | **能**（`fs.read` + `materials.suggest`），见 §3 |
| 3 | 班级与标签重算时 translation 会重新随机吗 | **不会**：等距选点，确定性可复现（有测试） |
| 4 | 题库编辑器预览参考答案仍见 `\f`/`\t` | **真实缺陷**：模型输出**裸换行**导致 JSON 非法 → 已修（见 §1） |
| 5 | 题库 AI 作答勾选标注，编辑器看不到 | **真实缺陷**：编辑器用浏览器内存副本，引擎写 xlsx 后不重读 → 加「从引擎重载题库」 |
| 6 | 知识点标注章节下拉为空 | **真实缺陷**：`fetchKbCatalog` 失败时静默返回空 → 改为显示错误 + 重试 |
| 7 | 逐生转写/批阅/完整会覆盖旧内容吗 | **会**（D157 起固定 `force: true`），是刻意行为 |
| 8 | translation 题号后另起一行 | 数据层差异：`read_translation` 的 content 内含 `\n`；本轮**保持原样**（见 §4） |
| 9 | 作业包删作业纸后计数不减 | **真实缺陷**：只删清单、没清包内引用 → 已修 |

## 1. LaTeX 裸换行（问题 4）

`parse_llm_json` 之前只处理"LaTeX 反斜杠被吃"。新发现的第二类失败：
模型把**真实换行**直接写进 JSON 字符串 → `Invalid control character`。

修复顺序（很关键）：
1. 先 `_fix_latex_in_json`（`\frac` 是"反斜杠+已知命令名"，判定可靠）；
2. 再 `_escape_control_chars`（字符串内的裸换行/制表符转义）；
3. 兜底 `_escape_bare_backslashes`。

反过来会把 `\frac` 当"换页符"处理，再也救不回来。

## 2. 标注不可见 / 章节下拉为空（问题 5、6）

- **标注不可见**：题库编辑器读的是**浏览器内存副本**；引擎 `apply_related` 写的是
  `kb/*.xlsx` → 前端不会自动重读。
  新增 `GET /kb/full` + 编辑器「🔄 从引擎重载题库」按钮 + `kb.adoptEngineKb()`。
- **章节下拉为空**：`fetchKbCatalog` catch 后**静默返回空**。改为返回 `error`，
  面板显示「读取题库目录失败：…」+「重试」。

## 3. Atopia 能否分析文档（问题 2）

**能**，链路已通：
```
fs.search / fs.read（D148 只读文件能力）
  → materials.suggest（L1，AI 抽知识点）
  → materials.confirm（L2，教师确认后生效）
```
「上传 PPT → AI 解析 → 写回课堂资料」的**上传入口**与「从 Atopia 复制」
仍属 D150 规划（未实施）。

## 4. translation 题号换行（问题 8）

`read_translation()` 生成的 content 是：
```
请翻译以下内容：
{saying} (by {author}, {book}, {year})
并回答：…
```
**内含换行**，而 `summary` 等题型是单行 → 视觉上"题号后另起一行"。
这是数据生成方式的差异，不是渲染 bug。本轮**未改**（改了会影响已导出作业纸的比对）。

## 5. 种子往返丢失（问题 8 的另一半）

**真实缺陷**：`parseTaskpad`/`serializeTaskpad` **都没处理 `random_seed`** →
保存后再载入种子丢失 → 翻译题回到默认（永远同一道）。

修复：
- `serializeTaskpad` 写入 `random_seed`；
- `parseTaskpad` 读回 `random_seed`；
- `makeRandomSeed()` 同毫秒递增（避免连续新建拿到相同种子）。

## 6. 作业包计数（问题 9）

`taskpad.removeFromLibrary()` 只删清单记录，**没清作业包内的 `pads` 引用** →
包名后的「N 张」不减。

修复：`removeFromLibrary` 同步清理所有作业包引用并 `persistLocal()`，返回受影响包 id。

## 7. 验收

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 裸换行 + LaTeX 都能解析 | ✅ | `test_bare_newline_*`（2 项） |
| 2 | 引擎能返回含 related 的题库 | ✅ | `test_kb_full_endpoint_returns_related` |
| 3 | 标注写回后可读 | ✅ | `test_apply_related_writes_then_readable` |
| 4 | translation tag 确定性 | ✅ | `test_translation_tag_is_deterministic` |
| 5 | 种子在序列化往返中保留 | ✅ | `selfcheck-d162-taskpad-seed`（4 项） |
| 6 | 删作业纸后包内引用清理 | ✅ | `selfcheck-d162-pack-count`（4 项） |
| 7 | pytest / build / selfcheck / 脱敏 | ✅ | **1278 passed** · 0 error · **35/35** · 通过 |

## 8. 未做（明确记录）

- 课堂资料「没有上传键」若确属"未选中章节"，建议增加**空态提示**（本轮未加，需确认现场）；
- translation content 的换行格式（改了会影响已有作业纸）；
- D150 Atopia 工作区与「从 Atopia 复制」。
