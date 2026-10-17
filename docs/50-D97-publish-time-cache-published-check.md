# D97 任务需求单：发布作业——默认时间(now+5min/now+5days) + 题干本地缓存 + 逐班「已发布」判定

> 日期：2026-10-17
> 状态：**已拍板**（讨论定调），按 §6 执行。
> 关联：`docs/48-D95`、`docs/49-D96`；engine `xxt/work.py`（`list_works`/`published_library_ids`/`publish_work`/`work_detail`）、
> PWA `PublishView.vue`。

## 1. 问题查证（2026-10-17）

| # | 现象 | 根因 |
|---|---|---|
| Q1 | 默认 18:00 开始，若已过 18:00 则=now，提交时可能"开始<当前"被平台拒 | `defaultTimes()`：`start = 今天18:00（<18点）否则 now`；平台前端 `checkQuestion/publicWork` 校验"开始日期不能小于当前日期"。CLI 同理 |
| Q2 | 勾选作业后**总先提示"题干未读取到"，过一会儿才显示** | `works` 缓存**只存作业列表**（`list_works.text`），**不含题干**；题干来自另一个浏览器调用 `work_detail`（开编辑器 6s+）。`loadDetail` 先清空后填 → 先空后现 |
| Q3 | 其他班（旧届）发过、**当前新班未发**，却提示"已发布禁止重复" | `list_works` 的 `publishedClasses` 仅填**查询时那一个班**（`[class_id] if wid in published`，`published`=该班已发集合）；PWA `workPublished` 只看**基准班** → 基准班发过即误报；且 `publishedClasses` 信息不完整（未含全部目标班） |

## 2. 拍板结论

1. **默认时间**：`start = now + 5 分钟`（含秒），`end = now + 5 天`（同时刻）；PWA 与 CLI 统一；
2. **题干缓存**：本地缓存题干（按 `workLibraryId`）+ **先显缓存、后台刷新**（`loadDetail` 不再先清空）；
3. **已发布判定 = 逐目标班**：对每个**勾选的目标班**分别查"该班是否已发此作业"；
   - UI：作业列表**逐班**标注（哪些勾选班已发/未发）；
   - 发布：**自动跳过已发布班**，只对未发布班发布，并提示"班X已发过已跳过"；
   - 若**全部**目标班都已发 → 才提示"已全部发布，禁止重复发布"。

## 3. 设计

### 3.1 默认时间（Q1）
- `defaultTimes()`：`start = fmt(now + 5min)`；`end = fmt(now + 5days)`；`lateDeadline` 保持"end+2天18:00"或 `end+2d`；
- **PWA** + **CLI**（`work-publish` 缺省 start/end 时）同口径：`start = now+5min`，`end = now+5days`；
- `refreshStale` 逻辑不变（过期则回默认）。

### 3.2 题干缓存（Q2）
- **PWA 本机缓存** `xxt-work-detail-cache-v1`：`{ workLibraryId: {title, stemHtml, used, at} }`（localStorage）；
- `loadDetail`：命中缓存 → **立即显示**（title/stem/used），随后**后台** `fetchXxtWorkDetail` 刷新并更新缓存；
- 未命中 → 显示"（题干读取中…）"占位（非"未读取到"），返回后填入并缓存；
- 可选：`works` 列表里若平台已带题干摘要，直接预填。

### 3.3 逐班「已发布」判定（Q3）
- **引擎**：`list_works(..., class_id)` 保持；新增/复用"**逐目标班**查 `published_library_ids`"的聚合：
  - serve `/xxt/work/list` 或新端点 `POST /xxt/work/published`：入参 `{courseId, classIds:[...], cpi, workLibraryIds:[...]}` →
    返回 `{workLibraryId: {classId: bool, ...}}`；
  - 或 PWA 对每个目标班各调一次 `published_library_ids`（真实调用需浏览器，**逐个班代价高**）→ 倾向**引擎聚合一次**（内部对每班查一次，或尽量合并）。
- **PWA `workPublished(w)`** → 改 `workPublishedForPicked(w)`：
  - `已发班 = pickedClasses.filter(c => w.publishedClasses.includes(c.classId))`（若 publishedClasses 为"各班合并"）；
  - 需引擎把 `publishedClasses` 填成**全部目标班中已发布的那些**（而非仅基准班）；
- **发布时**：`classIds = 未发布的勾选班`；若为空 → 提示"全部已发布"；否则发布这些班，并在日志提示"跳过已发布班：…"。

## 4. 涉及改动

| 模块 | 改动 |
|---|---|
| `app/src/views/PublishView.vue` | 默认时间 now+5min / now+5days；题干本地缓存+先显后刷；逐班已发布判定/跳过 |
| `engine/src/assist/xxt/work.py` | `list_works` 的 `publishedClasses` 支持**多目标班**（或新增聚合查询）；`work_detail` 不变（慢，靠 PWA 缓存） |
| `engine/src/assist/serve.py` | `/xxt/work/list` 支持 `classIds`（返回逐班已发布）；或新增 `/xxt/work/published` |
| `engine/src/assist/xxt/cli.py` | `work-publish` 缺省时间 now+5min / now+5days |
| `app/src/lib/engineClient.ts` | `fetchXxtWorkList` 支持多班已发布返回 |
| 文档 | docs/04/13/15/49/50 |

## 5. 真实性与性能注意
- 逐班 `published_library_ids` 每次要开浏览器 → **多班代价高**；优先**一次页面内**取多班已发布（若平台支持），否则 PWA 缓存 + 有限并发；
- 题干 `work_detail` 无法批量化 → 靠**本地缓存**显著改善（Q2）。

## 6. 分期实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| W1 | PWA 默认时间 now+5min / now+5days（含 CLI） | `PublishView.vue` + `cli.py` | ⏳ |
| W2 | 题干本地缓存 + 先显缓存后刷新 | `PublishView.vue` | ⏳ |
| W3 | 引擎：逐目标班「已发布」聚合（`list_works`/新端点） | `xxt/work.py` + `serve.py` | ⏳ |
| W4 | PWA：逐班已发布标注 + 发布跳过已发班 + 提示 | `PublishView.vue` + `engineClient.ts` | ⏳ |
| W5 | 文档 + 验证 + 去敏 push | 文档 + CI | ⏳ |

## 7. 验收

- 默认开始时间 = 现在 + 5 分钟、截止 = 现在 + 5 天；发布不再因"开始<当前"被拒（PWA/CLI 一致）；
- 选作业后**立即**显示（有缓存时）上次读到的题干，随后后台刷新；无缓存显示"读取中…"而非"未读取到"；
- 同一课程内：某作业**只在旧届班发过**，勾选**当今新班**时**不再**误报"已发布"；逐班显示已发/未发；
- 发布时**跳过已发布班**并提示；全部已发才拒绝；
- engine pytest / PWA build+selfcheck / 脱敏扫描 全绿。
