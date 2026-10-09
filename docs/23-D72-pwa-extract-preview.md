# D72 任务需求单：PWA 一键提取账户信息 + 预览整合（作业纸 / 批阅报告 / 过程页）

> 状态：**需求定稿 / 待实施**。
> 关联：
> - `docs/16-xuexitong-integration.md` §14/§17/§19/§20.3/§25
> - `docs/22-D71-engine-launcher-two-phase-update.md`
> - 旧只读脚本：`.scratch/xxt_readonly_extract.py`、`.scratch/xxt_extract_full.py`、
>   `.scratch/xxt_notice_full.py`、`.scratch/xxt_session_check.py`
> - engine 现有：`assist/xxt/extractor.py`、`assist/xxt/extract_run.py`
> - PWA 现有：`XxetongView.vue`、`ProcessStreamView.vue`、`SheetPreviewSection.vue`、
>   `lib/reports.ts` / 批阅报告 D64-N4 demo

---

## 1. 目标

在 PWA 学习通选项卡增加**一键提取账户数据**能力：

```text
扫码登录成功
→ 点击「📥 提取账户数据」
→ engine 后台 job：发现课程/班级/作业/通知/名单
→ 写 run JSON + pages/shots
→ PWA 自动刷新列表
→ 在同页可看导航过程预览 / 作业纸预览 / 批阅报告预览
```

核心原则：

1. **PWA 做 CLI 套壳**：提取逻辑只保留一份，PWA 只提交 job、显示进度、消费结果；
2. **单一真会话**：全程复用 engine 的 storage，不出现第二登录；
3. **只读提取**：学习通侧零写改删；
4. **先发现、后提取**：借鉴旧 `xxt_readonly_extract.py`，先读课程/班级，再提取信息；
5. **预览本地化**：过程截图/作业纸/批阅报告都从本地 run JSON / 工件读取，不直接访问 chaoxing 域。

---

## 2. 当前缺口

### 2.1 PWA 只有“读取”，没有“提取”

- 按钮「⟳ 刷新/更新列表」调用 `GET /xxt/runs`，只读已有 run；
- 没有 `POST /xxt/extract` 端点；
- 没有“扫描账户里有哪些课程/班级”的能力。

### 2.2 CLI 提取依赖 targets JSON

现有命令：

```text
assist xxt extract --targets targets.json
```

它要求先有课程/班级清单，不负责“扫描教师账号”。

### 2.3 artifact 路径不一致

CLI 写：

```text
<xxt_home>/runs/xxt-*.json
<xxt_home>/pages/shots/*.png
```

serve 读：

```text
<xxt_home>/xxt-*.json
<xxt_home>/<run_id>.json
<xxt_home>/xxt-pages/shots/*.png
```

即使 CLI 提取成功，PWA 也可能看不到。

### 2.4 旧只读方法已验证，但未正式纳入 engine

旧脚本已证明可读：

- 课程：`a[href*="courseId="]`
- 班级：`li.classli`
- 作业：`[onclick*="viewWork"]`
- 学生：`review-work` 页 / 批阅名单
- 通知：`myNoticeList`
- 每次导航：`_step()` + 截图（过程预览数据源）

---

## 3. D72-1：统一 artifact 路径契约（先行）

定义统一 helper：

```python
xxt_runs_dir()  = xxt_home() / "runs"
xxt_pages_dir() = xxt_home() / "pages"
xxt_shots_dir() = xxt_pages_dir() / "shots"
```

- CLI `xxt extract` 继续写 `runs/`、`pages/`；
- serve：
  - `/xxt/runs` 扫描 `runs/xxt-*.json`，兼容旧根目录；
  - `/xxt/run/<id>` 先查 `runs/<id>.json`，兼容旧根目录；
  - `/xxt/shot/...` 先查 `pages/shots/`，兼容旧 `xxt-pages/shots/`；
- 新增回归测试防止再次漂移。

**验收**：CLI 运行 extract 后，PWA 刷新列表能看到新 run；过程框能加载截图。

---

## 4. D72-2：engine “账户发现 + 全量提取”

### 4.1 借鉴旧脚本

旧 `.scratch/xxt_readonly_extract.py` 的步骤映射：

| 旧函数 | 功能 | D72 落点 |
|---|---|---|
| `extract_courses(page)` | 互动页扫描课程 | `assist/xxt/discover.py::discover_courses` |
| `extract_classes(page, course_id)` | 扫 `li.classli` | `discover_classes` |
| `extract_homeworks(page)` | 扫 `viewWork` | 复用 `extractor.py` 逻辑 |
| `extract_students_from_review(...)` | 批阅页学生状态/名单 | 复用 `extractor.py` |
| `save(name,page)` | HTML 存档 | `pages/` + `archive()` |
| `_step` 截图 | 导航过程预览 | `pages/shots/` + `steps[]` |

旧 `.scratch/xxt_extract_full.py` 可直接作为全量 driver 参照：

- 读取 round-1 清单；
- 对每门课探测 cpi；
- 逐班直达导航；
- 输出 run JSON + HTML 存档。

### 4.2 新增 CLI 能力

建议：

```text
assist xxt extract --all
```

内部流程：

1. `check_session()` → alive；
2. 发现课程；
3. 发现班级（可过滤已结课/默认班级/无作业班，需定口径）；
4. 生成 targets；
5. 调用现有 `run_extract()`；
6. 写 `runs/xxt-*.json` + `pages/shots`；
7. 保留 `--targets` 显式路径作为兼容/精确提取。

### 4.3 run JSON 需要保留的预览字段

在现有 schema 基础上，明确保留/补充：

- `steps[]`：导航过程事件（action/detail/title/url/ts/shot）；
- `archives`：HTML/截图相对路径；
- `submitted_names[].review_path`：批阅报告后续数据源；
- `session`：storage/verdict（不写敏感内容）；
- `failures[]`：失败留痕三分类。

---

## 5. D72-3：engine `POST /xxt/extract` job

建议端点：

```text
POST /xxt/extract
body: { "mode": "all" | "targets", "targets": {...}, "skip_notices": true|false }
→ { ok: true, job_id }
```

- 后台执行与 CLI 相同的 engine 函数；
- 复用现有 `/jobs/<id>` 与 SSE 输出；
- 不阻塞 HTTP；
- 失败时任务日志完整可读；
- 提取完成后写入 run JSON，不自动触发任何写操作。

---

## 6. D72-4：PWA 学习通页新增“提取”按钮

### 6.1 第一版（推荐先做）

```text
【📥 提取账户数据】
```

点击后：

1. 调 `POST /xxt/extract`（mode=all）；
2. 轮询 job 状态并显示进度；
3. 完成后调 `GET /xxt/runs`，自动载入最新 run；
4. 列表、通知、过程预览自动刷新。

### 6.2 第二版

- `【读取课程/班级】` → 展示勾选列表；
- 老师选择目标班级；
- `【开始提取】` → `mode=targets`。

### 6.3 文案修正

- 现有「刷新/更新列表」改为「刷新列表（读取已有 run）」；
- 明确区分：
  - 刷新 = 读已有；
  - 提取 = 去学习通抓新数据。

---

## 7. D72-5：预览页面整合

### 7.1 提取过程预览（已有组件 `ProcessStreamView`）

- 数据源：run JSON `steps[]` + `/xxt/shot/<run_id>/<file>`；
- 每次导航 `_step()` 写 step、截缩略图；
- PWA 学习通页复用现有过程框；
- 批阅页后续复用同一组件（D64-N3）。

### 7.2 作业纸预览

- 现有作业纸预览（`SheetPreviewSection` / `sheetHtml`）继续作为模板级预览；
- D72 提取结果提供班级/学生/作业上下文后，班级与标签页可据此生成整班作业纸预览；
- 预览仍从本地 taskpad/run 数据渲染，不新增 chaoxing 直连。

### 7.3 批阅报告预览（D64-N4）

- D64-N4 的前端报告版式 demo 保留；
- D72 的 run JSON 需保留 `review_path` 等字段，供后续：
  1. 下载学生作答；
  2. 转录/评阅；
  3. 按作业纸式报告版式预览/导出。
- D72 只做数据准备与预览挂载，不做批阅回写（仍冻结）。

### 7.4 预览硬边界

- 截图/HTML 存档只来自 engine 真会话；
- PWA 不直接向 chaoxing 域请求；
- 预览数据只读本地文件；
- run 删除/损坏时，预览降级为空态而不是报错白屏。

---

## 8. D72-6：验收标准

- [ ] CLI `assist xxt extract` 产物能被 PWA 列表和过程预览读取；
- [ ] 扫码登录后，PWA 一键提取可成功发现课程/班级并写 run JSON；
- [ ] job 有进度、有失败日志，不阻塞页面；
- [ ] 提取完成后列表自动刷新，通知/步骤/截图可见；
- [ ] 作业纸预览与批阅报告预览可使用本地 run 数据，无 chaoxing 直连；
- [ ] 学习通侧零写改删；
- [ ] `pytest`、`npm run build`、`lint_bat`、脱敏检查通过。

---

## 9. D72-7：实施顺序

1. D72-1 路径契约统一 + 回归测试；
2. D72-2 `discover.py` + `assist xxt extract --all`；
3. D72-3 `POST /xxt/extract` job；
4. D72-4 PWA 提取按钮 + 进度 + 自动刷新；
5. D72-5 预览整合：
   - 过程预览复用 `ProcessStreamView`；
   - 作业纸/批阅报告预览挂到 run 数据源；
6. 真实账号只读验收。

---

## 10. 待拍板问题

1. 第一版默认“全部课程/班级”，还是“先发现再勾选”？
2. 是否默认跳过已结课/默认班级/无作业班？
3. 通知抓取是否默认开启，还是沿用 `skip_notices` 选项？
4. 批阅报告预览所需数据：D72 只保留 `review_path`，还是同时下载少量样例原图做离线 demo？
5. 过程截图保留策略：每 run 全留，还是保留最近 N 个 run？

---

## 11. 非目标

- 本单不实现批阅回写/公告发布；
- 本单不重写学习通前端；
- 本单不让 PWA 直接访问 chaoxing 域；
- 本单不改变 CLI 作为超集/应急通道的地位。
