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

> **状态校正（2026-10-09）**：T1–T9 均已有提交落地（T1 `af0b449`、T2 `a34c6e5`、T3 `dde1110`、T4 `1bb9b13`、T5 `d76c385`、T6–T9 `2c815dc`），T10 冻结不变。上表是需求启动时视图，状态已滞后；后续进度以提交、docs/12 与 §27 为准。

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

> **状态校正（2026-10-09）**：N1–N3 已由 `c8c303c` 落地；N4 前端版式 demo 已由 `c8c303c`/`ba9648e` 落地，但真实数据与引擎 `sheet_html report` 模式仍未接。上表状态已滞后，后续以提交与 §27.6 为准。

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
| 1 | 「联网安装 Playwright」按钮闪一下即回落，安装输出区始终保持空白 | 引擎 SSE 写帧体把真换行写成**字面反斜杠+n**（`b"\\n\\n"`）：EventSource 解析不出任何 message/done 事件；`es.onerror` 静默 resolve(-1) 把错误吞没 | `9409469`（serve.py 540/543 行帧尾真换行 + runInstall 离线/中断/非零 rc 均落提示） | curl SSE `data:…$ $` / `event: done\ndata: 0` 逐帧可见；回归测试 `engine/tests/test_sse_framing.py` |
| 2 | 终端窗口一关/会话被清 → 引擎"神秘失踪"，Pages 显示离线 | 引擎进程生命周期与其启动终端绑定（开发期临时 `nohup`/前台进程），无常驻保障 | 用户侧行为约定：**双击 start.bat**（工作区收纳引擎）。新增 `/restart` 端点（回环哨兵 + os.execv 同端口再生）供已装用户免终端重启 | 实测 8767/8601 两端口 execv 再生成功；PWA「🔄 重启引擎」按钮闭环（受理→轮询 /status→自动重跑体检） |
| 3 | fetchDoctor 把引擎检查项的 **id 与 fix 字段映射时丢弃** → 🔧修复按钮永不出现、store id 定版失效回落名字启发式 | engineClient.ts 映射函数序列化不全 | `5951f03`（id/fix 透传 + 体检键永远可点、离线提示含目标地址与具体失败原因） | build 全绿；bundle 含 restartEngine |
| 4 | Pages(公网 https PWA) → 本机引擎 全线失联（体检/安装离线） | Chrome **Private Network Access**：公共上下文访问本机私有地址需预检回 `Access-Control-Allow-Private-Network: true`，引擎一直未回该头 | `8e09b64`（do_OPTIONS 补头） | curl 伪造 Chrome PNA 预检 204 + 四 ACA 头齐 |

> 教训：SSE/安装这类"进程↔浏览器"链路必须有字面字节级验证（cat -A）；跨公网页面触达本机引擎必须把 PNA 头纳入端点验收清单。

### 26.2 决议：不做「协议启动键」，start.bat-first（2026-10-08 用户拍板）

- 曾讨论 `assist://` 自定义协议句柄方案（install.sh/ps1 注册、网页拉起进程）：**否决**——浏览器拉进程永远跨一道 OS 注册坎，收益低复杂度高；
- 采纳现实路径：体检离线态文案改为 **"双击工作区文件夹里的 start.bat"** 优先（`c77da46`），`assist serve`/`uv run assist serve` 降为终端备选；CLI 已装用户的日常重启用 PWA「🔄 重启引擎」键；
- 超集保障不变：LAN 全功能方式 = `assist serve --lan`（强制随机 token，URL 样式 `http://<ip>:8602/?token=…`）。

### 26.3 start.bat 幂等口径（教师 FAQ 预写，下一步上 HelpView）

- 反复双击**不会重复下载**：Miniconda（仅无系统 python 时首装）、venv、引擎 zip、playwright 内核全部命中 `workspace/.runtime/` 既有缓存，二次启动 3–5 秒直达 `[6/6]`；
- **端口漂移特性**：8601 被占用时自动扫描 8601..8649 取第一个空闲口，浏览器地址栏端口以实际为准（曾因此误判"没打开 8601"）；
- 引擎退出/失败看 `start.log`（与 start.bat 同目录）尾部几行即可定位；窗口全英文提示为设计取舍（cmd 对 UTF-8 中文注释解析歧义，docs/05-D25/D27）。

### 26.4 本地同源页 vs Pages（教师何时用哪个）

| 入口 | 前端新鲜度 | 跨源关卡 | 建议用途 |
|---|---|---|---|
| start.bat 自开页 `http://127.0.0.1:<port>/` | 永远最新（引擎托管 dist-lan） | 无（同源） | **安装/修复类 SSE 进度流**（首次装 playwright 等）；离线兜底 |
| GitHub Pages | 按 main CI 滞后数分钟 | PNA（`8e09b64` 后引擎侧已豁免） | 日常编辑/预览/导出；体检/批阅（需本机已起引擎） |

后面待办：HelpView 顶部引导卡与设置中心 "?" 帮助卡按 §26.3/§26.4 口径更新文案（用户指示"先记文档、后上网页"）。

#### 26.1-5 内核下载中断 · SSL DECRYPTION_FAILED_OR_BAD_RECORD_MAC（2026-10-09 晨 · 环境 TLS 面问题）

- **现场**：_engine 陈旧副本清除→start.bat 重拉新引擎→修复安装流水线全部走通（镜像 pip ✓ 包→dry-run ✓ 4 任务→cdn.npmmirror ✓ 195MiB 开始），
  但 chromium-1243(zip 205,123,748B≈195.6MiB) 下载至 8/195MiB @3s 时 urllib 抛
  `SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC`（OpenSSL 记录完整性校验失败）。
- **归因（证据链）**：
  1. 源侧健康：引擎日志属性齐全（server: Tengine / x-oss-request-id: 6AC8330A01F8FB391A40183 / content-length 205123748 / accept-ranges: bytes），沙箱侧另实测 TLSv1.3 直读 3MiB 无损——**非 CDN/对端问题**；
  2. pip 装 playwright Python 包同 TLS 栈已成功 → **排除 Python/TLS 配置**；
  3. 错误形态（传输中坏记录 MAC）是典型 **客户端环境 TLS 中间层干扰/链路抖动**：人群侧常见为网络加速器 / TUN 类代理（Clash 等）/ 校园网或运营商 DPI / 安全软件 TLS 优化 / 网卡 offload 兼容（Windows + 大范围分包）；
  4. 与 workspace 位于 `D:\BaiduSyncdisk`（百度网盘同步目录）**无关**（路径不涉网络）。
- **处置**（无代码改动）：
  1. 直接**再点一次 🔧修复**（每次写新 .part.zip，无残留/半截状态），瞬时抖动场景 1~3 次内多可成功；
  2. 连续失败走**浏览器直下人工解压**：浏览器（自带下载栈+断点续传）下载
     `https://cdn.npmmirror.com/binaries/playwright/builds/<build>/win64/chrome-win64.zip`
     （build 号=修复输出里"需 chromium-<N>"，示例 1243；历史 cft/153.0.8010.12），
     解压到 `<workspace>\.runtime\browsers\chromium-<N>\`（zip 内 chrome-win64/ 平铺即正确布局），
     并在 `chromium-<N>` 内新建空文件 `INSTALLATION_COMPLETE`（防 playwright 误判缺装；自带 DEPENDENCIES_VALIDATED 可省）；
  3. 机器本就装着 Chrome/chromium 时走**免下载通道**：系统级 `setx XXT_CHROME "C:\Program Files\Google\Chrome\Application\chrome.exe"`（路径以本机为准）→ PWA 🔄 重启引擎 使引擎进程读到新 env → 学习通只用本机 chrome，完全跳过 195MiB 内核下载（session.py L37/L39 已按此设计）；
  4. **不要改代码**（用户 2026-10-09 拍板）：本次为环境问题，"重试+多镜像/分片直连"等 afterwards 另提像 features 不阻塞。
- **留档影响**：§26.1 事故共 5 案；"安装农家乐"三信道（在线镜像 / 人工解压 / XXT_CHROME）今后写入 HelpView 文案时按 (1)(2)(3) 顺序给教师分层次的关键口径。

---

## 27. D65 浏览器获取与安装优先级 + 代码审核（用户重新明确 · 2026-10-09）

> 背景：昨晚首判为 start.bat/引擎下载问题；实际是工作区残留旧 `engine/` 目录，start.bat 命中 `ENGINE_LOCAL` 分支后跳过在线更新，继续使用旧 CLI；删除该目录后重新下载正常。随后阻塞点变为 Playwright chromium 下载卡在 `chromium-headless-shell`。
>
> 用户重新明确本任务：**本机浏览器优先 → 无则下载 → 多镜像源备用 → 网页直下包并注明安装位置、由 PWA 启动安装**；同时先做一轮代码审核，清理此前 AI 幻觉留下的未批准改动。
>
> 本节是重新立项后的正式实现需求，覆盖 §26.1-5 中“本次不改代码”的现场处置边界；§26.1-5 的事故结论仍保留。T10 / D64-f 写操作继续冻结。

### 27.0 当前事实基线（进入 R0 审核前）

- `start.bat` 当前确有旧目录遮蔽问题：
  - 脚本先判断 `%WORKSPACE%\engine\pyproject.toml`、`%ROOT%\engine\pyproject.toml`，命中即 `goto ENGINE_LOCAL`；
  - 只要工作区已有旧 `engine/`，就不会进入 `engine-main.zip` 下载链；
  - 验收目标是教师**不需要手工删除 `engine/`**，也能得到最新 CLI。
- Playwright 版本相关行为必须先审计再定版（当前只读抽查到 Playwright 1.57 的行为）：
  - `python -m playwright install chromium` 默认同时涉及 `chromium` 与 `chromium-headless-shell`；
  - `python -m playwright install chromium --no-shell` 可跳过 headless shell（版本兼容性、Windows 参数均需 R0 实测）；
  - Playwright 默认 `headless=True` 且未显式传 `channel` / `executable_path` 时，可能选中 `chromium-headless-shell`；
  - 显式使用本机浏览器 `channel=msedge|chrome`，或显式 `executable_path`，或完整版 `channel=chromium`，可不依赖 headless shell。
- 初步结论（待 R0 证据化）：**本机有可用浏览器时，不必要下载 headless 包；无本机浏览器时也优先只下载完整版 chromium，并通过显式启动链避免 headless shell。**

### 27.1 需求项与验收锚点

| 编号 | 需求 | 验收锚点 |
|---|---|---|
| D65-P0.0 | start.bat 快速缓存启动，且不被旧 `engine/` 目录遮蔽 | 有 `_engine` 时直接复用快速启动（不默认下载）；无 `_engine` 时下载最新；旧 `engine/` 不参与；更新检测/更新动作移到 D65-P4 |
| D65-P0.1 | 浏览器优先级链 | Ⅰ `XXT_CHROME` 显式路径 → Ⅱ 本机 Edge → Ⅲ 本机 Chrome → Ⅳ 其他受支持本机 Chromium → Ⅴ 才进入下载；每档真启动验证，前一档失败才降级 |
| D65-P0.2 | headless 包按需、默认不下载 | 有本机浏览器：零内核下载，体检/启动用本机浏览器；无本机浏览器：只准备完整版 chromium，`--no-shell`（或等价）通过 R0；任何启动档都不去找旧 headless shell |
| D65-P1 | 多镜像下载备用 | 以 Playwright `--dry-run` 给出的真实包名/URL 为基准；主源保留 npmmirror，另接华为云/官方等备用源；逐源重试、Content-Length 校验、失败可继续下一源，错误不得吞 |
| D65-P2 | 网页直下包 + PWA 启动安装 | PWA 展示每个包的下载链接、原文件名、目标相对路径、解压结构；用户放入指定收包目录后，PWA 识别“包已就位”并可启动安装；无需命令行 |
| D65-P3 | 教师可见引导与文档 | HelpView/docs/15 写清“本机浏览器优先、多镜像、人工直下、XXT_CHROME”的层次与各自适用场景 |
| D65-P4 | PWA 侧「检测更新 / 更新引擎」按钮（用户拍板 2026-10-09） | start.bat 保持快速缓存启动；PWA 对比远端 `engine-version.json` 与本地 engine commit；有更新才下载并提示重启；CLI 提供等价 `assist engine version/update` |
| D65-R0 | 代码审核前置门禁 | 先审后改：所有未提交/后续 AI 改动必须能映射到真实需求、真实文档或实测证据；未过审不得合入 |
| D65-D | 文档状态校正 | 修正 §18/§25 等滞后状态；禁止让后续模型只读旧表得出“T1–T9/N1–N4 全未做”的结论 |

### 27.2 浏览器优先级链（定版方向）

建议链序：

1. `XXT_CHROME` 环境变量显式路径（教师/运维手配，最高优先级）；
2. 本机 Edge（Windows 自带率最高，`channel=msedge`）；
3. 本机 Chrome（`channel=chrome`）；
4. 本机 Chromium / 发行版浏览器（`channel=chromium` 或显式路径）；
5. 以上全不可用：安装/使用 Playwright 完整版 chromium（不装 headless shell）。

要求：

- PWA/doctor 必须显示“当前实际会用的浏览器档位 + 路径 + 是否零下载”；
- 上一档启动失败时记录失败原因，再尝试下一档；全部失败才提示下载；
- 不修改系统默认浏览器、不要求管理员权限、不假设网络一定能直连官方源。

### 27.3 下载与多镜像（D65-P1）

1. 仅在“本机浏览器全不可用”时才下载内核；
2. 下载对象必须是 Playwright 当前锁版要求的**完整版 chromium**，默认跳过 `chromium-headless-shell`；
3. 安装命令优先使用 `python -m playwright install chromium --no-shell`；若当前 Playwright 版本不支持，必须写出等价过滤/只装完整版的兼容实现，并加回归测试；
4. URL 不靠猜测：
   - 首选从 `python -m playwright install chromium --dry-run` 输出中解析真实 `Download url` / `Install location`；
   - 镜像只允许替换已知 URL 前缀，不允许模型自行拼接不存在域名；
5. 源顺序（实现前 R0 可再定）：
   - 主：npmmirror（延续 D63 §22.1 口径）；
   - 备：华为云；
   - 末：dry-run 给出的官方 URL；
6. 每个源都必须：
   - 带 Content-Length 校验；
   - 支持重试；
   - 失败清理 `.part.zip`；
   - 输出可诊断日志（源、URL、已收字节、错误）。

### 27.4 网页直下包 + PWA 启动安装（D65-P2）

备用方案的完整闭环：

1. PWA 展示：
   - 包名（如 `chromium-<build>`）；
   - 原文件名（必须来自 dry-run URL 最后一段）；
   - 可复制/可点击的下载链接（多源）；
   - 目标解压位置：`<workspace>/.runtime/browsers/<browser-dir>/`；
   - 收包位置：`<workspace>/.runtime/browsers_pkgs/`（可再审核命名，但 UI 必须展示完整路径）；
   - 解压后的目录结构要求与 `INSTALLATION_COMPLETE` 标记说明。
2. 用户从浏览器下载 zip，放入收包目录；不要求自己解压到最终目录。
3. PWA 检测到包已就位，显示“开始安装”按钮。
4. 点击后由 PWA 调引擎执行：校验 zip 完整性 → 解压到 Playwright registry 目标目录 → 写 `INSTALLATION_COMPLETE` → 重跑 doctor → 状态变绿。
5. 全程不要求用户执行命令行、不要求手工建标记文件；命令行路径只作为终端用户的兜底说明。

### 27.5 代码审核门禁 D65-R0（本轮先做）

审核对象：

- 当前工作区未提交的 5 个 modified + 1 个 untracked（`serve.py`、`xxt/cli.py`、`xxt/extract_run.py`、`xxt/installer.py`、`xxt/session.py`、`xxt/browsers.py`）；
- 其中大量注释引用 **“D64 §26 A1/A2/A3”**，但该编号在 docs/16 正式文档中不存在，属于疑似幻觉编号；
- 审核这些改动与 D65 需求、§26.1-5 现场处置的关系，决定保留、重构、回滚或重写。

审核项：

| 编号 | 审核项 | 产出 |
|---|---|---|
| R0.1 | 工作区文物盘点：改动文件、时间、来源、是否引用不存在章节 | 清单 + “未批准改动”标记 |
| R0.2 | Playwright 版本/行为实测：默认装什么、`--no-shell` 是否可用、headless 何时选 headless shell | 实测日志 + 结论 |
| R0.3 | 启动链审核：本机浏览器探测、失败降级、是否可能回落到 headless shell | 每档证据 + 修复清单 |
| R0.4 | 安装器审核：dry-run URL、镜像 URL 真实性、重试/校验/解压/标记文件 | 风险清单 + 逐源验证 |
| R0.5 | start.bat 审核：旧 `engine/` 遮蔽、版本新鲜度、手动删除依赖 | 复现 + 定版修复方案 |
| R0.6 | PWA/接口审核：doctor 显示、修复按钮、SSE 终态、直下包 UI 是否已有 | 缺口清单 |
| R0.7 | 文档状态校正：D63/D64 旧表状态、D65 索引、HelpView 文案待办 | 更新记录 |
| R0.8 | 回归测试设计：浏览器探测、URL 解析、镜像回退、包完整性、无网络 mock | 测试用例清单 |

审核纪律：

- 每条结论标注依据：`文档/提交/实测/推断`；
- 只有 `文档/提交/实测` 支持的改动才可进入实现；
- 凡引用不存在的需求编号，一律先更正编号，不得继续沿用；
- 未过 R0，不进入 P0–P3 写代码。

### 27.6 执行批次（R0 通过后）

1. **P0**：start.bat 新鲜度 + 浏览器优先级链 + “不依赖 headless shell”闭环；
2. **P1**：多镜像下载与校验；
3. **P2**：人工直下包 + PWA 启动安装备用方案；
4. **P3**：HelpView/docs/15 教师引导 + doctor 展示 + 验收；
5. **P4**：PWA「检测更新 / 更新引擎」按钮 + CLI 等价命令；start.bat 保持快速缓存启动；
6. 全批次期间：D64-f 回写 / T10 继续冻结；不碰学习通写操作。

### 27.7 当前状态

- 2026-10-09：需求已由用户重新明确，登记为 D65。
- **R0 只读审核已完成，结论见 §27.8**；P0/P1 核心实施记录见 §27.9。
- 本文档为 D65 主需求档；docs/13 只保留索引。

### 27.8 D65-R0 审核结果（2026-10-09 · 只读）

> 本轮只读取证与文档更新，未修改 `engine/` / `app/` 代码。被审对象 = 工作区已有未提交改动（5 modified + 1 untracked）。

#### R0.1 文物盘点与幻觉编号

- 被审文件：
  - `engine/src/assist/serve.py`
  - `engine/src/assist/xxt/cli.py`
  - `engine/src/assist/xxt/extract_run.py`
  - `engine/src/assist/xxt/installer.py`
  - `engine/src/assist/xxt/session.py`
  - `engine/src/assist/xxt/browsers.py`（untracked）
- 文件时间戳均为 2026-10-09 11:12 左右，晚于 `f024429`（08:23）的“不要改代码”决议。
- 代码中 6 处注释引用 **“D64 §26 A1/A2/A3”**；`git grep` 在 HEAD 提交、docs/16 正文中均不存在该编号。该编号属于未落文档的**幻觉编号**。
- 结论：不能按“已拍板功能”直接接受；只能作为 D65 候选实现进行审核/重构/回滚。

#### R0.2 Playwright 行为实测（本机 Playwright 1.57.0）

- `python -m playwright install --help` 支持：
  - `--dry-run`
  - `--no-shell`（不装 headless shell）
  - `--only-shell`
- `python -m playwright install chromium --dry-run` 输出：
  1. `chromium` 完整版（本机 Linux 样例 `chromium-1200`）；
  2. `ffmpeg`；
  3. `chromium-headless-shell`；
  4. **再次输出 `ffmpeg`（重复项）**。
- `python -m playwright install chromium --no-shell --dry-run` 输出只剩完整版 `chromium` + `ffmpeg`，可天然避开 headless shell 与重复解析。
- 启动器源码审计：Playwright `getExecutableName(options)` 在：
  - `options.channel` 存在时直接返回 channel；
  - 否则 `headless=True` 返回 `chromium-headless-shell`；
  - 否则返回 `chromium`。
- 因此：
  - 有本机 Edge/Chrome，或显式 `executable_path`，或显式 `channel="chromium"` → 不走 headless shell；
  - 不显式指定 channel/executable_path 的 `headless=True` → 可能找 headless shell。
- 结论：D65-P0.2 成立；应优先用 `--no-shell`，启动链必须显式化。

#### R0.3 镜像可用性实测（HEAD 请求）

| 源 | Linux / Windows 样例 | 结论 |
|---|---|---|
| `cdn.npmmirror.com/binaries/playwright/builds/...` | `200 application/zip` | **可用**（现有主源） |
| `registry.npmmirror.com/-/binary/playwright/builds/...` | `302` 跳转至 cdn 后 `200 application/zip` | **可用，可作备用** |
| dry-run 官方 URL `cdn.playwright.dev/dbazure/download/...` | `307` 跳转 Google 存储后 `200`，zip | **可用** |
| `playwright.azureedge.net/builds/...` | `307` 跳转 Google 存储后 `200`，zip | **可用，可作备用** |
| 代码中的 `mirrors.huaweicloud.com/playwright/...` | `200 text/html`（SPA 页面），不是 zip | **不可用/伪源**，必须移除或替换 |

- 未提交代码中的 `MIRROR_PLAYWRIGHT_HW = https://mirrors.huaweicloud.com/playwright/` 会导致：
  - 主源失败后把 HTML 当 zip 下载；
  - 解压失败时不继续尝试官方源，直接失败。
- 结论：多镜像实现必须先做 URL 真实性验证，禁止模型拼接域名。

#### R0.4 未提交代码逐文件审核

| 文件 | 与 D65 的关系 | 风险/缺陷 | 处置建议 |
|---|---|---|---|
| `xxt/browsers.py` | 实现本机浏览器探测/优先级，方向对 | 文档引用幻觉编号；`inventory()` 只查文件存在，不验证可启动；Windows 不盘 Chromium；未记录实际选档 | 保留思想，重构 + 正编号 + 启动 probe + 返回 pick 证据 |
| `xxt/session.py` | `_launch` 逐档尝试，方向对 | 失败原因只存最后一个；无实际选档日志；测试缺失 | 保留重构，补日志/测试 |
| `xxt/extract_run.py` | 改用 `_launch`，方向对 | 依赖尚未审核的 launch 链 | 保留，随 session 一起定版 |
| `xxt/installer.py` | 本地包/多源/跳过 headless 方向对 | 用 `install chromium --dry-run` 解析出重复 `ffmpeg`；未去重；未用 `--no-shell`；华为云伪源；未校验 Content-Type/zip 魔数；`pkg_manifest` 用当前解释器 `find_spec` 而非目标 venv；loc/url 仅按位置 zip 配对 | **不可原样合入**；按 R0.2/R0.3 重写解析与源列表 |
| `xxt/cli.py` | 新增 `assist xxt install`，符合 CLI 超集 | 依赖 installer 重写 | 保留，随 installer 定版 |
| `serve.py` | doctor 本机浏览器优先 + `/pw/pkgs` 方向对 | `/pw/pkgs` 调用上述有缺陷的 manifest；doctor 可能因文件存在假绿；PWA 尚未消费 `/pw/pkgs` | 保留方向，随 P2 重构并补 PWA 消费 |
| 文档引用 | 多处 `D64 §26 A1/A2/A3` | 无对应拍板 | 改为 D65-P0.1/P0.2/P1/P2 等真实编号 |

#### R0.5 `start.bat` 旧 `engine/` 遮蔽

- `start.bat` 当前判断顺序：
  1. `%WORKSPACE%\engine\pyproject.toml` 存在 → `goto ENGINE_LOCAL`；
  2. `%ROOT%\engine\pyproject.toml` 存在 → `goto ENGINE_LOCAL`；
  3. 否则才走 `engine-main.zip` 下载链。
- 工作区只要残留旧 `engine/`，就会绕过在线更新，继续使用旧 CLI。与用户现场完全一致。
- 验收需要：无需手动删除 `engine/`；陈旧副本能自动识别并刷新，或给出明确一键更新路径。

#### R0.6 测试与 PWA 现状

- 现有 engine 回归：`40 passed`（本机 `.scratch/venv` + `PYTHONPATH=engine/src`），但**没有**新增代码的回归用例。
- 新增代码缺测试：浏览器档位、URL 解析、镜像回退、`--no-shell`、zip 校验、inbox 认领、start.bat 分流。
- PWA 现状：`SettingsView` 只有“联网安装 Playwright”按钮；无 `/pw/pkgs` 调用；无直下链接/收包路径/目标路径 UI；P2 完整未实现。
- SSE/`/install/playwright` 已有链路可复用，但输出与终态需随 installer 重写回归。

#### R0.7 门禁结论

- 结论：**R0 审核不通过原样合入**。
- 可保留的骨架：
  - 浏览器优先级概念；
  - `_launch` 逐档尝试；
  - `/pw/pkgs` 清单端点概念；
  - `.runtime/browsers_pkgs` 收包目录概念；
  - `assist xxt install` CLI。
- 必须先修正：
  1. 删除/更正全部幻觉编号；
  2. installer 改用 `--no-shell`、去重、真实镜像、Content-Type/zip 校验、目标 venv 检测；
  3. 浏览器 inventory 改为可启动验证，doctor 不假绿；
  4. start.bat 消除旧 `engine/` 遮蔽；
  5. 补回归测试与 PWA 消费 UI。
- 下一批次：按 §27.6 P0 开始；P0 完成后才能进入 P1/P2。

### 27.9 D65-P0/P1 实施记录（2026-10-09）

> 依据 §27.8 R0 结论实施；仍不触碰学习通写操作（T10 / D64-f 冻结）。

已完成：

- **P0.0 start.bat 旧 `engine/` 遮蔽 + 版本比较更新**
  - `tools/start.bat`、`app/public/start.bat`：`workspace\engine` / `ROOT\engine` 仅在显式 `ASSIST_ENGINE_LOCAL=1` 时才作为开发态复用；否则走 `_engine`。
  - 新增版本对比：远端 `dl/engine-version.json` vs 本地 `_engine\engine-version.json`；`FC /B` 相同则复用，不同才下载 `engine-main.zip`。
  - 版本检测失败（如 Pages 不可达）时回退使用本地 `_engine`，不冒险更新；更新流程走完依赖安装后启动**新的引擎进程**，即需要重启才生效。
  - CI `pages.yml` 新增发布**确定性** `engine-version.json`（只含 engine_version + commit；同一 commit 字节一致，避免 CI 重跑导致无意义更新）。
  - `tools/lint_bat.py` 通过。
- **P0.1 本机浏览器优先级**
  - `xxt/browsers.py`：链序 `XXT_CHROME → Edge → Chrome → Chromium → Playwright 完整版`。
  - `inventory(probe=True)` 会真正启动验证；doctor 不再仅按“文件存在”报绿。
  - `xxt/session.py` 的 `_launch` 使用同一链，逐档失败降级并保留最后错误。
- **P0.2 不依赖 headless shell**
  - installer 优先执行 `playwright install chromium --no-shell --dry-run`；旧版本不支持时回退普通 dry-run 并过滤 `headless_shell`。
  - 启动链始终显式 `channel` / `executable_path`，不落回默认 headless shell。
- **P1 多镜像与包校验（核心）**
  - 移除伪源 `mirrors.huaweicloud.com/playwright`。
  - 真实源顺序：`cdn.npmmirror.com` → `playwright.azureedge.net` → `registry.npmmirror.com` → dry-run 官方 URL。
  - 每个源校验 Content-Length、拒绝 HTML Content-Type、校验 zip 文件头；失败自动下一源。
  - dry-run 结果按 `Install location` 去重，修复重复 `ffmpeg` 任务。
  - 本地包目录 `.runtime/browsers_pkgs/` 认领优先于联网。
- **P2 备用方案（已落地）**
  - `/pw/pkgs` 返回每个包的直下链接、原文件名、收包目录、目标目录、安装/在包状态。
  - PWA 设置中心 Playwright 卡新增「浏览器内核直下（备用方案）」：
    - 「获取/刷新直下清单」；
    - 展示包名、原文件名、目标目录、收包目录、安装/在包状态；
    - 多镜像直下链接（npmmirror / azure / registry / official）；
    - 「从收包目录安装 / 复查内核」按钮复用 PWA 安装流程，本地包优先认领。
  - `engineClient.ts` 新增 `fetchPwPkgs()`；settings store 新增 `loadPwPkgs()`。

验证：

- `pytest engine/tests -q`：`46 passed`
- `python tools/lint_bat.py`：通过
- `bash tools/check-secrets.sh`：脱敏检查通过
- 新增回归：`engine/tests/test_d65_install_priority.py`

验证（P2 追加）：

- `npm run build`：通过。
- `npm run selfcheck:roster-fig`：ALL PASS。

- **P3 教师引导（已落地）**
  - `HelpView` 设置中心速查 + FAQ 已加入本机浏览器优先、直下备用、旧 `engine/` 更新说明。
  - `docs/15-usage-manual.md` 新增「D65 浏览器获取/安装速查」。

遗留：

1. 新版本 Playwright（dry-run 官方 URL 已不含 `builds/`）的国内镜像适配需按目标锁版再做一次实测；当前实现会安全退回官方 URL，不会造假源。
2. 仍待真机 Windows 验证：start.bat、Edge/Chrome 探测、人工直下包闭环。
3. 未提交：本次 D65 代码/文档改动均在工作区，等待复核与提交。


### 27.10 决议修订：更新检查改为 PWA 按钮触发（2026-10-09 用户拍板）

> 用户拍板：**PWA 侧提供「检测更新 / 更新引擎」按钮的方案更好；start.bat 的快速缓存启动保留。**
> 因此 D65-P0.0 的目标调整为“启动快、缓存优先、旧目录不遮蔽”，而“版本对比 + 是否更新”的主入口移到 D65-P4。

#### 27.10.1 调整后的职责边界

| 入口 | 职责 |
|---|---|
| `start.bat` | 有 `_engine` → 快速复用直接启动；无 `_engine` → 下载一次；旧 `engine/` / 仓库 `engine` 仅在 `ASSIST_ENGINE_LOCAL=1` 时用作开发态。默认启动路径不做大文件下载。 |
| PWA 设置中心 | **D65-P4 主入口**：显示本地 engine 版本/commit、远端 `engine-version.json`；用户点「检测更新」；有更新才点「更新引擎」。 |
| CLI | D1 超集等价：`assist engine version`、`assist engine update --check`、`assist engine update`（命令名实施时定版）。 |

#### 27.10.2 D65-P4 实施清单

- **P4.1 本地版本暴露**
  - 本地元数据文件：`<workspace>\_engine\engine-version.json`（CI 随 Pages 发布）。
  - 引擎读取本地元数据，并通过 `/status` 或新端点返回：
    - `engine_version`；
    - `commit`；
    - 本地 `_engine` 路径/是否存在。
- **P4.2 PWA 检测更新**
  - PWA 拉取远端：
    `https://pancong0711.github.io/assignment-assistant/dl/engine-version.json`
  - 与本地 engine commit 对比；
  - UI 三态：
    - 已是最新；
    - 有更新（显示远端 commit / 构建信息 / 「更新引擎」按钮）；
    - 无法检测（远端不可达；不阻塞使用）。
- **P4.3 PWA 触发更新**
  - 仅在用户点击「更新引擎」后下载 `engine-main.zip`；
  - 解压到 `_engine` 并重装 editable 依赖；
  - 更新完成后必须重启：调用现有 `/restart`，或由 PWA 引导用户关闭旧引擎后重新双击 start.bat；
  - 更新完成后 PWA 轮询 `/status`，确认 commit 已变为远端版本；
  - 全程走 jobs/SSE，输出失败有终态，不静默。
- **P4.4 start.bat 简化**
  - 保留快速缓存启动；
  - 27.9 中已实现的“启动时版本对比”视为**过渡实现**；P4 落地时按本次拍板决定移除或缩为可选 `--check-update`，避免每次双击都发版本请求。
- **P4.5 验收锚点**
  - 无更新：检测显示“已是最新”，不下载 zip；
  - 有更新：只有点击「更新引擎」才下载；
  - 更新后：重启成功、`/status` 的 commit 与远端一致；
  - 远端不可达：快速缓存启动与静态功能不受影响；
  - CLI 等价命令可完成 check/update。

#### 27.10.3 当前实现状态（2026-10-09 更新）

- 27.9 的 start.bat 版本对比已落地，作为过渡；
- **D65-P4 已实施**：
  - 引擎新增 `engine_update.py`，提供本地/远端版本对比与按需更新；
  - `serve` 新增 `GET /engine/version`，并支持 `POST /install/engine_update` 走 jobs/SSE；
  - PWA 设置中心新增「引擎更新」卡：检测更新、有更新才显示「更新引擎」、更新完成后自动 `/restart` + 轮询 + 重跑版本对比/体检；
  - CLI 新增 `assist engine version`、`assist engine update --check`、`assist engine update`；
  - UI 指引同步到 `HelpView` 与 `docs/15`。
- 远端 `engine-version.json` 由 CI `pages.yml` 随 Pages 发布；首次部署后生效。
- P4 验证：`pytest engine/tests -q` → `52 passed`；`npm run build` 通过；`selfcheck:roster-fig` ALL PASS；`/engine/version` 集成 curl 通过（远端标记部署前为 404，UI 如实显示“无法检测”，不阻塞本地使用）。
