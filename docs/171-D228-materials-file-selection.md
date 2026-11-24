# D228：课堂资料按文件抽取/知识点识别 + provider 选择生效

> 日期：2026-11-25
> 状态：**已完成（2026-11-25）**
> 关联：`docs/79`（课堂资料）、`docs/105-D162`（资料重载）、
> `docs/169-D226`（题库目录实时刷新）
>
> 隐私：无学生数据；本轮只改课堂资料原件处理链路。

---

## 0. 教师反馈

1. 课堂资料「① 抽取」可以正常进行，但**不能指定文件**；
2. 更新一个文件后，是否意味着需要把整章重新抽取？
3. 「② AI 建议知识点」识别失败；
4. 希望能**逐一文件识别**，最好有勾选实现多选/全选。

---

## 1. 结论

### 1.1 更新文件不需要全章重抽

引擎原本已有 sha256 增量：

- 文件未变 → 跳过；
- 文件内容变化 → sha256 变化，只重抽这个文件；
- `--force` 才忽略缓存强制重抽。

本轮补的是**可见性与控制权**：PWA 原来只能整章触发，教师无法确认哪些文件会处理、
也无法只重跑一个问题文件。

### 1.2 知识点识别失败：provider 下拉框此前没有真正生效

PWA 允许选择「建议用模型」的 provider，但提交时只传了 `model`：

```text
PWA provider 下拉 → 只存本地；请求只带 model
服务端 → LLMClient(ws=ws)  // 仍使用评阅段 provider
```

因此教师选了一个有 key 的 provider，实际仍可能走默认评阅 provider，
表现为“知识点识别失败/配置不对”。

修复：

- PWA 请求同时传 `provider + model + files`；
- serve `/materials/suggest` 改用 `build_client_for(ws, provider, model)`；
- CLI `materials suggest` 新增 `--provider`；
- 错误信息细化：LLM 未配置、API 调用失败、选中文件未抽取等分别给出可读原因。

---

## 2. 实现

### 2.1 引擎按文件处理

`engine/src/assist/files/materials.py`：

- 新增 `resolve_source_selection()`：
  - 接受 `_source/plan/a.pptx`、`plan/a.pptx`、唯一 `a.pptx`；
  - 校验路径必须位于 `_source/` 内；
  - 返回选中真实路径 + 找不到的文件；
- `extract_chap(..., files=...)`：
  - 只处理选中文件；
  - 未选中文件的旧索引条目**原样保留**；
  - 返回 `selected_files` / `skipped_unchanged` / `skipped_unselected` / `errors[]`；
- `read_source_text(..., files=...)` 与 `read_source_images(..., files=...)`：
  - 知识点识别只汇总选中文件的文本/页图；
- `suggest_knowledge(..., files=...)`：
  - 选中文件若尚未抽取 → 明确报错，提示先抽取；
  - `知识点清单.ai.json` 记录本次 `source.fileNames` 与 `source.selected`；
- `files_of()`：
  - 每个原件增加 `indexed / extracted / extractMode / extractChars / extractImages / extractedAt`。

### 2.2 API / CLI

- `POST /materials/extract` 新增 `files: string[]`；
- `POST /materials/suggest` 新增 `provider`、`files`；
- CLI：
  - `assist materials extract --chap ... --file ... --file ...`
  - `assist materials suggest --chap ... --provider ... --file ...`
  - `--file` 可多次传入；缺省 = 全部。

### 2.3 PWA

「课堂资料 → 原件」表格：

- 每行新增复选框；
- 表头支持全选；
- 工具条提供「全选 / 全不选 / 反选」；
- 显示每个文件的「已抽取 / 未抽取」与抽取方式/字数/图数；
- 「① 抽取选中 N 个」只处理勾选文件；
- 「② AI 建议知识点」也只处理勾选文件；
- 选中文件存在未抽取项时，②按钮禁用并给出提示；
- 新增「强制重抽（忽略 sha256）」复选框；
- 上传新文件后自动加入当前选择；切换章节默认全选本章原件。

---

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 只勾选一个更新过的文件 | 仅该文件重抽；其它文件索引不变 |
| 2 | 勾选多个文件 | 多选抽取/识别 |
| 3 | 全选 / 全不选 / 反选 | 选择状态正确 |
| 4 | 更新文件但内容未变 | sha256 命中，跳过；可勾选强制重抽 |
| 5 | 选中未抽取文件直接识别 | 明确提示先抽取，不发模型请求 |
| 6 | 选择有 key 的 provider | 请求真正使用该 provider |
| 7 | 逐文件排查 | 只选一个文件识别，结果范围可审计 |

### 自动化

- 引擎 `test_d131_materials.py`：**38 passed**（新增按文件抽取、索引保留、
  未抽取拦截、按文件识别、CLI 多文件、serve provider 透传）；
- PWA `selfcheck-d228-materials-file-selection.mjs`；
- 前端 build 通过。
