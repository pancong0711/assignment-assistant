# D165 需求单：跨班发布被误判「已发布，禁止重新发布」

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/95-D148`（同批修复）、`docs/12`

## 0. 现象

在同一课程**其他班**发布过、但目标班**没发过**的作业，点发布时：

```json
{"ok": false, "mode": "send", "runId": "...",
 "response": {}, "responseText": "", "requests": [], "responses": []}
```

页面提示「已发布，禁止重新发布」。

## 1. 根因

发布设置页 URL **只带 `courseid`，不带 `clazzid`**：

```python
url = (f".../work/library/setting"
       f"?courseid={course_id}&cpi={cpi}&workLibraryId={work_library_id}"
       f"&fromCreate=1&from=")          # ← 缺 clazzid
```

平台因此按**课程**维度判断"该作业库条目是否已发布"——同课程任一班级发过就拒绝。

**佐证**：同文件的其它 URL 全都带 `clazzid`：

| 用途 | 是否带 clazzid |
|---|---|
| 已发布列表 `class_works_url` | ✅ |
| 作业库列表 `list_folders` | ✅ |
| 作业详情 | ✅ |
| **发布设置页** | ❌ ← 遗漏 |

**第二佐证**：报错里 `requests: []`、`responses: []` —— AJAX **根本没发出**，
说明是**平台前端**的前置校验拦下的，与"页面显示禁止重复发布"完全吻合。

## 2. 修复

### 2.1 URL 带 clazzid（主修）

```python
url = (f".../work/library/setting"
       f"?courseid={course_id}&clazzid={targets[0]}&cpi={cpi}"
       f"&workLibraryId={work_library_id}&fromCreate=1&from=")
```

多班时平台本身支持"发放对象"多选；`clazzid` 用于**前置校验的上下文**（取第一个目标班）。

### 2.2 重复校验改为逐班

此前只查 `targets[0]`，多班时漏检其它班：

```python
already = []
for cid in targets:
    pub = published_library_ids(storage, course_id, cid, cpi)
    if work_library_id in pub:
        already.append(cid)
if already:
    return {"ok": False, "error": f"该作业已在班级 {already} 发布过…"}
```

**报错要指明具体班级**，而不是笼统"禁止重复发布"。

### 2.3 失败时带出页面提示

新增 `pageHint`：抓取点击「发放」后的页面提示文字（layer 弹层 / 提示条 / 关键词兜底）。

若**一个请求都没发出**，明确提示：

> 点击「发放」后没有发出任何请求：通常是平台前端校验未通过
> （如「已发布，禁止重新发布」）。请查看截图确认提示文字。

## 3. 验收

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 发布 URL 带 `clazzid` | ✅ | `test_publish_url_includes_clazzid` |
| 2 | 对照组：其它 URL 一直带（证明是遗漏） | ✅ | `test_other_urls_also_have_clazzid` |
| 3 | 重复校验逐班 | ✅ | `test_dup_check_is_per_class` |
| 4 | 失败带 `pageHint` | ✅ | `test_failure_carries_page_hint` |
| 5 | 无请求时提示"前端校验未通过" | ✅ | `test_no_request_means_frontend_blocked` |
| 6 | pytest / build / selfcheck / 脱敏 | ✅ | **1298 passed** · 0 error · **35/35** |

## 4. 局限（重要）

- 本机**无法验证学习通真实行为**（没有账号/环境）。本次修复基于
  "URL 差异 + 报错里 requests 为空"的推断，**需要实测确认**；
- 若仍失败，`pageHint` 会给出页面实际提示文字，可据此继续定位。
