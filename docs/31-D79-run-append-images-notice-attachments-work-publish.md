# D79 任务需求单：run 增补 / 图片更新 / 通知通用附件 / 发布作业（2026-10-13）

> 来源：2026-10-13 用户对 run 语义、作答图片重复下载、通知附件、发布作业功能的集中反馈。
> 关联：`docs/30-D78-pwa-notice-publish.md`、`docs/16-xuexitong-integration.md` §23、
> `docs/24-D73...`（run 生命周期）、`docs/26-D75...`（批阅下载/写操作冻结）。
> 状态：**需求讨论稿，先评审，再开发。**

---

## A · run 语义与增补

### A1. 当前口径

- 每次「提取所选」= 引擎 `assist xxt extract` 跑一次，写一条新 run JSON 到
  `xxt_home()/runs/xxt-<timestamp>-<rand>.json`；
- run 是不可变的历史批次，PWA「发现作业」展示最近 run；
- 历史 run 可删除/清空，也支持导入旧 run JSON。

### A2. 问题

教师一次没选全班级时，重新「提取所选」会产生一条**新 run**，之前的 run 被顶到历史；
用户需要再次勾选已选班级，且新 run 与旧 run 之间要人工对照。

### A3. 方案（建议 A1）

| 方案 | 行为 | 优点 | 缺点 |
|---|---|---|---|
| A1 追加到当前 run（推荐） | `assist xxt extract --append <run_id> --targets …`；同一 courseId+classId 覆盖，其他保留；workId 粒度合并 | 增量增补、保留历史、diff 可见 | 需要定义合并语义 |
| A2 只保留一个 run | 每次提取覆盖唯一 run | 用户理解最简单 | 丢失历史/diff/回滚，和现有 D73/D74 设计冲突 |
| A3 run patch 文件 | 只写“增补补丁”，不改 run | 实现轻 | PWA/批阅/预览要支持合并视图，复杂度更高 |

**建议**：保留多 run，但增加「追加到当前 run」按钮（A1）。

CLI：

```text
assist xxt extract --append <run_id> --targets <json>
```

语义：

1. 读取目标 run JSON；
2. 对每个目标班/作业重新实时抓取；
3. 按 `courseId -> classId -> workId` 合并：同键覆盖，新键追加；
4. 班级级 `status/notes/roster/notices` 一并覆盖；
5. 记录 `appended_at`、`source_run`、`append_targets`；
6. 写回同一 run 文件；旧 run 内容先在 `.history/` 快照（与 kb 写盘口径一致）；
7. journal 记 `xxt_extract_append`。

PWA：

- 「提取所选」旁新增「➕ 追加到当前 run」；
- 默认目标 = 当前 `curRun`；若没有 run 则退化为普通提取；
- 追加完成后自动刷新当前 run 视图；
- 与「单 run 模型」不冲突：仍可在历史里删除/清理。

### A4. 1.1 作答图片重复下载 / 更新全部图片

现状：

- `assist xxt review-download` 逐生打开 review-work 详情，下载**作答图片+批语**，
  写 `pages/review/<classId>/<workId>/students.json`；
- 重复执行会重下已有作答图片，也找不到“只补批语/只补缺图”的入口。

建议新增语义（2026-10-13 用户确认 `missing`，并澄清与 `comments-only` 的区别）：

```text
assist xxt review-download --mode full|missing|comments-only
```

- `full`：现状；重下作答图+批语，整包覆盖；
- `missing`：**补漏模式**。逐个学生比对 `students.json`：缺作答图则只下缺失的图、
  缺批语字段则补批语；**已存在的图片/批语不覆盖**；
- `comments-only`：**更新模式**。对全部学生重新抓两栏批语/分数并覆盖 manifest 中
  批语/分数字段，但**完全不下载作答图片**；
- 两者的区别：`missing` 不覆盖已有内容、以“补齐”为目标；`comments-only` 覆盖更新
  批语/分数、以“刷新”为目标。
- 新增 `--refresh-index`：完成后重扫 `pages/review/**/students.json`，PWA 刷新索引。

PWA：

- 「批阅图片」卡新增：
  - `⬇ 补下缺失`；
  - `💬 仅更新批语`；
  - `🔄 更新全部（全量）`；
- 执行前显示将处理的学生数/已存在图片数；
- 写入前对 `students.json` 做合并而不是整包覆盖，保留旧命名映射。

### A5. 1.2 run 的中文词

建议 UI 统一使用：

- 主词：**提取批次**
- 辅助括注：`提取批次（run <id>）`
- 短标签：**批次**

CLI / API / 文档继续保留 `run`（与 D73/D74 契约一致），只改用户界面文案。
D79 实施时更新帮助手册、空状态提示、按钮与历史管理标题。

---

## B · 通知附件与标题

### B1. 当前限制

D78 的附件选择器只扫描 `classes/**/sheets/**/*.pdf`，不适合“普通通知”的图片/截图/PDF。

### B2. 目标

通知附件是**通用附件**；2026-10-13 用户拍板：**限制为图片 / PDF / doc**（jpg/png/webp/gif + pdf + doc/docx）。
实现分两步：

1. **附件来源**：
   - 保留作业纸 PDF 快捷区；
   - 新增“本机上传”入口：PWA 选择文件 → `POST /xxt/notice/upload` →
     引擎存入 `<workspace>/.runtime/xxt/notice-uploads/<ts>/` → 返回可发布路径；
   - 也允许选择 workspace 内任意文件（路径必须在 workspace 下）。
2. **学习通侧上传**：
   - 复用 D78 已打通的 WebUploader 隐藏 input（`.edui-for-attachment input[type=file]`）；
   - 平台输入本身没有 accept 限制（实为通用附件），图片/PDF/doc 不应受我们前端白名单限制；
   - 增加大小/数量上限提示（待实测平台单文件/总大小上限）。

### B3. 标题默认值

默认标题改为：

```text
作业通知-大学物理
```

正文保持：

```text
作业纸见附件，请各位同学打印自己的那一张并手写完成、拍照上传到学习通作业里面。
```

附件文件名仍自动进入标题后缀/正文“附件文件名”行。

---

## C · 发布作业（学习通平台作业）

### C0. 结论

**是**：先做 CLI（engine 写会话），PWA 只做参数化表单和显示，符合 D1「CLI 超集先行、PWA 显示壳」。

### C1. 已完成的只读侦察（2026-10-13）

- 新建入口：课程作业列表「新建作业」→
  `/mooc2-ans/work/goToWorkEditor?courseid=&clazzid=&mooc=1&workid=&built=1&from=`
- 编辑器字段：作业类型（题目型/答题卡）、评分机制（百分制平均/自定义）、题型归类、
  题型按钮（单选/多选/填空/判断/简答/更多）、选题、智能导入；
- 保存接口：`GET /mooc2-ans/work/save-work`
  （courseid/clazzid/cpi/workid/title/grading/directoryid/workStatus/questionGroup）；
- 发布设置页：`/mooc2-ans/work/library/setting?courseid=&cpi=&workLibraryId=&fromCreate=1&from=`
- 作业库：`/mooc2-ans/work/library?courseid=&clazzid=&cpi=&...`；
  作业库文件夹以 `directoryid` 区分，条目 `ul.dataBody_td[data=<workLibraryId>]`。

发布设置页已核对到的主要开关：

- 发放对象（班级/学生/分组；本轮只做整班）；
- 有效时段：开始时间、结束时间；
- 允许学生补交 + 补交截止时间；
- 高级设置：
  - 及格标准（未达及格自动打回重做）；
  - 重做设置：截止前允许重做 + 重做次数；多次作答取历史最高；重做时保留前一次作答记录；
  - 防作弊：提交后查看作业、允许查看答案（教师批阅后/学生提交后/作业结束后）、
    不允许粘贴、被打回显示对错、题目乱序、选项乱序；
  - 作业查看设置：允许查看分数、查看题型分数、隐藏批语；
  - 督促设置：结束前 N 小时提醒、每隔 N 小时再次提醒；
  - 作答要求：完成任务点百分比；
  - 评分设置：填空类设为主观题、大小写/符号/多选半分等。
- 发布动作：`发放`；发布前可通过 `应用模板/保存模板` 预置配置。

**注意**：用户提到的“截止前是否可以修改及修改次数”，在本发布页对应的是
“重做设置/重做次数”；作业本身的 edit 权限由平台发布状态控制，不在同一个开关里，
需在实施时再确认。

### C2. 本轮要发布的测试作业（用户给定）

- 课程/班级：仅 `217801417 / 40009084`（大学物理知识点拾遗（by pc）/ 默认班级）；
- 作业只设 1 题；
- 题型：简答题；
- 题目内容：

```text
请查看学习通班级消息，打印自己的那份作业纸，手写完成，签名并记录日期，
拍照原图上传，纸质版于作业截止后课前提交。（如有疑问，及时与授课老师联系）。
```

- 题目需保存到**教师个人作业库文件夹**；
- 2026-10-13 拍板：**固定教师个人作业库文件夹，由用户自己填写**（不自动猜测/不跨教师）；
- 具体 folderId 不写进仓库；实施时读 `/mooc2-ans/work/library?...&directoryid=...` 树供用户选择或填写；
- 本次真机测试的目标课程作业库为空（无文件夹），测试作业保存在作业库根/draft。

### C3. 建议的 CLI 形态

```text
assist xxt work-list    --course <id> [--class <id>] [--json]
assist xxt work-create  --course <id> --title <名> [--directory <id>]
                        --question-file <json> | --question-type 简答 --stem <文本>
assist xxt work-publish --course <id> --work-library-id <id>
                        --class <id>...
                        [--start <time>] [--end <time>]
                        [--late-submit --late-deadline <time>]
                        [--redo-times N] [--highest] [--keep-last]
                        [--view-answer after-review|after-submit|after-end]
                        [--remind-before-hours N] [--remind-interval-hours N]
                        [--dry-run|--send]
```

- `--question-file` 用结构化 JSON 描述题目，便于跨题型扩展；
- 发布配置可用 `--publish-spec <json>` 承载更多高级设置，避免命令行过长；
- 默认 dry-run；真正发布要显式 `--send` + 二次确认；
- 写操作沿用白名单：当前仅目标班级。

### C4. PWA 形态

学习通页新增/扩展「发布作业」卡：

1. 选课程/班级（整班多选，沿用 D76 勾选树；白名单限制）；
2. 选择：
   - 新建作业：标题、题目（简答模板可直接用用户给定文案）、保存文件夹；
   - 或从已有作业库列表选择一项（`work-list` 返回已发布/未发布）；
3. 发布设置表单：开始/截止、允许补交+补交截止、重做次数、最高分、保留作答、
   查看答案策略、提醒等（先实现用户高频项，其余收进“高级设置”）；
4. 预览 payload → dry-run → 二次确认 → 发布；
5. 回执：workId/workLibraryId/链接/截图。

### C5. 与作业纸/通知的关系

- 作业纸仍走「通知」通道（分层作业纸无法按学生下发到平台作业）；
- 平台作业只是一个“统一入口”：学生拍照上传作答，教师后续批阅；
- 因此发布作业与发布通知是两个并列能力，不在同一条数据流上强制耦合。

---

## D · 开发顺序与验收

1. **D79-A**：run 追加 + 作业纸/批语图片增量下载（engine + PWA）；
2. **D79-B**：通知通用附件 + 标题默认值（engine + PWA）；
3. **D79-C**：发布作业 CLI（先只读 work-list，再 dry-run create/publish，再真机测试班）；
4. **D79-C2**：PWA 发布作业向导（复用 D79-C）；
5. 每个写操作：白名单 + dry-run + 截图/receipt + journal + 二次确认；
6. 验收：目标班真机发布 1 次简答作业，且不触碰其他班级。

## E · 已拍板（2026-10-13）

1. run 增补：采用 **A1 追加到当前 run**；
2. 图片模式：保留 `missing`（补漏，不覆盖）与 `comments-only`（刷新批语，不重下作答图）两种；
3. 通知附件：限制 **图片 / PDF / doc**；
4. 保存文件夹：**固定教师个人作业库文件夹，用户自己填写**；
5. 已有作业二次发布：**原样发布，不复制/不新建**；
6. 发布作业：**先创建未发布草稿 → 预览 → 再发放** 的两阶段流程；
7. 重做设置：测试作业使用 **截止前允许重做 3 次**；
8. 默认时间（2026-10-13 追加）：发布当天 18:00 前 → 开始=当天 18:00；已过 18:00 → 开始=当前时间（北京时间）；截止=开始+5 天 18:00；补交截止=截止+2 天 18:00；
9. 提供「记住为默认」开关：勾选后把本次起止/补交/重做等写回 workspace `settings.local.json` 的 `xxt.publish_defaults`；
10. 选项卡拆分：确认拆为 **作业预览-学习通**（只读/管理）+ **发布-学习通**（通知/作业发布）；
11. `review-download` 默认模式：**missing**。

## F · 真机测试结果（2026-10-13）

- 仅对目标班 `217801417 / 40009084` 创建并发布了一道简答题作业；
- 题目内容按用户给定文案；
- 发布请求：`POST /mooc2-ans/work/library/publish`；payload 中发放对象仅
  `[{"classid":40009084,"publishType":0}]`；
- 平台返回：`{"msg":"发布成功","workRelationArray":[{"classId":40009084,"workId":56864879}],"taskId":133034928,"status":true}`；
- 真机复核：`assist xxt discover-works` 可见 1 份作业（`workId=56864879`），
  未发现其他班级被发放；
- 备注：作业库为空时，草稿默认保存于作业库根；发布时标题为平台默认
  `新建作业<时间戳>`（本次未重命名）。

## G · 本轮实现进度（2026-10-13）

已实施：

- engine：
  - `assist xxt extract --append <run_id>`（A1 追加批次；同班覆盖、新班追加，HTML 存档迁移）；
  - `assist xxt review-download --mode full|missing|comments-only`，默认 `missing`；
  - `assist xxt work-list`（只读作业库列表）与 `assist xxt work-publish`（dry-run/发布已有作业）；
  - `POST /xxt/notice/upload`（PWA base64 上传通用附件）；
  - `GET /xxt/work/list`、`POST /xxt/work/publish`；
- PWA：
  - 顶层选项卡拆分：`作业预览-学习通`（原学习通）+ `发布-学习通`（新）；
  - 预览页增加「➕ 追加到当前批次」、批阅图片增加「⬇ 补下缺失」「💬 仅更新批语」；
  - 发布页支持：通知发布（通用附件上传）、作业库选择已有作业原样发布、起止/补交/重做次数、记住为默认；
- 测试：engine pytest 142+；`npm run build` 通过。

待继续：

- 通知默认标题/正文与附件文件名联动细节打磨；
- 作业草稿创建（新建 1 道简答题）PWA 表单：本轮先支持“已有作业原样发布”，草稿创建仍可用 CLI/临时脚本；
- 教师个人作业库文件夹的显式配置读取；
- 通知/作业发布 receipt 展示与回执落盘页面。

## H · 白名单/文件夹/草稿/防重 补充实施（2026-10-13）

- 白名单改为 workspace `settings.local.json` 的 `xxt.write_allowlist`：
  - 默认空；PWA「发布-学习通」逐班勾选加入/移出；
  - engine 发布前读同一份配置做二次校验。
- 作业库文件夹：
  - 新增 `GET /xxt/work/folders`，按 `courseId` 展示文件夹；
  - PWA 按 courseId 记忆所选文件夹，并提供「🔄 刷新文件夹」；
  - 新建草稿保存到所选文件夹（`directoryid`）。
- 新建 1 道简答题草稿：
  - CLI `assist xxt work-create --course --class --cpi --title --stem [--directory-id]`；
  - PWA「新建作业草稿」表单，创建后自动刷新作业库。
- 作业详情：
  - `GET /xxt/work/detail` 读取标题、题干、`workUsed`（是否已发布）；
  - PWA 选中作业后显示标题与题干，题干可确认后再发布。
- 防重复发布：
  - 本地 `work-publishes/index.json` 记录 `courseId|workLibraryId|classId`；
  - `workUsed=true` 的已发布作业默认拒绝再次发布；
  - 提示用户在学习通创建副本（副本+时间戳）后再发布，符合“同班同作业硬拒绝”的决策。
- 时间过期：
  - PWA 打开/切回页面时检查开始时间；
  - 用户未手动改过则按规则自动刷新；
  - 已手动修改则提示过期，并提供「↺ 恢复默认时间」。
- 真机验证：
  - 新建草稿 `f88430ceb891495ea8b599ade00c4a42`（大学物理作业纸提交（D79草稿））保存成功；
  - `work-detail` 成功读回题干；
  - 已发布的测试作业 `049cd37e...` 返回 `workUsed=true`，将被防重逻辑拒绝再次发布。

## I · 文件夹/作业列表本地缓存（2026-10-13）

- PWA 首次读取「作业库文件夹」「已有作业」时写入 localStorage：
  - `xxt-work-folders-cache:<courseId>`
  - `xxt-work-list-cache:<courseId>:<directoryId>`
- 缓存 TTL = 30 天，过期自动重新拉取；
- 点「🔄 刷新文件夹 / 🔁 刷新作业库」强制实时更新；
- 新建草稿/发布成功后强制刷新当前文件夹作业列表。
- 修复：`work-list` 改用学习通 `intoFolder` 的真实 URL 契约
  （`courseid&directoryid&cpi&from&topicid&backurl`），并过滤 `type=0` 的文件夹条目，
  「已有作业」只显示当前文件夹下的作业。

## J · 通知附件格式与图片附件验证（2026-10-14）

- 学习通新建通知页「附件」按钮的 WebUploader hidden input **没有 accept 扩展名限制**；
- 真机 dry-run 验证：
  - PDF：上传成功，插入 `editor-iframe`（附件块）；
  - PNG 图片：上传成功（pan-yz upload/v2 200），插入 `drag-image-wrap` / `editor-img`（内联图片块）；
- engine 原先只按 `editor-iframe` 判断附件成功，因此图片会被误判失败；已改为同时统计
  `editor-iframe` 与 `drag-image-wrap`；
- CLI/PWA 当前允许的通知附件后缀：pdf/doc/docx/jpg/jpeg/png/webp/gif；
- 是否完全去掉后缀白名单待用户确认；平台 input 本身不限制，但建议只放开常用格式以避免
  平台对不常见格式的处理不一致。

## K · 附件格式白名单（2026-10-14）

- 拍板：通知附件按**白名单模式**管理格式，不做完全放开；
- 配置位置：workspace `settings.local.json` 的 `xxt.notice_attachment_exts`；
- 默认：`pdf/doc/docx/jpg/jpeg/png/webp/gif`；
- CLI：`safe_attachment_path` 与 `save_notice_uploads` 按该白名单校验；
- PWA「发布-学习通 → 发通知」新增「附件格式白名单」折叠区：
  - 勾选允许的扩展名；
  - 保存后立即生效；
  - 上传/文件选择器只接受白名单内格式；
- 作业新建保持简单：仍只做 1 道简答题草稿，不做复杂题型/题库选题。
