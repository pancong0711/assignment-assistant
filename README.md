# assignment-assistant

大学物理（环境/化工等通识课程）作业助理：**作业纸设计与 AI 辅助批阅的一站式工具**。

- 由两个先行项目合并而来：2603paperDesign（分层个性化作业纸，试行 5-6 学期）
  与 2601playwright（学习通 AI 批阅，试行 1 学期）。
- 目标形态：**Python CLI 引擎 + PWA 网页前端**，数据全部保存在教师本地；
  仓库（MIT）仅含代码与合成示例，不含题库/学生数据/任何密钥。
- 讨论与设计文档见 `docs/01-architecture.md` 起的系列；**引擎 v0.5.0 / PWA v0.5.0**，
  阶段 0–4 已完成、阶段 5 收尾中，阶段 6（学习通）已接入发布/成绩源（见 `docs/16`）。
- 当前重点：**知识点分析线**（失误率统计 → 共现/聚类 → 可视化）与 **Atopia 任务化解析**，
  口径与路线见 `docs/112-D168`、`docs/113-D169`。

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
- `docs/05-decisions.md` — 决策记录（D1–D58；与其他文档冲突时**以最新需求单为准**）
- `docs/06-roadmap.md` — 六阶段路线图（0–5，含验收标准）
- `docs/07-incremental-vs-rewrite.md` — 增量迁移 vs 重写的开发思路判定
- `docs/11-deployment.md` — GitHub Pages 部署（阶段4b）
- `docs/13-taskboard.md` — 任务需求单（D43–D62 历史；**当前活动需求单见 `docs/112`/`docs/113`**）
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
- `docs/78-D130-source-aware-grading-rules.md` — **D130 按题目来源分型的评阅规则 + AI 生成评阅要点 + 知识点体系 + Assistopia（项目游乐城）**
- `docs/79-D131-materials-and-summary-grading.md` — **D131 课堂资料 `<ws>/materials/` → 知识点清单 → `summary` 批阅联动（P2）**
- `docs/80-D126B-teacher-report.md` — **D126-B 教师总结报告：易错知识点汇总 + 共现 + 得分率**
- `docs/81-D132-assistopia.md` — **D132 Assistopia：AI 调用本项目工具的安全工作区（工具白名单/分级/审计/护栏/扩展隔离）**
- `docs/83-D134-atopia-workspace-and-summary-grading.md` — **D134 Atopia 专用工作区（重命名 + 目录收拢）+ summary 双轨评阅（资料口径 / 保底口径）+ 资料上传**
- `docs/84-D135-knowledge-trend.md` — **D135 跨多次作业的知识点趋势（同一知识点反复出错 / 改善 vs 持续；只给教师）**
- `docs/86-D136-opencode-go-session-header.md` — **D136 opencode-go 会话头（x-opencode-session）+ provider 级自定义请求头（白名单）**
- `docs/87-D137-pwa-cli-parity.md` — **D137 PWA ↔ CLI 能力对齐（provider 请求头 / 资料页三动作 / Atopia 护栏）**
- `docs/88-D138-knowledge-topic-layer.md` — **D138 知识点两层分类（章 → 主题 → 术语；不做 parent/child）**
- `docs/89-D140-atopia-chat-tab.md` — **D140 Atopia 独立选项卡 + 对话模式（Playground 保持单次）**
- `docs/90-D143-translation-question-id.md` — **D143 翻译题库题号重复修复（答案互相覆盖的静默数据损坏）**
- `docs/91-D144-remove-rubric-toggle.md` — **D144 删除规则卡里的「生成 AI 评阅要点」开关（改为代码口径）**
- `docs/92-D145-provider-header-ux.md` — **D145 provider 请求头 UI 重做（勾选式会话头 / 顺序 / 留空语义 / 保存反馈）**
- `docs/93-D146-atopia-provider-model.md` — **D146 Atopia 可选 provider / 模型（与 Playground 共用构造逻辑）**
- `docs/94-D147-confirm-scope.md` — **D147 Atopia L2 确认精确到「工具+参数」（安全修复）**
- `docs/95-D148-atopia-read-project.md` — **D148 Atopia 只读文件能力（fs.ls/read/search）+ 知识点选项卡 + 逐生补批**
- `docs/96-D149-grading-as-score-source.md` — **D149 AI 批阅成绩作为成绩源（每包一列，未批阅记 0）**
- `docs/97-D150-plan-atopia-workspace.md` — **D150 规划：Atopia 工作区（D164 已实施）**
- `docs/98-D151-prompt-templates.md` — **D151 提示词模板中心（5 类 system prompt 可改/可存/可删）**
- `docs/99-D152-ai-workbench-move.md` — **D152「题库AI+」整合题库 AI 作答（已完成）**
- `docs/100-D153-report-multi-select.md` — **D153 教师报告多选班级/作业包/tag（已完成）**
- `docs/101-D154-per-student-button-feedback.md` — **D154 逐生审核按钮反馈修复**
- `docs/102-D155-materials-feature-name.md` — **D155 课堂资料按特征名管理 + 上传按类型归档**
- `docs/103-D156-D160-grading-quality.md` — **D156–D160 批阅正确性与质量（落错人/结果不变/太简略/转写 schema）**
- `docs/104-D161-translation-seed.md` — **D161 翻译题随机种子（新建随机 / 落盘 / 可重抽）**
- `docs/105-D162-batch-fixes.md` — **D162 一批修复（LaTeX 裸换行 / 标注可见性 / 章节下拉 / 种子往返 / 包计数）**
- `docs/106-D163-materials-page-and-translation-line.md` — **D163 课堂资料页可新建/可上传 + 翻译题题号不换行**
- `docs/107-D164-atopia-work-and-materials-upload.md` — **D164 Atopia 工作区（上传/解析）+ 从 Atopia 复制 + 标注章节联动**
- `docs/108-D165-publish-cross-class.md` — **D165 跨班发布误判「已发布」（URL 缺 clazzid）**
- `docs/109-D166-escape-and-related-json.md` — **D166 LaTeX 转义根因 + 知识点 JSON 化 + AI 再整理**
- `docs/110-D167-examAnalysis-integration.md` — **D167 2508 知识点共现/得分率整合评估（只记录，未动代码）**
- `docs/112-D168-metrics-and-snapshot.md` — **D168 知识点失误统计口径 + 数据快照（roster/submissions）**
- `docs/113-D169-roadmap-and-architecture.md` — **D169 实现路线 + 架构决策（atopia 权限/工具治理/可视化）**
- `docs/114-versioning.md` — **版本号规则**（engine / app / launcher 三段，何时升、发布链路）
- `docs/115-D170-usage-fixes.md` — **D170 实际使用缺陷修复**（间隔号姓名/重载卡死/发布误判/抄写题规则等）
- `docs/116-D171-grading-workflow-and-extract.md` — **D171 批阅三键/结果落草稿/抄写题计分/抽取改纯 Python**
- `docs/117-D174-three-keys-and-translation-lenient.md` — **D174 逐生三键语义确认 + 翻译题批阅放宽（5/5/10）**
- `docs/118-D175-review-comment-score-merge.md` — **D175 逐生审核批语/分数一体化（一键保存 + 报告预览）**
- `docs/119-D176-question-kind-pipeline.md` — **D176 题目类型(kind)贯通 + translation 不要求示意图**
- `docs/120-D177-single-prompt-builder.md` — **D177 评阅提示词合并为唯一实现（消除双份漂移）**
- `docs/121-D178-copyonly-tag-alias.md` — **D178 copyonly 学生批阅无分/无批语（tag 等价别名 + 跳过可见）**
- `docs/122-D179-grading-analysis-shape-normalization.md` — **D179 评阅结果字段类型归一化（修复 sequence item 20）**
- `docs/123-D180-audit-apply-preview-tag-source.md` — **D180 采用审计 tag 后主表 tag 未刷新（preview 优先读快照）**
- `docs/124-D181-tag-edit-and-audit-apply-path.md` — **D181 AI 审计/手动改写 tag 不生效（无快照 + 作用域刷新断裂）**
- `docs/125-D182-stale-update-pending-launcher.md` — **D182 陈旧 update.pending 导致 launcher 启动失败（自愈清理）**
- `docs/126-D183-snapshot-plan-tag-selection.md` — **D183 批阅 plan 按作业包快照 tag 选题（修复审计后仍走旧 tag）**
- `docs/127-D184-audit-tag-upsert.md` — **D184 审计采用 tag 支持快照 UPSERT（补齐实际提交学生）**
- `docs/128-D185-evaluation-json-parse-retry.md` — **D185 评阅 JSON 解析失败重试/增强修复（未转义引号、尾逗号、截断）**
- `docs/129-D186-summary-prompt-lenient.md` — **D186 summary 题目提示与评阅口径适度放宽（定义/公式二选一、不要求列全）**
- `docs/130-D187-report-scope-checkbox-and-append-merge.md` — **D187 报告生成 classDir / 强制重做复选框 / 追加批次 works 合并**
- `docs/131-D188-xxt-relogin-and-extract-error-detail.md` — **D188 学习通重新扫码登录按钮 + 会话失效提示 + 提取失败详情**
- `docs/132-D189-xxt-relogin-success-detection.md` — **D189 重新扫码登录判定收紧（旧 _uid 不再误判成功）+ 登录状态可读化**
- `docs/133-D190-xxt-qr-before-avatar.md` — **D190 重新扫码时先显示二维码、登录成功后才显示头像**
- `docs/134-D191-xxt-login-attach-and-stale-state.md` — **D191 已有扫码任务时页面接管（409 不再卡死）+ 遗留登录态/旧二维码不再冒充当前扫码**
- `docs/135-D192-xxt-cancel-stuck-login-and-reissue.md` — **D192 审核：卡住的扫码任务可取消并强制重新出码（无需退出学习通账号）**
- `docs/136-D193-upload-gbk-unicode-and-report-versioning.md` — **D193 上传批语/成绩 GBK 编码崩溃修复 + 已批阅三态对照 + 报告内容哈希版本（.versions 历史）**
- `docs/137-D194-report-render-interrupt-resume.md` — **D194 一键生成报告的中断语义与续做（逐生隔离 + 进度落盘 + resume/只补失败）**
- `docs/138-D195-report-scope-and-duplicate-students.md` — **D195 只部分出报告/重复姓名的根因（按学生合并多键 + 生成前范围核对 + 重生成/清理入口）**
- `docs/139-D196-upload-submitted-only-and-per-student.md` — **D196 只上传已提交学生 + 批语缺失提醒 + 逐生上传**
- `docs/140-D197-cleanup-index-and-roster.md` — **D197 清理报告同步清理版本索引 + 按本次作业名单核对（修复版本列表残留 106 条）**
- `docs/141-D198-version-records-vs-students.md` — **D198 版本“记录数≠学生数”：清理无内容时解释原因 + 压缩版本历史**
- `docs/142-D199-report-version-roster-alignment.md` — **D199 报告版本以逐生审核名单为基准（修复 57 人只显示 53 人）+ 报告按学生姓名命名**
- `docs/143-D200-report-image-upload-default.md` — **D200 上传“报告图+分数”即算就绪（修复 48 人被误判批语为空）+ 默认不重复上传批语文本**
- `docs/144-D201-upload-draft-scope.md` — **D201 逐生上传“本地无该作业的批阅草稿”（上传链路补 classDir/taskId scope）**
- `docs/145-D202-upload-verification.md` — **D202 上传“显示成功但平台未批阅/无分数”（提交后核验 + 提交前分数校验）**
- `docs/146-D203-submit-confirmation-click.md` — **D203 提交后仍“待批阅”：确认弹窗支持 confirmPiyueWork/文案兜底 + 多层确认 + 失败证据**
- `docs/147-D204-submit-session-and-dryrun.md` — **D204 “未找到提交按钮”先判会话过期/页面不对 + 提交按钮兜底 + 逐生「演练」**
- `docs/148-D205-e2e-mock-upload-test.md` — **D205 本地仿真批阅页端到端验证上传图片/打分/提交/核验（并修复重试与确认重复点击）**
- `docs/149-D206-real-platform-validation.md` — **D206 真实学习通实测：提交按钮是 DIV/英文界面/列表无状态文本（三处差异已修）**
- `docs/150-D207-completed-status.md` — **D207 真实状态是「Completed（教师提交）」：状态解析与核验口径修正（防只改分未提交假成功）**
- `docs/151-D208-upload-code-review.md` — **D208 上传/打分代码审核：修错人上传、确认名单被忽略、误点下一份、重复提交（含 2 个高危）**
- `docs/152-D209-real-confirm-chain.md` — **D209 真机实测「手动测试作业发布」：确认链是「保存并继续(checkPass)」→「提交」，修复后图片+打分上传成功**
- `docs/153-D210-preview-cache.md` — **D210 上传前对照本地缓存（21.7s→0s）+ 手动刷新平台状态；顺带修复「已完成」被误判未批阅**
- `docs/154-D211-dedupe-and-overwrite.md` — **D211 逐生上传重复学生（112=56×2）按学生去重 + 新增「覆盖」原报告（清旧图写新图新分）**
- `docs/155-D212-review-download-update-history.md` — **D212 作业预览重复下载：覆盖+哈希去重+`.history` 归档+孤儿清理（update 模式为默认）**
- `docs/156-D213-kind-resolution-consistency.md` — **D213 innovation 评阅过严：提示词与算分的题库(kind)解析口径统一 + 旧 plan 补 kind + 兜底可见**
- `docs/157-D214-grading-prompt-composition-and-tag.md` — **D214 说明：AI 批阅如何按 tag 选题、提示词只注入出现的题型、tag 错时为何仍出分及风险**
- `docs/158-D215-align-before-grade-design.md` — **D215 设计：用程序对齐替代大模型题目比对（一次计算两处复用、省 token、错卷前置拦截）**

> **当前活动需求单 = `docs/112-D168`（口径/快照）+ `docs/113-D169`（路线/架构）**；
> 历史条目保留供追溯，与最新口径冲突时以这两份为准。
- `docs/85-D135-knowledge-hierarchy.md` — **D135 待决：知识点层级（上位/下位概念）方案与取舍**
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

见 `docs/06-roadmap.md`（六阶段）与 `docs/12-backlog.md`（总账）。

- **已完成**：阶段 0/1/2/3/3.5/4；作业纸 HTML/PDF 主通道、班级分层、批量批阅 CLI、
  TinyTeX/KaTeX、Pages 部署、学习通发布与成绩源；
- **进行中（阶段 5 收尾）**：知识点分析线（`docs/112-D168`）、Atopia 任务化解析
  （`docs/113-D169`）、工具面治理；
- **最后**：阶段 6 学习通剩余项（`docs/16`）。
- CLI 始终是**超集**：PWA 能做的是 CLI 的子集，便于 AI agent 在网页不可用时接管全流程。

## 依赖安装（可选 extras）

主依赖（`pip install -e engine`）覆盖作业纸与批阅。以下为**按需安装**，不装也能正常用主体功能：

| extra | 内容 | 用途 | 缺失时 |
|---|---|---|---|
| `playwright` | playwright | 学习通浏览器自动化 | 学习通功能不可用（体检标黄） |
| `viz` | matplotlib / networkx / numpy | 知识点失误率图 + 共现网络图 | 图表接口返回 501 + **可读提示** |

```bash
pip install -e "engine[viz]"            # 只要分析图表
pip install -e "engine[viz,playwright]" # 图表 + 学习通
```

> `start.sh` / `start.bat` 每次启动都会执行 `pip install -e`，**会自动补齐新增依赖**；
> 失败时体检项（`viz`）会标黄并给出可读指引，而不是抛 import 异常。

## AI / 脚本调用约定

- **直接调用 `assist <cmd>`，不需要 `assist serve` 常驻**：CLI 是进程内实现，读写本机
  workspace 文件；`serve` 只是给浏览器（PWA）的 HTTP/SSE 门面。
- **机读错误**：设置 `ASSIST_JSON_ERRORS=1`，失败时 stderr 输出一行
  `{"ok": false, "error": "...", "type": "...", "exitCode": N}`，退出码 0=成功、
  1=业务失败、2=用法错误。
- **并发安全**：配置/草稿类"读-改-写"已加文件锁 + 原子写，多个 CLI 并行不会丢更新。
- **更新引擎**：`assist engine update` 只暂存新版本，需 launcher（`start.bat/start.sh`）
  重启后安装；用 `assist engine status [--json]` 查看当前停在哪一步。
