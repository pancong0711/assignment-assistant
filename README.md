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
- `docs/16-xuexitong-integration.md` — **阶段6 学习通整合任务需求单**（登录/读取/下载/上传/发布）
- `_legacy/` — 原始两项目解档（仅本地参考，已被 gitignore，永不推送）

## 里程碑

见 `docs/06-roadmap.md`（六阶段）。当前：阶段 0/1/2/3/3.5 已完成，
阶段 4a 主体完成；作业纸 HTML/PDF 主通道、班级分层、批量批阅 CLI、TinyTeX/KaTeX
可选依赖与 Pages 部署均已上线。剩余重点为阶段5 产品化收尾与阶段6 学习通接入；
CLI 保持超集，便于 AI agent 在 PWA 不可用时作为备份完成全流程。
