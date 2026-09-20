# assignment-assistant

大学物理（环境/化工等通识课程）作业助理：**作业纸设计与 AI 辅助批阅的一站式工具**。

- 由两个先行项目合并而来：2603paperDesign（分层个性化作业纸，试行 5-6 学期）
  与 2601playwright（学习通 AI 批阅，试行 1 学期）。
- 目标形态：**Python CLI 引擎 + PWA 网页前端**，数据全部保存在教师本地；
  仓库（MIT）仅含代码与合成示例，不含题库/学生数据/任何密钥。
- 讨论与设计文档见 `docs/01-architecture.md` 起的系列（开发尚在讨论阶段）。

> 作业纸不是筛选工具，而是沟通的桥梁。分层不是给学生贴标签，
> 而是让每个学生都能在适合自己的难度上获得练习与反馈。

## 文档索引

- `docs/01-architecture.md` — 宏观架构（Engine+App 双层、模块划分、monorepo 布局）
- `docs/02-pwa-feasibility.md` — PWA 可行性结论与风险
- `docs/03-module-migration.md` — 旧项目 → 新项目迁移映射
- `docs/04-data-model-and-privacy.md` — 数据契约、脱敏红线、协议声明
- `docs/05-decisions.md` — 决策记录（D1–D13；与其他文档冲突时以 05 为准）
- `docs/06-roadmap.md` — 六阶段路线图（0–5，含验收标准）
- `docs/07-incremental-vs-rewrite.md` — 增量迁移 vs 重写的开发思路判定
- `_legacy/` — 原始两项目解档（仅本地参考，已被 gitignore，永不推送）

## 里程碑

见 `docs/06-roadmap.md`（六阶段）；阶段 0 讨论奠基已完成，
下一步进入阶段 1（engine 内核：kb 读写 + 竖/横版版式）。
