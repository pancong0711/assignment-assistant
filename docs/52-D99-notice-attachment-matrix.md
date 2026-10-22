# D99 · 通知附件类型矩阵与上传就绪判定（xlsx 支持）

> 日期：2026-10-22
> 触发问题：PWA 首次用 **xlsx** 发通知失败，报
> `Page.goto: Timeout 60000ms exceeded ... richtextNotice?courseId=...`
> 关联：`docs/31-D79...`（通知附件白名单）、`docs/48-D95...`（多班通知）、
> `engine/src/assist/xxt/notice.py`、`engine/src/assist/xxt/allowlist.py`、`app/src/views/PublishView.vue`。

## 1. 原报错根因（先澄清）

原错误发生在**打开新建通知表单页的 `page.goto`**，此时附件还没开始上传，
因此**不是 xlsx 被拒**。它属于页面加载超时（网络/首跳慢），与附件类型无直接因果关系。

真正和附件相关的两个隐患在代码里：

| # | 问题 | 影响 |
|---|---|---|
| 1 | `_editor_attachment_count` 在上传刚触发时就统计块数；此时 DOM 里已有 `editor-iframe`，内容写的是「正在上传...」 | **假阳性**：还没传完就判成功，随后点发送 |
| 2 | 上传后固定 `page.wait_for_timeout(2500)` | 小文件白等 2.5s；大文件/云盘慢时仍可能没传完 |
| 3 | 默认白名单不含 `xls/xlsx` | CLI 传 xlsx 会被静默拒绝 |

## 2. 真机矩阵验证（大学物理知识点拾遗 / 默认班级 `217801417:40009084`）

只填表 + 上传，**未点发送**；每类附件单独一页。

| 类型 | 平台结果 | 编辑器结构 | 就绪耗时 |
|---|---|---|---|
| pdf | ✅ | `editor-iframe`（云附件 `insertCloud.html`） | ~1.1s |
| png | ✅ | `drag-image-wrap` + `<img src=p.cldisk.com/...>` | ~1.1s |
| docx | ✅ | `editor-iframe`（云附件） | ~1.1s |
| **xlsx** | ✅ | `editor-iframe`（云附件） | ~1.1s |

结论：**xlsx 与 pdf/docx 走同一条云附件链路，平台侧没有格式限制**。
（附件按钮的 WebUploader input 本身无 `accept`；页面另有 `.doc,.docx,.pdf` 的
文档转在线 input，但并非附件按钮所用。）

### 2.1 上传时序（png，250ms 采样）

```
 0.07s  count=1  errors=1  pending=false      ← 出现 imguploaderror 瞬时节点
 0.33s  count=1  errors=1  hasImg=true        ← 已经插入真实 <img>
 1.11s  count=1  errors=0  hasImg=true        ← 错误节点被清掉
```

这说明：**失败占位 `imguploaderror` 是瞬态的**，不能一出现就判失败；
必须等「成功证据」或宽限期耗尽。

## 3. 修复内容

### 3.1 就绪判定（`notice.py`）

- `_editor_snapshot(page)`：**一次** `page.evaluate` 取回
  `{len, count, pending, errors, settled}`。
  - 关键：图片进度层是瞬态的，分两次 evaluate 取「块数」和「错误数」会互相翻转，
    导致把成功误判成失败（本次实测踩到过）。
- `_upload_progress()`：块数 > 上传前 **且** 无 `正在上传/uploadinfotext/attachprogress`。
- `_wait_upload(..., before_failed, error_grace_s=5.0)`：
  - 块数增加 + 无 pending + `settled` + 连续 `stable_hits=2` 次快照一致 → 成功；
  - 出现**新增**失败占位不立即失败，给 `error_grace_s` 宽限；
    宽限内看到成功证据（真实 `<img src>` / progress 层清空）→ 成功；
  - 宽限耗尽仍失败 / 90s 超时 → 失败。
- 删除上传后的固定 `wait_for_timeout(2500)`。
- receipt 新增 `uploadWaits: [{name, ok, wait_s, pending?, failed?, count?, errors?}]`。
- 失败信息区分三种：UEditor 不可用 / 本次新增失败占位 / 仍在「正在上传」或未稳定。

> 说明：干跑里一个**内容损坏但扩展名合法**的 xlsx 也会成功——云附件链路只保证
> 文件已传到云盘，平台不校验内容。这是平台行为，不是我们的判定缺陷。

### 3.2 默认白名单（`allowlist.py`）

`DEFAULT_NOTICE_ATTACHMENT_EXTS` 增加 `xls/xlsx`：

```
pdf doc docx xls xlsx jpg jpeg png webp gif
```

`ppt/pptx/zip/txt` 仍通过 PWA 勾选 / CLI `attachment-exts set --add` 扩展。

### 3.3 CLI

- `xxt notice-send --attachment` 帮助改为指向 `xxt.notice_attachment_exts`；
- `xxt attachment-exts set` 新增 `--add`：在**当前生效**白名单（含默认值）上追加，
  避免误把默认 pdf/doc 覆盖掉；
- 附件被拒时错误信息带上允许后缀与扩展命令。

### 3.4 PWA

- `attExts` 默认勾选与引擎默认值对齐（xls/xlsx 默认开）；
- 引擎返回空数组时视为「未配置」，保留默认勾选。

## 4. 验证

```
engine pytest（notic/attachment-exts 相关）   40 passed
真机 dry-run（四类附件，默认班级）           xlsx/pdf/png/docx 全部 ok，各 ~1.1s
```

## 5. 未做 / 后续

- 原 `page.goto` 60s 超时仍是硬编码；慢网络下的重试/预热未在本次改动内
  （本次实测页面 ~1s 打开，建议单独跟进）。
- xls/xlsx 未做「真发」端到端验收（仅 dry-run + 平台编辑器结构确认）。
