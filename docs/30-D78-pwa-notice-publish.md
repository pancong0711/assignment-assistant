# D78 实施记录：PWA 课程通知发布（CLI 套壳 + 附件上传 + 白名单）

> 日期：2026-10-12
> 关联：`docs/16-xuexitong-integration.md` §23（公告发布预研）、`docs/26-D75...`（写操作解冻）、
> `docs/28-D76...`（发现/提取入口）、`docs/29-D77...`（feishu 话题问题）
> 状态：**已实施并真机验证（附件通知已实际发布到测试班）**

## 1. 目标与架构

- engine/CLI 为唯一执行体：`assist xxt notice-send`（默认 dry-run，`--send` 才真正发布）；
- PWA 只做参数化界面：班级多选、标题/正文、附件选择、预检、二次确认、job 进度；
- 数据源限制为“已提取班”（最近 run 的 courses/classes）；
- 当前测试白名单：课程 `217801417`（大学物理知识点拾遗（by pc）） / 班级 `40009084`（默认班级）；
  其他已提取班在 PWA 中正常显示但不可勾选，engine 侧也会拒绝。

## 2. 学习通附件链路（本次侦察确认）

- 发布页 `richtextNotice?courseId=` 的 UEditor「附件」按钮使用 WebUploader；
- 页面存在 3 个 hidden file input：附件按钮对应 **`.edui-for-attachment input[type=file]`**（无 accept），
  另有图片 input 和 `.doc,.docx,.pdf` 的“转在线文档” input；**不要选错**，否则走 `convertToHtml` 而非附件上传；
- 附件上传真实请求：`POST https://pan-yz.chaoxing.com/upload/v2?...&source=notice`，成功后再写草稿；
- 上传完成后 UEditor 正文插入：
  `<div class="editor-iframe"><iframe src=".../attachment/insertCloud.html" name="<base64 JSON>">`；
- 发送请求：`POST /pc/course/notice/addNotice`，成功响应含 `status:true` 与 `msg.id/idCode/attachment`；
- 附件必须等 WebUploader 收尾（iframe 出现后再等约 2.5s）再点发送，否则可能被前端校验拦住。

## 3. 代码落点

### engine

- `engine/src/assist/xxt/notice.py`（新增）：
  - `normalize_targets` / `validate_targets`（白名单）；
  - `safe_attachment_path`（仅 workspace 下 pdf/doc/docx）；
  - `list_notice_attachments`（`classes/**/sheets/**/*.pdf`）；
  - `send_notice_from_spec`：Playwright 打开新建通知 → 注入收件人 sendMap →
    `UE.getEditor('container').setContent` → WebUploader 上传附件 → dry-run 截图 或 点发送 → 回查通知列表；
  - receipt/截图写入 `<xxt_home>/notice-sends/`。
- `engine/src/assist/xxt/cli.py`：新增
  - `assist xxt notice-attachments`（列出附件候选）；
  - `assist xxt notice-send --spec …` / `--target courseId:classId[:className] --title --body --attachment … [--send]`。
- `engine/src/assist/serve.py`：新增
  - `GET /xxt/notice/attachments`；
  - `POST /xxt/notice/send`（写 spec → `assist xxt notice-send --spec … [--send]` 流式 job）。
- 版本：engine `0.1.0 → 0.4.0`（D75-6 约定：0.4.0 = 写操作接入）；`/status` 增加短 commit。

### app

- `XxetongView.vue`：原 disabled「发公告」卡改为可用向导：
  - 已提取班多选（白名单外 disabled）；
  - 默认标题 `大学物理课作业通知`，默认正文
    `作业纸见附件，请各位同学打印自己的那一张并手写完成、拍照上传到学习通作业里面。`；
  - 附件 PDF 清单（来自引擎 workspace）勾选后，文件名自动进入标题后缀与正文“附件文件名”行；
  - 「🧪 预检/试运行」与「📢 发布通知（二次确认）」；
  - job 轮询显示进度/错误。
- `engineClient.ts`：`fetchXxtNoticeAttachments` / `startXxtNoticeSend`；`/status` commit 字段。
- `settings`/`SettingsView`：版本 chip 显示 `v0.4.0 <short-commit>`。

## 4. 验收

- 真机 dry-run（附件）：成功上传 PDF 并插入 UEditor，截图/receipt 落盘；
- 真机发布（附件）：向 `217801417/40009084` 发布测试通知成功（`addNotice status=true`，
  通知列表可查到标题，`attachment` 字段含 PDF）；
- `engine/tests/test_xxt_notice.py`：纯函数回归 3 passed；
- `npm run build`：vue-tsc + vite 通过。

## 5. 已知边界/后续

- 「附件文件名自动进入标题」目前取前 2 个名称 + “等”，标题超 128 自动截断；
- 定时发送/提醒渠道本轮不开放；
- 白名单是临时硬编码（engine + PWA 各一份），扩大范围时改为配置；
- 跨课程批量为循环发布：每个 course 打开一次新建通知页，同标题/正文/附件。
