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
- ✅ `assist sheet make --task <task>` 按任务包逐生生成横/竖版带水印 PDF（roster 驱动，已实跑验证）；
- ✅ `assist kb stats/export/snapshot` 往返可用；`assist doctor` 逐项体检（uv/依赖/TeX 黄灯）；
- ✅ `assist bootstrap`（D14：.runtime/venv + 缓存重定向）；
- ✅ CLI 超集初验（全部功能不依赖前端可复现）；
- ⏳ 细化项：横版版式的边距/字号按真实题图细调；`assist bootstrap` 同时指 UV_PROJECT_ENVIRONMENT（pyproject sync 模式）；
- 开发环境注意：本机沙箱 `~/.cache/uv` 只读 → 用 `UV_CACHE_DIR` 指向 workspace（与 D14 一致）。

## 阶段 2 · App 骨架：作业纸设计上线（纯静态 PWA）

**范围**
- app/：Vue 3 + Vite + TS + Pinia、PWA manifest/service worker、
  GitHub Pages 部署配置。
- 页面：题库编辑器（浏览器读写 xlsx：SheetJS 读 → 编辑 → 导出/写回）、
  设计器（选章选题/分层标签/横竖版切换/页眉页脚/所见即所得预览）、
  任务包生成与导出（01/04 的 JSON 格式）、导入导出 zip。
- 设置中心雏形 + 首次运行向导（D13）。

**交付/验收（✅ 已完成，子代理构建+本侧复验 npm run build）**
- ✅ Vue3+Vite+TS+Pinia 骨架、manifest+SW（vite base=/assignment-assistant/app/），build 通过（bundle ~644kB，code-split 待优化）；
- ✅ 题库编辑器（SheetJS 读写 kind xlsx，列结构兼容 05-D3；Chrome 原地写回/降级导出）；
- ✅ 作业纸设计器（横竖 A4 预览、横版左右两半各一题、任务包 JSON schema 同 docs/04 §1，可导入续编）；
- ✅ zip 导入导出（JSZip；过滤 .runtime//.history/ 与路径穿越，D14）；
- ✅ 设置中心 + 三步首次运行向导 + D13 条件式置灰（引擎依赖按钮灰 + 黄横幅）；
- 遗留（阶段4+）：体检页真实接入 assist serve/doctor；fig 题图上传 UI；SheetJS 写样式局限待引擎 openpyxl 补；bundle 拆分；grade 表单（模型配置）。

## 阶段 3 · 批阅引擎迁移（CLI）+ 批阅工作台（静态态）

**范围**
- `assist grade`：下载占位 → 转录（多模态 LLM）→ 评阅（LLM，标签差异化：
  copy 只查完整性等 2601 规则迁移）→ 报告（MD/HTML/PNG（可选依赖））；
- **评阅 prompt 绑定作业纸题目与 kb 的 solution**（合并核心收益点，
  顶替作业就地告警）；
- LLM client：多模型配置、重试次数、国内镜像/兼容 base_url、
  apikey 从 settings.local.json 读；
- 产物落入 `classes/<class>/grading/<task>/` 结构（04 §1）。

**交付/验收（✅ 已完成，子代理迁移+本侧验证）**
- ✅ 对一组本地作业图片完成"转录→评阅→报告"全链路（无需学习通在线）；
  合成数据端到端测试 3 条通过（stub LLM/mock httpx；得分校验 95、journal 步骤、--rerun）；
- ✅ 任务包 journal 记录运行历史（D8），`--rerun` 单步重跑可用；
- ✅ 评阅 prompt 绑定任务包每题 content+solution；question_match 对不上 →
  verdict:"suspected-substitution"（顶替嫌疑 🚨 告警）；
- 标签差异化规则逐段迁移（copy 只查完整性等），评分公式搬运（20 分上限/
  缺图放宽/签名书写扣分/下限 40）；
- 遗留（阶段4）：download/upload、PNG 截图、per-run 日志文件、
  MD→HTML 转换按需引入 markdown 库、每题多问式细分。

## 阶段 3.5 · M5 成绩管理（用户提级新增，✅ 已完成）

**范围（纯本地闭环，不依赖学习通；D17/D18）**
- ✅ engine `assist roster tag`：点名册 + 多源成绩 xlsx（"文件:列[:权重]"，
  列可自动识别）→ 加权均值 → 分数降序按比例切分 tag
  （默认模板 = 2603 默认比例 5/10/10/25/35/15/10）→ 带 tag 名单 xlsx/summary；
  `special_tag_cfg` 人工覆盖（含 punish/penalty 归一 punish）；
- ✅ app「班级与成绩」选项卡：名单导入/手动管理、成绩源列表（起名/权重/
  手动选分数列）、比例表单（默认模板可改+合计提示）、punish 勾选列、
  manualTag 覆盖在重算时保留、导出 roster.xlsx/JSON/任务包 zip；
- ✅ tag 体系 9 项固定（D17）：copy/copySp/copyOnly/qa/summary/
  distinguish/innovation/translation/punish；
- 遗留（后续）：学号匹配回退、多 sheet 成绩源、rainclass 签到分析模块接入、
  roster 目录句柄独立连接。

## 阶段 4a · Companion 模式（纯本地闭环，不含学习通；2026-09-20 修订）

**背景**：用户拍板"学习通放最后"（还要接雨课堂等），并把"本地 serve/体检/工作台"
先行（批阅落盘先以手动图片目录跑通，下载/上传留挂点）。

**范围**
- `assist serve`：本地 HTTP API（stdio 无依赖，stdlib http.server）：
  `/doctor`（体检 JSON，供 PWA 体检页真接入）、`/status`、`--lan/--token` 可选；
  engine 产物目录静态托管（PWA 与引擎同源）；
- PWA：体检页真接入（fetch /doctor 渲染绿黄红）、向导"上一步"+状态缓存、
  批阅工作台页（手动图片目录模式）、水印编辑器（items 列表 + 9 宫格）、
  页面级引擎在线检测与黄色横幅联动；
- 引擎：`assist grade --images` 已通（阶段3），此处补 serve 端任务触发
  （journal + SSE 日志流）。

**交付/验收**
- 教师浏览器（本机或 LAN）体检页显示真实绿黄红；
- 手动图片目录跑通一次完整批阅（无需学习通在线）；
- 水印编辑器与多水印 items 生成的任务包可被引擎读取。

## 阶段 5 · M5 补强 + 后勤收尾

- rainclass 签到明细分析（迁 analyze_attendance.py）＋学号匹配回退＋多 sheet 成绩源；
- 便携引擎包（Releases，engine-portable-<platform>.zip，D5/D14）；
- 文档：教师使用手册、NOTICE、卸载指引（删 workspace）；
- 手机第二屏（局域网连接）与浏览器降级细化（D9/D11）。

## 阶段 6 · 学习通接入（原阶段 4 的学习通部分，后置；用户拍板 2026-09-20）

- 登录（浏览器 profile）/课程/班级/作业浏览与 id 字典/作业下载
  （迁移 2601 xuexitong 模块）；
- 批阅上传：评语+图片+自动打分（D7）、可选预览确认、v1/v2/v3 三代上传策略择优；
- 公告/通知发布（含附件）；
- `serve --https`（自签证书，可选）；
- 需要真实账号配合调试，单独收尾。


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

## （历史）阶段 5 雏形 → 已并入 4a/5/6（保留供索引）


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
