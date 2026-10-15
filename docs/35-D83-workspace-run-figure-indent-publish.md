# D83 — 工作目录记忆 / 插图位置四态 / 题号缩进开关 / 页眉日期 / 新建作业白名单与文件夹

> 关联：docs/34-D82（题图最大框/题号）、docs/31-D79（新建作业/文件夹）、docs/30-D78（发布）。
> 前置结论：**新建作业被拒的根因 = workspace 不一致**（见 §4.0），非白名单 UI 问题。

## 需求与决定（逐条）

### 1. 工作目录记忆与自动恢复（Q1）
- 现状：目录句柄已入 IndexedDB；启动 `restoreKbDir()` 只恢复句柄，**未重扫** `kb/*.xlsx` + `kb/fig`；
  故刷新后题图缩略图/题库为空，需手动重连。
- 决定：
  - `restoreKbDir()` 成功后**自动重扫**（复用 `loadWorkspaceKbFiles`），刷新即恢复题图与题库；
  - 设置中心显示"已记住的工作目录 + 状态（已连接 / 需重新授权）"；
  - 权限为 `prompt` 时给"点击恢复权限"按钮（FSA 需用户手势，不能静默授权），并提供"更换目录"。

### 2. 插图位置四态（Q2.1）
- 现状 `lt/rt/center` 语义与直觉不符（实际只改左右列顺序/对齐），横版双列更看不出区别。
- 决定改为四态（`layout.figure.pos`）：
  | 值 | 语义 | 实现 |
  |---|---|---|
  | `text-right`（**默认**） | 文左图右（同一行） | 两列 [文, 图] |
  | `text-left` | 文右图左（同一行） | 两列 [图, 文] |
  | `below-left` | 题文满宽，图另起一行左对齐 | 纵向 [文(满宽), 图] hAlign=LEFT |
  | `below-right` | 题文满宽，图另起一行右对齐 | 纵向 [文(满宽), 图] hAlign=RIGHT |
- "below-*" 两种：**题文占满整行**，不再为插图空出列。
- 旧值兼容：`rt→text-right`、`lt→text-left`、`center→below-right`。
- 三端同口径：引擎 PDF（`_question_flowable`）、引擎 HTML 模板、PWA `sheetHtml.ts`。

### 3. 题号缩进开关（Q2.2）
- 决定新增 `layout.indent: 'none' | 'first' | 'hanging'`，**默认 `none`**（题号紧挨文字，无额外缩进/悬挂）。
- `first` 首行缩进（约 2 字符 ≈ 7mm）；`hanging` 悬挂缩进（题号宽 ≈ 13mm，续行对齐正文）。
- 三端同口径；PWA 版式 UI 提供勾选/下拉。

### 4. 页眉日期与整行分布（Q2.3）
- 现状页眉 `sh-info` 有"日期"，页脚也有"日期" → 重复。
- 决定：**删除页眉日期**（页脚保留），页眉 `sh-info` 改为各 span **等宽左对齐**、铺满整行。
- 三端同口径（引擎 HTML 模板 + PDF 页眉 `_make_onpage` + PWA `sheetHtml.ts`）。

### 5. 新建作业到指定文件夹（Q3）

#### 5.0 根因（已定位）
- serve `_xxt_env()` 给 CLI 子进程设 `ASSIST_WORKSPACE = _ws()`，而 `_ws() = find_workspace(None)`；
  当 serve 以 `--workspace X` 启动但环境变量缺失时，`_ws()` 可能解析到**另一个目录**。
- 结果：白名单由 serve 写到 `self.ws=X`，但 `work-create` 子进程 `validate_work_target(course,class)`
  （未传 ws）从 `find_workspace(None)` 读 → **读到别处的空白名单 → 拒绝已勾选班级**。
- 复现：`is_allowed(cid,kid, ws=X)=True` 而 `is_allowed(cid,kid)=False`。
- 另：`serve.py` 的 `/xxt/work/publish` 调 `validate_work_target(...)` **漏传 ws**（其它端点都传了）。

#### 5.1 决定
- `_xxt_env()` 用 **serve 的 workspace（`self.ws`）**，不再 `find_workspace(None)`；
- 所有 `validate_work_target` 调用**统一显式传 ws**（含 `/xxt/work/publish`）；
- 白名单拒绝时**回显**：请求的 `courseId:classId` + 实际读取的白名单文件路径 + 现有条目（便于自证）。

#### 5.2 文件夹记忆按班级（Q3.1）
- 现状 key = `courseId`（`folderMap[c.courseId]`、缓存 `xxt-work-folders-cache-v2:${courseId}`），未区分班级；
  学习通作业库文件夹按班级独立 → "选文件夹却建到根目录/别处"。
- 决定：key 改 **`courseId:classId`**；`loadFolders/loadWorks/setFolder/createFolder/createDraft/copy` 全按当前班级取 `directoryId`。

#### 5.3 白名单 UI（Q3.2）
- 结论：新建作业与发布/通知**共用同一白名单**，非硬编码；问题在 §5.0（读端 workspace 不一致）。
- 加固：
  - 班级来源以 **"当前 run"** 为准（见 §6），并提供"显示全部已发现班级（targets.json）"兜底；
  - 勾选保存由"整体覆盖 classes.value"改为按当前列表**可靠增删**（避免因列表不含某班而丢失/加不上）；
  - 新建/发布按钮点击时，非白名单给出**明确指引**（提示去白名单勾选），而非笼统"请选择白名单内班级"。

### 6. "当前 run" 全局共享（Q3 附带）
- 现状：`XxetongView.curRun` 只在本地（默认 `runs[0]`）；`PublishView.loadClasses()` 写死 `runs[0]`；
  两页无共享"当前 run"。
- 决定：新增轻量持久化 `xxt.currentRunId`（localStorage + 小 store）：
  - `XxetongView` 选中写入；`PublishView`（及通知等）读取；为空回落 `runs[0]`；
  - `PublishView` 顶部"当前批次"显示并真正使用该 run。

## 验收
- 刷新 PWA 后题图/题库自动恢复；设置页可见并管理已记住目录；
- 插图四态在 PDF/引擎 HTML/PWA 三端位置一致，"below-*" 题文满宽；
- 题号缩进三态可选，默认 none；
- 页眉无重复日期、各 span 等宽左对齐铺满；
- 同一白名单在发布/新建/通知一致；`--workspace X` 启动下已勾选班级新建作业通过（workspace 一致）；
- 文件夹按班级各自记忆；"当前 run" 三页一致。

### 7. 新建作业插入附件（Q4 · 新需求）
- 需求：在「发布作业 → 新建作业草稿」区增加**附件上传**（图片/pdf/doc 等），
  全部插入到那道**唯一简答题的题干**里（图片内嵌正文、文档以链接/附件形式附于题干）。
- 格式白名单：**复用发布通知那套** `settings.local.json → xxt.notice_attachment_exts`
  （默认 pdf/doc/docx/jpg/jpeg/png/webp/gif，PWA 可配）；不做第二套。
- 引擎：`xxt.work.create_work` 现仅 `UE.setContent(stemHtml)`；扩展为
  「先按序把本地附件经学习通上传通道传成 CDN URL/附件 → 拼进 stem HTML → 再 setContent」。
  图片走 UEditor `insertimage`/上传接口；文档走附件上传接口（与 notice 同源，见 docs/30-D78）。
- PWA：新建草稿区加「选择附件」（多选，限白名单扩展名）→ 随 createDraft 一并提交文件；
  serve `/xxt/work/create` 接收附件（multipart 或 base64+name），落临时目录后交给 CLI。
- 口径确认：附件内嵌进简答题干（非独立作业附件）。

## 实施进度（2026-10-15）
- ✅ §5.0 workspace 一致性（serve `_SERVE_WS` + publish 端点传 ws + 拒绝诊断回显 + 回归测试）
- ✅ §5.1 拒绝信息回显实际白名单文件路径与条目
- ✅ §5.2 文件夹记忆 key 改 `courseId:classId`（folderKeyOf/cache-v3）
- ✅ §5.3 白名单 UI 加固（当前 run + 显示全部已发现班级 + 增量保存 + 明确指引）
- ✅ §6 "当前 run" 全局共享（xxtRun store；XxetongView 写、PublishView 读）
- ✅ §2 插图位置四态（text-right/text-left/below-left/below-right；旧值兼容；三端同口径；四态 PDF 实跑通过）
- ✅ §3 题号缩进开关（none 默认/first/hanging；三端同口径）
- ✅ §4 页眉删日期 + 各 span 等宽左对齐铺满（模板/PWA/PDF 页眉；页脚保留日期）
- ⏳ §1 工作目录自动恢复与记忆（进行中）
- ⏳ §7 新建作业插附件（待做）

## 实施顺序
1. §5.0 workspace 一致性（最紧急，直接决定"新建作业能不能用"）；
2. §6 当前 run 共享 + §5.3 白名单 UI 加固；
3. §5.2 文件夹按班级；
4. 2/3/4（插图四态 / 缩进开关 / 页眉）；
5. §1 工作目录自动恢复与记忆；
6. §7 新建作业插入附件（复用通知附件白名单与上传通道）。
