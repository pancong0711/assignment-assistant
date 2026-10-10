# D73 任务需求单：提取任务不中断 + Playwright 浏览器操作历史 + `assist.cli` 导入失败修复

> 状态：**需求定稿 / 待实施**。
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
