# D73 任务需求单：提取任务不中断 + Playwright 浏览器操作历史 + `assist.cli` 导入失败修复

> 状态：**D73-1..D73-5、D73-8 已实施，待真机复测；D73-7/D73-9 待实施**。
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
检测到新版本：0.1.0（commit be5efb740ddc）
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
- 旧 `.scratch/xxt_readonly_extract.py` 只扫描一次 `a[href*="courseId="]`，
  **不支持课程文件夹递归**；之前可工作是因为当时课程在根目录；
  现在用户用文件夹管理课程，根目录只有文件夹，因此会返回 0；
- 其他可能原因：
  1. 页面 JS 渲染/跳转比 5s 更慢；
  2. Edge/Chrome 与旧 Playwright Chromium 的 DOM/登录后页面差异；
  3. 课程链接形态变化（`courseid=` / `%3D` / `data-courseid` / 卡片非 `<a>`）；
  4. 互动页需要等待某个 tab/接口返回；
  5. 登录会话虽然 alive，但账号首页/课程页未渲染。

**2026-10-10 `discover-courses.html` + 只读端点实测结论：**

- 这份 HTML 根目录 `a[href*="courseId="]` 数量为 **0**；
- 但存在 3 个顶层课程文件夹：
  - `fileid=5210383`，名称“在教”；
  - `fileid=3038132`，名称“实验”；
  - `fileid=2344825`，名称“其他”；
- 用保留会话对这些 folder id 只读调用 `POST /mooc2-ans/visit/courselistdata`：
  - 5210383 → 2 门唯一课程；
  - 3038132 → 8 门唯一课程；
  - 2344825 → 13 门唯一课程；
- 说明课程确实在文件夹里，必须按 `courseFolderId` 递归请求；
- 本次样本没有发现二级文件夹，但解析仍需支持 `li[fileid]` / `intoFolder(id)` 递归。

**2026-10-10 `discover-courses.html` 实测分析（D73-8 定因）：**

已收到教师机 `discover-courses.html`，只读统计：

```text
courseId=    0
courseid=    0
getFileCourseList 只出现函数定义，1 次
courselistArea 容器存在，但没有课程数据
```

说明：

- 页面框架加载了，但**填充课程列表的 AJAX 没有成功**；
- `#courselistArea` 仍是空壳，所以 `a[href*="courseId="]` 为 0；
- 这不是“账号没有课程”，而是 discovery 所在的浏览器上下文把课程列表请求拦截了。

**根因：`ReadOnlyExtractor._install_readonly_route()` 把所有非 GET 请求都 abort 了。**

学习通互动页的课程列表是：

```text
POST /mooc2-ans/visit/courselistdata
```

这是一个**只读列表 POST 接口**，不是写操作。  
当前 route 硬只读策略把 `POST` 全部 abort，导致：

- 页面自己的 `ajaxGetCourseList()` 失败；
- `#courselistArea` 为空；
- `discover_courses()` 扫描不到任何课程；
- 旧 `.scratch/xxt_readonly_extract.py` 没有这个 route 拦截，所以当时能跑通。

这解释了两个现象：

1. 旧代码能提取、PWA/engine `--all` 为空；
2. 有文件夹/无文件夹账号都会失败，不是文件夹本身导致。

**修复优先级：**

1. 在 route 白名单中允许：
   ```text
   POST /mooc2-ans/visit/courselistdata
   ```
   （以及后续确认的其他只读 POST 列表接口；其余非 GET 继续 abort）
2. 或让 discovery 使用 `ctx.request.post` 直接调该端点，绕过页面 route；
3. 仍保留写操作 POST/PUT/DELETE 拦截。



在保留的旧会话上做只读测试，确认学习通互动页的课程列表实际是 AJAX 加载：

- 页面内 JS 函数：
  ```js
  function ajaxGetCourseList() {
    ...
    $.ajax({
      url: "/mooc2-ans/visit/courselistdata",
      type: "post",
      data: {
        courseType, courseFolderId, query, pageHeader,
        single, superstarClass, isFirefly, fid, from
      },
      dataType: "html",
      success: function(data){ $("#courselistArea").html(data); ... }
    });
  }
  ```
- 文件夹点击函数：
  ```js
  function getFileCourseList(obj, id, name) { intoFolder(id) }
  function intoFolder(courseFolderId) {
    $("#courseFolderId").val(courseFolderId);
    ajaxGetCourseList();
  }
  ```
- 也就是说：
  - 根目录课程和文件夹由 `/visit/courselistdata` 返回；
  - 文件夹里的课程需要带着 `courseFolderId` **递归请求同一端点**获得；
  - 旧 `.scratch/xxt_readonly_extract.py` 只扫描一次 `a[href*="courseId="]`，
    因此它天然只能发现**根目录课程**，无法发现文件夹里的课程；
  - 当前 `discover_courses()` 更是叠加了 route 拦截：页面 AJAX 被 abort，
  连根目录课程都拿不到；文件夹递归则是第二层待补能力。

只读实测还确认：

- 用 Playwright 的 `ctx.request.post("/mooc2-ans/visit/courselistdata", form=...)`
  可以拿到与页面 AJAX 相同的 HTML；
- 该 HTML 里包含课程卡片和文件夹回调；
- 对 `courseType=0`（我教的课）和 `courseType=1`（我学的课）都要兼容探测；
- 根目录一次返回可能出现**重复链接**，必须按 `courseId` 去重。

**修复方案（D73-8 定版方向）：**

在 `ReadOnlyExtractor.discover_courses()` 内改为：

1. goto `https://mooc2-ans.chaoxing.com/visit/interaction`；
2. 读取隐藏字段：
   `courseType / superstarClass / single / filterFid / from / tchPageHeader / stuPageHeader / isFirefly`；
3. 对 `courseType=0` 和 `courseType=1`：
   - 从 `courseFolderId=0` 开始 BFS；
   - 用 `ctx.request.post` 调用 `/mooc2-ans/visit/courselistdata`；
   - 解析返回 HTML：
     - `a[href*="courseId="]` → 课程，按 courseId 去重；
     - `[onclick*="getFileCourseList"]` → 文件夹 id/name；
   - 对每个未访问的 folder id 继续请求；
4. 保存每个 folder 响应 HTML 到：
   `pages/discover-courselist-<courseType>-<folderId>.html`；
5. 将发现结果写入 run JSON 的 `steps[]` 与 failures 诊断；
6. 保留 DOM fallback：若请求端点失败，再扫描当前页面 anchors。

**注意：**

- `/visit/courselistdata` 是 POST，但它是**只读列表接口**；
  需要在 route 白名单中允许该路径，或使用 `ctx.request` 绕开页面 route；
- 这是本轮“发现能力可靠性”的核心修复点。

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

### D73 未完成

1. D73-7 launcher 更新状态回执；
2. D73-9 旧数据兼容/导入；
3. 历史管理 UI 完善（时间/班级/作业/失败数、清空全部）；
4. HTML 存档按 run_id 归档后再纳入删除。
5. D73-8 已实施（只读 POST 白名单 + courseFolderId BFS + 根目录/文件夹课程发现）。

### 建议顺序

1. D73-7：修 launcher/PWA 更新状态对账；
2. D73-9：兼容旧数据，让“以前提取过”的数据能被 PWA 看到；
3. D72-5：作业纸/批阅报告真实预览（可先用某门已批阅课程/作业纸作为样例）；
4. 历史管理与 targets 选择作为收尾增强。

---

## 10. D73-8 实施记录（2026-10-10）

### 10.1 route 白名单

`ReadOnlyExtractor` 新增纯函数：

```python
def readonly_route_decision(method, url) -> "continue"|"abort"
```

规则：

- `GET/HEAD/OPTIONS` → continue；
- `POST /mooc2-ans/visit/courselistdata` → continue（只读课程列表接口）；
- 其余 POST/PUT/DELETE → abort。

即：**放行只读列表 POST，继续拦截所有写操作。**

### 10.2 discover_courses BFS

重写 `ReadOnlyExtractor.discover_courses()`：

1. goto 互动页，等待页面壳；
2. 读取隐藏字段：
   `courseType / superstarClass / single / filterFid / from / tchPageHeader / stuPageHeader / isFirefly`；
3. 对 `courseType=0/1`：
   - 从 `courseFolderId=0` 开始 BFS；
   - 通过 `ctx.request.post` 调 `/visit/courselistdata`；
   - 解析响应 HTML：
     - `.course` 容器 / `input.courseId` / `.course-name` → 课程；
     - `a[href*="courseId="]` 兜底；
     - `li[fileid]` / `intoFolder` → 文件夹；
   - 文件夹递归；
4. 课程按 `courseId` 去重；
5. 每个响应保存到：
   `pages/discover-courselist-<courseType>-<folderId>.html`；
6. 每个 folder 写一条 `steps[]`。

### 10.3 实测验证（保留会话，只读）

根目录/文件夹实测：

| courseType | folder | 唯一课程 |
|---|---:|---:|
| 0 | 0（根目录） | 6 |
| 0 | 5210383 在教 | 2 |
| 0 | 3038132 实验 | 8 |
| 0 | 2344825 其他 | 13 |
| 1 | 0（我学的课） | 23 |

合计发现 **52 门唯一课程**。  
说明“根目录课程 + 文件夹课程”都能被发现；后续可通过 targets 勾选只提取子集。

### 10.4 验证

- `pytest engine/tests -q` → **85 passed**；
- 新增 `readonly_route_decision` 回归：只放行 GET/HEAD/OPTIONS + 指定只读 POST；
- 解析器修复：兼容新版 `.course` 卡片结构（封面 `<a>` 无课程名、名称在 `.course-name`）。

### 10.5 边界

- `/visit/courselistdata` 只用于读取列表；
- 不调用任何发布/删除/上传/评分/公告接口；
- 学习通侧写操作继续 abort；
- 后续 D72/D73 全部完成前，不在真实课程上做任何写测试。

---

## 11. 二次交接总结（2026-10-10 晚）

> 本节在压缩会话交接后复核对齐生成。§9 的收尾清单仍然有效，但**执行顺序与范围口径以本节为准**。

### 11.1 本轮新增结论

1. **引擎更新已可正常使用（D73-7 降级）**
   - 用户真机反馈：更新到 `6e2df05` 后未再出现“引擎在时限内未重回在线”，terminal 也不再停在“按任意键继续”。
   - 处置：D73-7 从“必修阻塞”降级为“健壮性增强/待观察”；`update.status.json` 阶段回执仍建议做，用于区分“安装中 / 启动失败 / 已成功”，但不再阻塞主线。
2. **提取范围收敛：仅“我教的课”（D73-10，已实施）**
   - 决策：项目定位教师端（作业纸设计 + 批阅），`xxt extract --all` **默认只扫描 `courseType=0`（我教的课）**，不再默认扫描 `courseType=1`（我学的课）。
   - 实现：`engine/src/assist/xxt/extractor.py` 新增 `DEFAULT_DISCOVER_COURSE_TYPES = ("0",)`；`discover_courses(course_types=None)` 默认只用该常量；需要学生视角时可显式传 `("0", "1")`。
   - 回归：`engine/tests/test_xxt_extract_pure.py::test_discover_defaults_to_teacher_courses_only`。
   - 影响：此前 §10.3 实测的 52 门唯一课程含“我学的课”23 门；收敛后数量应明显下降，属预期行为。
3. **运行时已产出较多课程/页面存档**
   - 用户观察到 `workspace/.runtime/xxt/pages`（对应 `xxt_home()/pages`）下缩略图很多，说明发现阶段确实在产出多课程数据；
   - PWA 是否已完整展示全部班级仍待上线后真机复核（用户当时不在电脑前）。
   - 复核项：课程数 / 班级数 / run JSON 与 `pages/shots` 是否一致；确认“仅我教的课”范围生效。

### 11.2 已完成里程碑（D66 → D73-8）

| 编号 | 内容 | 提交 |
|---|---|---|
| D66 | 二维码不显示修复：统一 QR 路径、no-store、预加载重试 | `f5e3409` |
| D67 | Windows start.bat 托管式重启：退出码 75、`:ENGINE_LOOP`、`instance_id` 校验 | `e13d56d` |
| D68 | 扫码后无反应：登录走 CLI、教学域登录态、status 缓存按 mtime 失效 | `7b5d07f` |
| D69 | 依赖安装 uv→venv pip 回退（后被 D71 取代，仅留 `/install/deps`） | `a4fbce9` |
| D70 | 浏览器存活检查 / cookie 诊断 / CLI 输出实时转发 | `1562d57` |
| D71 | 两阶段自更新 + launcher/engine 解耦 + 导航竞态修复 | `c10beae`、`12f9481` |
| D72 | PWA 一键提取第一阶段：路径契约、extract job、过程预览 | `66a6504` |
| D73-1~4 | 提取 job 跨 tab 恢复、解释器修复、Playwright 历史、删除 run | `be5efb7` |
| D73-8 | 发现 0 课程修复：只读 POST 白名单 + `courseFolderId` BFS | `6e2df05` |
| D73-10 | 提取范围收敛为“我教的课” | 本节随附 |

### 11.3 不变口径

- **只读边界**：仅放行 GET/HEAD/OPTIONS + 白名单只读 POST `/mooc2-ans/visit/courselistdata`；其余 POST/PUT/DELETE 一律 abort；发布公告/删除/上传/评分回写等写操作继续冻结。
- **架构**：Python-first；系统 Python 优先 → Miniconda fallback → venv+pip 保底；uv 仅可选加速，不作运行前置。
- **更新模型**：PWA 只下载解压到 `_engine/staging` 并写 `update.pending`；旧 engine 停止后由 launcher 安装、失败回滚。
- **artifact 路径**：run JSON → `xxt_home()/runs/xxt-*.json`；截图 → `xxt_home()/pages/shots/`；兼容旧根目录与 `xxt-pages/shots`。
- **隐私红线**：真实学生数据、QR、storage JSON、教师工作区数据一律不入库。

### 11.4 规划（建议顺序）

0. **真机验证（前置）**：更新 engine 到最新 → PWA 强刷 → 扫码登录 → 提取；
   - 确认根目录 + 文件夹课程都能进列表（新版 `.course` / `.course-name` 解析）；
   - 确认“我教的课”范围生效；
   - 验证跨 tab job 恢复、Playwright 历史卡、删除 run。
1. **D73-10 生效复核**：确认提取课程/班级列表不再包含“我学的课”。（D73-9 与 D72 targets 已实施，见 §12）
2. **D73-9 旧数据兼容/导入**：legacy run 扫描 + `assist xxt run import <json>`（或 PWA 导入入口），让旧 run JSON 可见。
3. **D72-5 真实数据预览**：作业纸预览接已批阅样例；批阅报告按 D64-N4 接 submission/图片/转录/评阅（样例需去敏后入库）。
4. **D72 targets 模式**：先发现课程/班级（默认“我教的课”）→ 勾选 → 提取；保留 `--all` 为快捷方式。
5. **历史管理增强**：列表显示时间/班级/作业/失败数；清空全部；HTML 存档按 run_id 归档并纳入删除。（D73-11 已实施，见 §13）
6. **D73-7 状态回执（增强，可穿插）**：`_engine/update.status.json` + PWA 阶段驱动轮询。
7. **写操作解冻（最后）**：上述全部完成后，先在特殊课程测试，再扩到其他课程，最后上线。

### 11.5 脱敏与推送纪律

- `.gitignore` 已新增忽略 `.feishu4dsh/`：此前 `git status` 会直接列出 `.feishu4dsh/inbox/*/discover-courses.html`（含真实课程页），存在误提交风险。
- 推送前必须执行 `bash tools/check-secrets.sh`；该脚本默认只检查**已暂存文件**，因此流程应为 `git add` 指定文件 → 检查 → 再 commit。
- 禁止 `git add -f` 绕过忽略规则；`.scratch/`、`workspace/.runtime/`、`xxt_home()` 下的 `runs/`、`pages/`、QR、storage JSON、run JSON、HTML 存档、截图一律视为潜在真实数据，不入库。
- 推送网络不稳时使用：`git -c http.version=HTTP/1.1 push origin main`，失败后 sleep 重试。

### 11.6 验证命令

```bash
pytest engine/tests -q          # 应 86 passed（D73-10 新增 1 条）
python tools/lint_bat.py
bash -n tools/start.sh
cd app && npm run build
bash tools/check-secrets.sh
```

### 11.7 隐私事件记录：飞书收件箱照片误入库，已从历史移除

- **事件（2026-09-23）**：旧提交 `43446dc`（start.bat v9 final）把
  `.feishu4dsh/inbox/1790144067019-ccc144/image-919e05` 纳入版本控制。该文件为手机拍摄照片
  （EXIF 含 GPS 定位信息），仓库为公开仓库。
- **发现（2026-10-10）**：二次交接核对时 `git ls-files` 发现该文件仍在跟踪列表；
  `.feishu4dsh/` 当时未被 `.gitignore` 覆盖。
- **处置一（非破坏性）**：`git rm --cached` 从当时 HEAD 移除（本地原文件保留），
  `.gitignore` 已覆盖 `.feishu4dsh/`，main 该路径 raw URL 失效。
- **处置二（历史重写，2026-10-10 已执行）**：经确认后执行 `git filter-branch` 从全部历史移除该路径：
  - 217 个提交中，自 `43446dc`（含）起共 **136 个提交 SHA 变化**；重写后 tip 为 `80259a6`，
    随后补文档提交为 `b073799`，并已 force-push 同步远端 `refs/heads/main`；
  - 已删除 `refs/original`、过期 reflog 并 `git gc --prune=now`，该照片 blob 在本地对象库已不可达；
  - 旧历史完整备份为 gitignored 的 `.scratch/pii-rewrite-backup/pre-rewrite.bundle`（不入库），
    照片本体另存本地；
  - 文档中受影响的提交短哈希已按 old→new 映射批量更新；本节刻意保留旧哈希 `43446dc` 仅作历史指代。
- **仍未解决（GitHub 侧，2026-10-10 实测）**：
  - `main` 分支该路径已 404；但旧 `blob/43446dc/...image-919e05` 页面仍返回 **HTTP 200**，
    说明 GitHub 尚未 GC 不可达对象，知道旧 SHA 的人仍可访问到该照片；
  - 补救路径（按优先级）：
    1. 向 GitHub Support 提交 **Private information removal** 请求，附仓库、旧 commit SHA 与文件路径，
       请其清除缓存视图与不可达对象（推荐，需登录账号操作）；
    2. 若接受代价，可**删除并重建仓库**（当前仓库公开、0 star / 0 fork / 0 issue，迁移成本低），
       删除后旧 URL 立即失效，但 GitHub 对删除仓库保留约 90 天恢复窗口；
    3. 仅等待 GitHub 自动 GC 时间不可控，不建议作为唯一手段。
  - 已被克隆 / fork / 第三方归档（GH Archive 等）的副本无法回收；
  - 结论：**force-push 只保证“main 及此后提交不再包含”，旧 SHA 的完全回收需上述支持请求或重建。**
- **其余大体积入库图片**：`pwa-*.png`、`local-designer*.png` 经 OCR 抽查仅含界面/帮助文案，
  未发现真实名单；但同样属于“人工确认后才可入库”的范畴。
- **纪律强化**：
  1. 任何 `Bin` 变更与新增 `.png/.jpg/.zip/.tar.gz` 必须逐个人工确认来源与内容后才能 `git add`；
  2. `git status --short` 出现 `.feishu4dsh/`、`.scratch/`、`workspace/` 相关内容一律先移除；
  3. `check-secrets.sh` 只能拦截已知文本模式，不能替代二进制文件的人工审计。

---

## 12. D73-9 旧数据导入 + D72 targets 勾选提取（实施记录，2026-10-10）

### 12.1 D73-9：旧 run / targets JSON 导入（已实施）

**问题**：D63/D72 早期提取产物落在 `.scratch/` 或仓库根目录，不在 `xxt_home()/runs/`，
PWA 的 `/xxt/runs` 看不到。

**实现**：

- 新增 `engine/src/assist/xxt/legacy.py`（纯函数、不触网）：
  - `normalize_run_id`：保留合法 `run_id`；否则用文件名前缀；最后生成 `xxt-<ts>-import-<hex>`；
  - `normalize_legacy_run`：把旧 run / targets 规整为当前 schema（保留 course/class/work 已知字段，
    补 `imported`/`imported_at`，丢弃未知噪声；空 courses 拒绝）；
  - `import_run_data` / `import_run_file`：写入 `runs/<run_id>.json`，重名自动 `-2`/`-3`；
  - `scan_legacy_run_files`：目录扫描，排除 `xxt-storage.json` / `xxt-login-state.json` 等会话文件。
- CLI：`assist xxt run import <files…>`（或 `--scan <dir>` 批量）；`assist xxt run list` 查看结果。
- serve：`POST /xxt/run/import`，接受 `{data: <run JSON>}`（PWA 上传）或 `{path: "..."}`（本机路径），
  20MB 上限。
- PWA：新增卡「选择课程/班级提取」内含「📂 导入旧 run JSON」文件选择，导入后自动刷新列表。

**本机已有可导入数据**（`.scratch/`，gitignored；含真实姓名，仅本地使用）：

| 文件 | 内容 |
|---|---|
| `xxt-20261008-122317-full.json` | 5 课 / 多班（D63 全量提取） |
| `xxt-20261008-184915.json` | 1 课 1 班 9 作业（含 submitted_names/anchor） |

导入示例：

```bash
assist xxt run import --scan .scratch
assist xxt run list
# 或 PWA：学习通 → 选择课程/班级提取 → 📂 导入旧 run JSON（选文件即可）
```

### 12.2 D72 targets：发现 → 勾选 → 提取（已实施）

- 引擎 `extract_run.discover_targets(storage, archive_dir)`：会话体检 → 只读发现「我教的课」
  （`discover_courses` 默认 courseType=0）→ 逐课 `discover_classes`；返回
  `{ok, discovered_at, courses:[{name,courseId,classes:[{name,classId}]}], steps}`，不写 run。
- 路径契约：`layout.targets_json(home)` = `xxt_home()/targets.json`。
- CLI：`assist xxt discover [--out FILE]`（默认写 `xxt_home()/targets.json`）。
- serve：
  - `POST /xxt/discover` → CLI stream job；
  - `GET /xxt/targets` → 最近一次发现结果（无结果 404 + hint）；
  - `POST /xxt/extract`：`mode=all`（原有）或 `mode=targets`；
    targets 先经 `xxt.targets.sanitize_targets` 白名单校验（只允许 courseId/classId/name，
    非法 id 整体拒绝），再写入 `xxt_home()/xxt-extract-targets.json` 并调用
    `assist xxt extract --targets`。
- PWA：新增卡「选择课程/班级提取」——「🔍 发现课程/班级（只读）」→ 课程/班级 checkbox
  （默认全选）→「📥 提取所选（N 个班）」；提取 job 复用 `xxtJobs` store，跨 tab 恢复。

### 12.3 验证

- 新增测试：`engine/tests/test_xxt_legacy.py`（8）、`engine/tests/test_xxt_targets.py`（5）、
  `test_xxt_layout.py` +1（targets 路径）；
- 本沙箱无 pytest，用等价 harness 手跑 24 项纯函数测试全绿；全量 `py_compile` 全绿；
- `npx vue-tsc --noEmit` 0 err；`cd app && npm run build` 成功；
- 预期完整 `pytest engine/tests -q` = **99 passed**（原 85 + 新增 14）。

### 12.4 安全边界

- 导入的 run 含真实姓名 / 未交名单，只写本机 `xxt_home()/runs/`，不得入库
  （`.scratch/`、`runs/` 均已 gitignore）；
- `discover` 全程只读（GET/HEAD/OPTIONS + 白名单只读 POST `/visit/courselistdata`），
  不触发任何写操作；
- `mode=targets` 只改变提取范围，仍走同一套 `ReadOnlyExtractor` route 拦截。

### 12.5 下一步

1. 真机验收：更新引擎 → 扫码 → 「发现课程/班级」→ 勾选 → 「提取所选」；
   确认清单只含「我教的课」、勾选班正确、跨 tab job 可恢复。
2. D72-5 真实数据预览（作业纸 → 批阅报告）。
3. 历史管理增强（时间/班级/作业/失败数、清空全部）——D73-11 已实施，见 §13。

---

## 13. D73-11 历史管理增强（实施记录，2026-10-10）

### 13.1 HTML 存档按 run 归档

- `ReadOnlyExtractor` 新增可选 `html_dir`：HTML 存档写 `html_dir`，截图仍写 `archive_dir/shots/`
  （`shot` 字段与 `/xxt/shot/<run>/<file>` 契约不变，ProcessStreamView 不受影响）。
- `run_extract` 传入 `html_dir = <archive_dir>/runs/<run_id>`，即 `xxt_home()/pages/runs/<run_id>/`；
  每个 run 的 `v2-list-* / v2-review-* / v2-notice-*` 等 HTML 独立归档，可随 run 删除。
- `discover_targets` 不传 `html_dir`，发现诊断 HTML 仍平铺在 `pages/` 根目录（跨 run 共享，不随单 run 删除）。
- 旧版平铺 HTML 兼容读取，但**不纳入单 run 删除**（避免误删其他 run 共用文件）——文档明确此边界。

### 13.2 删除与清空

- `layout.run_pages_dir(run_id, home)` = `pages/runs/<run_id>`；
- `delete_run_artifacts` 现在删除：run JSON（runs/ 与 home 根目录）+ `shots/<run_id>-*.png`
  + `pages/runs/<run_id>/` 整目录；
- 新增 `layout.clear_runs(home)`：对 `run_json_files()` 识别出的全部 run 逐个删除，
  返回 `{runs, removed}`；**永不触碰** `xxt-storage.json` / `xxt-login-state.json` 等会话文件；
- serve 新增 `POST /xxt/runs/clear`。

### 13.3 PWA 历史管理卡

- 新增「历史 run 管理」卡：
  - 列：run_id / 结束时间（缺省用开始时间）/ 班级数 / 作业数 / 失败数；
  - 操作：载入该 run、🗑 单条删除（JSON + 截图 + run 级 HTML 存档）；
  - 卡头「🗑 清空全部历史（N）」：二次确认后调用 `/xxt/runs/clear`，清空并刷新；
- 原有下拉选择器与「删除本 run / 重载本 run」保留，作为快捷入口。

### 13.4 验证

- `engine/tests/test_xxt_layout.py` 新增 2 条：`run_pages_dir` + `delete_run_artifacts` 删除 run 级 HTML、
  `clear_runs` 保留会话文件；
- 沙箱等价 harness：4 个 xxt 测试模块共 **26 项全绿**（legacy 8 / targets 5 / layout 7 / extract_pure 6）；
- `py_compile` 全绿；`vue-tsc --noEmit` 0 err；`npm run build` 成功；
- 预期完整 `pytest engine/tests -q` = **101 passed**（原 85 + D73-9/D72 的 14 + 本节 2）。

### 13.5 安全边界

- 删除/清空只作用于本机 `xxt_home()` 工件，不触网、不涉及学习通写操作；
- run JSON / HTML 存档含真实姓名，删除即本地删除；备份请自行在删除前拷贝。

### 13.6 下一步

- D72-5 真实数据预览（作业纸 → 批阅报告）；
- 真机验收 D72 targets 与历史管理。

---

## 14. D73-12 引擎更新后 xxt 模块缺失事件（2026-10-10 现场 start.log）

### 14.1 现象

老师 Windows 机器（`D:\BaiduSyncdisk\toolsPy\2609assignment`）在 **17:24 更新引擎后**，
学习通页所有请求 500，日志反复出现：

```
serve.py, in _xxt_home / _xxt_session_check_cached
ModuleNotFoundError: No module named 'assist.xxt.session'
```

时间线（start.log）：`10:38` 启动正常；`13:52` 重启后扫码登录正常（msedge + QR）；
`17:24` 更新后新 serve 进程立即失败；`13:53`–`17:24` 之间 xxt 一直可用。

### 14.2 根因判断

- **不是发布产物问题**：线上 `engine-main.zip`（Pages `dl/`，commit edbfdb7）完整包含
  `engine/src/assist/xxt/session.py`（已下载核对）。
- **是老师本机 `_engine\engine` 安装树不完整**：serve 能启动说明 `assist/serve.py`、
  `assist/xxt/__init__.py`、`assist/xxt/layout.py` 都在；但 `_xxt_home()` 的**懒加载**
  `from .xxt.session import xxt_home` 找不到 `session.py`。
- 触发链：`start.bat :APPLY_UPDATE` 把旧 `_engine\engine` 移到 `.bak` 后，
  `xcopy /E /I /Y` 复制 staging；xcopy 只校验了 `pyproject.toml`，
  **丢失/漏拷部分文件（含 `xxt/session.py`）时仍判定成功** → pip editable 安装成功 →
  serve 启动 → 首次访问 `/xxt/*` 才暴露。
- 老师引擎 traceback 行号与本仓库任何提交都不一致，进一步说明其安装树是
  “新旧文件混合/非完整快照”，而非单一干净版本。

### 14.3 立即修复（老师本机操作，一次性）

```bat
REM 1) 先关闭引擎 cmd 窗口（停止进程，避免文件占用）
REM 2) 删除不完整的引擎安装与 staging（会重新下载）
rmdir /S /Q D:\BaiduSyncdisk\toolsPy\2609assignment\_engine\engine
rmdir /S /Q D:\BaiduSyncdisk\toolsPy\2609assignment\_engine\staging
if exist D:\BaiduSyncdisk\toolsPy\2609assignment\_engine\engine.bak rmdir /S /Q D:\BaiduSyncdisk\toolsPy\2609assignment\_engine\engine.bak
del /Q D:\BaiduSyncdisk\toolsPy\2609assignment\_engine\engine-version.json
REM 3) 可选：清理 pip 残留的无效分布
del /Q /S D:\BaiduSyncdisk\toolsPy\2609assignment\.runtime\venv\Lib\site-packages\~ssist-engine*
REM 4) 重新双击 start.bat（重新下载 engine-main.zip 并安装）
```

### 14.4 防复发加固（已实施）

- `start.bat`：
  - `:ENGINE_CHECK` 检查 `src\assist\xxt\session.py`；缺失则强制重下一次（`REDOWNLOADED`），
    仍缺失则明确报错并指向 `_engine` 删除；
  - `:EXTRACT_ENGINE` 解压后清理 `src\**\__pycache__`，避免陈旧 pyc；
  - `:APPLY_UPDATE` 改用 `robocopy /MIR`（失败再回退 `xcopy`），并在复制后**校验**
    `src\assist\xxt\session.py` 与 `src\assist\serve.py`，缺失即回滚；
  - 下载前清理旧的 `engine-main.zip` / `full-repo.zip`，避免复用上一次失败下载的残缺包；
  - 本地版本“已是最新/版本检查离线”时也先走 `:ENGINE_CHECK` 完整性检查。
- `engine/run_engine.bat`：启动 serve 前执行 `python -c "import assist.xxt.session"` 自检，
  失败时打印中文修复指引并 `pause`，不再让 serve 起来刷 traceback。
- `engine_update.py`：新增 `REQUIRED_STAGE_FILES`；下载的 zip **解压前**校验 zip 名单、
  **解压后**校验磁盘文件，缺任一关键文件则不写 `update.pending`。
- `serve.py`：新增 `_xxt_import_error()`；所有 `/xxt/*` 请求先探测，
  失败时返回可读提示（`/xxt/status` 降级为 200 + hints，其余 503），
  PWA 会显示“学习通模块不可用（引擎安装不完整）+ 修复步骤”。
- `tools/start.bat` 与 `app/public/start.bat` 已同步（lint_bat 通过）。

### 14.5 验证

- `tools/lint_bat.py`：3 个启动脚本通过；
- 新增纯函数测试：`missing_required_files`（空目录全缺 / 补齐后为空）、
  `test_start_bat_d73_12_integrity_contract`（robocopy + REDOWNLOADED + run_engine 自检）；
- 预期完整 `pytest engine/tests -q` = **103 passed**（原 101 + 本节 2）。

### 14.6 遗留

- `start.bat` 的 release 备用源（`releases/download/dl/engine-main.zip`）实测 404，
  仅剩 Pages 主源 + ghfast/全仓兜底；后续可移除死源或补一个真实备用包。
- 若再次出现“安装树混杂”，优先怀疑 BaiduSync 同步/文件占用导致复制不完整；
  可考虑把 `_engine` 放到非同步目录（该项需教师拍板）。

---

## 15. D74 实施记录：发现缓存/差异 + 操作记录 + 网盘检测 + 作业级展开（2026-10-10）

> 需求单：`docs/25-D74-xxt-discover-cache-and-ui.md`；本节为实现记录。

### 15.1 D74-6 白屏修复（最高优先级）

- 提取勾选清单改写到 `xxt_home()/targets/extract-spec.json`（非 run 扫描目录），
  serve 同时清理旧 `xxt-extract-targets.json`；
- `layout.is_run_shape()` + `run_json_files`/`find_run_json` 内容白名单：
  顶层必须有 `courses` list 且 `run_id` 以 `xxt-` 开头，targets spec / 坏 JSON 不再入列；
- PWA `loadRun` 防御性归一（`courses/classes/works` 缺省），坏数据只提示不白屏。

### 15.2 D74-1/2/2b/11 文案与布局

- 卡名「选择课程/班级提取」→「发现课程/班级」；
- 页面底部顺序：发现课程/班级 → 发现作业 → 历史 run 管理 → Playwright 操作历史；
- 去掉每课 420px 内滚动与 `<tr>` sticky，改为整页滚动（修 Edge 无滚动条）。

### 15.3 D74-3 发现快照缓存/diff

- `targets-history/` 归档当前快照，保留最近 5 份；`prune_history` 滚动删除；
- `GET /xxt/targets` 返回 `diff`（新增/移除/改名）、`age_seconds`、`history_count`；
- PWA：年龄配色（<24h 绿 / 1–7 天黄 / >7 天红）、陈旧提示、刷新按钮、
  diff 摘要（一次性「知道了」）、新增/改名 badge、`POST /xxt/targets/history/clear` +
  「🧹 清理发现快照」。

### 15.4 D74-4 作业级惰性展开

- `ReadOnlyExtractor.list_works()` 只读 `work/list`（不进 mark、不抓名单）；
- `extract_class(work_ids=...)` 支持只提取选中 workId（选中清单已失效 → not_extracted + 提示）；
- `discover_works()` + CLI `assist xxt discover-works` + `POST/GET /xxt/works`；
- `sanitize_targets` 支持 `classes[].works[]`（缺省=全部作业）；
- PWA「📚 发现所选班级的作业（只读）」→ 作业级勾选 → 提取只带选中 workId；
  结果卡「读提取结果」改名「发现作业」。

### 15.5 D74-7 云同步/网盘占用检测

- 新增 `xxt/sync.py`：路径关键字（BaiduSyncdisk/OneDrive/Dropbox/坚果云/微云…）、
  同步进程、`*.baiduyun.p.downloading` 残留三层检测；
- `/doctor` 新增 `sync_root` 检查项（黄条 + 修复指引）；
- `start.bat` 更新前 warn；完整性失败/自检失败提示「暂停同步 + 退出客户端 + 删除 _engine 重试」。

### 15.6 D74-8 操作前置新鲜度预判

- `xxt/targets.freshness()`：ok/warn/danger/unknown（24h/7 天阈值）；
- `GET /xxt/freshness`；
- PWA 提取前预判：danger 时二次确认（可继续，不强制刷新），warn 提示。

### 15.7 D74-9 全局操作记录

- 新增 `xxt/journal.py`：JSONL 按月分片、保留 6 个月滚动、失败也记、名单类参数只记数量；
- serve：CLI job/install/import/delete/clear/prune/restart 全部落日志；
  `GET /journal`（时间范围/类型/limit）+ `POST /journal/clear`；
- PWA 新增顶层「操作记录」选项卡：时间范围 + 类型过滤、导出 JSON、清空。

### 15.8 容量控制

- `layout.run_artifacts_stats()` / `prune_runs()`：总数 ≤ 1000 且总大小 ≤ 50MB（先到先删最旧）；
- 每次提取结束自动清理；`GET /xxt/storage` + `POST /xxt/runs/prune`；
- PWA 历史卡显示「条数/上限 · 大小/上限」+「🧹 按容量清理」。

### 15.9 验证与边界

- 新增/更新纯函数测试：layout（12）、targets（12）、legacy（8）、extract_pure（6）、
  journal（5）、sync（2），沙箱 harness 共 **45 项全绿**；
- `lint_bat` 3 脚本通过；`vue-tsc` 0 err；`npm run build` 成功；
- 预期完整 `pytest engine/tests -q` = **123 passed**（`grep "def test_"` 实测计数）；
- 边界不变：只读；写操作仍冻结；journal/快照/runs 全部本机、不入库。

---

## 16. D75 第一批实施记录：发现作业 UI + 真实批阅列表预览（2026-10-10）

### 16.1 D75-2 发现作业 UI

- **数字含义**：列表显示的 `待批/已交/未交` 现在带中文标签，不再是无说明的 `21/21/3`；
- **跨课程对齐**：结果卡从「每课程一张独立表」改为**单张表 + 课程分组行**，
  `table-layout: fixed` + `<colgroup>` 固定列宽（22%/44%/12%/22%），跨课程严格对齐；
- **多行显示**：班级/作业单元格 `white-space: normal; word-break: break-word`，
  长作业名自动换行；操作按钮允许换行；
- 每个作业行新增 **「👁 预览」** 按钮。

### 16.2 D75-1a 真实批阅列表预览（已实施）

- 新增 `engine/src/assist/xxt/preview.py`（纯函数，不触网）：
  - `list_review_archives(home)`：扫描 `pages/` 与旧 `xxt-pages/` 下的 `v2-review-<classId>-<workId>.html`；
  - `parse_review_list(html)`：解析 `dataBody_td` 学生行（姓名、分数、评阅链接；无分数时推断「待批阅」）；
  - `preview_students(home, classId, workId)`：返回学生列表/已评分人数。
- serve 新增 `GET /xxt/preview/archives`、`GET /xxt/preview/students/<classId>/<workId>`；
- PWA：结果卡每个作业「👁 预览」→ 模态展示真实学生列表（姓名/分数/已批阅状态）；
- 本机真实存档验证：`.scratch/xxt-pages/v2-review-*` 共 106 份；样例班 39 人、39 人有分、评阅链接完整。
- 单测：`engine/tests/test_xxt_preview.py`（合成 fixture 2 条）。

### 16.3 D75-1b 下一步：单生照片/评语预览

- 现状：review **列表页**只有姓名/分数/评阅链接；学生上传照片与评语在**单生 review-work 详情页**，
  需带会话逐生打开下载（只读）。
- 计划：
  1. 先抓一份单生 `review-work` 页面样本（新增一个只读 CLI 或由教师浏览器另存 HTML）；
  2. 按样本实现 `assist xxt review-download --work <id>`：逐生打开详情页 → 保存图片/评语/评分到
     `pages/review/<classId>/<workId>/`；
  3. PWA 预览模态接入图片缩略图与评语，并作为 D75-3 AI 评阅的输入。
- 在详情页样本到手前不盲写解析器。

### 16.4 验证

- 沙箱 harness：上述纯函数测试 + 既有 xxt 模块共 **49 项全绿**；
- `py_compile` / `lint_bat` / `check-secrets` 通过；`vue-tsc` 0 err；`npm run build` 成功；
- 全库 `def test_` 计数 **127**，预期 `pytest engine/tests -q` = 127 passed。
