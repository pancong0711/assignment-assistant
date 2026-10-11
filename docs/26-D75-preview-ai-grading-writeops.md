# 26 — D75 任务单：真实预览 + 发现作业 UI + AI 辅助评阅 + 写操作解冻方案

> 来源：2026-10-10 真机验收通过后讨论（用户 1/1.1/1.2/1.3/3 + 写权限解冻）。
> 关联：`docs/16-xuexitong-integration.md`（§7 安全幂等、§8 验收、§23 公告）、
> `docs/24 §15`（D74 实施）、`docs/25`（D74 需求单）。
> 状态：**需求整理，按下面顺序实施。**

---

## D75-1 · 真实数据预览（D72-5 收尾，优先级最高）

**目标**：提交前「所见即所发」——作业纸、批阅报告、评分/评语与将来上传的 payload 完全同源。

> 进度：D75-1a 真实批阅**列表**预览已实施（docs/24 §16）；D75-1b 单生照片/评语需先抓详情页样本。

**样本来源（本机已有，无需登录学习通）**
- `.scratch/xxt-pages/v2-review-*.html` 共 106 份 review 存档；
- 命中环班 classId：`128430077`、`153247224`、`153844506`（含已批阅数据）；
- `.scratch/xxt-20261008-184915.json` 含 `review_path` 与 `submitted_names`。
- 边界：存档只有 review HTML；学生上传图片是否已本地化需确认。若需要真实图片，
  需新增「批阅图片/附件下载」步骤（带会话），或由教师提供本地目录。

**实现分解**
1. 作业纸预览：真实班级/学生上下文 → 现有 `SheetPreviewSection`/`sheetHtml`；
2. 批阅报告预览（D64-N4）：submission 图片/转录 → 评阅 → 版式；
3. 评分汇总：每生 final score + 评语，表格与上传 payload 同源；
4. 图片缺失时的占位与错误提示（不静默成功）。

**验收**：用环班样本打开预览，作业纸/报告/评分与本地存档一致；上传 payload 可在预览中逐字段核对。

---

## D75-1b · review-probe：只读侦察（已实施，见 docs/24 §17.1）

**目的**：`review-work` 详情页可能像通知页一样用 POST AJAX 加载作答图片/批语（docs/16 §24.1 教训）。
在放开任何写权限前，先只读侦察「打开一个学生详情页需要哪些请求」。

- CLI：`assist xxt review-probe --course --class --work`（或 `--review-path`）；
- 行为：GET 放行；所有非 GET 只**记录** `(method,url)` 到 probe JSON（不继续、不写平台）；
- 同时记录 `img.ans-ued-img` 命中数、两栏批语字段是否可读；
- 产出：`xxt_home()/runs/xxt-review-probe-<ts>.json`；
- 依据 probe 结果，把详情页**只读** AJAX 加入 route 白名单，再实现下载。

---

## D75-1c · review-download：作答图片 + 两栏批语（已实施，见 docs/24 §17.2）

**参考旧代码**（`_legacy/2601playwright/src/xuexitong/homeworks.py` + `path_utils.py` + `uploader.py`）：

- 学生列表：`ul.dataBody_td` → `div.py_name`（姓名）、`a.cz_py[data]`（含 `workAnswerId`）、状态、提交时间；
- 单生作答页：`/mooc2-ans/work/library/review-work?courseid&clazzid&workId&workAnswerId`（旧版兜底 `reviewTheContentNew`）；
- 图片：`img.ans-ued-img` 等选择器，优先 `data-original`；过滤头像/编辑器图标/小图；
- 下载：`page.context.request.get(url)`（复用登录会话）；
- **作业批语**：`textarea[name="comment"]`（UEditor `edui1`）；
- **题目批语**：`textarea[id^="answer"]`（多个）/ `#ueditor_0` iframe body；
- 分数：`#tmpscore` 等（用于核对已有批阅结果）。

**命名（采用旧代码的友好命名，用户拍板）**

- 目录：`xxt_home()/pages/review/<classId>/<workId>/`；
- 图片文件：`{学生名}_{班级名}+{作业名}_pNN.{ext}`（`sanitize_filename`，沿用 `path_utils.build_image_path`）；
- 兼容：同一目录下额外写 `students.json`，记录映射与两栏批语。

**`students.json`（manifest）字段**

```json
{
  "classId": "...", "workId": "...", "courseId": "...",
  "courseName": "...", "className": "...", "workName": "...",
  "generated_at": "2026-10-10 20:00:00",
  "students": [{
    "studentId": "...", "name": "...", "workAnswerId": "...", "status": "...",
    "images": ["张三_示例班+热力学作业_p01.jpg", "..."],
    "comment": "作业批语 HTML/文本",
    "per_question_comments": ["题目1批语", "题目2批语"],
    "score": "95"
  }]
}
```

- 说明：`images[]` 记录的就是旧命名文件名；`name`/`studentId`/`workAnswerId` 做映射，
  两者同时保留，既方便用户阅读，也方便 AI 按 id 索引。

**边界**
- 只读；不调用任何写接口；
- 学生图片可能懒加载：`wait_for_selector` + 逐步滚动；
- 逐生顺序处理 + 延时 + 失败重试；每生写 `steps[]` 便于 PWA 观察。

---

## D75-1d · 批阅图片目录浏览 + 时长清理（已实施，见 docs/24 §17.3）

- 存储：`xxt_home()/pages/review/`（按班级/作业分文件夹）；
- 接口：
  - `GET /xxt/review/index`：返回目录树 `{classId, className, works:[{workId, workName, count, bytes, mtime}]}`；
  - `GET /xxt/review/file/<classId>/<workId>/<filename>`：图片预览；
  - `POST /xxt/review/prune`：按保留时长清理（默认 **6 个月**，可配）。
- PWA：新增「批阅图片」区（按班级 → 作业 折叠），展示缩略图/两栏批语/分数；
  提供「🧹 按 6 个月清理」按钮；**与「历史 run 管理」的清空/容量清理相互独立**。
- 容量：批阅图片目录大，纳入容量统计但按**时长**清理（用户拍板），不与 50MB/1000 条的 run 规则混用。

---


## D75-2 · 发现作业 UI 修正（已实施，见 docs/24 §16.1）

### D75-2a 数字含义（1.1 答复）
- 显示顺序 = **待批 / 已交 / 未交**（来自 `JS_READ`：`pending` / `submitted` / `unsubmitted`）。
- `21/21/3` = 已交 21 份、待批 21 份（尚未批阅）、未交 3 份。
- 改进：表头加「待批/已交/未交」列名或 tooltip，避免误读。

### D75-2b 跨课程列对齐（1.2）
- 原因：每个课程一个独立 `<table>`，列宽按各自内容自动计算 → 跨课程不齐；
  长作业名换行进一步放大错位。
- 方案（推荐 A）：
  - A. 所有课程合成**一张表**，课程名作为跨列分组行，列宽全局一致；
  - B. 保留分组表但统一 `table-layout: fixed` + `<colgroup>` 固定列宽。
- 多行显示：可行。列内文本 `white-space: normal; word-break: break-word`，
  操作列按钮 flex 自动换行；表头与内容用同一 colgroup 保证对齐。

**验收**：跨课程同名数列严格对齐；长作业名/多行状态下不错位。

---

## D75-3 · AI 辅助评阅（两段式 + batch + base URL）

### D75-3a 流程（仿旧代码，拆两段）
```
学生图片
  └─(LLM-1 Transcriber)─→ Markdown（题目/作答/公式/步骤；只转写不判断）
        └─(LLM-2 Grader)─→ 评分 + 评语 + 逐题依据（结构化 JSON）
              └→ 报告生成 → 人工复核 → （解冻后）回传
```
- 两次调用都**无历史**；system prompt 精简固定；
- 转写产物落盘（可复用/可审计），评阅只吃文本，不再重复传图片。

### D75-3b Token/成本策略
- 图片先压缩/裁剪；一题一图或一页一图；
- 题目/参考答案/评分标准做成共享前缀（支持 prompt caching 时复用）；
- 结构化 JSON 输出，减少往返；
- **Aliyun Batch 调用（待核实）**：DashScope batch 通常面向文本模型；**多模态批量是否支持需先验证**。
  建议：**转写（图片输入）走实时多模态**；**评阅（纯文本、输入很小）走 batch**，输入价再降约一半。
  交互式单条仍走实时接口。
- 设计 `engine/src/assist/grading/llm_batch.py`：
  - 任务 JSONL（custom_id + request）生成；
  - 提交 / 轮询 / 下载结果 / 失败重试 / 断点续跑；
  - 与单次调用共用同一 prompt 构造与解析。

### D75-3c Base URL / Provider 配置
- `settings.local.json` 增加 `llm.providers[]`：
  `{name, base_url, model, api_key_ref, batch_support}`；
- 内置默认 **Aliyun DashScope OpenAI-compatible**
  `https://dashscope.aliyuncs.com/compatible-mode/v1`；
- PWA 设置中心：下拉选择 provider，支持「+ 自定义」（名称/base_url/key/model）；
- key 只存本机（settings.local / 系统凭据），不入库；journal 只记 provider 名，不记 key。

### D75-3d 批阅细节加固（实施时逐项 review）
- 分数口径/权重/总分；单题分与总分一致性；
- 评语模板、语气、长度；缺交/白卷/异常图片处理；
- 图片顺序与题目绑定；同名/多页归并；
- 失败重试、幂等、人工复核覆盖点；
- 报告导出格式（HTML/JSON/CSV）。

**验收**：以环班已批阅样本回放：转写正确率可复核；评分与人工分对比有差异说明；
batch 任务可提交/下载；base URL 可切换 Aliyun 与自定义并持久化。

---

## D75-4 · CLI 直跑操作记录（已实施）

- CLI `check/extract/discover/discover-works/login/run import` 均写 journal，`source=cli`；
- serve 套壳子进程注入 `ASSIST_NO_JOURNAL=1`，避免 PWA 侧重复记录；
- 单测：`engine/tests/test_xxt_cli_journal.py`（CLI 直跑写入 / serve 环境跳过）。
- 待真机验证：直接终端跑 `assist xxt extract ...`，PWA「操作记录」应出现 `source=cli` 记录。

---

## D75-5 · 写操作解冻方案（先设计 + dry-run，不直接提交）

**结论**：写操作按「逐个操作、分阶段」解冻，不做一次性放开。

**准入门槛**
1. D75-1 真实预览完成（所见即所发）；
2. D74-8 新鲜度预判接入写操作入口；
3. 按操作的最小权限 route 白名单（公告域 / 上传 CDN）；
4. 写会话独立 context；发送前快照（payload JSON + 截图）；
5. 双确认 UI；幂等键 + 限流 + 失败重试；回滚/撤回路径；
6. journal 记录写 payload（去敏）与结果；
7. 指定「特殊测试课程/班级」（建议无真实学生）。

**阶段**
- P0：dry-run 框架（只生成 payload + 截图，不提交）；
- P1：测试班发一条测试公告（可删除撤回）；
- P2：作业纸附件 / 发作业；
- P3：批阅报告上传；
- P4：打分回写（最高风险，单生 → 批量）；
- P5：特殊课程 → 本学期课程 → 全量，每步人工确认。

**待教师拍板**
1. 特殊测试课程的课程/班级 id；
2. 第一个写操作 = 测试公告（建议）；
3. 是否接受 dry-run 阶段；是否保持「默认 dry-run + 双确认 + 仅测试班」；
4. 回滚策略：公告删除/作业撤回/评分覆盖哪些平台支持。

---

## 建议实施顺序

1. **D75-1 真实预览**（先 HTML/JSON，再图片）；
2. **D75-2 UI 对齐/数字说明**（可与 1 并行）；
3. **D75-3 AI 评阅**（先 CLI 离线两段式 + batch，再 PWA）；
4. **D75-4 CLI journal**（已实施，等真机确认）；
5. **D75-5 写操作 dry-run**（依赖 1 + 测试班确认）。

## 非目标

- 不一次性放开写权限；
- 不自动后台发现/自动提交；
- 不把 API key、学生数据、run 存档入库或上传。
