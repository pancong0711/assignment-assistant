# D73 任务需求单：提取任务不中断 + Playwright 浏览器操作历史 + `assist.cli` 导入失败修复

> 状态：**第一阶段已实施（D73-1..D73-5 核心），待真机复测**。
> 关联：`docs/23-D72-pwa-extract-preview.md`（D72 第一阶段已落地）、
> `docs/16-xuexitong-integration.md` §20.3 过程预览、§25 D64 预览整合。
> 来源：2026-10-09 现场实测：
> - 点击「📥 提取账户数据」后切换选项卡，回来像“中断失败”；
> - 过程栏只有一张缩略图；
> - 失败提示：
>   `...\python.exe: No module named assist.cli`。

---

## 1. 现场现象

### 1.1 切换选项卡像“中断”

- 点击提取后，engine 侧 `POST /xxt/extract` 已返回 `job_id`，后台 job 实际在跑；
- 一旦切走学习通 tab，再回来：
  - 提取进度消失；
  - 看不到完成结果；
  - 重新点提取可能又发一个 job。

### 1.2 过程栏与“历史”

- 当前过程栏显示的是 run JSON 里的 `steps[]` + 截图；
- 实测只看到一张缩略图；
- 用户希望该栏目命名为：
  **Playwright 浏览器操作历史**
- 需要明确：
  - 新操作是覆盖，还是接续添加？
  - 能不能手动删除？

### 1.3 提取失败

```text
提取失败：D:\BaiduSyncdisk\toolsPy\2609assignment\.runtime\venv\Scripts\python.exe:
No module named assist.cli
```

这不是学习通登录问题，也不是提取算法问题，而是 engine 启动提取子进程时，
目标 Python 找不到 `assist.cli` 模块。

---

## 2. 代码级分析

### 2.1 job 本身不会因切换 tab 而中断

提取实际在 engine 侧：

```text
POST /xxt/extract
→ job_id
→ serve 后台 Popen 执行 assist xxt extract --all
→ 写 runs/xxt-*.json + pages/shots
```

切换 PWA tab 只会让 `XxetongView.vue` 卸载：

```ts
onUnmounted(() => {
  loginSeq += 1
  stopLoginPolling()
  stopExtractPolling()
})
```

所以：

- **engine job 不会因 tab 切换而停止**；
- 但 PWA 的 `extractTimer`、`extracting` 是组件本地状态；
- 切走后 job_id 丢失，回来不会自动恢复轮询；
- 结果可能已经写好，但 UI 不知道。

因此这不是“提取被中断”，而是**PWA 任务跟踪生命周期没有设计好**。

### 2.2 历史语义目前是“run 级”，不是单会话级

- 每次 `run_extract()` 生成新 run：
  ```text
  runs/xxt-<YYYYmmdd-HHMMSS>.json
  ```
- 导航步骤 `steps[]` 写在各自 run JSON 内；
- 截图写到：
  ```text
  pages/shots/xxt-<run_id>-stepNN.png
  ```
- PWA 当前只加载最新 run，或通过下拉选择旧 run；
- **新 run 不会覆盖旧 run**，历史是接续追加的；
- 但没有 run 删除接口，也没有历史管理 UI；
- 当前 run_id 只到秒，同一秒启动两个提取有覆盖风险。

### 2.3 `No module named assist.cli`

serve 侧执行 job 时用的是：

```python
cmd = [str(_venv_python()), "-m", "assist.cli", "xxt", "extract", "--all"]
```

可能原因：

1. `_venv_python()` 找到的 venv，当前没有安装/可导入 `assist` 包；
2. engine 进程本身不是由这个 Python 启动（例如 start.bat/手动终端/其他环境混用）；
3. 解耦后运行 engine 的 interpreter 与 `_venv_python()` 推导出的 interpreter 不是同一个；
4. Popen 的 `cwd`/环境没有把 engine 源码路径暴露给子进程；
5. editable 安装状态在半升级/回滚后处于不一致状态。

结论：

> 这是 engine 侧“子进程解释器/导入路径选择”问题，不是 tab 切换导致；  
> 但要一起修，因为提取按钮的可靠性依赖它。

---

## 3. D73 需求

### D73-1 job 生命周期跨 tab 恢复（必须）

目标：点击提取后，切走再回来，仍能看到进度或结果。

要求：

- 提取 job_id / 状态 / 开始时间保存到：
  - Pinia store；或
  - localStorage/IndexedDB（跨组件卸载恢复）。
- `XxetongView` onMounted 时：
  - 若存在活动 job，自动恢复轮询；
  - 若已结束，自动刷新 `/xxt/runs` 并载入最新 run。
- 组件卸载时只停止“轮询定时器”，不把 job 判失败。
- 按钮：
  - 有活动 job 时显示「提取中…」并禁用；
  - 防止重复提交。
- 若页面关闭/engine 重启导致 job 丢失：
  - 回退到“读取已有 run”；
  - 显示 job 可能已完成/已丢失的提示。

### D73-2 子进程解释器与导入路径修复（必须）

要求：

- 不要盲目使用 `_venv_python()`；以**正在运行 engine 的 Python**为准：
  - 优先 `sys.executable`；
  - 或对候选 Python 做 preflight。
- preflight：
  ```python
  python -c "import assist.cli; print('ok')"
  ```
  - 失败则在 job 第一行给出明确错误，不进提取流程。
- 子进程环境显式补：
  - `PYTHONPATH=<engine_root>/src`（源码/editable 场景）；
  - `ASSIST_WORKSPACE=<workspace>`；
  - `XXT_HOME` / `XXT_STORAGE`。
- `cwd` 固定到 `<workspace>`，不要依赖 `_ENGINE_ROOT.parent`。
- CLI 继续保留；PWA 仍只做 CLI 套壳。

### D73-3 Playwright 浏览器操作历史（必须）

UI 名称改为：

```text
Playwright 浏览器操作历史
```

定义：

- 每次提取 run = 一段独立历史；
- 新 run **接续添加**，不覆盖旧 run；
- 历史条目字段：
  - run_id
  - 开始/结束时间
  - 班级数/作业数/失败数
  - 是否含通知
  - 截图数量
- 选中某条历史：
  - 加载该 run 的 `steps[]`；
  - 显示对应 `/xxt/shot/...` 缩略图；
- run_id 建议加随机后缀，避免同一秒覆盖：
  ```text
  xxt-20261009-221233-a1b2c3
  ```

### D73-4 历史删除（必须，按用户口径确认程度）

需要支持手动删除，至少：

- 删除单条 run：
  - `runs/<run_id>.json`
  - `pages/shots/<run_id>-*`
  - `pages/<run_id>-*.html`
- 清空全部历史：
  - 严格二次确认；
  - 只删本次 run 产物，不删 storage/login-state。
- 删除接口：
  - 建议 `POST /xxt/run/<id>/delete`（沿用现有 POST/CORS 体系）；
  - 或新增 DELETE 并处理预检。
- 安全：
  - run_id 白名单正则；
  - 禁止 `..`/路径穿越；
  - 删除后 PWA 自动选中上一条或空态。

### D73-5 失败与过程输出（必须）

- job 进度写入 `/jobs` + terminal；
- 提取开始、发现课程、发现班级、逐班提取、完成/失败都要有日志；
- 失败时 PWA 显示最近 N 行，不只一行 error；
- `No module named assist.cli` 这类错误应在 job 开头就被 preflight 拦截并显示。

### D73-6 预览整合

- Playwright 操作历史使用现有 `ProcessStreamView`；
- 作业纸预览/批阅报告预览继续按 D72-5/D64-N4 的本地 run 数据源；
- 删除 run 后，对应预览数据同步失效并回到空态。

---

## 4. 验收标准

- [ ] 点击提取后切换 tab，再回来能看到“提取中”或已完成结果；
- [ ] 不会因切 tab 重复提交第二个 job；
- [ ] 提取 job 不再出现 `No module named assist.cli`；
- [ ] 过程栏命名为「Playwright 浏览器操作历史」；
- [ ] 新提取接续添加历史，不覆盖旧 run；
- [ ] 可查看历史 run 的 steps/截图；
- [ ] 可手动删除单条历史；删除后 JSON/截图/HTML 同步清理；
- [ ] 失败时显示 preflight/最近任务输出；
- [ ] 学习通侧仍然只读、零写改删。

---

## 5. 待拍板问题

1. 历史默认保留策略：永久保留，还是保留最近 N 条？
2. 删除入口放在历史条目行内，还是统一「管理历史」页？
3. 是否允许“清空全部历史”？
4. 提取默认是否抓通知（当前 D72 默认抓；耗时可能较长）？
5. 是否默认跳过已结课/默认班级/无作业班？

---

## 6. 非目标

- 不重写 Playwright 提取算法；
- 不改变 CLI 超集地位；
- 不引入 PWA 直连 chaoxing；
- 不处理批阅回写/公告发布；
- 不重构 D71 launcher/engine 解耦本身。

---

## 7. 实施记录（2026-10-09）

### 7.1 D73-1 提取 job 跨 tab 恢复

- 新增 Pinia store `app/src/stores/xxtJobs.ts`：
  - `extractJobId` / `extractStartedAt` / `extractMsg`；
  - localStorage key：`assignment-assistant.xxt-extract-job.v1`。
- `XxetongView.vue`：
  - `extracting` 改为由 `xxtJobs.extractJobId` 派生；
  - `startExtract` 提交成功后写 store；
  - `pollExtractJob` 轮询 job，消息写 store；
  - 组件卸载只 `stopExtractPolling()`，不清 job；
  - `onMounted` 若 store 有 job_id，自动恢复轮询；
  - 活动 job 时按钮禁用，防重复提交。

### 7.2 D73-2 子进程解释器/导入路径修复

`serve.py` 新增：

- `_xxt_python()`：优先 `sys.executable`（正在运行 engine 的解释器），fallback `_venv_python()`；
- `_xxt_env(home)`：
  - `XXT_HOME`、`XXT_STORAGE`；
  - `ASSIST_WORKSPACE`；
  - `PYTHONPATH=<engine_root>/src` 前置；
- `_xxt_cli_cmd(args)`：统一 `[python, -m, assist.cli, ...]`；
- `_xxt_preflight(cwd, env)`：
  - 执行 `python -c "import assist.cli"`；
  - 失败时返回可读 stderr，并让 `/xxt/login/start`、`/xxt/extract` 直接返回 500，而不是后台 job 里只报一条 `No module named assist.cli`；
- `_start_stream_job(..., cwd=...)`：cwd 固定 workspace，不再依赖 `_ENGINE_ROOT.parent`。

### 7.3 D73-3 Playwright 浏览器操作历史

- 学习通页过程卡标题改为：
  **Playwright 浏览器操作历史**；
- run 列表下拉文案改为「历史 run」；
- 新提取生成新 run，不覆盖旧 run；
- `extract_run.run_id` 增加随机后缀：
  ```text
  xxt-YYYYmmdd-HHMMSS-<6hex>
  ```
  避免同一秒启动两个提取时覆盖。

### 7.4 D73-4 历史删除

- `layout.delete_run_artifacts(run_id, home)`：
  - 删除 `runs/<run_id>.json` 或旧根目录 `<run_id>.json`；
  - 删除新/旧 `shots/<run_id>-*.png`；
  - HTML 存档暂不删（当前按 class/work 命名、跨 run 共享）。
- `serve.py` 新增：
  ```text
  POST /xxt/run/<run_id>/delete
  ```
- PWA 新增「🗑 删除本 run」按钮，删除当前选中 run 后自动刷新列表。

### 7.5 D73-5 失败与过程输出

- preflight 失败：HTTP 500 + `detail`；
- 提取 job 输出继续经 `/jobs`/terminal/start.log 实时转发；
- PWA 失败时显示最近一条任务输出。

### 7.6 验证

- `pytest engine/tests -q` → **84 passed**；
- `python tools/lint_bat.py` → 通过；
- `bash -n tools/start.sh` → 通过；
- `npm run build` → 通过；
- 新增回归：
  - `_xxt_env` 含 `PYTHONPATH/ASSIST_WORKSPACE`；
  - `delete_run_artifacts` 删 JSON + run 级截图；
  - layout 路径契约；
  - CLI `xxt extract --all`。

### 7.7 待复测/后续

- 真机验证切换 tab 后 job 恢复；
- 真机验证 `No module named assist.cli` 不再出现；
- 后续可扩展：
  - 历史列表 UI（时间/班级/作业/失败数）；
  - 清空全部历史；
  - HTML 存档按 run_id 重命名后再纳入删除。

---

## 8. D73 现场新增问题（2026-10-10）

### 8.1 更新引擎：PWA 报超时，但 start.bat 显示安装成功

**现场输出（PWA）：**

```text
检测到新版本：0.1.0（commit 7c4af0527059）
下载 engine-main.zip → staging
✓ 新引擎已暂存...
♻ 更新包已暂存，正在请求重启并由 launcher 安装……
⚠ 更新包已暂存，但自动重启/安装失败：引擎在时限内未重回在线；
  请关闭终端后双击 start.bat。
```

**terminal：** 安装成功，然后出现“按任意键继续”。

**代码分析：**

- `restartEngineAndWait(180000)` 只轮询 `/status` 是否回在线，没有读 launcher 的安装状态；
- start.bat `:APPLY_UPDATE` 成功/失败没有写状态文件，PWA 无法区分：
  - 还在 pip install；
  - 安装成功但 engine 启动失败；
  - 安装成功、engine 已回在线但 PWA 没看到；
- “按任意键继续”说明 start.bat 走到了某个 `pause`，需要结合 `start.log` 判断
  是 engine 启动后退出，还是 `:UPDATE_APPLY_FAILED`；
- 仅靠加长 PWA 等待时间不是根治：必须有 launcher 状态回执。

**D73-7 要求：launcher 更新状态回执 + PWA 对账**

- start.bat/start.sh 在 `:APPLY_UPDATE` 写状态文件：
  ```text
  _engine/update.status.json
  {
    "stage": "pending|installing|installed|failed",
    "commit": "...",
    "started_at": "...",
    "finished_at": "...",
    "returncode": 0/1,
    "log_tail": "..."
  }
  ```
- PWA 更新流程：
  - 先轮询 `/status`；
  - 同时轮询更新状态（或 `/engine/update/status` 端点）；
  - 如果 launcher 报 `installed` 但 `/status` 未回在线，显示 `start.log` 尾部，
    而不是只说“超时”；
  - 如果 launcher 报 `failed`，直接显示失败原因和回滚状态。
- 只有确认新 engine 回在线且 `instance_id` 变化，PWA 才显示更新成功。
- PWA 的等待策略改为“阶段驱动”，不再只靠固定 180s。

### 8.2 `xxt extract --all` 发现 0 个课程/班级

**现场 run JSON：**

```json
{
 "run_id": "xxt-20261010-124628-000102",
 "session": {"verdict": "alive"},
 "courses": [],
 "failures": [{"kind":"not_extracted","detail":"discover found 0 courses/classes"}],
 "target_source": "discover",
 "steps": [
   {"action":"发现课程列表","title":"课程",
    "url":"https://mooc2-ans.chaoxing.com/visit/interaction"}
 ]
}
```

**代码分析：**

- `discover_courses()` 已成功 goto 互动页，并保存 `pages/discover-courses.html`；
- 但 `JS_COURSES` 没有扫描出任何 `a[href*="courseId="]`；
- 旧 `.scratch/xxt_readonly_extract.py` 同样用这个 selector，之前可工作；
  现在失败可能原因：
  1. 页面 JS 渲染/跳转比 5s 更慢；
  2. Edge/Chrome 与旧 Playwright Chromium 的 DOM/登录后页面差异；
  3. 课程链接形态变化（`courseid=` / `%3D` / `data-courseid` / 卡片非 `<a>`）；
  4. 互动页需要等待某个 tab/接口返回；
  5. 登录会话虽然 alive，但账号首页/课程页未渲染。

**D73-8 要求：发现课程/班级可诊断、可降级**

- 保留 HTML archive：`pages/discover-courses.html`；
- 诊断字段写入 run JSON/failures：
  - `final_url`
  - `title`
  - `anchor_count`
  - `course_link_count`
  - `body_snippet`
  - `browser`（msedge/chrome/chromium）
- 发现课程 fallback 顺序：
  1. 等 `networkidle` 或更长 settle（可配置）；
  2. `a[href*="courseId="]`；
  3. `a[href*="courseid="]` / URL decode / `%3D`；
  4. `[data-courseid]` / 课程卡片选择器；
  5. 若仍为 0，失败时明确给出 HTML archive 路径与诊断计数。
- 班级发现同理增加 fallback 和诊断。
- 保留 CLI `--targets` 精确路径；后续 PWA 可上传 targets 兜底。

### 8.3 旧提取数据为什么“没展示在 PWA 上”

用户口径：旧代码能提取，数据已存在；但 PWA 没有展示。

**代码分析：**

- 旧脚本产物是：
  - `.scratch/xxt-readonly.json`：目标清单语义（courses/classes/homeworks/samples），不是 run schema；
  - `.scratch/xxt-*.json`：旧全量 driver 产物，schema 与 D63 §19 run 不完全一致；
- 当前 PWA `/xxt/runs` 只扫 `xxt_home()/runs` + 旧根目录，并加载 run schema：
  - 需要 `run_id`、`courses[].classes[]`、`works[]`、`steps[]` 等；
- `layout.run_json_files()` 主动排除了 `xxt-readonly.json`、`xxt-notices.json` 等旧文件；
- 教师机 `xxt_home()` 是 `.runtime/xxt`，旧 `.scratch` 数据即使存在，也可能不在扫描路径；
- 所以“旧代码有数据但 PWA 不显示”不是数据消失，而是：
  1. 数据不在当前 artifact 路径；
  2. 旧 schema 与 PWA 消费 schema 不一致；
  3. PWA 没有“导入旧 run/兼容旧格式”入口。

**D73-9 要求：旧数据兼容/导入**

- 提供诊断命令或 PWA 空态提示：
  - 当前 `xxt_home` 路径；
  - 扫描到的 run 文件列表；
  - 发现旧文件但不满足 schema 时，列出文件路径与原因；
- 增加 `assist xxt run import <json>`（名称待定）：
  - 把旧 `.scratch/xxt-*.json` 规范化为 run schema；
  - 或至少复制到 `xxt_home()/runs/` 并补 `run_id`；
- PWA 空态提供“扫描旧数据”按钮或明确 CLI 命令提示；
- 不自动吞掉旧文件，避免把非 run JSON 误当 run。

---

## 9. D72 / D73 收尾清单（截至 2026-10-10）

### D72 未完成

1. **D72-5 真实数据预览**：
   - 过程预览已打通；
   - 作业纸预览真实班级/学生上下文已具备数据基础；
   - 批阅报告预览（D64-N4）尚未接真实 submission/图片流转录。
2. **D72-2/D72-3 targets 模式**：
   - 第一版只有 `--all`；
   - “先发现课程/班级 → 勾选 → 提取”未做；
   - targets 上传/默认来源未做。
3. **发现能力可靠性**：见 D73-8。

### D73 未完成

1. D73-7 launcher 更新状态回执；
2. D73-8 课程/班级发现 fallback 与诊断；
3. D73-9 旧数据兼容/导入；
4. 历史管理 UI 完善（时间/班级/作业/失败数、清空全部）；
5. HTML 存档按 run_id 归档后再纳入删除。

### 建议顺序

1. D73-8：先让 `--all` 能发现课程/班级（提取链路根）；
2. D73-7：修 launcher/PWA 更新状态对账；
3. D73-9：兼容旧数据，让“以前提取过”的数据能被 PWA 看到；
4. D72-5：作业纸/批阅报告真实预览；
5. 历史管理与 targets 选择作为收尾增强。
