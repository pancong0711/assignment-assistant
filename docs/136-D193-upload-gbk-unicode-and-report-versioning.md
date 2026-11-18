# D193：上传批语/成绩报 GBK 编码错 + 报告版本与覆盖策略评审

> 日期：2026-11-18
> 状态：**编码修复已完成（2026-11-18）；报告版本化方案待确认（见 §4）**
> 关联：`docs/127-D184-audit-tag-upsert.md`、`docs/117-D174-three-keys-and-translation-lenient.md`、
> `docs/120-D177-single-prompt-builder.md`
>
> 隐私：需求单只用合成数据（学生甲/学生乙）；不记录真实学生姓名/学号/作答内容。

---

## 0. 现场

教师已生成批阅报告，点上传播报：

```text
上传失败：UnicodeEncodeError: 'gbk' codec can't encode character '\u2212' in position 965:
illegal multibyte sequence
```

## 1. 根因（已修复）

`\u2212` 是**数学减号 `−`**（不是 ASCII 连字符 `-`），AI 批语里很常见
（如「10 − 2 = 8」）。上传链路：

```text
PWA → POST /xxt/grade/upload → serve 启动 CLI 子进程
    → assist xxt grade-upload --from-drafts --confirm-send
    → click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
```

Windows 下 `serve` 用 `subprocess.Popen(text=True)` 起子进程时，子进程 stdout 继承
GBK 控制台编码；`click.echo` 写 `−` 直接抛 `UnicodeEncodeError`：

- 批语/分数其实**已写进平台页面**（`set_comment_html`/`fill_scores` 已执行），
  但打印结果时崩溃 → 任务失败 → 教师看到“上传失败”，且不知道是否已提交；
- 该异常发生在 `--confirm-send` 的**提交后**，所以平台侧可能已部分落库。

### 修复

1. `serve._xxt_env()`：给所有 CLI 子进程加
   `PYTHONIOENCODING=utf-8:replace` + `PYTHONUTF8=1`；
2. `Popen(..., encoding="utf-8", errors="replace")`：父进程按 UTF-8 解码子进程输出；
3. `assist.cli.main()` 入口 `_force_utf8_output()`：把 stdout/stderr 切到
   UTF-8（`errors="replace"`），即使直接命令行运行、没有环境变量也不会崩；
4. 顺带修掉 `cli.py` 中一处**多行 f-string**（Python 3.12+ 语法）——
   引擎声明 `requires-python >=3.11`，3.11 下会让整个 CLI 语法错误、所有 xxt 命令不可用。

> 设计原则：**诊断输出不得让主流程失败**。编码兜底用 `replace` 而不是 `strict`，
> 最坏情况只是终端显示成 `?`，业务数据（批语/分数/清单 JSON）始终是完整的 UTF-8。

## 2. 上传时是否要检查「已批阅」状态？

现状（`xxt/grade_upload.upload_grade`）：

```python
if "已批阅" in str(row.get("status") or "") and not force:
    return {"ok": False, "status": "already-reviewed",
            "error": "该学生已是「已批阅」；如需覆盖请加 force"}
```

即：**默认跳过已批阅，`force=True` 才覆盖**。这个语义是对的，但当前实现有 3 个缺口：

| # | 缺口 | 后果 |
|---|---|---|
| G1 | 只按平台行状态判断，未与**本地草稿版本/报告版本**对照 | 平台被同事改过、或本地是新报告，仍然静默跳过或盲目覆盖 |
| G2 | 批量的 `--from-drafts` 只输出最后一行 JSON，`already-reviewed` 的跳过项不汇总 | 教师只看到“上传完成”，不知道谁被跳过 |
| G3 | 覆盖前没有把“平台当前分数/批语”与“将写入的内容”做差异记录 | 覆盖后无法回溯，争议时无据 |

**建议口径**（待实现）：
1. 未批阅 → 直接上传（现状行为，保持不变）；
2. 已批阅 → 先 `read_back(page)` 读平台当前分数/批语，与本地草稿比对：
   - 分数与批语**一致** → 记为 `unchanged`，跳过（不打扰教师）；
   - **不一致** → 记为 `conflict`，需教师确认后才覆盖（`force` 仅用于“我确认覆盖”的显式点击），
     并在上传清单里记录 `platformBefore`（分数 + 批语摘要，非全文）；
3. 汇总输出 `applied / unchanged / skipped / conflict / failed` 五类，前端逐类展示。

## 3. 报告文件名加时间戳 + 版本号？

现状：`grading/<taskId>/reports/<学生>.md|.html|.png`，**同名覆盖**；
版本信息只有页脚 `__version__`（引擎版本），不是报告版本。

教师诉求（加时间戳便于对照）与“新版覆盖旧版”其实**不冲突**，建议二者兼得：

### 3.1 推荐方案：内容版本 + 固定“最新”指针（而不是只靠文件名）

```text
grading/<taskId>/reports/
  <学生>.md / .html / .png                 ← 始终指向“当前最新”（覆盖写，前端零改动）
  .versions/<学生>/20261118-140302-ab12cd.md/.html/.png   ← 历史版本（内容哈希后缀）
  .versions/index.json                     ← [{student, version, ts, kind, sha256, reason}]
```

- **版本号 = 内容哈希前 6 位**（`sha256(md)[:6]`），天然幂等：
  内容没变就不会产生新版本，避免“每点一次生成就多一份”；
- `index.json` 记录 `ts / student / kind(ai|human|ai-revised)/ score / sha256 / 触发原因`；
- 草稿 JSON 增字段 `report: {version, sha256, generatedAt, file}`（与上传清单共用）；
- 报告页脚显示：`v20261118-140302-ab12cd`，教师可在报告与上传清单里对上号。

### 3.2 为什么不全用“文件名带时间戳”

- 文件名一改，**前端、上传、报告预览、历史引用全部要跟着改路径**，回归面大；
- 每次生成都产生新文件，磁盘很快膨胀，且教师看到的“报告列表”里出现一堆近似重名；
- 版本号是**内容**的属性，不是时间的属性：同一内容重复生成不应该算新版本。

### 3.3 上传时如何“对照”

上传清单 `upload/<workId>.json` 增加：

```json
{"student": "学生甲", "reportVersion": "ab12cd", "reportFile": "学生甲.png",
 "score": 8, "platformBefore": {"score": 7, "commentLength": 42},
 "decision": "overwrite|skip-unchanged|conflict|new"}
```

前端在「上传全部」前展示一张对照表：学生 | 本地版本 | 本地分数 | 平台状态 | 平台分数 | 决定。
教师确认后才 `send`，这样“新版覆盖旧版”是**显式**动作，而不是盲写。

## 4. 结论

- **编码报错**：已修复（D193），报告已生成但上传中断的问题不再出现；
- **是否要检查已批阅**：要，且应升级为“比对分数+批语+报告版本”的三态判断（§2）；
- **报告加时间戳**：建议改为**内容哈希版本 + `.versions/` 历史 + 固定最新文件名**（§3.1），
  比“文件名加时间戳”更稳、回归面更小；
- **新版覆盖旧版**：保留覆盖语义，但先在对照表里显式确认，并记录 `platformBefore`。

## 5. 范围与实施

已实施（本次）：
- `engine/src/assist/serve.py`：`_xxt_env` UTF-8 环境、`Popen` UTF-8 解码；
- `engine/src/assist/cli.py`：`_force_utf8_output()`、修复 3.12+ 多行 f-string；
- 测试：`engine/tests/test_d193_unicode_console_and_fstring.py`（8 项）。

待确认后实施（§2/§3）：已批阅三态比对、报告版本索引、上传对照表。

## 6. 验收（已实施部分）

| # | 场景 | 期望 |
|---|---|---|
| 1 | 批语含 `−`、emoji，Windows GBK 控制台 | 不抛 UnicodeEncodeError |
| 2 | 子进程输出 | 父进程按 UTF-8 解码，无乱码 |
| 3 | 直接命令行运行 CLI | 入口强制 UTF-8 |
| 4 | Python 3.11 语法 | 源码可解析（无 3.12+ 多行 f-string） |
| 5 | 回归 | 全量 pytest 通过（1747 passed） |
