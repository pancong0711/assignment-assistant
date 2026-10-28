# D108 任务需求单：AI 作答要求提示词「模板库」（保存/默认/删除）

> 日期：2026-10-25
> 状态：**T1–T5 全部完成**（2026-10-25）
> 关联：`docs/57-D105`（md+html 答案）、`docs/59-D107`（CLI 能力对等）、D104（`--requirement` 单次输入）

## 1. 背景

D104 让教师可以在「AI 辅助批阅 → 题库作答」输入一次性作答要求（`--requirement`），
但每次都要重新输入，常用要求（画示意图 / 输出 HTML / 分步解析）反复粘贴很低效。

## 2. 用户拍板（2026-10-25）

| 项 | 决定 |
|---|---|
| 存储位置 | **`<ws>/prompts/ai-solve/*.json`**（CLI/AI 可复用，换浏览器不丢） |
| 「勾选」语义 | **「设为默认」（单选）**，不做多选叠加（多模板叠加会产生语义矛盾） |
| 内置模板 | 预置 5 条，「标准完整解答」为出厂默认 |
| 内置可删性 | **不可删，但可复制**（防误删无法恢复） |
| 临时修改 | 点「AI 作答」直接用**文本框当前内容**，不强制先保存 |
| 长度限制 | 单模板 ≤ 2000 字（校验，避免误粘贴无关内容） |

## 3. 数据模型

`<ws>/prompts/ai-solve/<id>.json`：

```jsonc
{
  "id": "with-svg",
  "name": "含示意图（几何/受力题）",
  "text": "请画出示意图：需要图示时用内联 <svg>（黑白线稿、viewBox ≤ 200×150、≤20 图元、不引用外链）…",
  "default": true,
  "builtin": false,
  "updatedAt": "2026-10-25 10:00:00"
}
```

- `default` 至多一个为 true（写入时互斥）；
- `builtin: true` 的内置模板不可删除/不可改 id，但可「复制为新模板」后编辑。

## 4. 内置模板（5 条）

| id | 名称 | 要点 |
|---|---|---|
| `standard` | 标准完整解答（默认） | 物理过程 → 逐步推导 → 结论；公式 `$..$` / `$$..$$` |
| `with-svg` | 含示意图（几何/受力题） | 内联 `<svg>`：黑白线稿、viewBox ≤ 200×150、≤20 图元、禁外链 |
| `html-doc` | 输出 HTML 文档 | Markdown + HTML 白名单（表格/列表/SVG/data:image），禁 script/style |
| `step-by-step` | 分步解析（教学向） | 已知/求/解/答 四段式 + 每步物理意义 |
| `concise` | 精简答案 | 只给关键步骤与结果（适合答案格空间有限） |

## 5. 接口

### 5.1 引擎 CLI

```bash
assist prompt list   [--workspace ws]
assist prompt save   --id <id> --name <名称> [--text <文本> | --file <路径>] [--default]
assist prompt delete --id <id>
assist prompt use    --id <id>            # 设为默认
assist kb ai-solve ... --requirement-template <id>   # 直接套用某模板
```

### 5.2 serve（PWA）

```
GET  /prompts/ai-solve            → { ok, items: [...] }
POST /prompts/ai-solve            → { action: save|delete|set_default, ... }
```

### 5.3 PWA 交互

```
[模板 ▼]  [☑ 设为默认]  [＋新建]  [💾 保存]  [🗑 删除]
┌──────────────────────────────────────────┐
│ 文本框（选中模板的内容，可临时修改）        │
└──────────────────────────────────────────┘
```
- 打开面板时自动载入**默认模板**内容；
- 「AI 作答」发的是**当前文本框内容**（临时修改立即生效）；
- 「保存」覆盖当前模板；「＋新建」另存为新模板。

## 6. 任务分解

| # | 任务 | 文件 |
|---|---|---|
| T1 | `files/prompts.py`：CRUD + 默认互斥 + 内置模板 + 长度校验 | `engine/src/assist/files/prompts.py`（新增） |
| T2 | CLI `assist prompt list/save/delete/use` + `kb ai-solve --requirement-template` | `engine/src/assist/cli.py` |
| T3 | serve `GET/POST /prompts/ai-solve` | `engine/src/assist/serve.py` |
| T4 | PWA：`fetchPromptTemplates` / `mutatePromptTemplate` + 面板 UI（下拉/新建/保存/删除/设默认） | `app/src/lib/engineClient.ts`、`AiGradingPanel.vue` |
| T5 | 测试：CRUD/默认互斥/内置保护/超长拒绝/CLI 与 serve 一致性 | `engine/tests/test_d108_prompt_templates.py` |

## 7. 回滚

模板库为**纯增量**：删除 `prompts/ai-solve/` 即回退到"只有单次输入框"的行为。
`--requirement-template` 缺省时不生效，`--requirement` 仍可用。

---

## 8. 实施记录（待填）

## 9. 实施记录（2026-10-25）

### 9.1 完成项

| # | 内容 | 文件 |
|---|---|---|
| T1 | `files/prompts.py`：CRUD + 默认互斥 + 5 条内置模板 + 长度/ID 校验 + `requirement_text()` | `engine/src/assist/files/prompts.py`（新增） |
| T2 | CLI：`assist prompt list/save/delete/use`；`kb ai-solve --requirement-template` | `engine/src/assist/cli.py` |
| T3 | serve：`GET/POST /prompts/ai-solve`；`/kb/ai-solve` 支持 `requirementTemplate` | `engine/src/assist/serve.py` |
| T4 | PWA：`fetchPromptTemplates` / `mutatePromptTemplate`；面板下拉+设为默认+保存+另存为+删除 | `engineClient.ts`、`AiGradingPanel.vue` |
| T5 | 测试 15 例（数据层 11 + CLI 2 + serve 1 + 兼容 1） | `engine/tests/test_d108_prompt_templates.py` |

### 9.2 关键行为（实测）

| 场景 | 结果 |
|---|---|
| 首次访问 | 自动落盘 5 条内置模板，`standard` 为默认 |
| 保存并设默认 | 原默认自动清除，**全库至多 1 个 default** |
| 切换默认 | `use --id with-svg` → 默认切到 with-svg，旧的清掉 |
| 删除内置 | 拒绝：`内置模板不可删除（可复制为新模板后编辑）` |
| 删除默认（自定义） | 成功且**自动回落**到内置 `standard` |
| 超长内容 | 拒绝：`模板内容过长（3000 > 2000 字）` |
| 非法 id | 拒绝（`../x`、`a/b`、空、`-x`） |
| 改内置内容 | 允许（`builtin` 标记保留，仍不可删） |
| 模板优先于单次输入 | `requirement_text(ws, "t1", "单次输入")` → 模板内容；模板缺失 → 回退单次输入 |

### 9.3 UI

```
提示词模板：[★ 标准完整解答（默认） ▼] [设为默认] [💾 保存] [＋ 另存为] [🗑 删除]
作答要求（选中模板会载入其内容，可再临时修改，直接点「AI 作答」即生效）：
┌──────────────────────────────────────────────┐
│ 文本框                                         │
└──────────────────────────────────────────────┘
留空 = 系统默认风格。模板保存在 <workspace>/prompts/ai-solve/，
CLI/AI 同样可用（assist prompt list / kb ai-solve --requirement-template <id>）。
```

### 9.4 验证

| 项 | 结果 |
|---|---|
| engine pytest | **586 passed**（新增 D108 15 例） |
| app `vue-tsc` / `build` | **0 error** |
| app `npm run selfcheck` | **全绿** |
| 端到端（浏览器 fetch 引擎端点） | 5 条内置、保存+设默认成功、默认切换、内置删除被拒 400 |

---

## 10. 缺陷修复（D108-FIX，2026-10-28）：中文 id 导致「另存为 / 新建模板」不可用

### 10.1 现象

点「＋ 另存为」或「💾 保存（新建）」时：

- 看不到「新模板 id」的选择结果（模板列表不新增）；
- 面板下方出现**蓝字**提示：`模板 id 非法（1..64 位，字母数字开头，可含 _ . -）`。

### 10.2 根因

前端 `window.prompt` 收集 id 后**原样提交**，而引擎 `files/prompts.py` 的
`_ID_RE = ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$` **只允许 ASCII**：

| 用户输入 | 旧行为 |
|---|---|
| `我的模板` | 400 `模板 id 非法` |
| `my template`（带空格） | 400 `模板 id 非法` |
| `测试` | 400 `模板 id 非法` |
| `ＡＢＣ`（全角） | 400 `模板 id 非法` |

教师天然会用中文命名模板，于是"另存为"几乎必失败；且弹窗对合法字符**毫无提示**，
报错又不回显输入，难以自查。注：同一仓库的 `grading/items.py` 早已允许中文 id，
`prompts.py` 与之不一致才是缺陷。

### 10.3 修复

1. **引擎允许中文 id**（`_ID_RE` 增加 `\u4e00-\u9fff`，与 `grading/items.py` 对齐）：
   仍拒绝路径分隔符/空白/控制字符，不得以 `.` `-` 开头；**路径穿越已回归验证**。
2. **报错可操作**：回显非法输入并给出完整规则；`delete/set_default` 缺 id 时
   报「缺少模板 id（未选中…）」而不是含混的「模板 id 非法」。
3. **前端归一化 + 预填建议值**（新模块 `app/src/lib/promptId.ts`，与后端同一正则）：
   - 空格转 `-`、丢弃非法字符、去开头 `.`、截断 64；
   - 弹窗默认值由模板名称生成，并自动避让已占用 id（`我的模板-2`）；
   - 无法修复时就地提示规则，不再提交必失败的请求。
4. **另存为不再静默覆盖**：目标 id 已存在时提示换名（`save` 是 upsert 语义）。
5. **引擎离线可诊断**：`mutatePromptTemplate` 网络失败返回
   `引擎未连接（<addr>），请先启动 assist serve`，列表读取失败也明确提示，
   不再表现为"没有模板可选"。

### 10.4 验证

| 项 | 结果 |
|---|---|
| engine pytest | **589 passed**（D108 用例 15 → 18） |
| app `vue-tsc -b` / `npm run build` | **0 error** |
| app `npm run selfcheck` | **全绿**（新增 `selfcheck-d108-prompt-id.mjs`） |
| 端到端（HTTP 打引擎端点） | 中文 id 新建/另存为/设默认/删除全部 200；非法 id 400 且回显输入；默认互斥在中文 id 下正常 |
