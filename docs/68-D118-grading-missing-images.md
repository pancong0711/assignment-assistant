# D118 缺陷修复：AI 批阅报 `FileNotFoundError [WinError 3] …\images`

> 日期：2026-10-28
> 状态：已实现并验证
> 关联：`docs/05-D86`（批阅流程）、`docs/32-D80`（批阅测试）、`docs/16`（学习通下载）

## 1. 现象

```
❌ AI 批阅失败：FileNotFoundError: [WinError 3] 系统找不到指定的路径。:
'D:\BaiduSyncdisk\toolsPy\2609assignment\grading\202610-chap05-811\images'
```

用户确认：**该文件夹下确实没有图片**。

## 2. 根因

两层问题叠加：

### 2.1 直接原因：`group_images()` 不判空目录

`engine/src/assist/grading/transcribe.py`：

```python
for f in sorted(Path(images_dir).iterdir()):   # ← 目录不存在 → FileNotFoundError
```

目录不存在时直接抛 `FileNotFoundError`，Windows 上就是 `[WinError 3]`。

### 2.2 为什么走到了这条 fallback

`flow.py::_run_transcribe`：

```python
plan_groups = _plan_student_images(ctx) if ctx.get("plan") else {}
if plan_groups:
    groups = plan_groups            # 有图的学生
else:
    images_dir = ctx["images_dir"]  # ← 一名学生都没图时，反而去 iterdir 默认目录
    groups = group_images(images_dir)
```

`_plan_student_images()` 只返回**有图片的学生**。
当**所有学生都没有图**（尚未从学习通下载作答图）时，`plan_groups` 为空 →
错误地回退到 `ctx["images_dir"]`（`grading/<class>/<work>/images`，从未创建）→ 抛异常。

### 2.3 为什么下载目录是空的

作答图需要先在「作业预览-学习通」对某次作业点「⬇ 下载作答/批语」，
才会落到 `<ws>/grading/<班级>/<作业>/images/`。AI 批阅面板**从未提示这是前置条件**，
用户直接点「开始 AI 批阅」就会撞上这个报错，而错误信息只有一个 Windows 路径堆栈。

## 3. 修复

| 层 | 修改 |
|---|---|
| `transcribe.group_images()` | 目录不存在 → 返回 `{}` 并 `logger.warning`（不再抛异常） |
| `flow._run_transcribe()` | plan 模式下"**一名学生都没图**"→ 抛 `GradingInputError`（可读文案），**不再**静默回退到不存在的目录 |
| `flow.GradingInputError` | 新增输入侧业务异常（与 `RuntimeNotFoundError` 区分） |
| `cli.grade` | 捕获 `GradingInputError` → `click.ClickException`（可读错误，无堆栈） |
| `serve._grade_preflight()` | `/xxt/grade/ai-run` **启动 job 前**先装配 plan 做体检：0 人有图 → 直接 400 + 可读错误 + 下一步指引 |
| PWA | 无需改动（`startAi` 的 catch 已把错误写入进度条） |

## 4. 修复后的用户体验

前端直接显示：

```
❌ AI 批阅失败：没有任何学生有作答图，AI 批阅无法开始。
请先到「作业预览-学习通」对该作业点「⬇ 下载作答/批语」，再回到本页重试。
```

而不再是 `FileNotFoundError [WinError 3]`。

## 5. 验证

| 项 | 结果 |
|---|---|
| `group_images(不存在目录)` | 返回 `{}`（原：`FileNotFoundError`） |
| `group_images(正常目录)` | 仍按文件名前缀正确分组（2 人 3 图） |
| plan 模式 0 人有图 | `GradingInputError`，文案含"没有任何学生图片"+"下载"+"images" |
| CLI `grade` | 输出可读错误（`ClickException`），**无 Python 堆栈** |
| `POST /xxt/grade/ai-run` | **HTTP 400** + `{"error":"没有任何学生有作答图…","detail":{students,withImages,hint}}` |
| engine pytest | **636 passed**（新增 `test_d118_grading_missing_images.py` 5 例） |

## 6. 执行中发现的连带问题

| # | 问题 | 说明 |
|---|---|---|
| N1 | `serve._grade_preflight` 首版**静默失效** | `except Exception: logger.debug(...)` 把内部错误吞了，体检等于没做。改为 `logger.warning(..., exc_info=True)`，并用真实 HTTP 请求验证到 400 |
| N2 | 体检参数传错 | 把 `pads`（list）当目录传给 `tasks_dir`；改为从 `args` 里取 `--pads-dir` 的真实路径 |
| N3 | 测试数据踩坑 | `students_with_tags()` 找的是 `<class_dir>/roster/roster.xlsx`（**子目录**），不是 `<class_dir>/roster.xlsx` |

## 7. 给教师的最短操作路径

1. 「作业预览-学习通」→ 选中作业 → 点 **⬇ 下载作答/批语**（等完成）
2. 回到「AI 辅助批阅」→ 选同一作业 → 点「▶ 开始 AI 批阅」
