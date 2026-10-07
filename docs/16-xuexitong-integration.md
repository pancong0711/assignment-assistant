# 16 — 学习通整合任务需求单（阶段6）

> 状态：需求已确认，准备执行；先只读核对，后写操作。
> 原则：先读后写、先单后批、先预览后提交、先 CLI 后 PWA。
> 安全底线：只读阶段禁止发布/上传；发布公告/作业仅使用测试内容，班级必须人工确认。

## 1. 目标主链

登录/会话 → 读取课程班级学生 → 读取作业/公告 → 下载学生作业图片 →
本地批阅 → 上传批阅报告与打分 → 发布公告/通知 + 作业纸附件。
发布“具体学习通作业/题目”本阶段搁置，教师手动完成，后续再评估。

## 2. 已确认决策

1. **发布公告/通知 + 作业纸附件**：在 PWA 学习通选项卡中实现。
2. **上传批阅**：写入作业批阅入口，填分数，评语内容与批阅报告一致。
3. **登录方式**：优先扫码登录；二维码由 engine 生成图片发给教师扫描。
4. **上传确认**：默认自动；逐条预览后续与 AI 辅助批阅一起做。
5. **不下载学习通成绩**：本地 roster/成绩导入链继续独立，不因学习通整合而改变。
6. **发布极度谨慎**：只发测试公告/作业；班级、课程、标题、附件、范围均需人工确认。
7. **先只读核对**：登录成功后先提取课程/班级/学生/作业/公告信息给教师核对；
   确认后再进入下载、上传、发布阶段。

## 3. 本期范围

### In Scope
- 扫码登录、会话复用（本地 profile，不入库）。
- 读取课程列表、班级列表、学生名单与内部 id。
- 读取已发布作业列表、提交状态、未交/已交名单。
- 读取已发布公告/通知列表与详情/附件。
- 下载学生作业图片（原图/附件，批量、增量、失败重试）。
- 本地批阅结果上传：评语、批阅报告图片、分数。
- 发布公告/通知（含作业纸附件）。
- CLI 超集、JSON/JSONL 输出、`--dry-run`。
- PWA 学习通选项卡：登录状态、任务列表、只读预览、上传/发布前的确认 UI。

### Out of Scope（本阶段）
- 在学习通中创建具体作业/题目。
- 自动同步学习通成绩到本地。
- 公告定时发布、模板管理、高级排版。
- 雨课堂等其它平台（保留适配接口，不实现）。

## 4. 建议推进阶段

| 阶段 | 内容 | 写操作 |
|---|---|---|
| P0 | 盘点 legacy `xuexitong` 模块；定义 CLI/JSON/目录契约；搭建离线 fixture | 无 |
| P1 | 扫码登录 + 课程/班级/学生读取 | 无 |
| P2 | 作业/公告读取 + 提交状态 + 只读核对 | 无 |
| P3 | 下载学生作业图片/附件；增量、去重、重试、未交清单 | 无 |
| P4 | 接入 `assist grade` 的 download/upload；先 dry-run，再单生，再批量 | 上传 |
| P5 | 发布公告/通知 + 作业纸附件；测试内容 + 人工确认 | 发布 |
| P6 | 限流、版本适配、PNG 报告、`serve --https`、真账号验收 | — |

## 5. 建议 CLI 形态

```text
assist xxt login
assist xxt courses
assist xxt classes --course <id|name>
assist xxt students --course <id> --class <id>
assist xxt assignments list --course <id>
assist xxt announcements list --course <id>
assist xxt download --assignment <id> --out <dir>
assist xxt publish announcement --course <id> --class <id> --file <html|pdf> --dry-run
assist xxt publish assignment --course <id> --class <id> --file <html|pdf> --dry-run

assist grade --task <taskpad.json> --download
assist grade --task <taskpad.json> --upload
```

所有命令优先输出 JSON/JSONL；写操作默认 `--dry-run`，真正执行需显式 `--yes`。
发布公告/作业必须附加 `--confirm-class <class_id>` 或交互确认。

## 6. 数据与目录约定

```text
classes/<class>/
  xxt/
    profile/                 # 浏览器 profile（不入库、不打包）
    ids.json                 # 课程/班级/学生/作业 id 字典（本地）
    assignments.json         # 只读作业列表缓存
    announcements.json       # 只读公告缓存
    submissions/<work>/      # 下载的学生图片/附件
    uploads/<work>/          # 上传前报告/评语/分数快照
    xxt-journal.jsonl        # 下载/上传/发布审计日志
```

## 7. 安全与幂等

- cookie/profile 只存本机，绝不入 git、绝不上传。
- 下载/上传限流，逐条记录 run_id + 学生 + 作业 + 动作。
- 上传幂等：已批阅时默认跳过，覆盖需人工确认。
- 发布公告/作业：双确认；默认只发测试对象。
- 所有写操作保留本地快照，支持回滚/追溯。
- 版本适配：沿用 legacy `submit_v2/v3` 多套上传策略，选择器失败自动降级。

## 8. 验收标准

1. 登录成功后能列出课程、班级、学生、作业、公告，且与网页一致。
2. 可批量下载某次作业的已交图片，未交名单准确，失败有日志。
3. 可对单名学生 dry-run 上传批阅，确认后批量上传；分数/评语正确，无重复。
4. 可向教师确认过的测试班级发布一条测试公告 + 作业纸附件。
5. 离线 fixture 测试通过；真账号验收一遍只读 + 下载 + 单生上传 + 测试发布。
6. CLI 与 PWA 同接口；PWA 不可用时 AI agent 可用 CLI 完成同一流程。

## 9. 待教师确认/配合

- 扫码窗口（engine 输出二维码图片）。
- 只读核对结果：课程、班级、学生、作业、公告。
- 测试发布：班级、标题、正文、附件、发布范围。
- 真实账号验收窗口。
