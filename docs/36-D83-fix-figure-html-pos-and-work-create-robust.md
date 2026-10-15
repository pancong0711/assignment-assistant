# D83 交付后修复：插图排版右下角 + 新建作业点击超时（2026-10-15）

## 背景

D83（9b98a37）交付后用户实测发现两个问题：

1. **插图排版错误**：横版两列一行时，`text-right`（文左图右）的图显示在**右下角**；
   仅 `text-left`（文右图左）正确，`below-left/below-right` 的图也在右下角。
   要求全量检查横竖版、多行多列的插图排版逻辑。
2. **新建作业到文件夹失败**：Playwright 报
   `element is not visible - retrying click action - waiting 20ms/100ms/500ms`（点击超时）。

## 问题1 排查结论与根因

全矩阵实测（横竖版 × 1x1/1x2/2x1/2x2 × 四态 pos，reportlab drawOn 层取坐标）：
**引擎 PDF 落位全部正确**（text-* 两列表格图在右/左列顶部；below-* 图在题文下方贴左/右内容边）。

根因在 **HTML 侧**（PWA 预览 sheetHtml.ts + 引擎模板 assignment.html.j2）：

- **根因 A（PWA 独有）**：`figHtml()` 对 `text-right` 生成 inline
  `align-self:flex-end`——`.sheet-frame` 是 **row** 方向，`align-self` 控制的是**纵向**
  对齐 → flex-end = 行底，图被压到右下角。`text-left` 碰巧用 flex-start（顶部）所以正确。
- **根因 B（两份 HTML 都有）**：`.q-img { margin-left: auto }` —— `below-*` 是
  **column** 方向，flexbox 规范里 **auto 边距优先于 align-self**，把 below-left 的图
  也推到了右侧（与 align-self:flex-start 冲突）。

### 修复

- `sheetHtml.ts` `figHtml`：align 改为 `below-right ? 'flex-end' : 'flex-start'`
  （row=纵向一律顶部；column=横向左/右）；
- 两份 CSS 的 `.q-img` 删 `margin-left: auto`（row 下 q-body flex:1 已天然把图推到行尾）；
- 模板顺带补齐 **scale 透传 parity**（此前 PWA 对 max-w/max-h 乘 scale、模板不乘）；
- 模板 inline align 由 `doc.figure.pos` 决定（避免内联样式压过 `.pos-below-right` 类规则）。

### 回归保障（三端）

- `engine/tests/test_d83_figure_layout_matrix.py`（新增，28 用例）：PDF 侧 drawOn
  落位矩阵断言（含 frame 默认 6pt padding 口径）；
- `engine/tests/test_sheet_html.py`（扩展）：四态 HTML align 口径 + `.q-img` 禁
  `margin-left:auto`（渲染产物与两份源码双哨兵）；
- `app/tests/selfcheck-roster-fig.mjs`（扩展）：PWA `stringifySheetHtml` 四态断言。

## 问题2 排查结论与修复

报错形态（"element is not visible"）说明**元素存在但隐藏**：`create_work` 三个关键
点击都用 `.first`（按文档序取第一个），页面上存在同名隐藏节点（模板/下拉容器）时
必然点中隐藏元素超时。

修复（`engine/src/assist/xxt/work.py`）：

- 新增 `_click_first_visible()`：多定位器逐个尝试 + `filter(visible=True)` 可见过滤
  （Playwright ≥1.51）+ JS 兜底（可见且叶子文本精确匹配再 click）；
- 三个关键点击（选"简答题" / 点"完成" / 点"保存"）全部换用；
- 全流程步骤标记（step）+ try/except：失败即 `_fail_shot()` 截图到
  `<xxt_home>/work-drafts/`，返回 `{"error": "新建作业失败（步骤：X）：…", "step": X,
  "screenshot": …, "requests": …}`，PWA 可直接显示是哪一步、看现场截图；
- 附件上传失败分支同样补截图。

回归：`engine/tests/test_xxt_work_create_robust.py`（4 用例，stub locator 无浏览器）。

## 顺带质量修复

- `PublishView.vue`：`xxt-work-folders` 载入时过滤 D83-5.2 之前的裸 `courseId` 旧键
  （避免 localStorage 永久残留死数据）。

## 验证

- engine pytest：200 passed（含新增 28+5+4 用例）；
- `npm run build` / `npm run selfcheck`（含新 D83 四态断言）/ `check-secrets.sh` 全过。

## 追加修复（2026-10-15 第二轮用户实测反馈）

### 问题1 续：below-* 的图跑到帧的左/右下角

第一轮修好 text-right/text-left 后，用户实测 below-* 的图落在**当前题目 frame 的
左下/右下角**（而非题文正下方）。

根因：`.q-body { flex: 1 }` 是为 **row** 方向（text-right 时把图推到行尾）设计的；
`below-*` 切成 **column** 方向后，`flex:1` 让正文沿**主轴上**张满整个 frame，
图片被挤到 frame 底部 —— 横向再由 align-self 决定，于是呈现"左下角/右下角"。

修复（两份 HTML 同步）：新增

```css
.sheet-frame.pos-below-left .q-body, .sheet-frame.pos-below-right .q-body { flex: none; }
```

（类选择器特异性高于 `.q-body`，无需调整声明顺序。）

回归：`test_sheet_html` 与 PWA selfcheck 均改为**按 CSS 规则块解析**并断言
below-left/right 的 `.q-body` 规则含 `flex:none`（顺带修掉两个哨兵此前因
用 `bodyOf()` 裁掉 `<head><style>` 而**空跑**的问题）。

### 问题2 续：失败信息只剩「}」，看不到具体错误

根因：`create_work` CLI 失败时先 `click.echo(json.dumps(rep, indent=1))`，末行是 `}`；
PWA 与 serve journal 都取**末行** → 显示/记录「}」。

修复：

- `app/src/lib/engineClient.ts` 新增 `extractJobError()`：取**最后一个**
  `"error"` 字段（JSON 转义解码，含后端步骤名），无 JSON 时回退 traceback 末行；
  PublishView 的 task 失败提示与「新建失败」提示改用它；
- `engine/src/assist/serve.py` 新增 `_job_error_summary()`：journal 只在
  失败时记录 error（成功记空，不再记 `}`），同样优先解析 JSON error 字段，
  并覆盖整形后的长 JSON（不受尾部行数窗口限制）;
- `create_work` / `rename_work` 失败返回的 error 文案追加**现场截图路径**，
  PWA 可直接显示去哪看截图。

回归：`engine/tests/test_job_error_summary.py`（5 例）+ PWA
`selfcheck:job-error`（5 例，esbuild 打包 engineClient 后 node 断言）。

## 追加修复（2026-10-15 第三轮：真机侦查定位「新建作业」附件路径 + 成绩表头）

用户反馈「新建作业到文件夹依然失败」但无法提供错误信息。本轮用**保存的登录会话 +
本机 playwright chromium** 做了真机侦查（`.scratch/d83_work_probe.py` 等只读探针），
并用生产 CLI 端到端复跑，定位到根因。

### 结论1：无附件的 create_work 在真机上是通的 → 用户侧大概率跑的是旧代码

- 用真机会话复跑 `assist xxt work-create --directory-id 21400987` 成功
  （草稿 `7c9d302c…`）；`D83诊断草稿（可删）` 可删；
- 用户看到的「任务失败：}」正是**修复前**才会出现的文案（修复后 PWA 会显示
  JSON error 字段/步骤名）→ 说明浏览器 PWA 缓存与 engine 都还是旧版；
- 处置：PWA 硬刷新（Ctrl/Cmd+Shift+R 或清站点数据，Service Worker 会缓存旧 bundle）
  + 引擎用「检测更新/更新引擎」或 start.bat 更新后再复验。

### 结论2：附件路径有 3 个真机级缺陷（本次修复）

真机 DOM 事实（`.scratch/xxt-pages/d83-work-probe.html`）：

| # | 旧实现 | 真机事实 | 后果 |
|---|---|---|---|
| B1 | 找 `.edui-for-attachment` | 作业编辑器是 `.edui-for-attachment_new`（通知页才是旧名） | 按钮点不到，弹窗不出现 |
| B2 | 主页面找 `input[type=file]` | 弹窗是 iframe `.../dialogs/attachment_new/attachment.html`，file input 在 iframe 内 | 永远找不到输入框 → 30s 超时 |
| B3 | 只数 `editor-iframe`/`drag-image-wrap` | 图片插入为 `<img class="ans-ued-img">`；PDF/doc 为 `<div class="editor-iframe">` | 图片附件被判「未插入」→ 90s 失败 |

修复（`engine/src/assist/xxt/work.py`）：

- `_ATTACH_MARKERS` 统一四种标记（editor-iframe / attach-iframe / drag-image-wrap / ans-ued-img）；
- 新增 `_attachment_dialog_frame()`（按 URL 找弹窗 iframe）与
  `_open_work_attachment_dialog()`（`.edui-for-attachment_new` 优先，回落旧名）；
- `_upload_work_attachments()`：弹窗 iframe 内 `set_input_files`（失败重开弹窗一次），
  再回落旧的「主页面 hidden input」口径；每份附件用正文标记增长判定成功；
- 真机验证：`--attach demo_task_fig.png --attach attach-test.pdf` 端到端成功
  （草稿 `ee81ecab…`，两次 `ueditorupload/attachment` POST；两个测试草稿均可删）。
- 回归：`engine/tests/test_xxt_work_attachments.py`（8 例，stub 无浏览器）。

### 结论3：engine 成绩表三段式表头定位（docs/12 遗留项，本次修复）

- 真实「xxx成绩统计.xlsx」首行是大标题、表头在第 2~3 行；旧实现把首行当表头 →
  找不到「期末」列、回退也取不到 → 返回空；
- 新增 `_locate_header_row()`（与 PWA `rosterXlsx.locateHeader` 同口径：
  找含姓名语义列 + 非空列≥2 + 其后确有姓名数据的行；`prefer` 优先命中目标列），
  `read_exam` 与 `read_flex` 都改用它；
- 真机/真实文件验证：`化工251-成绩统计.xlsx` 34 人、`化工252班成绩统计.xlsx` 33 人
  全部正确；标准表头文件行为不变；
- 回归：`engine/tests/test_scores_header_offset.py`（4 例，含 legacy skip-safe）。

### 验证

- engine pytest **217 passed**；`npm run build` / selfcheck（9 组）/ `check-secrets.sh` 全过。
