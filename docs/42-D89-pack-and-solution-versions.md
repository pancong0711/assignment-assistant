# D89 任务需求单：作业包（pack）实体 + 题库 solution 多版本/AI 作答 + 样式反查 + SW 修复

> 日期：2026-10-16
> 状态：已拍板（讨论定调），按 §6 分期执行。
> 关联：`docs/40-D87-...`（水印样式库；本单在其上加"样式↔多作业纸"反查）、
> `docs/39-D86-...`（AI 批阅引擎/端点）、`docs/04`（数据模型）、`docs/41-D88`（AI 选项卡六区）。

## 1. 背景与问题（2026-10-16 讨论）

1. **术语混同**：`taskpad` 现被叫「作业纸」，但一次分层作业需要**多张作业纸**（每类型/tag 一张）。
   当前 `taskpadStore.saved` 是**扁平散装清单**，不表达"这些作业纸属于同一次作业"。
   AI 批阅面板的"选择作业包(taskpad)"下拉实际选的是**单张作业纸**，命名误导。
2. **缺"保存/载入作业包"**：设计页只有「仅保存」= 保存**当前这一张**作业纸；无整包的新建/保存/载入。
3. **solution 单列无法承载多版本**：kb xlsx `solution` 是单字符串列（`kb_io.py:17`），
   无法记录"AI 作答 / 多模型 / 多时间 / 置顶"等长期演进信息。
4. **水印样式只能一对一**：`style_ref` 是作业纸字段；缺"一个样式应用到多张作业纸"的反查 UI。
5. **SW 缓存名固定 `assignment-assistant-v1`**：升级后旧用户可能滞留旧包（潜在长期坑）。
6. **D87 PWA 未部署**：本地 6 个提交未 push → 线上看不到水印样式库（本次已 push 修复）。

## 2. 概念定义（用户拍板）

- **作业包（pack）** = 一次分层作业的**全部作业纸的集合**；每张作业纸对应一个 tag/类型；
  "最简、不可约"集合 = 一次作业所需全部类型；整个班（含重复类型）= 该班的包（集合，含重复项）。
- **包内清单** = 该包中作业纸的展开视图（**只显示所选包内的作业纸**，不再显示全部）。
- 包的层级（UI 从大到小）：**① 作业包（最上）→ ② 包内作业纸列表 → ③ 单张作业纸版式与头部 → ④ 内容/预览/输出**。

## 3. 设计决策（用户拍板 + 默认推荐）

| 项 | 决定 |
|---|---|
| 包存储 | **落盘** `<ws>/packs/<id>.pack.json`（与 kb/assets 一致；便于长期维护/跨设备/去敏） |
| 包↔作业纸关系 | 包**引用** padId（作业纸是唯一真源，包只做组织）；删测量纸 → 悬空引用告警，不静默丢 |
| 包语义 | **纯设计态**（不含 courseId/classId/workId；发布信息归学习通/AI 批阅侧） |
| solution 存储 | **独立文件** `kb/solutions/<qid>.json`（xlsx `solution` 列降级为"汇总/兼容"，UI 以版本库为准） |
| solution 读取 | **实时从 kb 读"最新置顶版"**；作业包 items 内联 solution 视为旧快照，出批阅计划时优先实时读 |
| AI 作答语义 | **不覆盖**；每次 AI 作答**新增一版**（`source=ai` + `model` + `at` 时间戳）；人可**置顶**任一版 |
| AI 相关入口 | **全部集中到「AI 辅助批阅」选项卡**（含题库 AI 作答），命名/管理统一 |
| 样式↔多作业纸 | 样式侧支持多选"应用到哪些作业纸"（写入各作业纸 `style_ref`；冲突以样式侧显式选择为准） |

## 4. 数据模型

### 4.1 作业包 `<ws>/packs/<id>.pack.json`

```json
{
  "id": "2026S1-化工25-chap10-分层",
  "name": "第10章分层作业",
  "term": "2026S1",
  "class_dir": "classes/2026S1-大学物理-化工25",
  "pads": [
    { "padId": "202610-chap10-321", "tag": "distinguish" },
    { "padId": "202610-chap10-322", "tag": "copy" }
  ],
  "note": "",
  "updatedAt": "2026-10-16 10:00:00",
  "schema": 1
}
```

### 4.2 solution 版本库 `<ws>/kb/solutions/<qid>.json`

```json
{
  "qid": "chap04-1",
  "kb": "problems", "chap": "chap04",
  "versions": [
    { "id": "v1", "text": "...", "source": "human", "model": "", "at": "2026-01-01 09:00", "pinned": false },
    { "id": "v2", "text": "...", "source": "ai", "model": "qwen-max", "at": "2026-10-16 10:00", "pinned": true }
  ]
}
```

- `versions[]` 追加不可覆盖；`pinned` 至多一个（最新置顶版 = 生效答案）。
- 无版本文件时回落 xlsx `solution` 列（兼容旧数据）。

## 5. 端点 / CLI

| 类型 | 名称 | 说明 |
|---|---|---|
| serve | `GET /packs` / `GET /pack/<id>` | 列出/读取作业包 |
| serve | `POST /pack` | 保存/删除作业包（`action`） |
| serve | `GET /kb/solutions/<qid>` | 读题目全部版本 |
| serve | `POST /kb/solution` | 追加/置顶/删除某题的某个版本 |
| serve | `POST /kb/ai-solve` | 题库 AI 作答（选题 → LLM 作答 → 写回新版本；默认不覆盖） |
| CLI | `assist pack list|save|delete|show` | 作业包管理 |
| CLI | `assist kb solution list|add|pin|rm --qid` | 版本管理 |
| CLI | `assist kb ai-solve --chap --ids --provider --model` | 题库 AI 作答（dry-run 默认） |

## 6. 分期实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| N8 | 部署：push 本地 6 提交，线上出现 D87 | git push | ✅ |
| N7 | 修复 SW 缓存：缓存名随构建版本走 | `app/public/sw.js` + 构建注入 | ✅ |
| N1 | 作业包实体：engine `packs.py` + serve/CLI + PWA store + 设计页顶部「作业包」栏（选择/新建/保存/载入） | `engine/src/assist/packs.py` + `serve.py` + `cli.py` + `app` store/UI + 单测 | ⏳ |
| N2 | 包内清单：③段清单改为"所选包内作业纸"；作业纸操作下沉 | `SheetPreviewSection.vue` + 设计页结构 | ⏳ |
| N3 | solution 多版本：`kb/solutions/` 读写 + 置顶 + xlsx 兼容 + 实时读取 | `engine/src/assist/kb/solutions.py`（或 `files/solutions.py`）+ 单测 | ⏳ |
| N4 | 题库编辑器：solution 预览键 → 弹窗（题+答案，多版本勾选/置顶） | `KbEditorView.vue` | ⏳ |
| N5 | 题库 AI 作答：入口在 AI 辅助批阅；`/kb/ai-solve` + CLI；不覆盖/多版本/标 ai+model+时间 | `grading/` 新增 + `AiGradingPanel.vue` | ⏳ |
| N6 | 水印样式一关联多作业纸：样式侧多选应用（写各作业纸 style_ref） | 样式 UI + 端点 | ⏳ |
| N9 | 文档（docs/04/13/15/39/40）+ 验证 + 去敏 push | 文档 + CI | ⏳ |

## 7. 验收

- 设计页顶部有「作业包」栏：可新建/选择/保存/载入；**清单只显示所选包内**的作业纸；
- 作业包落盘 `<ws>/packs/`，删除包内引用的作业纸有告警；AI 批阅面板改为"选作业包"（按 tag 自动挑作业纸）；
- 题库 solution 支持多版本：AI 作答**不覆盖**、带 model+时间戳、可置顶；作业包/批阅**实时读置顶版**；
- 题库编辑器 solution 单元格为**预览键**，弹窗可勾选查看不同版本并置顶；
- 一个水印样式可**应用到多张作业纸**；
- SW 升级后不再滞留旧包；
- engine pytest / PWA build+selfcheck / 脱敏扫描 全绿。
