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
  classes/                         # 所有 班级×学期 目录并列放这里（05-D6）
    2025S2-大学物理-化工25/
      roster/                      # 点名册/成绩/分组结果
      sheets/                      # 作业纸任务包 + 生成产物 out/*.pdf
      grading/                     # <task>/ images transcripts evaluations reports summary.xlsx
    2026S1-大学物理-classA/
      roster/  sheets/  grading/
    _archived/                     # 毕业的班（不再使用但可查档）
  exports/                         # zip 导出包暂存
  settings.local.json              # 教师私有：LLM apikey、引擎地址、默认班级（不入库）
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

**作业任务任务包（05-D2 的固化产物）**：

```jsonc
{
  "id": "2026S1-classA-chap10-1",
  "class_dir": "classes/2026S1-大学物理-classA",
  "course": "大学物理C1", "class": "classA", "term": "2026S1",
  "layout": { "orientation": "portrait" | "landscape", "per_page": 1|2,
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
