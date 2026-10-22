# assignment-assistant

大学物理（环境/化工等通识课程）作业助理：**作业纸设计与 AI 辅助批阅的一站式工具**。

- 由两个先行项目合并而来：2603paperDesign（分层个性化作业纸，试行 5-6 学期）
  与 2601playwright（学习通 AI 批阅，试行 1 学期）。
- 目标形态：**Python CLI 引擎 + PWA 网页前端**，数据全部保存在教师本地；
  仓库（MIT）仅含代码与合成示例，不含题库/学生数据/任何密钥。
- 讨论与设计文档见 `docs/01-architecture.md` 起的系列；当前主体功能已上线，
  正在进行阶段5/6 产品化收尾（学习通接入最后做）。

> 作业纸不是筛选工具，而是沟通的桥梁。分层不是给学生贴标签，
> 而是让每个学生都能在适合自己的难度上获得练习与反馈。

## 在线使用（PWA 直达）

- 线上入口：<https://pancong0711.github.io/assignment-assistant/>（GitHub Pages，HTTPS，
  可安装到主屏/离线打开；数据全在教师本地）
- 引擎联动（体检真项/批阅/学习通）：教师本机运行 `assist serve`（默认 http://127.0.0.1:8601）
  → 设置中心填该地址即可跨域联调。部署说明见 `docs/11-deployment.md`。

## 文档索引

- `docs/01-architecture.md` — 宏观架构（Engine+App 双层、模块划分、monorepo 布局）
- `docs/02-pwa-feasibility.md` — PWA 可行性结论与风险
- `docs/03-module-migration.md` — 旧项目 → 新项目迁移映射
- `docs/04-data-model-and-privacy.md` — 数据契约、脱敏红线、协议声明
- `docs/05-decisions.md` — 决策记录（D1–D58；与其他文档冲突时以 05 为准）
- `docs/06-roadmap.md` — 六阶段路线图（0–5，含验收标准）
- `docs/07-incremental-vs-rewrite.md` — 增量迁移 vs 重写的开发思路判定
- `docs/11-deployment.md` — GitHub Pages 部署（阶段4b）
- `docs/13-taskboard.md` — **任务需求单 / 近轮实施记录**（D43–D62）
- `docs/15-usage-manual.md` — 教师使用说明（同源 HelpView）
- `docs/22-D71-engine-launcher-two-phase-update.md` — **D71 扫码导航竞态 + engine 两阶段自更新 + launcher/engine 边界**
- `docs/23-D72-pwa-extract-preview.md` — **D72 PWA 一键提取账户信息 + 作业纸/批阅报告/过程预览整合**
- `docs/24-D73-xxt-extract-history-job-lifecycle.md` — **D73 提取任务跨 tab 恢复 + Playwright 浏览器操作历史 + assist.cli 导入修复**
- `docs/28-D76-selection-folding-merge-preview.md` — **D76 发现结果默认不选/课程折叠/提取入口合并/预览回退**
- `docs/29-D77-feishu4dsh-long-reply-thread-loss.md` — **D77 feishu4dsh 长回复分片落到话题外诊断**
- `docs/30-D78-pwa-notice-publish.md` — **D78 PWA 课程通知发布（CLI 套壳 + 附件上传 + 白名单）**
- `docs/31-D79-run-append-images-notice-attachments-work-publish.md` — **D79 run 增补/图片更新/通知通用附件/发布作业（讨论稿）**
- `docs/32-D80-grade-upload-collab-test-plan.md` — **D80 LLM 两步批阅 + 上传协作测试计划（白名单）**
- `docs/33-D81-workspace-kb-doctor-published-cache.md` — **D81 班级发布判定缓存/Workspace-kb 管理/体检项清理**
- `docs/34-D82-kb-read-order-image-upload-batch.md` — **D82 kb 多文件读取/题目排序/插图参数/草稿修复/上传试跑/batch**
- `docs/16-xuexitong-integration.md` — **阶段6 学习通整合任务需求单**（登录/读取/下载/上传/发布）
- `_legacy/` — 原始两项目解档（仅本地参考，已被 gitignore，永不推送）

## AI agent 使用（无 API key 也能跑）

`skills/` 里是给 AI agent 的操作规程（先读 `skills/README.md`）。核心链路：

```bash
assist doctor --json                 # 探测能力：api / command / batch / agentCli
assist grade --task a.json --xxt-class c:k --work w   # 程序逐生独立请求（隔离）
```

- **路径优先级**：`type=command`/本地端点 > `subagent` > `plan/collect`（兜底）> 逐条（禁止）；
- **无 API key**：`assist llm provider --action set --type command --cmd <agent-cli>` 让程序回环
  调用你的 agent CLI（每次新进程=天然隔离）；或 `assist grade-plan ...` 生成清单让 agent 自己做；
- **批阅严谨性**：`json_schema` + `evidence`（引用原文）+ `confidence`（low 不计分）；
- **执行报告**：`<grading>/batch-report.json`（成功/失败/耗时，失败可重跑）。

## 里程碑

见 `docs/06-roadmap.md`（六阶段）。当前：阶段 0/1/2/3/3.5 已完成，
阶段 4a 主体完成；作业纸 HTML/PDF 主通道、班级分层、批量批阅 CLI、TinyTeX/KaTeX
可选依赖与 Pages 部署均已上线。剩余重点为阶段5 产品化收尾与阶段6 学习通接入；
CLI 保持超集，便于 AI agent 在 PWA 不可用时作为备份完成全流程。

## AI / 脚本调用约定

- **直接调用 `assist <cmd>`，不需要 `assist serve` 常驻**：CLI 是进程内实现，读写本机
  workspace 文件；`serve` 只是给浏览器（PWA）的 HTTP/SSE 门面。
- **机读错误**：设置 `ASSIST_JSON_ERRORS=1`，失败时 stderr 输出一行
  `{"ok": false, "error": "...", "type": "...", "exitCode": N}`，退出码 0=成功、
  1=业务失败、2=用法错误。
- **并发安全**：配置/草稿类"读-改-写"已加文件锁 + 原子写，多个 CLI 并行不会丢更新。
- **更新引擎**：`assist engine update` 只暂存新版本，需 launcher（`start.bat/start.sh`）
  重启后安装；用 `assist engine status [--json]` 查看当前停在哪一步。
