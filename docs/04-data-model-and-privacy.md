# 04 — 数据模型 与 仓库脱敏规范

## 1. 数据契约（教师本地工作区，第一版草案 · D6 修订）

**workspace = 多学期多班级共享**；kb 题库在根目录（最常编辑、全局复用）；
每个"学期×班级"一个独立子目录（sheets/grading/roster 各自隔离）。

```
<workspace>/                       # 单个教师的管理根目录
  kb/                              # 题库（跨学期复用，最常编辑，故在根）
    problems.xlsx  copy.xlsx  qa.xlsx  distinguish.xlsx
    innovation.xlsx  translation.xlsx
    .history/                      # 写盘前自动快照（版本备份）
    fig/                           # 题图（xlsx 中 img_path 为相对路径引用）
    export/                        # 引擎导出的 JSON 副本（交换/AI阅读/diff 基准）
    examples/                      # 合成示例（唯一允许入库的部分）
    solutions/                     # D89：题目答案多版本 <qid>.json（AI 作答/多模型/置顶，追加不覆盖）
  classes/                         # 所有 班级×学期 目录并列放这里（05-D6）
    2025S2-大学物理-化工25/
      roster/                      # 点名册/成绩/分组结果
      sheets/                      # 作业纸任务包 + 生成产物 out/*.pdf
      grading/                     # <task>/ images transcripts evaluations reports summary.xlsx
    2026S1-大学物理-classA/
      roster/  sheets/  grading/
    _archived/                     # 毕业的班（不再使用但可查档）
  exports/                         # zip 导出包暂存
  packs/                           # D89：作业包 <id>.pack.json（一次分层作业全部作业纸的集合）
  assets/                          # D87：教师手工维护的静态素材（workspace 优先）
    watermark/                     #   水印图片（PWA 经引擎上传落盘；教师也可手工放）
      styles/<样式名>.json          #   命名水印样式（default 单选；与作业纸 style_ref 关联）
    fonts/                         #   可选：用户字体覆盖（simsun.ttc / simkai.ttf / wqy-*.ttc）
    report/                        #   预留：报告模板/封面/落款 logo
  settings.local.json              # 教师私有（不入库）：xxt 白名单/附件名单/class_map、watermark、LLM 非敏感项
  settings.local.secrets.json      # 教师私有（不入库，0600）：LLM providers 的 api_key（每 provider 一份）
  .runtime/                        # 引擎环境（不入库，绝不打包）——05-D14
    venv/                          # .venv（引擎依赖）
    cache/                         # UV_CACHE_DIR 重定向
    browsers/                      # PLAYWRIGHT_BROWSERS_PATH 重定向（Playwright 内核）
```

要点：
- **kb 全局共享但有章节范围覆盖**：不同专业班级用同一题库即可（分层标签
  从题库 per-chapter 抽取），若需班级间差异化克隆，用 `assist kb branch`
  建立副本到某班级目录（后续阶段再议是否引入）；
- **班级子目录命名约定**：`<学期批号>-<课程简称>-<班级名>`（见上文示例），
  由 PWA 新建向导与 CLI `assist class new` 都按此生成，保证可排序可筛选；
- **命名中允许使用真实班级名**（本机数据，不入库），push 前由
  check-secrets.sh 兜底拦截；
- workspace 位置不写死：默认 `~/.assignment-assistant/`（跨平台），支持
  `settings.local.json` 或 `--workspace` 指定任意路径，便于云盘同步方案。
  **密钥拆分（D86）**：api_key 只写 `settings.local.secrets.json`（0600），PWA 仅掩码回显，
  日志/journal 只记 provider 名与 base_url host，绝不记 key。
- **素材目录解析（D87）**：`--assets-dir` 显式 > `<ws>/assets`（存在 `watermark/` 或 `fonts/` 时）
  > 引擎内置 `engine/assets`；字体注册优先 `<ws>/assets/fonts/`。语义 = 教师手工维护的静态素材；
  运行期上传（通知/作业附件、临时文件）**不放这里**（仍在 `<xxt_home>/notice-uploads`、`<ws>/tmp/`）；
  题图继续留 `kb/fig/`（随题库走）。
- **水印样式与关联（D87）**：命名样式存 `<ws>/assets/watermark/styles/<样式名>.json`
  （schema：`{name,enabled,pageText,default,items:[{image,pos,ratio,alpha}],updatedAt}`）；
  `items[].image` 用**相对 assets_dir** 的 `watermark/<文件名>`（引擎兼容旧值 `assets/watermark/x`）。
  解析优先级：`作业纸 watermark.items` > `watermark.style_ref`（随类型/tag 走）> 默认样式
  （`default=true` 或名为 `_default`）> 引擎内置三槽。PWA 上传经 `POST /watermark/upload` 落
  `<ws>/assets/watermark/`；离线时 dataURL 仅本浏览器预览有效（界面明确提示）。

## D89：作业包与答案多版本（数据模型）

### 作业包 `<ws>/packs/<id>.pack.json`

作业包 = **一次分层作业全部作业纸的集合**（每张对应一个 tag/类型），**引用** padId
（作业纸是唯一真源，包只做组织），纯设计态（不含发布信息）。

```jsonc
{
  "schema": 1,
  "id": "2026S1-化工25-chap10",
  "name": "第10章分层作业",
  "term": "2026S1",
  "class_dir": "classes/2026S1-大学物理-化工25",
  "pads": [ { "padId": "202610-chap10-321", "tag": "distinguish" },
            { "padId": "202610-chap10-322", "tag": "copy" } ],
  "updatedAt": "2026-10-16 10:00:00"
}
```

- PWA 设计页最上方「作业包」栏：选择/新建/保存/删除；③段「作业纸清单」**只显示所选包内**作业纸；
- 「仅保存」保存**当前这一张**作业纸，并自动纳入当前包；
- AI 辅助批阅 ③区可选**作业包**（多作业纸按 tag 自动匹配学生）；
- CLI：`assist pack list|show|save|delete`；serve：`GET /packs`、`GET /pack/<id>`、`POST /pack`。

### 答案多版本 `<ws>/kb/solutions/<qid>.json`

```jsonc
{
  "qid": "chap04-1", "kb": "problems", "chap": "chap04",
  "versions": [
    { "id": "v1", "text": "...", "source": "human", "model": "", "at": "...", "pinned": false },
    { "id": "v2", "text": "...", "source": "ai", "model": "qwen-max", "at": "...", "pinned": true }
  ]
}
```

- **追加不覆盖**；`pinned` 至多一个 = 生效答案（"最新置顶版"）；无版本文件回落 xlsx `solution` 列（兼容旧数据）；
- 作业包/批阅**实时读最新置顶版**（`flow.expand_items` / `inputs._questions_of` 经 `effective_solution`）；
- 题库编辑器 solution 单元格为**预览键** → 弹窗（题+答案，多版本勾选/置顶）；
- AI 作答（AI 辅助批阅 ⑦区 / CLI `kb ai-solve` / `POST /kb/ai-solve`）：**不覆盖**、新增版本、标 source=ai + model + 时间戳；
- CLI：`assist kb solution list|add|pin|rm`；serve：`GET /kb/solutions[/<qid>]`、`POST /kb/solution`。

## 运行期目录（xxt 工件，D84–D86 新增）

```
<xxt_home>/
  pages/review/<classId>/<workId>/     # 批阅下载：作答图 + students.json（workAnswerId/分数/两栏批语）
  grade-drafts/<classId>/<workId>.json # 本地批阅草稿（D85/D86：人工与 AI 草稿；score/comment/images）
  grade-uploads/                       # 回传 receipt + 过程截图
  work-drafts/                         # 新建作业失败现场截图
```

workspace 侧批阅产物：

```
classes/<class_dir>/grading/<taskId>/
  plan.json          # 批阅任务清单（D86：学生↔tag↔题目/答案↔作答图↔workAnswerId）
  transcripts/       # 转录 JSON（markdown + quality）
  evaluations/       # 评阅 JSON（total_score/per_question_scores/feedback_md/tag…）
  reports/           # 报告 md/html/**png**（A4 宽、长图；AI/人工标注）；summary.xlsx
  journal.jsonl      # 运行记录（D8）
  diagnostics.jsonl  # D86：LLM 调用失败/异常诊断（provider/模型/错误原文）
```

## 密钥与隐私安全（D86 拆分 + D87 加固）

**数据流**：PWA（浏览器）→ 本机引擎 `http://127.0.0.1:8601`（JSON）→ `settings.local.secrets.json`（0600）。
引擎调用 LLM 时才读 key，经 `Authorization: Bearer` 发给服务商。

**已落实的防护**：
- 存储隔离：key 只写 `settings.local.secrets.json`（0600），非敏感配置写 `settings.local.json`；
- 回显掩码：PWA/CLI 只见 `sk-****1234`（`providers.public_config`，`save_provider` 返回值剔除 `api_key`）；
- 日志脱敏：LLM 报错只回 `status + body[:400]`，绝不带 Authorization 头；`BATCH-README.txt` 用 `$KEY` 占位；
- 仓库隔离：`.gitignore` 拦 `settings.local*.json`/`*.key`/`*apikey*`/`.env`；CI 跑 `tools/check-secrets.sh`
  （路径红线 + 已知厂商前缀 + 异形高熵 key 启发式 + 真实姓名），本地可随时手跑。

**需教师注意的边界风险**（代码挡不住，靠环境自律）：
1. **`--lan` 模式是明文 HTTP**：绑定 `0.0.0.0`（带一次性 `?token=` 鉴权），同网段可抓包。
   **不要在不可信网络用 `--lan` 输入/使用 API key**；本机模式（默认 `127.0.0.1`）风险最低。
2. **云盘同步 workspace**：`settings.local.secrets.json` 会被一起同步上云。若 workspace 放在网盘，
   请在同步规则中**排除 `settings.local.secrets.json`**（或用不进入云盘的本机目录作 workspace）。
3. **浏览器输入瞬间**：key 在 DevTools → Network 可见；请在可信设备上操作，勿在公共/共享电脑填写。
4. 扫描器是**兜底**而非唯一防线：非标准格式的 key 尽量靠"永不入库"的纪律保障。

**作业任务任务包（05-D2 的固化产物）**：

```jsonc
{
  "id": "2026S1-classA-chap10-1",
  "target_tag": "distinguish",            // 可选：D23 变体编排——绑定该作业包服务的分层
                                          // （缺省由 items 唯一 tag 推断；混合 tag 包必须显式绑定）

  "class_dir": "classes/2026S1-大学物理-classA",
  "course": "大学物理C1", "class": "classA", "term": "2026S1",
  "layout": { "orientation": "portrait" | "landscape",
              "per_page": 1..12,                 // D61：每页题数 N
              "grid_rows": 2, "grid_cols": 2,    // D61 可选：显式网格；缺省时走旧兼容语义
              "header": {"title": "..."}, "footer": {...} },
  "items": [ { "kb": "problems", "chap": "chap10", "ids": [...],
               "tag": "distinguish" }, ... ],
  "watermark": { "enabled": true, "style": "default" },
  "grade": {                                   // 该批可留空=仅出作业纸
    "steps": ["download","transcribe","evaluate","report","upload"],
    "students": { "mode": "tag", "tag_value": [...] },
    "models": { "transcription": "...", "evaluation": "..." }  // 不含 key
  },
  "journal": [ { "ts": "...", "run_id": "...", "steps_done": [...],
                 "log": "grading/.journal/....log" } ]  // 执行历史(debug 用)
}
```

（任务包兼任三个角色：CLI 参数、Web 按钮的后台实体、可携带/可重跑
执行记录，见 05-D2。）

## 2. 脱敏规范（仓库红线）

**绝不允许进入 git 的内容：**
- 题库真数据（kb xlsx/json 实题与题图）——仓库只放 `kb/examples/` 合成示例；
- 学生数据 roster/grading 中的一切内容（名单、成绩、作业图片、转录
  文本、评语、打分）；
- course/class/term 的真实值组合（示例中一律占位如 `class-2026-01`）；
- apikey/token/cookie/.env/state.json/xuexitong-ids.json 真实值。

**允许进仓库：** 代码、空 schema、README/文档、合成示例、
`install.ps1/sh` 安装脚本（含国内镜像源配置，见 05-D10）。

工具性保障：
- `.gitignore` 维护平台黑名单（kb 真数据、roster/、grading/、.env 等）；
- `tools/check-secrets.sh` 在 commit/CI 扫描（key 正则 + 真实姓名/班级字样）；
- 真实数据仅存在教师本机 workspace 与导出包中，均被 ignore。

## 3. 协议与第三方引用

- 本仓库 `LICENSE` = MIT。
- 引擎侧依赖（pyproject）：click、openpyxl、pandas、reportlab、loguru、
  httpx、playwright（Apache-2.0）等；
- 前端依赖在 package.json；`docs/NOTICE.md` 汇总各库协议（reportlab BSD、
  openpyxl MIT、pandas BSD、SheetJS Apache-2.0 等）；
- 中文字体 simsun.ttc / simkai.ttf 有版权限制，**字体文件不进仓库**，
  README 说明教师自备字体与放置路径。
