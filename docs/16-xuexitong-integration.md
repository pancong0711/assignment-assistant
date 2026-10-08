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

## 10. D62 只读提取第一轮复盘（2026-10-07）→ 第二轮提取设计约束

### 首轮问题定性（详见 docs/13 D62 收口节）
- 化工24/环24 "0 人" = 提取器导航缺陷，**非数据缺失**：两班各 9 作业、批阅名单 59/40 人均在；
- 首轮三缺陷：①单 page 导航进 mark 后班级侧栏归零致后续班静默跳过；②selectClass AJAX+固定 sleep 竞态；③名单唯一来源=第一个作业批阅页（无作业班结构性 0，名单=提交者）；

### 第二轮提取流程约定（约束落实进代码时遵守）
1. **会话前置体检**：加载 storage → goto i.chaoxing.com/base 判活（跳登录页=dead）
   → 存活即 `storage_state` 回写续期；dead 则触发重新扫码（沿用 xxt_login_capture 流程）；
2. **每班独立导航**：`work/list?courseid=&clazzid=&cpi=&selectClassid=&status=-1` 直达
   （服务端直出，无 AJAX 竞态），**禁用**"点击后固定 sleep"形态;
3. **读取一律 evaluate 直读渲染树**：禁 `wait_for_selector` 默认 visible 断言
   （班级侧栏处于 display:none 收起态，selector 断言会假失败；必要时用 state='attached'）;
4. **失败必须留痕**：返回/存档区分三种语义——`未提取（导航/等待失败）`/`确认为 0（真无作业）`/`名单不全（缺交者不在批阅页）`，确认单禁止把三者都显示为"0 人";
5. **名单语义与验收锚点**：批阅名单=提交者；满员花名册=67/43（化工24/环24 通知分母），
   差值即缺交名单——次轮交付应同时给"名单（批阅页）"与"锚点差值核对"两份数据。

### 登录态文件约定
- `xxt-storage.json`（Playwright storage_state，cookies+localStorage）**明文敏感**：
  仅存 .scratch/（gitignored），域外不复制、不入日志；每次成功提取/体检后回写一次。

## 11. 登录态运维 · 会期 2026-10-07→08 经验沉淀

### 11.1 昨日登录态确认过程（含一次波折）
- 存储形态：Playwright `storage_state` JSON（cookies+localStorage，明文敏感，仅 .scratch/）；
- 有效信号（最终判定依据）：goto `i.chaoxing.com/base` 后
  **a) 无 passport/login 重定向；b) 无密码输入框；c) 教师工作台文案正常渲染**（如"嘉兴大学(老师)·<姓名>"）；
- **波折记录（误判教训）**：probe1（22:45）三目标页面 selector 全超时，先被误归因为
  "会话 3 小时过期"，再被误归因为"URL 形态敏感"——两次都被后续证据推翻
  （体检 verdict=alive；probe2 存档 HTML 数据完整）。根因是**等待断言写错**
  （详见 §10.4），而非登录问题。教训：**下游页面 selector 超时 ≠ 会话失效；判活必须用专用体检**。

### 11.2 现在（2026-10-08 09:50 复检）
- verdict=**alive**（同 10-07 22:52 判定标准），storage 已回写续期；
- 经验：判定标准三信号 + 成功即回写，两步覆盖"判活/续期"闭环；
  登录死亡时才触发重新扫码（沿用 xxt_login_capture 流程）。

### 11.3 待写成约定的运维条目
- [ ] 每轮提取/上传前强制跑一次会话体检；体检失败 → 二维码重扫描（不得带死会话继续跑批）；
- [ ] 每轮成功结束时回写 storage_state（心跳刷新）；
- [ ] storage/log 一律脱敏：不入 git、不打 cookie 明文、HP 域外不复制；
- [ ] 体检判定不得使用下游功能性页面的 selector 结果（避免 §11.1 波折重演）。

## 12. 班级作业提取方法定案（探针复盘 → 可复用方法）

### 12.1 候选机制对照（probe1/2/3 三轮淘汰）
| 方案 | 做法 | 结果 |
|---|---|---|
| A 首轮 | 每门课一次 goto 列表页 + 点击班级 + 固定 sleep3 + DOM 读取 | 五门课各自"首个有作业班之后全零"断崖（腿一） |
| B probe1/2 | 直达 work/list?clazzid= + `wait_for_selector`（默认 visible） | 误报失败：节点存在但侧栏容器 display:none |
| C probe3（**最终采用**） | 直达 classid URL + `evaluate` 直读 + 短 settle 等待 | 全通：环24=9 作业+名单 40，化工24=9 作业+名单 59 |

定案机理：`work/list?clazzid=...` 服务端**静态直出**（无 AJAX 依赖），
evaluate 直读渲染树绕开可见性断言；逐班独立 goto 消除共享 page 状态踩踏。

### 12.2 之前读取有误的部分（次轮整改范围）
- 断崖班（各课首个有作业班之后全部班级，含化工24/环24）——由方案 C 整改；
- 列表页内前序班（化工251/2、环251/2、机器人中本25级等）——固定 sleep 竞态嫌疑，
  次轮用方案 C 重测判真伪；
- probe 自身误报（probe1/2 失败、probe3 通过）——区分"站点数据问题"vs"读法问题"，
  次轮验收锚点=67/43 满员 vs 59/40 批阅样本差值=缺交名单。

## 13. 学生人数口径：点名册为本，批阅名单降级为样本
- **canonical**：人数与花名册 = 点名册文件（legacy `student.py` 证明可行；化工24/环24
  文件仍缺，需教师提供结构不动的原件再接 locateHeader）；
- **样本层**：批阅页名单（probe3 已证 67/67 匹配或 59/40 + 缺交差值可解释），
  定位为"提交者样本/名字示例"，确认单上必须标注**"作业提交样例"而非"学生名单"**，
  防止把缺交者误读为"不存在的学生"；
- **借鉴 legacy 三条**：
  1) 表头动态定位（扫前 8 行找"成绩"行）替代硬编码 `iloc[8:-3]`，兼容导出版本漂移；
  2) merge 键用**学号**为主、姓名为辅（legacy 此处在 merge on name，旧代码已有注释警告但未启用）；
  3) 人工可读检查项输出（run.py 的 检查项/状态/详情 三列风格）复用到探针/提取报告；
- 边界：批阅样本姓名=PII，仅留 .scratch/；对外工件一律脱敏或只出计数。

## 14. 检测/提取脚本 → CLI 集成方案（讨论稿，未实施）

### 14.1 现状落点
- CLI 位于 `engine/src/assist/cli.py`（click 体系，`sheet`/`roster` 组）；
- roster 纯逻辑在 `engine/src/assist/files/roster.py`（读点名册 xlsx→students）；
- legacy 对照：`_legacy/2601playwright/src/browser_helper.py`（login/run 三段式）证明
  "CLI 包浏览器"形态可跑通。

### 14.2 拟新增 `xxt` 命令组（CLI 统一入口）
| 命令 | 来源脚本 | 边界 |
|---|---|---|
| `assist xxt login` | xxt_login_capture.py | 扫码→落 storage json（路径可配，默认 .scratch，gitignored）|
| `assist xxt check` | xxt_session_check.py | 三信号判活 + 存活即 storage_state 回写续期 |
| `assist xxt extract --course --class [--scope roster|homework|notice]` | xxt_readonly_extract.py v2 | 方案 C 直达导航 + evaluate 直读；失败留痕三分类（§12.2） |

- probe1/2/3 **不进 CLI**，转为 repo 内只读回归证据文档（含失败复现的价值）；
- 隔离策略：engine 主包保持零浏览器依赖，playwright 作 optional extra
  （导入失败给出明确安装提示），浏览器适配层单独模块（如 `assist/xxt/browser.py`），
  定位对标 legacy `browser_helper`/`subplaywright` 分层;
- **只读硬保证**：route 层拦截 POST/PUT/DELETE（D62 探针已实践），
  CLI 目录内不提供任何写命令，写沿用 legacy submit_v2/v3 多态上传策略（§7 版本适配口径）;
- 时序约束：`xxt check`/`xxt login` 可先行落地（语义已稳定）；
  `xxt extract` 待次轮名单口径/批阅 status 语义/点名册文件三案定案后再集成，避免固化腿三缺陷；
- 验收锚点：67/43 满员对齐 + 与 web 页面一致性抽检（docs/16 §8.1 延续）。

## 15. 作业基本信息之「作答状态」字段（2026-10-08 · 仅凭既有存档确认，零新增请求）

### 15.1 字段来源：作业列表 li 自带统计（CSS 类 `wid15` 区块）
每个作业 li 渲染：`<em>0</em>待批 | N 已交 | M 未交` + `作答时间：起 至 止` +
归属班级 title + workId(onclick 参数) + 默认批阅链接(href)。
**结论：作答情况提取无需进批阅页，作业列表一级即得「作业基本信息」全套**——
probe3 的 evaluate 直读法完全同构，只需追加解析 `wid15`/`list_li_time` 两个区块。

### 15.2 已从存档核实的实证（化工24级 9 份全量）
| 作业 | workId | 作答时间 | 待批/已交/未交 |
|---|---|---|---|
| 15-量子-作业纸2 | 49301435 | 12-23~12-28 | 0/59/6 |
| 15-量子-作业纸 | 49126196 | 12-16~12-21 | 0/61/4 |
| 08-电磁感应×2 | 48722286/48263628 | 12-02~12-11 | 0/62/3 |
| 07-稳恒磁场×3 | 48014185/47417832/46731168 | 10-14~11-16 | 0/58~63/2~7 |
| 05-静电场×2 | 46268657/45924205 | 09-23~10-08 | 0/63/2 |
（环24 同构：40/2 等；批阅页名单 40 与列表"40 已交"精确对上。）

### 15.3 口径警报（新发现，待教师核对）
- 已交+未交 ≈ 64~65（化工24），环24 ≈ 42 —— 即"班级参作人数"，但通知已读分母为 67/43；
  **差值 2/1 的语义待辨**（退课者/旁听/合班改名成员/账号重复等）；
- 含义：**"参作名单"（列表级）与"通知触达名单"（消息级）与"点名册"（教务）三口径并不天然相等**，
  次轮交付须三者并排展示差异，不得混用；
- 补充语义待次轮核实：批阅页 statusSet 出现过 `已完成（补交）`——补交者计入"已交"口径。

### 15.4 呈现建议（作业基本信息三态）
`待批(0/名)`、`已交(名单=批阅页 statusSet)`、`未交(名单=参作差集)`；
默认列表只显示 **三数字**（待批/已交/未交），点开才展开名单（PII 面积最小化）。

## 16. PWA 学习通视图 · 操作流需求（用户口径 2026-10-08 · 讨论稿）

### 16.1 登录确认
- **只通过扫码**：不提供账密表单自动登录路径（与 §11.2/§11.3 体检+回写闭环衔接；
  会话死 → 只能重新扫码，不给"自动续命"路径，凭据不落 PWA）；
- 扫码入口与体检状态显式分离：`未登录 → 扫码 → 体检通过 → 进入列表`；
  体检失败态要给明确文案（区分"未扫码/已过期/被判活过但当前失效"）。

### 16.2 列表呈现（基本信息层）
- 登录确认后以**列表**显示学习通要素基本信息（课程/班级/作业/作答统计），默认不进详情态；
- 列表数据 = §15.4 作业三态 + §13 名单三层口径，锚点差异（15.3）以警示徽标内联呈现。

### 16.3 列表交互需求（本轮新增）
- **置顶功能**：列表横向头部或尾部浮出"置顶"开关，用户可钉选常看行，便于查阅；
  置顶行适用 sticky/置顶位（与 D56-I1 三表粘性表头机制对齐，避免两套滚动语义）；
- **滚动承载**：列表区滚动，**不撑高页面**（节省页面空间；与 D61 rows×cols 显式网格
  的"整页不纵向无限生长"口径一致）；
- 未决项（待实施时定）：a) 置顶持久化层级（workspace 内 per-user 保存 vs 会话内记忆）；
  b) 置顶容量上限与"全部取消置顶"复位；c) 移动端触控下的横向滚动与置钮热区（PWA 触屏）。

### 16.4 与既有口径的对齐点
- 名单 PII 面积最小化（§15.4 默认只出数字）+ storage 明文敏感（§11.3）延续；
- 本节为需求讨论稿，**未落实现**；实施时勘误以代码评审增补，不改本节结论。

## 17. 执行方向与顺序（D63 蓝图 · 2026-10-08 用户确认收编）

### 17.0 口径警报收编（§15.3 降级为"已解释差异"）
- 用户裁定：通知/公告人数**含发布人（教师/教师团队），天然可能 +1**；参作与通知分母的
  1~2 人差属于正常噪声；学生是否全部入班由教师自查，不作为系统疑点；
- 修正口径展示约定：三层名单（点名册 canonical / 参作=已交+未交 / 通知触达=分母-发布人）
  中三层合并展示时，**差值 ≤2 直接灰显"含发布人/未入班"说明**，不再拉警报条。

### 17.1 执行顺序（依赖驱动，P0 先行）
```
P0-a 会话层（语义已稳，风险最低）
     assist xxt login（扫码→storage json）/ assist xxt check（三信号判活+回写续期）
P0-b 名单口径定案
     点名册 canonical 落位（化工24/环24 两份原件：结构不动，姓名可无）→
     locateHeader 动态定位 + 学号主键 merge（跑通 legacy 不走的欠账）→
     master 花名册 xlsx 生成（df-container 形态沿用）
P1 只读提取 v2（方案 C 落地）
     逐班直达导航+evaluate 直读 → 全量班级的
     [课程/班级/作业(三态数字+作答时间)/未交名单(批阅页差集)/通知] 五元组 →
     本地 JSON（.scratch，含失败留痕三分类语义）
P2-a PWA 学习通视图（与 P1 并行可启动 UI 骨架）
     扫码登录屏（体检显式分离）→ 列表视图（三态数字默认、点开见名单）→
     行置顶（sticky 对齐 D56-I1）+ 滚动承载（勿撑页，对齐 D61）
P2-b CLI 扩展收线（xxt.extract 入 click 组）
     --scope roster|homework|notice；route 层 POST/PUT/DELETE 拦截为硬只读
P3 写操作（远期，本阶段不动）
     批阅回传/测试公告发布——维持 D62 决议：双确认+仅测试班级
```

### 17.2 顺序理由
1. `xxt check/login` 是一切批次的安全闸：**无会话任何提取都不可靠**（§11 波折已证）；
2. 名单口径 P0-b 在 extract 前：**先有 canonical 才有"未交名单"的差集基准**；
   缺它则 extract 只能交给"参作口径"，验收锚点无从谈起；
3. extract v2 在 PWA 之前：UI 展示依赖数据字段定版（§15 已核），但**失败留痕三分类
   必须先在 CLI 侧打磨**，PWA 直接消费成型 JSON，避免 UI 重写解析层；
4. PWA 视图与 extract 并行：数据契约（五元组 JSON schema）P1 前半即冻结，
   UI 骨架按 D61 网格/agrid 骨架沿用既有组件；
5. 写操作押后：既有 D62 决议 + 仅测试班级 + 双确认三重门，无需提前。

### 17.3 每阶段验收锚点（冻结，不许漂移）
| 阶段 | 锚点 |
|---|---|
| P0-a | 体检 verdict=alive 3 次连续（跨 24h）；storage 回写时间戳递增 |
| P0-b | 化工24/环24 master 花名册人数与教师教务册一致（±0 差值）|
| P1 | 化工24 9 作业/环24 9 作业三态数字与存档逐条一致；未交名单差集≤2 皆有姓名 |
| P2-a | 列表页 42 行内全滚动+无纵向撑高；置顶行 sticky；PII 默认三数字 |
| P2-b | `xxt extract --help` 可见；提取产物出具 run_id |

### 16.3-R1 列表交互修订（用户拍板 2026-10-08）
- **置顶上限=10（可调）**；取代此前"3 行+提示"的讨论稿；
- 新增按钮：**移出列表**（把行从当前视图剔除，与置顶同区放置）；
- 新增按钮：**刷新/更新**、**从学习通恢复列表**（=丢弃本地编辑态、以最近一次
  只读提取结果为基准重建视图；不是另作提取请求，仅回放到最近 run 的 JSON）；
- **按课程分组**的多个列表，每列表独立滚动+独立置顶区；分组标题行 sticky；

## 17-R1 D63 蓝图修订（用户三项拍板 2026-10-08）
1. **P1 阶段性推进**：先三类对照班（化工24/环24/机器人中本24）冻结 schema →
   再放量 26 班（采纳原讨论稿倾向）；
2. **P2 门禁成立**：P1 产物经教师审核后才启动 P2（PWA 登录+基本信息获取），
   即 **P1 → 审核 → P2；P2 不得先行**；
3. **口径警报收编补充**：通知分母含发布人（+1 差属正常）+ 学生未入班由教师自查——
   §15.3 警报降级为灰注，不阻塞提取。

### 17-R1 P0-b 数据源新发现（2508examAnalysis 兄弟项目盘点）
- 路径：`~/Projects/2508examAnalysis/data/raw/26C1/`（只读盘点，未改动）；
- `学习通-26C1-化工25.xlsx`：**学号+姓名+院系+专业+班级**全字段，n=68
  （**2025 级 67 + 2024 级 1**）；`学习通-26C1-环25.xlsx`：n=54（2025 级 53 + 2023 级 1）；
- `得失分统计表-26C1.xlsx`：仅姓名无学号（化工25 69 / 环25 52）；
- ⚠ **口径冲突待拍板**：用户口述"化工/环24 = 26C1 考试班级"，但文件证据显示
  26C1 名单主体是 **2025 级学号**（2024 级各混 1 人，疑重修/插班）；
  而本项目（269）里 化工24/环24 是**大学物理C2 课**（classId 128430068/128430077，作业=静电场~量子），
  与 26C1（力学~热学，C1 课）**不是同一课程/同一 cohort**。
  → 待用户确认 canonical 源：a) 沿用 26C1 的 25 级名单（那"化工24 班"应是另一轮次课程）；
  b) 24 级 C2 点名册另有出处（原件待发）；c) 再往兄弟项目深处找 24 级 C1/C2 数据。

### 17-R2 P0-b canonical 源收编（2026-10-08 用户澄清后盘点定版）
- 口径澄清：**化工24/环24 = 上一学年（2024-2025 年度）cohort**；**26C1 = 本学年 25 级**——
  17-R1 的 cohort 冲突至此消解（26C1 目录不是本项目化工24/环24 的名单来源）；
- **历年试卷考点项目 = `~/Projects/2508examAnalysis`**（23C1/24C1/25C1/26C1 四年连续
  + 考点词云/共现网等），其 `data/raw/25C1/` 即化工24/环24 考试年全程在档，只读未动；
- **canonical 候选定版（均为学习通官方导出，字段完整）**：
  | 文件 | 学号n | 年份分布 | 备注 |
  |---|---|---|---|
  | 学习通-25C1-化工24-0621.xlsx | 66 | 2024级65+2023级1（重修/插班） | 班级：潘老师-化工24；任课：戈迪 |
  | 学习通-25C1-环24-0621.xlsx | 47 | 2024级46+2023级1 | 班级：潘老师-环24 |
  - 得失分统计表-25C1.xlsx：化工24/环24-分析 两 sheet（classic 风格），仅作交叉校验源；
  - 雨课堂-25C1-*.xlsx / 潘老师-*_统计一键导出：备用校验源；
- 口径对齐锚点（待 P1 交叉验证）：化工24=66 vs 学习通通知分母 67（差 1，与"分母含发布人"假设
  方向吻合）；环24=47 vs 通知分母 43（**超 4**，需 P1 用学号对齐查明：退课者仍在名单或
  班级成员变更）——不阻塞提取，进差值白名单核查项；
- 待办：教师拟找的**点名册原件**到档后与 25C1-0621 学号字段逐条 diff（P0-b 验收锚点±0 原
  缩略为"两源交叉一致"）。

## 18. D63 任务需求单（按推荐定版 · 本周执行框架）
> 依据 17/17-R1/17-R2 全部已拍板项汇编；以 21 行"班次×批次"推进，全程只读，未获教师放行不进 P2。

### 18.1 任务分解（含动/静状态说明）
| # | 任务 | 输入 | 输出/验收 | 依赖 | 状态 |
|---|---|---|---|---|---|
| T1 | CLI `xxt check`+`xxt login` 落 engine | xxt_session_check/login_capture 逻辑迁移 | click 组双命令；体检 alive→回写；seed doc | 无 | 待办(P0-a, 风险低先做) |
| T2 | 25C1 canonical master 花名册 | 25C1-0621 两 xlsx + 得失分统计表交叉 | df-container 形态 xlsx；学号主键；2023级插班行标注 | 无（教师原件到达后 diff 升级） | 待办(P0-b) |
| T3 | extract v2 schema 冻结 | probe3 五元组+15.4 三态+未交差集 | schema 文档（字段/枚举/三分类语义） | T2（差集基准） | 待办(P1-a) |
| T4 | extract v2 实现三类对照 | schema+probe3 读法 | 化工24/环24/机器人24 三班 JSON+HTML 存档；锚点 66/47 对齐 | T1+T3 | 待办(P1-a) |
| T5 | **教师审核 P1-a** | T4 产物 | 书面通过（或勘误清单） | T4 | 门禁 |
| T6 | extract v2 放量 26 班 | schema | 全量 JSON（含容器班真伪判定） | T5 | 待办(P1-b) |
| T7 | PWA 登录屏+列表视图 | T4/T6 JSON | 扫码/体检/列表三段落 UI（D61 网格沿用） | T5 | 待办(P2) |
| T8 | 列表交互三件套 | T7 | 置顶(≤10 可调)/移出/刷新/恢复 + 分组滚动 | T7 | 待办(P2) |
| T9 | CLI `xxt extract` 收线 + 秘密扫描 | T4/T6 | click 组；route 硬只读；check-secrets 白名单核对 | T5 | 待办(P2-b) |
| T10 | 写操作（批阅回传/测试公告） | —— | **本阶段冻结，不排期** | D62 决议 | 冻结 |

### 18.2 执行批次
- **批次一（本周）**：T1 → T2 → T3 → T4 → T5（阶段点：教师审核）；
- **批次二（审核后）**：T6 ∥ T7 → T8 → T9；
- 全程原则：只读+落点 .scratch；对外文档零姓名（docs/04 口径）；每批次一组 run_id。

### 18.3 待教师输入清单（唯一卡外因）
1. 点名册原件（化工24/环24）：到档后升级 T2 验收（「两源交叉一致」→「与原件±0」）；
2. T5 审核窗口（建议 1 个工作日内，避免批次一挂起过久）；
3. 2023 级插班生（两班各 1 人）与"环24 47>43"差值的处置口径（白名单/移出/保留）。

## 19. D63 T3：extract v2 数据 schema 冻结（2026-10-08 · 依据 probe3/15.x 定案）

### 19.1 顶层 RunRecord（一次只读提取=一个 run_id）
```json
{"run_id": "xxt-20261008-115", "mode": "readonly", "ts_start": "...", "ts_end": "...",
 "session": {"checked_at": "...", "verdict": "alive|dead", "storage": ".scratch/xxt-storage.json"},
 "courses": [ { "name": "大学物理C2", "courseId": "236230440", "classes": [ { "$ref": "19.2 ClassRecord" } ] } ],
 "failures": [ { "$ref": "19.4 FailureRecord" } ] }
```
- 会话体检失败（verdict=dead）→ 整个 run **直接失败退出**，不产出半成品数据；

### 19.2 ClassRecord（班级粒度）
```json
{"name": "潘老师-化工24级", "classId": "128430068", "cpi": "168131489",
 "works": [ { "$ref": "19.3 WorkRecord" } ],
 "roster": {"ref": "25C1-master-roster.xlsx", "total": 66,
            "note": "2023级插班 1 人；名称口径=学习通-25C1-0621 导出"},
 "notices": [ {"text": "...", "href": "..."} ],
 "status": "extracted", "notes": []}
```
- `status` 枚举（三分类语义，D62 收口定案）：
  `extracted`（正常产出）、`empty_confirmed`（页面直出"暂无作业"且 0 行=确认为 0）、
  `not_extracted`（导航/等待/会话失败——**不得记为 0**，同时进 failures）；

### 19.3 WorkRecord（作业粒度=「作业基本信息」）
```json
{"workId": "49301435", "name": "15-量子-作业纸2",
 "answer_window": "2025-12-23 15:59至 2025-12-28 19:59",
 "pending": 0, "submitted": 59, "unsubmitted": 6, "source": "list_wid15",
 "submitted_names": [{"name": "王冬梅", "status": "已完成（补交）"}],
 "unsubmitted_names": ["范心怡"], "roster_missing": [], "status": "extracted"}
```
- `pending/submitted/unsubmitted` 来自列表 li `wid15` 区块（15.1 定案，零额外请求）；
- `submitted_names` 来自 work/mark 批阅页（status=0&size=200；名单=提交者，15.3 口径）；
- **未交名单口径（关键定案）**：
  `unsubmitted_names = master花名册姓名 − 该作业 submitted_names`（学号优先、姓名回退）；
  `roster_missing` = 记录"在花名册但不在通知参作集"的行——口径差异白名单，
  **只提示不判错**（15.3 收编：含发布人、未入班、名单时间差）；
- 数字与名单双侧一致性校验：`len(submitted_names) == submitted` 且
  `|roster.total − (submitted+unsubmitted)| ≤ 2` 为绿，超出进 `notes`（灰注）；

### 19.4 FailureRecord
```json
{"scope": "class|work|notice", "ref": "128430068/49301435", "kind": "not_extracted|empty_confirmed",
 "detail": "...", "archive": "probe3-list-128430068.html"}
```
- kind 只有两种：`not_extracted`（失败）或 `empty_confirmed`（确认 0）；**禁止第三类"0"**；

### 19.5 验收锚点（T4）
1. 化工24 works=9、环24 works=9，三态数字与 probe2/3 存档逐条一致；
2. 化工24 roster.total=66、环24=47（T2 产物）；
3. `submitted` 数字与 `len(submitted_names)` 全等（抽 valley=最新作业必修对齐）；
4. `unsubmitted_names` 每班最新作业给出具体姓名（用于教师核查未交）；
5. 失败留痕：任何环节失败都必须在 failures 呈现 kind=not_extracted，**不得静默为空**。

### 19.6 T4 实况记录（2026-10-08 · run_id=xxt-20261008-113601）
| 班级 | works | 三态数字一致性 | roster | 未交名单 | 灰注 |
|---|---|---|---|---|---|
| 化工24级 | 9 | 名单数==已交数 9/9 全等 | 66 | 全部落名（6~10 人/作业） | roster_delta≤1 无 |
| 环24级 | 9 | 9/9 全等 | 47 | 全部落名（7~10 人/作业） | roster_delta=5（插班+未入班+发布人，灰注） |
| 机器人中本24级 | 4 | 4/4 全等 | —（25C1 无其名册） | —（无花名册基准） | 无 |
- 中途修正两枚（防复发均已注释/回归）：
  a) 列表页模板 href **不含 `size` 参数** → mark 页服务端每页 20 截断（仪表盘 59 vs 名单 20 的根因）；
     修法=href 规范化时缺 `size` 就补 `&size=200`；
  b) route.abort("forbidden") 为非法错误码 → 改 `route.abort()`（默认 failed）；
- 会话体检前置（T1 函数复用，verdict=alive）；HTML 存档 v2-* 全量落 .scratch/xxt-pages/；
- 产物：.scratch/xxt-20261008-113601-v2.json（含姓名，不入库）；
- **T5 待启动**：教师审核本 JSON/摘要报（通过后启动 T6 放量+T7 PWA）。

## 20. D63 T5 验收记录 + PWA「学习通tab」两框 UI 决议（2026-10-08）

### 20.1 T5 验收（门禁通过 ✅）
- 教师核对：化工24 三态数字与网页手动查询一致（环24 未抽查、由存档一致兜底）；
- 复核（学号视角的机械等价——名册无重名 → 姓名匹配=学号匹配）：
  | 班 | 名册n | 重名 | 提交者∪ | 提交但不在名册 |
  |---|---|---|---|---|
  | 化工24 | 66 | 无 | 65 | 刘明鑫/田海峰/罗庭伟（也不在成绩册 → 缺考/未入班镜像，白名单） |
  | 环24 | 47 | 无 | 42 | 李戈艺/胡航（同上，白名单） |
  | 机器人中本24 | — | — | 67 | 无 |
- 差值白名单口径定版：名单差集**只展示不判错**；其余提交者姓名 100% 对上成绩册 → **T6 放量与 T7 PWA 双双解锁**。

### 20.2 扫码框 → 头像框（可行 ✅）
- 登录前框内=QR png（`xxt login --qr` 产物）；verdict=alive 后 engine 以**同一真会话**
  抓工作台头像 → base64 data-URL 交 PWA → 框内容切换 QR→头像（圆形+“已登录”角标）；
- 硬边界：头像字节经 engine 中转（data-URL），**PWA 不再发起对 chaoxing 域的直接请求**；
- 头像随体检刷新；体检 dead → 头像退回 QR 态并提示重新扫码。

### 20.3 导航过程展示框（决议：CLI 套壳 = 方案 A）
- 显示内容=PWA 页宽、可鼠标滑动的过程流；数据=engine（serve.py 通道）：
  a) 导航事件流（URL/标题/step/提炼摘要），b) 每次跳转的低频 `page.screenshot` 缩略图；
- **三方案对照定案**：A 套壳 ✅（单一真会话，展示层零第二登录）；
  B PWA 从头重写学习通前端 ❌（双实现必漂移，D62 收口的教训反例）；C iframe 内嵌 ❌
  （X-Frame-Options/CSP + 域不共享 cookie → 第二登录，违背单一会话）；
- HTML/JS 仅用于我们自己 UI（两框+列表视图），不对标学习通页面本身；
- 数据契约顺延：提取事件/截图均为 engine 只读产物，进 19.1 run 记录的旁支（archives 字段）。

### 22.1 playwright 联网安装链路（T7.1 · 2026-10-08 拍板落地：镜像优先）
- **定案**：联网安装、零仓库分发安装包（用户口径）。engine 已有 `/doctor` 检查项
  与 `/install/playwright` 通道 → 本次接完两处缺线：
  1. `pyproject` 新增 `[project.optional-dependencies] playwright = ["playwright>=1.40"]`；
  2. `/install/playwright` 升级两步特殊项（`xxt/installer.py::install_playwright`）：
     ①Python 包走 `uv pip install --index-url`（缺省 **tuna**；教师 env 可覆）
       / 无 uv 回落 `pip -i` 同源；
     ②内核 `python -m playwright install chromium`（`PLAYWRIGHT_DOWNLOAD_HOST`
       缺省 **npmmirror**；教师 env 覆盖尊重）；
- **doctor fix 接线**：playwright 检查项补 `fix={type:"install", install:"playwright"}`
  → 设置中心体检卡自动出现「🔧修复」按钮；另给常驻卡
  「Playwright（学习通提取）」=一键联网安装 + 提示"装完需回体检"；
- **XXT_CHROME 边界**：env 指本机现成 chrome/chromium 可跳过②（仅终端路径，非默认）；
- 干跑实证：emit 输出+两步命令拼装正确（uv→tuna / chromium→npmmirror）；
- 未决远延：包安装与 serve 同进程磁盘/venv 推断仍有空间（现取 `_venv_python`），
  首次真实安装后若 vendored venv 缺 playwright 包路径不再报错即闭环。

### 22.2 待办顺延表（D63 结余）
1. 工作台头像 selector 首查（§21.5）；
2. 班级排序/筛选（按 status/有无作业）；
3. run JSON workspace 归属（部署切 XXT_HOME env）；
4. ~~playwright 一键安装/检测模块~~（本次完成）；
5. 教师机真装一遍 playwright（P0-b 后任一时点，约 40+150MB 镜像流量）。

## 23. 公告发布 · 网页预研与 PWA 可视化方案（T10 前置文档 · 2026-10-08 · 写操作仍冻结）

> 本节=纯文档；实现动工前置=用户解除 T10 冻结。侦察仅 GET（发布表单页已存档、零提交）。

### 23.1 页面结构（侦察存档：.scratch/xxt-pages/recon-notice-*.html）
| 要素 | 侦察结果 |
|---|---|
| 入口 | `myNoticeList` 页 A[href=CourseNotice.openDetail(this, CourseNotice.getCreateNoticeUrl())]（文案=**新建通知**）|
| 发布页 URL | `https://notice.chaoxing.com/pc/course/notice/richtextNotice?courseId=<cid>`（GET）|
| 标题 | `input.title`，maxlength=128（placeholder 请输入标题（限128字））|
| 正文 | **UEditor 富文本**（edui* 工具条；"附件/上传图片"按钮走 **webuploader** 多片上传通道）|
| 接收人 | `noticePersonList` 模板（头像列表+搜索筛选；按班级/成员勾选）|
| 发送 | 底部 `.sendNotice.submitBtn`「发送」div；**定时发送** switch `.scheduledSend`；提醒设置=四渠道(message/phone/学习通/wechat) receiver+sender 时间 inputs |
| 协议 | 发送即接受用户协议（本地化字符串表内含"请勿发布色情，反动等违法内容"）|

### 23.2 操作链（实现 textbook，T10 解冻后照方抓药）
```
1) GET myNoticeList?courseid&clazzid   → CourseNotice.getCreateNoticeUrl()
2) GET richtextNotice?courseId=…       → 表单锚点就绪（input.title / UEditor 实例索引）
3) setPlainText/richText 编辑器注入    → 标题、正文（UEditor setContent）
4) 附件：UEditor「附件」按钮 webuploader 队列（POST 到 upload CDN——**写会话专用**，
   route 白名单仅放行 notice.chaoxing.com 与上传 CDN 域；strip 其余）
5) 接收人：按已提取 run 的接收人名单勾选（领域知名=教师确认过的测试班/班次）
6) （可选）定时 switch + 提醒渠道缺省=关闭
7) 发送前**截图+快照**（pre-send archive 归档）→ 教师双确认 → 点 .sendNotice.submitBtn
8) 发送回执/已读分母写回 run JSON（与 19.1 records 联动，支持后续"申请补交/已读"核对）
```
- legacy 无公告通道（2601=批阅流；2603=作业纸生成）→ **自建**，但**沿用 legacy submit_v2/v3
  多步重试/降级框架**（版本适配口径延续，§7）；
- **两大硬约束**（延续 D62 决议）：a) 双确认 = 预览确认 + 二次确认按钮；b) 默认仅测试班级可选。

### 23.3 PWA 可视化（方便操作的三段式）
1. **发公告向导卡**（学习通 tab 内）：班级（多选，来自最新 run 已提取班级）→ 标题/正文 →
   附件选择器（默认列出「输出与交付」已生成的作业纸 PDF）→ 定时/提醒（缺省关）→ 预览卡
   → 二次确认（等 20.2 的头像/身份卡同区展示发送账号）；
2. **过程展示框**（已实装）承担执行观察：标题/正文/附件/接收人每一步截图实时入流的即视感，
   发送前一步必然出现"预览确认"截图卡；
3. **回执层**：发送后 run 记录发送时间/接收人数/公告 URL；通知列表与"已读 n/n"Kickoff 对齐
   （15.3 口径：含发布人 +1）。

## 24. 公告 PWA 实装（只读侧 ✅ + 发布占位 🔒；T10 冻结不变）

### 24.1 数据层（只读补抓）
- 新 driver `.scratch/xxt_notice_full.py`：30 班 myNoticeList 全量 GET → **94 条通知**
  合并进最新 full run（化24/环24 各 9 条=作业类通知，与 §15.3 口径互证）；
- **route 层边界修正（重要教训）**：通知列表页自身数据经 **POST AJAX** 拉取，
  "非 GET 全拦截"路由会误杀页面数据加载（首轮 0 条→撤销拦截后 94 条）。
  口径细化：**提取链路**（worklist/mark）保持 route 硬拦截；**内容页**（通知/未来公告页）
  用"行为约束"模式（脚本仅 goto+evaluate，零点击零提交）——写入 §12/§14 的实现须知。

### 24.2 PWA 实装（XxetongView 新增两卡）
1. **通知查看卡（真数据）**：班级筛选 + 通知表（班级/标题/时间/已读比）；
   已读比 <90% 黄色提示（对齐 15.3 灰注口径）；数据源=最新 run JSON notices[]；
2. **发公告向导卡（占位 disabled）**：按 §23.3 结构预置表单形态（班级多选/标题≤128/
   正文/附件选择器/定时提醒占位/预览+发布双按钮）——**fieldset disabled + 🔒冻结徽标**，
   零提交逻辑；解冻后按 §23.2 八步接引擎写会话即可（表单骨架已就位）。

### 24.3 边界重申
- 学习通侧本轮**零写改删**（通知补抓=纯 GET 列表读取）；
- 占位卡不含任何网络调用；T10 解冻窗口仍需：写侧侦察三项（POST 端点/webuploader/接收人交互）
  → 实现清单确认 → 编码。

## 25. D64 需求单：批阅选项卡 × 学习通（扫码前置/批阅后置/作业纸式批阅报告/过程预览）

> 用户口径 2026-10-08 晚 · 本节纯规划（未动代码）；学习通侧写改删仍全冻结（调研只读）。

### 25.1 用户四项需求 → 决议表
| # | 需求 | 决议/方案 | 状态 |
|---|---|---|---|
| N1 | 批阅依赖学习通扫码登录 → 批阅卡应写说明 | ✅ 批阅卡加"登录前置提示"区（复用 /xxt/status 体检：dead/unknown 显示"先去学习通 tab 扫码"，附跳转链接） | 待实施（纯前端） |
| N2 | tab 顺序调整：批阅后置到学习通之后 | App.vue tabs 顺序改为 settings→kb→design→roster→**xxetong→grading**→transfer→help（依赖在前的先给入口） | 待实施（一行级） |
| N3 | 批阅也做学习通网页过程预览（同学习通 tab 的导航过程框） | 复用 §20.3 套壳架构：engine 批阅工作的每跳 _step+截图 → run JSON steps[] → /xxt/shot 端点已备 → 批阅视图内嵌同款横向缩略流（组件级复用） | 待实施（复用现有件） |
| N4 | 作业纸式批阅报告（预览作业→生成报告→预览报告→报告写在同样格式作业纸上） | 详见 25.2 版式定案 | 规划定版 |

### 25.2 批阅报告版式（用户拍板 2026-10-08）
- **竖版**：逐题评阅——**每道题占满一行**顺次排（题目转录→作答转录→评语/得分），
  题多则续页；**不做 2×2 十字花**（评阅内容多，四格塞不下）；
- **横版**：分**左右两半**评阅（左半=题1..n/2，右半=题n/2+1..n 每半内部仍逐题纵向排）；
- 报告结构复用现有 sheet 模板基因（作业纸 HTML 通道）：页眉学籍三空位/题号分段命 CSL
  网格沿用 rows×cols（D61),但**内容区改为"逐题行"语义**（区别于留白作答页）；
- 数据流（新增字段提议，融合 §19 schema）：
  `WorkRecord.submission[] = [{student, images[], transcript, review, score}]`
  ——批阅=对每学生跑 转录→评阅→报告 三步（D27 grading flow 已有骨架可接），
  报告生成=把三步产物按 25.2 版式模板渲染（sheet_html 同一管线，新增 report 布局模式）。

### 25.3 需补充的学习通网页调研（只读侦察清单 · 未开展）
| # | 调研点 | 目标 DOM/行为 | 优先级 |
|---|---|---|---|
| R1 | 学生作答图片直链（ans-ued-img data-original 原图）与 download 端点 | legacy `get_student_answer_images` 已有草稿（2601 homeworks.py），验证现行版页面对齐 + 回落路径 | P0（报告素材） |
| R2 | 学生评阅入口 `enter_student_review` 的现行版 URL/参数（workAnswerId）与"得分/评语"输入控件定位 | legacy 已有函数，需对 v=0 页面重测 | P0（报告回写+人工复核联动） |
| R3 | 图片/作答的**分页容器**（学生答题图可能多页 lazy-load） | 滚动加载观测 | P1 |
| R4 | 批阅统计页（stat2-ans work-stastics）可只读字段清单 | 是否优先直接用统计面数据补充报告 | P2 |
| R5 | 附件下载的会话内直上（download 域白名单），防 403 教训复用（Referer 指纹） | 同 §22.1 头像修复方式 | P1 |

（R1/R2 legacy 草稿在 `_legacy/2601playwright/src/xuexitong/homeworks.py`——起手即有参照，
重测即可，不是从零侦察。）

### 25.4 D64 批次任务单（草案 · 未排期）
```
D64-a 批阅视图前置桥（纯前端）：N1 提示+登录态复用、N2 tab 后置重构（半天）
D64-b 过程预览组件化：把学习通 tab 的过程框抽为共享组件 ProcessStreamView
      （props=run steps+shot 端点 → 批阅视图复用；同时补 §22 待办"头像首查"回归）（1 天）
D64-c 批阅调研 R1/R2/R5（只读；产出=侦察报告+DOM 快照，复刻 §23 形式）（0.5~1 天）
D64-d 批阅报告版式：sheet_html report 模式（竖/横双版式 CSS + 逐题行数据绑定）
      + 快照预览（1~2 天）
D64-e 端到端演练：sample 图片 offline 流水线（不触学习通写——回写步骤双确认后单独批）
D64-f 批阅回写（写操作）：学习通侧填分/评语——**另行解冻**（T10' 门禁同公告）
```
- 依赖链：a/b 前端独立可先行；d 依赖 c 的 R1（原图）；f 最末；
- 验收锚点（先冻结，防漂移）：
  a) 批阅卡在未登录态显示"去学习通扫码"并可跳转；
  b) 过程框在批阅视图呈现最近 run 的 steps/截图；
  c) 竖版报告：5 题/20 分卷逐题行完整渲染且可打印 A4；
  d) 横版左右半版逐题渲染；
  e) 报告预览与导出 PDF/HTML 同页一致（沿用作业纸打印口径）。

### 25.5 边界重申
- 本节全部未动代码；学习通侧零写改删；R1—R5 全为 GET 侦察；
- 写回通道（D64-f）与公告发布同属 T10 族，解冻窗口/流程对齐 §23.2。

### 25.6 D64-c 只读调研结果（R1/R2 ✅ 2026-10-08 晚 · run xxt-20261008-184915 验证）
| 调研点 | 结果 |
|---|---|
| **R1 原图直链** | 学生批阅页 `/mooc2-ans/work/library/review-work?courseid&clazzid&workId&workAnswerId`；
| | 作答图 `img.ans-ued-img`；原图 `data-original`（`p.ananas.chaoxing.com/star3/750_1024/*.jpg`，实测 750×1000，直链可存） |
| | legacy mooc1 `reviewTheContentNew` 老版为回落路径（保留） |
| **R2 回写控件** | per-题分数 `input#score<题id>`（placeholder 0-100）+ 总分 hidden `#score/#fullScore`； |
| | per-学生评语 `textarea#comment<workAnswerId>`；打回理由 `textarea#textCon[name=reason]`； |
| | 提交三态按钮：`markAction(1)`=提交 / `markAction(0)`=提交并下一份 / `confirmPiyueWork()`；全部=写操作（未点击） |
| **R3 多图懒加载** | 本样例单页单图；多图/分页形态留待真数据批次观察（学生详情页可能有 tab） |
| **R5 下载白名单** | 下载域=**p.ananas.chaoxing.com** 加入"引擎取字节"域清单（与照片域 403 教训同族：Referer=来源页指纹） |
- **extractor 升级并复跑验证**：`submitted_names[]` 行新增 `review_path`（=列表页 `a.cz_py` data 属性自带的
  学生批阅 URL，含 workAnswerId）→ **报告管线从提取一步直通**（无需二次侦察跳）；
- 数据影响：run JSON 行多 240 字内 review 字段；**D64-d 报告版式（reports.ts）的 submission[]
  数据源确认为：名单行(name/status/review_path) + 逐学生批阅页(原图 R1) + grade 流转录/评阅产物**；
- 写侧（R2 按钮/post 端点）**全部未点击未侦察动作**——留 T10'（批阅回写）解冻后第一侦察点。


## 26. D64 §26 引擎运维三角：体检 / 安装 / 重启 + start.bat-first 引导（事故复盘与决议 · 2026-10-08 晚）

### 26.1 本轮四起事故 → 根因 → 修复（commit 对照）

| # | 症状（用户侧） | 根因 | 修复 commit | 验证 |
|---|---|---|---|---|
| 1 | 「联网安装 Playwright」按钮闪一下即回落，安装输出区始终保持空白 | 引擎 SSE 写帧体把真换行写成**字面反斜杠+n**（`b"\\n\\n"`）：EventSource 解析不出任何 message/done 事件；`es.onerror` 静默 resolve(-1) 把错误吞没 | `1e8ba3a`（serve.py 540/543 行帧尾真换行 + runInstall 离线/中断/非零 rc 均落提示） | curl SSE `data:…$ $` / `event: done\ndata: 0` 逐帧可见；回归测试 `engine/tests/test_sse_framing.py` |
| 2 | 终端窗口一关/会话被清 → 引擎"神秘失踪"，Pages 显示离线 | 引擎进程生命周期与其启动终端绑定（开发期临时 `nohup`/前台进程），无常驻保障 | 用户侧行为约定：**双击 start.bat**（工作区收纳引擎）。新增 `/restart` 端点（回环哨兵 + os.execv 同端口再生）供已装用户免终端重启 | 实测 8767/8601 两端口 execv 再生成功；PWA「🔄 重启引擎」按钮闭环（受理→轮询 /status→自动重跑体检） |
| 3 | fetchDoctor 把引擎检查项的 **id 与 fix 字段映射时丢弃** → 🔧修复按钮永不出现、store id 定版失效回落名字启发式 | engineClient.ts 映射函数序列化不全 | `9a23eed`（id/fix 透传 + 体检键永远可点、离线提示含目标地址与具体失败原因） | build 全绿；bundle 含 restartEngine |
| 4 | Pages(公网 https PWA) → 本机引擎 全线失联（体检/安装离线） | Chrome **Private Network Access**：公共上下文访问本机私有地址需预检回 `Access-Control-Allow-Private-Network: true`，引擎一直未回该头 | `3034b7c`（do_OPTIONS 补头） | curl 伪造 Chrome PNA 预检 204 + 四 ACA 头齐 |

> 教训：SSE/安装这类"进程↔浏览器"链路必须有字面字节级验证（cat -A）；跨公网页面触达本机引擎必须把 PNA 头纳入端点验收清单。

### 26.2 决议：不做「协议启动键」，start.bat-first（2026-10-08 用户拍板）

- 曾讨论 `assist://` 自定义协议句柄方案（install.sh/ps1 注册、网页拉起进程）：**否决**——浏览器拉进程永远跨一道 OS 注册坎，收益低复杂度高；
- 采纳现实路径：体检离线态文案改为 **"双击工作区文件夹里的 start.bat"** 优先（`081464f`），`assist serve`/`uv run assist serve` 降为终端备选；CLI 已装用户的日常重启用 PWA「🔄 重启引擎」键；
- 超集保障不变：LAN 全功能方式 = `assist serve --lan`（强制随机 token，URL 样式 `http://<ip>:8602/?token=…`）。

### 26.3 start.bat 幂等口径（教师 FAQ 预写，下一步上 HelpView）

- 反复双击**不会重复下载**：Miniconda（仅无系统 python 时首装）、venv、引擎 zip、playwright 内核全部命中 `workspace/.runtime/` 既有缓存，二次启动 3–5 秒直达 `[6/6]`；
- **端口漂移特性**：8601 被占用时自动扫描 8601..8649 取第一个空闲口，浏览器地址栏端口以实际为准（曾因此误判"没打开 8601"）；
- 引擎退出/失败看 `start.log`（与 start.bat 同目录）尾部几行即可定位；窗口全英文提示为设计取舍（cmd 对 UTF-8 中文注释解析歧义，docs/05-D25/D27）。

### 26.4 本地同源页 vs Pages（教师何时用哪个）

| 入口 | 前端新鲜度 | 跨源关卡 | 建议用途 |
|---|---|---|---|
| start.bat 自开页 `http://127.0.0.1:<port>/` | 永远最新（引擎托管 dist-lan） | 无（同源） | **安装/修复类 SSE 进度流**（首次装 playwright 等）；离线兜底 |
| GitHub Pages | 按 main CI 滞后数分钟 | PNA（`3034b7c` 后引擎侧已豁免） | 日常编辑/预览/导出；体检/批阅（需本机已起引擎） |

后面待办：HelpView 顶部引导卡与设置中心 "?" 帮助卡按 §26.3/§26.4 口径更新文案（用户指示"先记文档、后上网页"）。
