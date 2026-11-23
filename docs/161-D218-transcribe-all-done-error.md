# D218 修复：全班已有转写时点「转写+批阅」报 `items 必须是非空数组`

> 日期：2026-11-23
> 状态：**已完成（2026-11-23）**
> 关联：`docs/112-D168`（口径）、`docs/120-D177`、`docs/159-D216`
>
> 隐私：测试只用合成数据。

---

## 0. 现场

整班（非逐生）点击「转写+批阅」报：

```text
❌ AI 转写+批阅失败：assist.grading.items.ItemsError: items 必须是非空数组。
```

## 1. 根因

`grading/flow.py :: _run_transcribe()`：

```python
if not ctx.get("force"):
    groups = {stu: imgs for stu, imgs in groups.items()
              if not (transcripts_dir / f"{stu}.json").is_file()}   # 跳过已有转写
    ...
items = normalize_items([...])   # ← groups 为空时 items=[] → ItemsError
```

当**全班都已有转写**（典型：第二次点「转写+批阅」，且没勾「强制重做」）时，
过滤后 `groups` 为空 → `normalize_items([])` 抛错 → 整个任务失败。

**本质**：这是“无需转录”的正常状态，却被当成非法输入。

## 2. 修复

过滤后若 `groups` 为空：

```python
logger.info("[转录] 全部学生都已有转写，本次跳过转录（要重跑请用「强制重做」）")
return []
```

后续步骤（评阅/报告）照常继续：

- 已有评阅结果的学生会被 `_run_evaluate` 跳过（除非强制重跑）；
- 只有缺评阅结果的学生会被补评。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 全班已有转写、未勾强制重做 | 跳过转录，**不报错**，继续评阅 |
| 2 | 部分学生缺转写 | 仍对缺的学生尝试转录（不整体跳过） |
| 3 | 勾选「强制重做」 | 不跳过，重新转录 |
| 4 | 回归 | 全量 pytest `1980 passed` |

## 4. 测试

`engine/tests/test_d218_transcribe_all_done.py`（4 项）：

- 全班已有转写 → `_run_transcribe` 返回 `[]` 且不抛 `ItemsError`；
- 部分缺失 → 仍尝试转录（`chat_with_images` 被调用）；
- `force=True` → 不被“已有转写”跳过；
- 源码契约。

## 5. 说明：这与「强制重做」的关系

| 你想做的事 | 操作 |
|---|---|
| 只补没转写/没批阅的人 | 直接点「转写+批阅」（现在会安全跳过已完成的人） |
| 全部重跑（重新花额度） | 勾选「强制重做」再点「转写+批阅」 |
| 只补某个学生 | 逐生行内点「转写+批阅」 |
