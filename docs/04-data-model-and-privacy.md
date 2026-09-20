# 04 — 数据模型 与 仓库脱敏规范

## 1. 数据契约（教师本地目录，第一版草案）

```
<workspace>/
  kb/                 # 题库（xlsx 为 source of truth，见 05-D3）
    problems.xlsx  copy.xlsx  qa.xlsx  distinguish.xlsx
    innovation.xlsx  translation.xlsx
    .history/         # 写盘前自动快照（版本备份）
    fig/              # 题图（xlsx 中 img_path 为相对路径引用）
    export/           # 引擎导出的 JSON 副本（交换/AI 阅读/diff 基准）
    examples*/        # 合成示例（唯一允许入库的部分）
  roster/             # 点名册/成绩/分组（xlsx 或 json）
  sheets/             # 作业纸任务配置与产物
    2026S1-chap10-1.json
    out/*.pdf
  grading/
    <task>/  images/ transcripts/ evaluations/ reports/ summary.xlsx
  exports/            # zip 导出包
  settings.local.json # 教师私有：LLM apikey、端口、默认班级（不入库）
```

作业任务 `sheet task JSON`（旧 assignment_cfg 与 2601 task 合并的方向）：

```jsonc
{
  "id": "2026S1-chap10-1",
  "course": "大学物理C1", "class": "class-2026-01", "term": "2026S1",
  "layout": { "orientation": "portrait" | "landscape", "per_page": 2, "header": {...}, "footer": {...} },
  "items": [ { "kb": "problems", "chap": "chap10", "ids": [...], "tag": "distinguish" }, ... ],
  "watermark": { "enabled": true, "style": "default" },
  "grade": {
    "steps": ["download","transcribe","evaluate","report","upload"],
    "students": { "mode": "tag", "tag_value": [...] },
    "models": { "transcription": "...", "evaluation": "..." }   // 不含 key
  }
}
```

## 2. 脱敏规范（仓库红线）

**绝不允许进入 git 的内容：**
- 题库真数据（kb xlsx/json 实题与题图）——仓库只放 `kb/examples/` 合成示例；
- 任何学生数据：名单、成绩、作业图片、转录文本、评分数值、批阅文字；
- 任何 LLM 评测真题解答文本；
- apikey/token/cookie/.env/state.json/xuexitong-ids.json 的真实值；
- 学习通课程/班级/作业 ID 字典真值（示例用占位）。

**允许进仓库：** 代码、空 schema、README/文档、合成示例（假学生"张三"等）、
测试 fixtures（合成数据）。

工具性保障：
- `.gitignore` 顶层列黑名单（kb/*.json、roster/、grading/、.env 等
  —— 只允许显式 `!` 白名单例外）；
- `tools/check-secrets.sh` 在 CI 中扫描（key 正则 + 关键词
  如「真实姓名」「真实班级名」等）后再允许 push；
- 真实数据只在 `_legacy/`（本机）与教师导出包中，均被 ignore。

## 3. 协议与第三方引用

- 本仓库 `LICENSE` = MIT。
- 引擎侧主要依赖（pyproject 声明）：click、pandas、openpyxl、
  reportlab、loguru、httpx；Playwright（浏览器自动化，Apache-2.0）。
- 前端依赖按 package.json 声明；在 `docs/NOTICE.md` 汇总各库协议
  （reportlab BSD、openpyxl MIT、pandas BSD 等），README 中给指引。
- 中文字体：旧项目带 simsun.ttc / simkai.ttf（宋体/楷体有版权限制），
  **字体文件不进仓库**，README 说明教师自备字体与放置路径。
