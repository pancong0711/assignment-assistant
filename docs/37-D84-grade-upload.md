# D84 任务需求单：批阅回传（设为已交 + 评语/图片上传 + 打分）

> 日期：2026-10-15
> 状态：需求确认，按下面顺序**逐步执行**（每步完成即更新本文进度表）。
> 关联：`docs/32-D80-grade-upload-collab-test-plan.md`（§3.4 上传待实现）、
> `docs/16-xuexitong-integration.md`（批阅回传冻结条款）、`docs/31-D79...`（写操作白名单模式）、
> 遗留实现 `_legacy/2601playwright/src/uploader.py` + `submit_v3.py`（已真机跑通的蓝本）。
> 目标班级（白名单内）：大学物理知识点拾遗 / 默认班级 `217801417 / 40009084`。

## 1. 目标与范围

把本地 `assist grade` 两步批阅的产物（评语/分数/报告图）**回传**到学习通批阅页，
并支持测试所需的"先把一份作业设为已交"。

- **A. 设为已交**（教师侧写操作）：把某个「未交」学生置为已交，用于补交/测试；
- **B. 批阅上传**：批阅页写入
  - 作业批语（富文本，文字 + 图片）；
  - 题目批语（可选，按题）；
  - 每题分数 + 总分；
  - 提交（`markAction(1)`）并处理确认弹窗。

两项都：**写操作白名单** + **默认 dry-run** + receipt + journal。

## 2. 现状与依据

- 引擎已有**只读**批阅链路：`assist xxt review-download`（作答图片 + 两栏批语 +
  `workAnswerId` + 分数，落 `students.json`）、`assist xxt review-probe`；
- 引擎**没有**上传命令：`assist grade` 的 `STEPS` 含 `download/upload` 但都是
  `TODO(stage4)`；执行 `grade --rerun upload` 直接报"阶段4（TODO）"；
- 遗留蓝本（2026-01 真机跑通）：
  - `uploader.py`：显示隐藏的批语 UEditor 工具栏 → `insertimage` 弹窗上传评语图 →
    `fill_question_scores`（`.inputBranch.questionScore`）→ `fill_total_score`（`#tmpscore`）
    → `click_submit`（`markAction(1)`）→ `handle_confirmation_dialog`（`#popok/#popokTwice/#confirmPiyueWin`）；
  - `submit_v3.py`：stat2 统计页预扫描缺交 → mark 页（`submit=false&evaluation=0`）
    点「设为已交」→ 弹窗 `#submitScore` 填 0 → 点"确定" → 从 stat2 学生详情页取回新 `workAnswerId`。
- 存档批阅页 DOM（`.scratch/xxt-pages/recon-review-student.html`）与蓝本一致，已核对：
  - 作业批语 UE：`textarea[name="comment"]` → `UE.getEditor('comment<id>')`；
  - 题目批语 UE：`textarea[id^="answer"]` → `UE.getEditor('answer<qid>')`；
  - `#tmpscore` 总分、`.inputBranch.questionScore` 每题分；
  - `markAction(0/1)` 提交；`.kark_comment_edit{display:none}` 需先亮出工具栏。

## 3. 设计

### 3.1 复用与新增

| 层次 | 文件 | 内容 |
|---|---|---|
| 原语 | `engine/src/assist/xxt/marking.py`（新） | 打开批阅页 / 写批语 / 传评语图 / 填分 / 提交 / 处理弹窗（全部可选、可 dry-run） |
| 归档 | `engine/src/assist/xxt/grade_upload.py`（新） | 目标校验、幂等检查、数据装配（grading 产物 → 每生 payload）、receipt 落盘 |
| CLI | `engine/src/assist/xxt/cli.py` | `grade-upload` / `mark-submitted` 两个命令 |
| PWA | `app/src/views/XxetongView.vue` + `engineClient.ts` + `serve.py` | 批阅工作台"上传（dry-run 预览）"入口 |
| 存储 | `xxt_home()/grade-uploads/<ts>-<class>-<work>.json` + 截图 | receipt（可回查、可清理） |

### 3.2 CLI 形态

```bash
# A. 设为已交（测试/补交；默认 dry-run）
assist xxt mark-submitted --course <cid> --class <kid> --cpi <cpi> --work <workId> \
    --student <姓名|学号> [--score 0] [--confirm-send]

# B. 批阅上传（默认 dry-run；--confirm-send 才真正提交）
assist xxt grade-upload --course <cid> --class <kid> --cpi <cpi> --work <workId> \
    --student <姓名|workAnswerId> \
    [--comment "文字"] [--comment-image <workspace 内图片>]... \
    [--score 85] [--question-score 10,20,30]... \
    [--task <task.json> --run <run_id>]   # 从 grading 产物自动装配
    [--confirm-send]
```

- `--task/--run` 与手工参数二选一；`--report-png` 可显式指定评语图片；
- 未给 `--student` 时需 `--all`（默认禁用；PWA 侧逐生确认）；
- **默认 dry-run**：只打开/填入/上传图片（上传图片会产生一次媒体上传请求，但不提交批阅），
  截图 + 读回校验（`getContent()` / `#tmpscore`）。
- `--confirm-send` 为真提交；提交后截图 + 记录平台响应，落 receipt。

### 3.3 白名单与安全

- 目标班级必须命中 `settings.local.json → xxt.write_allowlist`（复用 `validate_work_target`）；
- 评语图片必须落在 workspace 内（复用 `safe_attachment_path` 思路，扩展名白名单复用
  `notice_attachment_exts`）；
- **幂等**：目标学生若已是「已批阅」状态，默认拒绝重复提交（`--force` 覆盖）；
- 所有写请求在 journal 记录 `xxt_grade_upload` / `xxt_mark_submitted`（source=cli/pwa），
  receipt 含 dry-run/真提交、分数、评语摘要、截图路径、请求计数；
- 其他班级**零写入**（白名单校验前置，校验不过直接返回 400/退出码 2）。

### 3.4 分阶段实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| §1 | 批阅页写入原语 `marking.py` | open / comment / image / score / submit / popup | ✅ 代码+单测（7 例）；真机待批阅页联调 |
| §2 | `assist xxt grade-upload`（dry-run/confirm-send、单学生） | CLI + receipt | ✅ 代码+单测（9 例）；白名单/参数守卫已验证 |
| §3 | `assist xxt mark-submitted`（设为已交） | CLI + 回读 waId | ✅ 代码；真机待已发布作业 |
| §4 | 从 grading 产物自动装配（`--task/--all`） | evaluations → payload | ✅ 代码+单测 |
| §5 | PWA 上传入口（dry-run 预览 + 二次确认） | serve 端点 + XxetongView | ⏳ 待做 |
| §6 | 文档与收口 | 本文进度表、docs/13 索引、docs/16 解冻记录 | ⏳ 收尾 |

### 3.4.1 当前阻塞（2026-10-15）

真机联调需要一份**已发布到目标班**的作业（批阅列表才会出现学生行）。当前
`217801417/40009084` 唯一在列作业 `049cd37e...` 打开批阅页返回"作业已删除！"，
其余均为未发布草稿（`publishedClasses: []`）。

**待用户确认**（发布会对学生端可见，可能带通知）：

```bash
# ① 新建一份明确的测试作业（标题带"测试/勿交"），或复用现有草稿
# ② 发布到默认班，时间窗设为已结束（最小打扰）
assist xxt work-publish --course 217801417 --class 40009084 --work-library-id <id>     --cpi 171743814 --start 2026-10-14 --end 2026-10-14 --send
# ③ 设为已交（单学生；dry-run → confirm-send）
assist xxt mark-submitted --course 217801417 --class 40009084 --cpi 171743814     --work <id> --student <姓名>            # dry-run
# ④ 上传批语+图片（dry-run → confirm-send）
assist xxt grade-upload --course 217801417 --class 40009084 --cpi 171743814     --work <id> --student <姓名> --comment "..." --comment-image <png> --score 88
```

### 3.5 验收（对齐 docs/32 §5）

- 同班同作业同学生不重复提交（幂等拒绝）；
- 上传只落在白名单班级；
- 平台侧评语/分数与本地报告一致（读回校验 + 截图）；
- receipt/journal 可回查；
- dry-run 零写（除媒体上传外不发提交请求）。

## 4. 风险

- **提交不可逆**（学生立刻可见分数）→ 默认 dry-run；首条在知识点拾遗/默认班级单学生验证；
- 「设为已交」改变学生提交状态 → 独立命令、默认 dry-run、需 `--confirm-send`；
- 平台 DOM 漂移（批语 UE id / 上传弹窗 / 确认弹窗）→ 沿用本次附件那种"可见性 + 多定位器 + JS 兜底"
  与失败截图；
- `markAction(1)` 可能触发二次确认/拦截弹窗 → 处理并记录，不盲目重试（避免重复提交）。
