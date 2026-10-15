# D85 任务需求单：新建作业（题型面板/文件夹）修复 + PWA 人工批阅栏（本地保存/上传）

> 日期：2026-10-15
> 状态：确认后逐步执行（每步完成即更新本文进度表 + docs/13）。
> 关联：`docs/37-D84-grade-upload.md`（批阅回传 CLI，已真机验证）、
> `docs/34-D82-...`（草稿修复）、遗留蓝本 `_legacy/2601playwright/src/uploader.py`。
> 用户实测反馈（2026-10-15）：① C2Z/C2 默认班级新建作业在"选择题型（简答题）"失败；
> ② 知识点拾遗班能建但落根目录而非指定文件夹；③ 希望把批阅上传入口放进逐生预览的
> "人工批阅"栏，并支持本地保存与一键上传全部。

## 1. 问题一：题型面板差异导致「简答题」找不到（已定位）

**真机证据（2026-10-15 只读侦察）**：`#questionTypeItem` 常驻隐藏；可见的「添加题目」
直接题型列表**按课程不同**：

| 班级 | 直接可见题型 |
|---|---|
| 知识点拾遗/默认班级（217801417/40009084） | 单选题 多选题 填空题 判断题 **简答题** 更多 |
| 大学物理C2（Z）/默认班级（236685449/81657984） | 单选题 分录题 多选题 资料题 填空题 更多（**无简答题**） |

简答题在后者只存在于 `<a id="addQTypeBtn" class="more">更多</a>` 的 `.morePop` 弹层内
（默认 `display:none`）。当前实现只 `get_by_text("简答题")` 直点 → 元素存在但不可见 →
3 定位器 + JS 兜底全失败（JS 兜底也要求可见）。实测「更多 → 弹层内简答题」可用
（`via-more`），知识点拾遗直点可用（`direct`）。

**另一个事实**：点题型按钮**本身即创建草稿**（点完 `#workid` 立即有值）。

### 1.1 修复设计

- 新增 `_ensure_question_type(page, title, value)`（`xxt/work.py`）：
  1) 直接区（`.addTitle`/`.qustion_type`）找 `[title="简答题"]`，可见即点其内 `<a>`/自身；
  2) 不可见/不存在 → 点「更多」(`#addQTypeBtn` / `.moreCon a.more`) → 在 `.morePop` 内点 `[title="简答题"]`；
  3) **成功判据**（新）：等待 `.eidt_stem` 出现该题型名 或 `#workid` 非空（超时→报错并说明尝试过的路径）。
- 选择器一律用 `title`/`value` 属性（不依赖文本渲染），并保留 `:visible` 过滤。

## 2. 问题二：新建作业落到根目录而非指定文件夹

**根因**：保存接口 `/mooc2-ans/work/save-work` 的参数全部**从页面 DOM 读**
（`$("#directoryid").val()`）；但 `create_work` 打开编辑器时 URL **没有 `directoryid`**，
服务端渲染 `#directoryid=0`；草稿在"加题"时即由服务端建立并固定目录，事后改隐藏域无效。
站点自身导航到编辑器是带 `&directoryid=` 的（`createWork.js` 跳转口径）。

### 2.1 修复设计

- 编辑器 URL 增加 `&directoryid=<目标文件夹>`（并继续设置隐藏域作兜底）；
- 保存后**回读校验**：主浏览器关闭后用 `list_works(..., directory_id=<folder>)` 确认
  新 `workLibraryId` 出现在该文件夹；未出现则在结果里给 `directoryCheck: {ok:false, hint}`；
- 结果/receipt 记录 `usedPath`（direct/more）、`directoryId`、`directoryCheck`。

## 3. 问题三：PWA 人工批阅栏（本地保存 + 上传）

落点：XxetongView「逐生两列预览」面板（当前写着"人工批阅…当前冻结"处）。

### 3.1 功能

| 控件 | 行为 |
|---|---|
| 分数 | 输入框，**默认 100**；随草稿保存 |
| 批语（作业批语） | 文本框；支持附加图片（png/jpg，复用通知附件白名单），随草稿保存 |
| 题目批语 | 可选：按题序号输入（CLI 已支持 `--question-comment`）；首版 PWA 支持"作业批语 + 总分" |
| 保存到本地 | **输入即存**（防丢）+ 显式「保存到本地」按钮（反馈"已保存 HH:MM"） |
| 上传本生 | 先 dry-run（引擎截图/读回校验，不提交）→ 弹窗确认 → 真提交；失败给步骤名+截图 |
| 上传全部批阅（含打分） | 遍历本地草稿逐生上传；默认**跳过"已批阅"**，提供「强制覆盖」开关；显示进度与逐生结果 |

### 3.2 存储与端点

- 引擎本地草稿：`<xxt_home>/grade-drafts/<classId>/<workId>.json`
  → `{ "<学生key>": {score, comment, commentText, images:[{name,data_b64}], updatedAt} }`
  （学生 key = `workAnswerId` 优先，回落姓名；与批阅清单同口径）
- 新增 serve 端点：
  - `GET  /xxt/grade/drafts/<classId>/<workId>` → 草稿表
  - `POST /xxt/grade/draft` → 保存单个学生草稿（含可选图片 base64）
  - `POST /xxt/grade/upload` → 套壳 CLI `xxt grade-upload`（job/SSE；`send=false` 即 dry-run）
  - `POST /xxt/grade/upload-all` → 套壳"逐生上传"（服务端循环，跳过已批阅除非 `force`）
- 图片：serve 端落 workspace 临时目录（复用 `save_notice_uploads`）→ 传 `--comment-image`。

### 3.3 安全

- 上传走 `xxt.write_allowlist`（D84 已实现，白名单外启动浏览器前即拒）；
- 保存草稿是**本地文件**写（不需白名单）；上传需 `--confirm-send` 语义（PWA 二次确认）；
- 幂等：已批阅默认跳过/拒绝，除非显式强制。

## 4. 分阶段实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| §1 | `create_work` 题型面板（更多兜底+成功判据） | `work.py::_ensure_question_type` + 6 例单测 | ✅ 真机：直点路径 `direct` 成功（`click:.addTitle-a`）；C2Z 只读校验「更多」弹层内可点（visible=True） |
| §2 | `create_work` 文件夹（URL 参数 + 保存后校验） | `directoryid` 入 URL + `directoryCheck` | ✅ 真机：`directoryCheck={directoryId:21400987, ok:true}`（草稿确实落在该文件夹） |
| §3 | 本地批阅草稿存储 + serve 端点 | `xxt/grade_store.py` + CLI `--from-drafts` + serve GET/POST | ✅ 单测 4 例；真机：`--from-drafts` 读出草稿→批语/分数写入批阅页→读回一致（dry-run 未提交） |
| §4 | PWA 人工批阅栏（分数默认100/批语/图片/保存/上传本生/上传全部） | `XxetongView.vue` + `engineClient.ts` | ✅ 代码+tsc/build/selfcheck 通过；serve 端点冒烟通过（POST draft / GET drafts / POST upload 作业流） |
| §5 | 记录更新（docs/13、docs/37 交叉引用、本文进度） | 文档 | ✅ |

### 4.1 真机验证记录（2026-10-15）

- **题型面板**：知识点拾遗班 = 直接列表有简答题（`usedPath=direct`）；C2Z 班只读校验：
  直接列表 `[title=简答题] a` 存在但 `is_visible()=False`（被 0×0/overflow 裁剪），
  点「更多」后 `.morePop` 内同元素 `is_visible()=True` → 与实现的两段式兜底一致。
- **文件夹**：编辑器 URL 带 `directoryid=21400987` 后，保存的草稿经
  `work-list --directory-id 21400987` 回读确认在文件夹内（`directoryCheck.ok=true`）。
- **人工批阅本地草稿**：`grade_store.save_draft` 写入
  `<xxt_home>/grade-drafts/<classId>/<workId>.json`；CLI `--from-drafts` 真机回填成功
  （批语文字 + 总分 88 读回一致，dry-run 未提交）；serve `POST /xxt/grade/upload`
  套壳 job 正常（status=done，rc=0）。
- 未决：PWA 界面需教师在有浏览器的机器上点一次「保存到本地 / 演练上传 / 上传并提交」做最终确认。

## 5. 验收

- C2Z 类班：题型走「更多」路径可加题（以只读面板检测 + 单测覆盖；该班不在本机白名单，
  端到端由用户在其白名单内实测）；
- 知识点拾遗班：新建作业**落到指定文件夹**（`work-list --directory-id` 复核），
  且 receipt 记录 `directoryCheck.ok=true`；
- PWA：逐生面板可改分数（默认 100）/批语 → 本地保存 → 上传本生（dry-run→确认→提交）
  → 上传全部（跳过已批阅、可强制），全程可见进度与错误；
- engine pytest / build / selfcheck / secrets 全绿，CI success。
