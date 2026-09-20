# 06 — 开发路线图（Roadmap）

> 共 6 个阶段（0–5）。每阶段结束交付可运行/可演示的产物；
> 遵守 D1 铁律：CLI 超集先行，PWA 是其参数化界面与结果展示器。
> 工程量直觉（粗估、非承诺）：阶段2≈25–30%、阶段4≈25–30%、
> 阶段1≈20%、阶段3≈15%、阶段5≈10%。

## 阶段 0 · 项目奠基 ✅ 已完成

已完成：旧项目解档入 _legacy/（不入库）、docs/01–05 讨论与决策
（D1–D13）、MIT LICENSE、.gitignore、tools/check-secrets.sh。

## 阶段 1 · Engine 内核：作业纸（CLI）

**范围**
- `engine/` 包骨架：uv 管理、click 命令组 `assist`、config/settings 加载、
  日志；`assist serve` 占位；`assist bootstrap`（D14：workspace 内
  .runtime/venv + UV_CACHE_DIR/PLAYWRIGHT_BROWSERS_PATH 重定向）。
- `assist kb *`：kb xlsx 读写（source of truth，列结构
  id/content/img_path/page/related/type/solution/note 兼容）、
  `export --fmt json`、写盘前 `.history/` 快照、`stats` 统计。
- `assist sheet *`：竖版 A4 迁移（基线还原）+ **横版 A4 双题版式**
  （landscape 两 frame 各一题）；页眉页脚参数化；水印直迁。
- 样题渲染（latex 可选依赖，缺失时提示降级路径——跳过样题图
  或由 PWA 预览替代）。

**交付/验收**
- `assist sheet make <task>` 产出横/竖版带水印 PDF（合成/本地数据）；
- `assist kb stats` 可查询题库统计；
- 全部能力不依赖前端可复现（CLI 超集初验）。

## 阶段 2 · App 骨架：作业纸设计上线（纯静态 PWA）

**范围**
- app/：Vue 3 + Vite + TS + Pinia、PWA manifest/service worker、
  GitHub Pages 部署配置。
- 页面：题库编辑器（浏览器读写 xlsx：SheetJS 读 → 编辑 → 导出/写回）、
  设计器（选章选题/分层标签/横竖版切换/页眉页脚/所见即所得预览）、
  任务包生成与导出（01/04 的 JSON 格式）、导入导出 zip。
- 设置中心雏形 + 首次运行向导（D13）。

**交付/验收**
- 浏览器内：kb 编辑 → 选题 → 预览 → 导出任务包；任务包丢给引擎 CLI
  即出 PDF（阶段1 联动）；
- 仓库内无任何真实数据（check-secrets 通过）。

## 阶段 3 · 批阅引擎迁移（CLI）+ 批阅工作台（静态态）

**范围**
- `assist grade`：下载占位 → 转录（多模态 LLM）→ 评阅（LLM，标签差异化：
  copy 只查完整性等 2601 规则迁移）→ 报告（MD/HTML/PNG（可选依赖））；
- **评阅 prompt 绑定作业纸题目与 kb 的 solution**（合并核心收益点，
  顶替作业就地告警）；
- LLM client：多模型配置、重试次数、国内镜像/兼容 base_url、
  apikey 从 settings.local.json 读；
- 产物落入 `classes/<class>/grading/<task>/` 结构（04 §1）。

**交付/验收**
- 对一组本地作业图片完成"转录→评阅→报告"全链路（无需学习通在线）；
- 任务包 journal 记录运行历史（D8），`--rerun` 单步/整单重跑可用。

## 阶段 4 · Companion 模式：学习通自动化 + 全链路联调

**范围**
- `assist serve`：本地 HTTP API + SSE 日志（沿用 webui.py 经验：
  端口探测、关页自停），token 访问保护；
- 学习通模块：登录（浏览器 profile）、课程/班级/作业浏览、id 字典、
  作业下载；上传（2601 v1/v2/v3 择优合并）：评语+图片+**自动打分**（D7）、
  可选上传前预览确认、限流与失败重试；
- PWA：引擎在线检测（D5）、环境体检/安装向导页（install.ps1/install.sh、
  国内镜像 D10）、workspace/班级管理向导、批阅任务执行与进度页。

**交付/验收**
- 真实闭环（教师机）：出作业 → 学生提交 → 一键批阅 → 上传+打分 成功；
- 环境体检页在 Win/Linux 各实测一次（镜像源生效）。

## 阶段 5 · 打磨与多教师可用性

**范围**
- 便携引擎包（Releases，`engine-portable-<platform>.zip`，D5）；
- 学习通公告/通知发布（含附件）；
- roster 迁移完善：点名册读取、成绩评分分组、分组标签 UI、
  签到分析（可选）；
- 汇总导出、错误恢复、教师使用手册（docs/，含"删除 workspace 即卸载"指引）、
  docs/NOTICE.md 依赖协议、手机第二屏（局域网连接）与浏览器降级提示（D9/D11）、
  导出/导入白名单（.runtime 永不打包，D14）。

**交付/验收**
- 至少一位你本人之外的老师从零（便携包或脚本）完成一次完整使用；
- NOTICE 与 README 完整申明依赖与数据红线。
