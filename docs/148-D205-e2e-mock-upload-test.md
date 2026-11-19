# D205：用本地仿真批阅页端到端验证「上传图片 + 打分 + 提交 + 核验」

> 日期：2026-11-18
> 状态：**已完成（2026-11-18）**
> 关联：`docs/145-D202-upload-verification.md`、`docs/146-D203-submit-confirmation-click.md`、
> `docs/147-D204-submit-session-and-dryrun.md`
>
> 隐私：仿真页只用合成数据（学生甲），不连接真实学习通、不使用真实学生数据。

---

## 0. 为什么需要这个测试

真实平台上“点了上传但没生效”的问题反复出现（D202/D203/D204），
而本机**没有可用的课程工作台会话**（打开批阅页会被跳 `passport2.chaoxing.com`，
见下方探测结果），无法在真实平台回归。

因此搭建**本地仿真学习通批阅页**，用真实代码路径跑通全流程：

```text
本地会话探测（只读）：
  check_session  → verdict=alive（个人空间）
  mooc1 工作台    → 302 → passport2.chaoxing.com/login（课程工作台已失效）
```

## 1. 仿真页与真实页面的对应关系

| 真实页面元素 | 仿真页实现 | 被验证的真实代码 |
|---|---|---|
| `textarea[name="comment"]` | 同名 textarea | `set_comment_html` / `read_back` |
| `.kark_comment_edit` + `.edui-editor` | 同名容器 | `_JS_REVEAL_TOOLBAR` |
| `.edui-for-insertimage .edui-button-body` | 同名按钮 | `_JS_CLICK_INSERTIMAGE` |
| insertimage iframe（`dialogs/image`）+ `input[type=file]` | 同名 iframe | `_image_dialog_frame` / `upload_comment_image` |
| `#tmpscore` / `.inputBranch.questionScore` | 同名输入框 | `fill_scores` |
| `a[onclick="markAction(1)"]` | 同名 | `_JS_CLICK_SUBMIT` |
| `#tabindexWorkpop` + `#popok` / `confirmPiyueWork()` | 两种变体都有 | `handle_confirmation_dialog` |
| `ul.dataBody_td` + `div.py_name` + `a.cz_py` | 同名结构 | `_students_from_mark_list` / `verify_submission` |

## 2. 测试场景（`engine/tests/test_d205_upload_e2e_mock_markpage.py`）

| # | 场景 | 断言 |
|---|---|---|
| 1 | 插图 + 批语 + 90 分 + 提交 | `ok=true`；批语里确有 `<img>`；平台保存分数 90；`afterSubmit.status=已批阅`、`score=90` |
| 2 | 确认按钮**只有** `confirmPiyueWork()`（无 `#popok`） | 仍成功；`clicks[0].how=onclick:confirmPiyueWork` |
| 3 | 第一次确认失效（未保存）→ 重试 | 会**重新打开批阅页并重填**；`submitAttempts` 长度 2；最终成功 |
| 4 | 批阅页变成登录页 | `submit.status=session-expired` 且提示重新扫码 |

运行：

```bash
PYTHONPATH=engine/src .scratch/venv/bin/python -m pytest \
  engine/tests/test_d205_upload_e2e_mock_markpage.py -q
# 4 passed
```

## 3. 测试中发现的真实缺陷（已修）

### A. 重试在错误页面上提交

D203 引入的“未生效重试一次”直接原地再点提交，但上一轮 `verify_submission`
已把页面导航到**批阅列表**——那里没有提交按钮，于是报
`未找到提交按钮：no-markAction(1)`（正是现场那条报错）。

修复：重试时 `_open_and_check()` 重新打开批阅页 → `_fill_page(first=False)`
重新传图/写批语/打分 → 再提交。

### B. 确认弹窗被重复点击

弹窗点击后若未立即关闭（导航/请求中），旧循环会反复点“确定”，
可能重复提交或打断请求。修复：记录已点击弹窗 key，同一弹窗只点一次；
仍未关闭则返回 `stillOpen` 与平台提示。

## 4. 仿真测试的边界（必须说明）

- **不覆盖**真实学习通的 UEditor/WebUploader 细节、跨域上传限制、服务端校验规则；
- **不覆盖**真实平台的“分数上下限/必填项/防重复提交”等业务校验；
- 真实环境仍需教师用「演练」按钮验证一次（只填不提交）。

## 5. 真实平台复测建议流程

1. 「🔁 重新扫码登录」→ 确认头像与体检 alive；
2. 「🔍 上传前对照」→ 目标学生 → **「演练」**（只填不提交）；
3. 演练通过 → **「上传」**（真提交 + 提交后核验）；
4. 学习通确认该生「已批阅」且分数正确；
5. 若失败，把 `upload/<workId>.json` 的 `submitAttempts` / `afterSubmit` /
   `submitCandidates` 与 `receipts/grade-upload-submitted*.png` 留证。

## 6. 验收

- 新增 `test_d205_upload_e2e_mock_markpage.py`（4 项，约 30s；无浏览器时自动 skip）
- 全量 pytest：`1869 passed`
- `selfcheck:d188–d205` 全部通过；前端 build 通过
- 脱敏检查、`git diff --check` 通过
