# D206：真实学习通平台实测（登录 → 演练 → 真提交 → 核验 → 还原）

> 日期：2026-11-19
> 状态：**已完成（2026-11-19）**
> 关联：`docs/145-D202-upload-verification.md`、`docs/146-D203-submit-confirmation-click.md`、
> `docs/147-D204-submit-session-and-dryrun.md`、`docs/148-D205-e2e-mock-upload-test.md`
>
> 隐私：本文不记录学生姓名、批语正文、作答内容；学生信息仅在本地 workspace 内。

---

## 0. 为什么必须做这次实测

D202–D205 全部基于**本地仿真页**验证。仿真页能证明逻辑，但不能证明真实页面结构。
本次用教师扫码登录真实学习通，在**白名单课程**「大学物理知识点拾遗（by pc）」
完成了一次真实上传/打分/核验，并把平台状态还原。

## 1. 实测环境

| 项 | 值 |
|---|---|
| 登录方式 | `assist xxt login` 扫码（headless 出码，教师手机扫） |
| 会话结果 | `verdict=alive`，可正常进入课程工作台 |
| 课程 | 大学物理知识点拾遗（by pc），courseId `217801417` |
| 班级 | 默认班级，classId `40009084` |
| 作业 | 「大学物理作业纸提交（测试）」，workId `56864879` |
| 白名单 | 临时 workspace 内 `xxt.write_allowlist` 加该 course:class |

## 2. 实测结果

### 2.1 既有状态（确认此前测试确实写成功）

| 项 | 值 |
|---|---|
| 平台分数 | `100` |
| 批语长度 | 233 字符 |
| 批语图片 | 2 张 |

→ 说明上一轮“上传图片做批语 + 改分”**真的落库了**，不是假成功。

### 2.2 演练（`send=false`，只填不提交）

- 结果 `status=dry-run-filled`；
- `#tmpscore` 回读 = 期望分；
- 批语图片从 2 张 → 3 张（新图插入成功）；
- 未提交 → 事后复查平台仍为原状态（2 张图、233 字）。

### 2.3 真提交（改分 → 核验 → 还原）

| 步骤 | 结果 |
|---|---|
| 第 1 次（改分 88） | ❌ `unverified`；提交按钮未找到 |
| 定位原因 | 真实提交按钮是 **`<div class="btnBlue fr fs14" onclick="markAction(1)">Submit</div>`**（也可能是 `<a>`），旧选择器只找 `a,button`；且界面为**英文** |
| 修复后（还原分数 100） | ✅ `ok=true`，`submitResult={text:"提交", tag:"A", cls:"btnBlue fr fs14"}` |
| 提交后核验 | ✅ 列表回读分数 `100`（与期望一致） |
| 最终平台状态 | 分数 `100`、批语 233 字、2 张图 —— **已还原** |

## 3. 真实平台与仿真的三处差异（已修）

### A. 提交按钮不是 `<a>/<button>`

```html
<div class="btnBlue fr fs14" onclick="markAction(1)">Submit</div>
```

修复：`_JS_CLICK_SUBMIT` 改为 `document.querySelectorAll('[onclick]')` 再筛
`markAction\(1\)`，并补充“文案为 Submit/提交”的退化路径。

### B. 界面可能是英文

`Submit` / `Submit and proceed to the next` / `Unreview`。
修复：兜底排序与确认按钮文案同时接受英文
（`submit|save`、`ok|confirm|yes|submit`）。

### C. 批阅列表行有时不渲染状态文本

实测列表 `status` 为**空串**，但分数已保存为 100。
旧核验只认「已批阅」→ 会把成功判成失败。

修复：`verify_submission` 判定顺序改为
1. 状态文本**明确**未批阅（`待批阅`/`Unreview`）→ 失败；
2. 分数与期望不符 → 失败（报“分数不一致”）；
3. 状态为空但分数与期望一致 → **通过**，并记 `note` 说明。

## 4. 测试

新增 `engine/tests/test_d206_real_platform_dom_quirks.py`（8 项）：

- `DIV` 提交按钮 + 英文界面 + 列表无状态文本 → 端到端必须成功；
- 状态为空但分数一致 → 通过并带 note；
- 状态为空且分数不符 → 失败；
- 英文 `Reviewed` → 通过；`Unreview` → 失败；
- 源码契约（`[onclick]`、英文文案、状态解析）。

全量 pytest：`1877 passed`。

## 5. 复测建议（教师本机）

1. 「🔁 重新扫码登录」；
2. 「🔍 上传前对照」→ 选学生 → **「演练」**（只填不提交）；
3. 通过后 → **「上传」**（真提交 + 提交后核验）；
4. 学习通确认分数与批语；若列表不显示状态文本，以**分数**为准。

## 6. 隐私与安全

- 登录 storage、二维码、批语截图、receipts 全部在 `.scratch/real-login/`（`.gitignore` 已忽略）；
- 本文与提交内容不含学生姓名/批语正文/作答图片；
- 实测只改动 1 名学生的**分数**（100 → 88 → 还原 100），批语内容未改动；
- 演练插入的测试图**未提交**，平台批语图片数保持 2 张。
