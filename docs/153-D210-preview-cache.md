# D210：上传前对照改为「本地缓存 + 手动刷新平台状态」

> 日期：2026-11-19
> 状态：**已完成（2026-11-19）**
> 关联：`docs/152-D209-real-confirm-chain.md`、`docs/151-D208-upload-code-review.md`
>
> 隐私：缓存只含学生名/状态/分数/批语长度，不含批语正文、cookie、token。

---

## 0. 为什么要缓存

读取平台状态需要：打开批阅列表 + 对**每个已批阅学生**打开批阅页读回内容。
真机实测：1 个学生的对照就要 **21.7 秒**；几十人的班级会到分钟级。

而教师通常连续多次查看对照表（改分前后、上传前后），重复读取非常浪费。

## 1. 设计

### 缓存位置

```
<ws>/<classDir>/grading/<taskId>/upload/preview-<workId>.json
```

与上传清单同目录，便于一起备份/清理。

### 缓存内容

```json
{
  "version": 1,
  "courseId": "...", "classId": "...", "workId": "...",
  "taskId": "...", "classDir": "...",
  "fetchedAt": 1763..., "fetchedAtText": "2026-11-19 23:45:00",
  "fingerprint": "本地内容指纹",
  "platformRows": [{"name","status","score","workAnswerId"}],
  "perStudent": {"学生甲": {"score","commentLength","commentImages"}}
}
```

**不含**批语正文、cookie、token。

### 命中规则

| 条件 | 行为 |
|---|---|
| 缓存存在且 `age <= 30min` 且本地未变 | 直接返回缓存结果（`cache.hit=true, stale=false`），**不开浏览器** |
| 缓存存在但**本地批语/分数/报告版本变了** | 仍用缓存的**平台快照**重新判定（秒开），标 `stale=true` 并提示刷新 |
| 缓存过期（>30min） | 重新实时读取 |
| 点「🔍 重新读取平台状态」 | 强制实时读取（`force=true`） |
| 上传任务启动 | **自动删除缓存**（平台状态即将变化） |

本地内容指纹 = 学生 / 分数 / 批语哈希 / 报告版本 / 图片数 的 SHA256 前 16 位。

## 2. 真机实测

| 操作 | 耗时 | 结果 |
|---|---|---|
| 强制实时读取 | **21.7s** | `hit=false`，状态 `已完成`，分数 88 |
| 再次打开对照（命中缓存） | **0.00s** | `hit=true`，`stale=false` |
| 本地改分后再打开 | 0.00s | `hit=true`，**`stale=true`**，按新分数重判 |
| 缓存 `stale` 时的决策 | — | 状态 `已完成` + 本地 95 → **`conflict`（需确认）** |

## 3. 顺带修掉一个真实缺陷（D210-FIX）

`grade_plan.decide()` 原来判断“已批阅”只认中文 **“已批阅”**：

```python
reviewed = "已批阅" in str(status or "")
```

真实平台状态是 `已完成 / Completed / Completed（教师提交）/ Reviewed` →
被判成**未批阅** → 直接 `new` → **跳过覆盖确认，静默覆盖平台已有批阅**。

修复：`decide()` 与 `verify_submission()` 统一使用
`grade_plan.is_reviewed_status()` / `is_pending_status()`，覆盖：

- 已批阅类：`已批阅 | 补交 | reviewed | completed | 完成 | 教师提交`
- 未批阅类：`待批阅 | unreview | 未完成 | unsubmitted | to be reviewed`

真机复验（缓存命中 + 本地改分）：

```
status: 已完成 | platformScore: 88.0
decision: conflict | needsConfirm: True   ✅
```

## 4. 前端交互

- 「🔍 上传前对照（含平台状态）」→ 优先用缓存（秒开）；
- 「🔍 重新读取平台状态」→ 强制刷新（`force=true`）；
- 对照表顶部显示缓存来源：

```
📦 平台状态来自本地缓存（2026-11-19 23:45:00，3 分钟前；有效期 30 分钟）。
   如需最新状态请点「🔍 重新读取平台状态」。
```

- 本地内容变化时变黄提醒：

```
⚠ 本地批语/分数/报告版本已变化（已按最新本地内容重新判定）；
   如需最新平台状态请点「重新读取平台状态」。
```

## 5. 测试

新增 `engine/tests/test_d210_preview_cache.py`（13 项）：

- 缓存路径/作用域校验；指纹随本地内容变化；
- **命中缓存不启动浏览器**；过期缓存触发实时读取；`force` 绕过缓存；
- 本地内容变化 → `stale=true` 且按新内容重判；
- 上传后 `invalidate_cache` 生效；坏缓存安全忽略；
- `decide()` 对 `已完成/Completed/...` 判 `conflict`，对 `待批阅/To be reviewed/Unreview` 判 `new`。

全量 pytest：`1913 passed`。

## 6. 边界

- 缓存只表示“平台状态是 X 分钟前的”，不是实时；需要实时请手动刷新；
- 若上传后缓存未失效（例如上传在另一台机器），下次对照可能短暂显示旧状态（可用强制刷新）；
- 缓存文件在 `upload/` 目录，属本地产物，不随代码库提交。
