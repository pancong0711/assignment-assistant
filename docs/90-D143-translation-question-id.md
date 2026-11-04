# D143 需求单：翻译题库题号重复（`translation` × N）

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/78-D130`（D111 题号唯一）、`docs/46-D93`（translation 合成题）、`docs/12`

## 0. 现象

AI 作答参考答案时，日志告警：

```
题库 translation 存在重复题号（1 个）：
translation@translation/translation/translation/…（×16）；请用 `assist kb normalize` 检查
```

## 1. 根因

`files/kb_io.py: read_translation()` 在逐行构造题目条目时**写死了同一个 id**：

```python
entries.append({"id": "translation", "content": tmp, "img_path": None})
```

于是 N 行翻译题 = N 条同号题目。

**这不只是告警**：答案版本库以 `qid` 为键（`solutions/<scope>.json`），
多道翻译题的答案会写进**同一个文件互相覆盖**——真实的静默数据损坏。

## 2. 修复

按**行序**生成稳定唯一题号，命名风格与其它题库一致（`<sheet名>-<题号>`）：

```
translation-01, translation-02, …, translation-16
```

- 行序稳定 → 重读题号不变（答案不会对错题）；
- 空行跳过但编号**连续**（不留空洞，避免教师以为丢题）。

## 3. 明确不改的部分

`paper/task.py` 里"每份作业纸只放**1 道**翻译题"的逻辑（`TRANSLATION_ID not in seen_ids`）
是 **D93 刻意保留的旧代码语义**（`docs/46 §2`：从 `translation.xlsx` 随机抽一行），
本轮**不动**。

## 4. 验收

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 16 行 → 16 个唯一题号 | ✅ | `test_translation_ids_are_unique` |
| 2 | 不再出现"重复题号"告警 | ✅ | `test_no_duplicate_warning` |
| 3 | 命名风格与其它题库一致 | ✅ | `test_translation_id_format_matches_other_kinds` |
| 4 | 两次读取题号一致（答案不会对错题） | ✅ | `test_translation_ids_stable_across_reads` |
| 5 | 空行不留编号空洞 | ✅ | `test_blank_rows_do_not_create_gaps_confusingly` |
| 6 | 不同翻译题答案落到不同文件 | ✅ | `test_translation_answer_files_do_not_collide` |

验证：pytest **1156 passed** · build 0 error · selfcheck **30/30** · 脱敏通过。

## 5. 已知影响（重要）

修复前，所有翻译题的答案都写进了同一个 `translation` 作用域文件，
**后写的覆盖先写的**——历史上保存过的翻译题答案已经无法区分属于哪一题。

- 修复后新生成的答案会正确分文件；
- 历史残留的 `translation` 单文件**保留不动**（可人工查看），
  但无法自动还原到具体题号；
- 若教师此前用 AI 批量作答过翻译题，建议**重新作答一次**。
