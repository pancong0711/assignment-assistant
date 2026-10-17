# D95 任务需求单：通知/作业发布——多班勾选 + 白名单联动（先真机验证）

> 日期：2026-10-17
> 状态：**已拍板**（讨论定调），先真机测试后做 PWA 改造。
> 关联：`docs/31-D79...`（通知/发布）、`docs/24-D73...`（写操作白名单）、`docs/04`；
> 引擎 `xxt/notice.py`（`send_notice_from_spec`）、`xxt/work.py`（`publish_work`）、`xxt/allowlist.py`。

## 1. 现状（代码核对）

| 环节 | 现状 |
|---|---|
| 白名单 | `PublishView.vue` 上方「写操作白名单」按课程折叠勾选 → `settings.local.json → xxt.write_allowlist`；班级下拉里非白名单班**显示但 disabled（灰）** |
| 发通知目标班 | **单选下拉** `noticeTarget`；`sendNotice` 只构造 1 个班 |
| 发作业目标班 | **单选下拉** `workTarget`；引擎 `publish_work(course_id, class_id, …)` **单班** |
| 引擎通知 | `send_notice_from_spec` **已支持多课/多班**（`courses[].classes[]`，一次注入多接收班）✅ |
| 引擎作业 | `publish_work` **单班**；平台"发放对象"页按 `classData`+`class_check` 点选 ❌ |

## 2. 拍板结论

1. **通知多班**：同一标题/正文/附件**一次发给多个勾选班**（不做逐班变量替换）；
2. **作业多班**：平台支持"依次发布多班"（本次真机验证）；实现上引擎扩展一次发布多班，或 PWA 逐班循环；
3. **白名单联动**：目标班可勾选列表 = **只列白名单内的班**（方案 A；非白名单班不出现）；白名单由页面上方「写操作白名单」维护；
4. 课程维度：通知允许跨课勾选；作业若跨课则逐课处理。

## 3. 先做的真机测试（本次，用户核验）

**目标**：用目标课程 **「大学物理知识点拾遗（by pc）」** 存在的两个班（**默认班级** + **新建班级2**）验证：
- **T-a 多班发通知**：一次调用把同一通知发给两个班 → 平台两端都能看到；
- **T-b 多班发作业**：一次调用把同一作业发布到两个班（新建简答草稿或已有库作业）→ 两端都发布成功；
- 均在真机、白名单内、`--confirm-send` 语义下执行；dry-run 先看截图。

> 说明：本测试在**引擎/CLI 层**做（不经 PWA），用于确认平台行为（多班能否一次发）；
> 测试通过后再做 PWA 改造（D95 §4）。

## 3bis. 真机验证结论（2026-10-17，已完成）

目标：课程 `217801417`「大学物理知识点拾遗（by pc）」的 **默认班级 `40009084`** + **新建班级2 `157567052`**。

- **T-a 多班通知** ✅：一次 `send_notice_from_spec` 注入两班收件人（dry-run 校验 `got_ids==want_ids` 通过），
  真发 `sent`、平台 200、receipt 两班都在。**平台支持一次发多班通知。**
- **T-b 多班作业** ✅：一次 `publish_work(class_ids=[两个班])` → 平台返回
  `{"msg":"发布成功","workRelationArray":[{"classId":40009084,"workId":57084818},
  {"classId":157567052,"workId":57108320}],"status":true}`。**平台支持一次发布多班作业。**
- **踩坑（已固化）**：
  1. 平台发布页前端 `checkQuestion()` 依赖隐藏域 **`#classid`**；**多选时页面不自动赋值** →
     点「发放」前需**显式补设 `#classid`**（否则 AJAX clazzid 空、校验不过、不触发提交）。已在引擎加。
  2. 前端校验"**开始日期不能小于当前日期**"：`--start` 必须晚于当前时刻，且格式含秒 `YYYY-MM-DD HH:MM:SS`。
- **引擎改造**：`publish_work(..., class_ids=[...])`（多班，逐个勾选 `.class_check`，逐班白名单+重复发布校验）；
  `assist xxt work-publish --class` 改为**可多次**。

## 4. PWA 改造（测试通过后）

| 模块 | 改动 |
|---|---|
| `PublishView.vue` 通知卡 | 目标班单选 → **多选勾选列表**（按课程分组，可选"全选本课程"，**只列白名单班**）；`sendNotice` 组装 `targets=[{courseId,classes:[…]}, …]` 一次 job |
| `PublishView.vue` 作业卡 | 同上多选；引擎扩展 `publish_work` 支持多 class_id（一次注入多个 `class_check`）；逐班重复发布校验与结果汇总 |
| 预览/确认 | `previewNotice/previewWork` 与确认弹窗列出**全部已选班**；发布按钮旁"已选 N 个班" |
| `engine/src/assist/xxt/work.py` | `publish_work` → 支持 `class_ids: list[str]`（或 PWA 循环 + 逐班 receipt） |
| 文档 | docs/13/15/31/48 |

## 5. 分期实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| U1 | 真机发现目标课程班级（确认"默认班级 / 新建班级2"） | 发现快照（29 课/218 班；目标 2 班） | ✅ |
| U2 | **多班发通知**真机验证（两班各收到） | receipt + 截图（两班均含） | ✅ |
| U3 | **多班发作业**真机验证 | 平台回 `workRelationArray` 两班各 workId + status:true | ✅ |
| U4 | PWA 通知卡多选（只列白名单班）+ `sendNotice` 多 target | `PublishView.vue`（复选列表按课程分组，全选/清空） | ✅ |
| U5 | 引擎 `publish_work` 多班 + PWA 作业卡多选 | `xxt/work.py` + `serve.py` + `PublishView.vue` + `engineClient.ts` | ✅ |
| U6 | 文档 + 验证 + 去敏 push | 文档 + CI | ✅ |

> **U1–U6 全部完成**（用户已核验真机多班发布成功）。PWA 通知/作业卡均为**多选勾选**（只列白名单班，按课程分组，全选/清空）；作业发布限**同课程**多班。

## 6. 验收

- 真机确认：同一通知/同一作业可**一次发给多个班**；两班平台端均可见；
- PWA 目标班为**多选勾选**且**只列白名单班**；预览/确认列出全部已选班；发布结果**逐班可见**（成功/已发过/失败）；
- 白名单仍由页面上方设置决定"哪些班可选"；
- engine pytest / PWA build+selfcheck / 脱敏扫描 全绿。
