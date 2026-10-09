# D67 任务需求单：Windows 下 PWA「重启引擎」不能自动重启/终端不退出

> 状态：**已实施（2026-10-09），待 Windows 真机验收**。
> 说明：本文件最初用于登记原因与需求，现保留为 D67 修复实施与验收入口。
> 日期：2026-10-09
> 关联：
> - `docs/16-xuexitong-integration.md` §26 引擎运维三角、§27.10 D65-P4 在线更新与重启
> - `docs/17-D66-xxt-qr-image-task.md` 同期改造，勿与本单重启协议混淆
> - 当前远端：`a3d6f73`（D66 已推送）
> 影响等级：**P0 运维**。教师机 Windows + `start.bat` 是主使用路径；重启失效会让 PWA 更新、配置变更、代码生效全部异常。

---

## 1. 现象

在 Windows 教师机上：

1. 双击 `start.bat` 启动引擎，PWA 可正常连接；
2. 在 PWA 设置中心点「🔄 重启引擎」；
3. 预期：引擎自动退出并重新启动，PWA 轮询回在线，同一端口继续服务；
4. 实际：**终端里的 engine 没有按预期自动关闭/重启**，终端窗口也不能自动收尾；
   必须手动关闭 terminal（相当于杀掉进程）后，再双击 `start.bat` 才能重新启动引擎。

结果就是 PWA 重启按钮对 `start.bat` 启动的 Windows 引擎基本不可用。

---

## 2. 当前代码链路

### 2.1 Windows 启动：`start.bat`

```bat
REM tools/start.bat:129-146
:AFTER_DEPS
...
echo engine http://127.0.0.1:%PORT%/ (log: %LOG%)
start "" http://127.0.0.1:%PORT%/

"%WORKSPACE%\.runtime\venv\Scripts\assist.exe" serve --port %PORT% >> "%LOG%" 2>&1

echo engine exited. see %LOG%
pause
endlocal
```

关键点：

- `assist serve` 是**前台子进程**，`cmd.exe` 会一直等待它结束；
- 引擎一旦退出，`start.bat` 必然执行到 `echo engine exited` + `pause`；
- `start.bat` 目前**无法区分**“崩溃退出”“用户 Ctrl+C”“PWA 主动请求重启”三种情况。

### 2.2 Engine 重启：`POST /restart`

```python
# engine/src/assist/serve.py:459-476
if u.path == "/restart":
    ...
    self._json({"ok": True, "restarting": True})
    import time as _t2, threading as _th
    def _reborn():
        _t2.sleep(0.5)  # 让响应字节先落到 socket
        os.execv(sys.executable,
                 [sys.executable, "-c",
                  "from assist.cli import main; main()", *_RESTART_ARGS])
    _th.Thread(target=_reborn, daemon=True).start()
    return
```

```python
# engine/src/assist/serve.py:662-663
_RESTART_ARGS = ("serve", "--workspace", str(ws), "--port", str(port)) + (("--lan",) if lan else ())
```

当前实现把“重启”建立在 **POSIX `os.execv` 的“原地替换当前进程”语义**上。
`docs/16 §26.1` 记录过“8767/8601 两端口 execv 再生成功”，但该验证没有覆盖
Windows 的 `cmd.exe + start.bat + 前台子进程 + 控制台/重定向`模型。

### 2.3 PWA 重启判定

```ts
// app/src/views/SettingsView.vue:129-152
await restartEngine(settings.engineUrl, settings.engineToken)
// 轮询等回在线（最多 12s）
for (let i = 0; i < 24; i++) {
  await new Promise(r => setTimeout(r, 500))
  const online = await settings.pingEngine()
  if (online) { ... return }
}
```

PWA 的“重启成功”只检查 `/status` 是否在线：

- 如果旧引擎根本没退出，`/status` 立刻返回在线 → PWA **误判重启成功**；
- 如果旧引擎退出了、新引擎没起来，PWA 15s 后只给“手动重跑”提示；
- PWA 无法知道“现在在线的到底是不是新进程”。

### 2.4 `/status` 缺少实例身份

当前 `/status` 只返回 `name/version/workspace/ws`，没有：

- `pid`
- 每次启动生成的 `instance_id`
- `supervised`（是否由 start 脚本托管）
- `started_at`
- `port`

因此前端无法可靠判断重启是否真的发生。

---

## 3. 原因判断

> 下面把“已由代码确认”与“Windows 现场需再确认”分开写，避免把猜测当结论。

### 3.1 主因：重启协议只适配了 POSIX，不适配 Windows 的批处理托管模型（高置信）

- `os.execv` 在 POSIX 上是“当前进程映像被替换”，PID/终端/父进程关系保持；
- 在 Windows 上，Python 的 `os.exec*` 不能保证和 POSIX 完全等价；`cmd.exe` 等待的是
  `start.bat` 最初启动的那个前台子进程，控制台、重定向、进程组模型都不同；
- 无论 `os.execv` 在 Windows 上是“新进程+旧进程退出”还是“派生新进程后返回”，都可能出现：
  - 旧 `cmd.exe` 等到子进程结束 → 执行 `echo engine exited.` + `pause`；
  - 新 engine 已脱离/仍在同一 console，但没有被 start.bat 正确托管；
  - 或旧 engine 根本没有被终止，端口仍被占用，新进程绑定失败；
- 从用户侧看，就是“terminal 不能自动关闭 engine，必须手动关 terminal 再双击 start.bat”。

### 3.2 `start.bat` 没有重启监督循环（高置信）

`start.bat` 现在只有“启动 → 引擎退出 → pause”的单次流程：

- 没有重启退出码约定，例如 `ASSIST_EXIT_RESTART=75`；
- 没有 `:ENGINE_LOOP` 之类的 supervisor 循环；
- 没有“正在重启，请勿关闭窗口”的状态输出；
- 因此 `/restart` 无论以何种方式退出，`cmd.exe` 都只能走 `pause`。

### 3.3 PWA 重启成功判定过弱（高置信）

`pingEngine()` 只判断 `/status` 在线。旧进程如果未被替换，PWA 会报告“已重启”，
教师会以为按钮生效，但实际代码/配置未重新加载。这会掩盖 Windows 重启失败。

### 3.4 缺少实例身份导致无法验收（高置信）

没有 `instance_id` / `pid` / `started_at`，PWA 和教师都无法区分：

- “旧引擎仍在”；
- “新引擎已起来”；
- “换了一个端口的新引擎”。

### 3.5 需要 Windows 现场确认的项（中低置信）

下次在老师电脑上可顺手确认，用于决定修复细节：

1. 点重启后终端最后几行是什么：
   - 是否出现 `engine exited. see ...` / `Press any key to continue`；
   - 是否一直停在原日志没有新行。
2. `netstat -ano | findstr :8601` 在重启前后：
   - 旧 PID 是否消失；
   - 是否出现 8602..8649 的新监听端口。
3. `start.log` 尾部是否出现新引擎启动记录。
4. 点击重启后 PWA `/status` 是否曾短暂离线，还是一直在线。
5. 是否曾在 Windows 上手动从终端运行过 `assist serve`，而不是通过 `start.bat`。

---

## 4. 目标行为（建议定版）

Windows `start.bat` 启动的引擎，点 PWA「🔄 重启引擎」后：

1. 旧引擎在 1~2 秒内退出；
2. 新引擎自动在同一端口重新启动；
3. 终端窗口作为引擎控制台继续保留，或明确自动收尾；**不需要用户手动关闭 terminal，也不要求再次双击 start.bat**；
4. PWA 能验证 `instance_id` 确实变化，并在新引擎上线后重跑体检；
5. 若引擎不是由 `start.bat` 托管，或重启协议确实无法执行，PWA 必须明确报错，而不是误报成功；
6. 正常崩溃 / Ctrl+C 仍保留 `start.log` 和 `pause`，方便教师查看错误。

---

## 5. 修复需求

### R1 · Windows 托管式重启协议（必须）

建议采用“**start.bat supervisor loop + 专用重启退出码**”，不再依赖 Windows 上的 `os.execv`：

- `tools/start.bat` 与 `app/public/start.bat`（两份当前完全相同，必须同步）：
  - 启动引擎前设置 `ASSIST_SUPERVISED=1`；
  - 把 `[6/6]` 改成循环：

    ```bat
    :ENGINE_LOOP
    "%WORKSPACE%\.runtime\venv\Scripts\assist.exe" serve --port %PORT% >> "%LOG%" 2>&1
    set "RC=%ERRORLEVEL%"
    if "%RC%"=="75" (
      echo [restart] engine restart requested, restarting...
      timeout /t 1 /nobreak >nul
      goto ENGINE_LOOP
    )
    echo engine exited. see %LOG%
    pause
    ```

  - 退出码 `75` 只代表“PWA 主动请求重启”，不能与崩溃/用户退出混淆；
  - 重启循环复用同一个 `%PORT%`，禁止因为旧进程未退出而漂移到 8602；
  - 若检测到端口未释放，循环内应等待重试，而不是占用新端口。

- `engine/src/assist/serve.py` `/restart`：
  - 若 `os.name == "nt"` 且 `ASSIST_SUPERVISED=1`：
    - 先返回 `{ok:true, restarting:true, mode:"supervised-exit75"}`；
    - 延迟 0.5s 后直接 `os._exit(75)`，让 `start.bat` 的 `%ERRORLEVEL%` 接管重启；
    - **不要**再调用 `os.execv`。
  - 若 `os.name == "nt"` 但不是 supervisor 启动：
    - 返回 `409` 或明确 `ok:false`，提示“本引擎非 start.bat 托管，请关闭终端后双击 start.bat”，
      避免 PWA 误判成功；
    - 也可实现安全的 detached 启动方案，但必须保证旧终端可关闭且 PWA 可验证新实例。
  - 若 POSIX：可继续保留 `os.execv`，也可统一改成 supervisor loop；两者选一，但要有测试覆盖。

### R2 · 引擎实例身份（必须）

- `serve()` 启动时生成 `_INSTANCE_ID`（例如 `secrets.token_urlsafe(6)`）和 `_STARTED_AT`。
- `GET /status` 返回：

  ```json
  {
    "name": "assist-engine",
    "version": "0.1.0",
    "workspace": true,
    "pid": 12345,
    "instance_id": "AbCdEf12",
    "started_at": "2026-10-09 21:00:00",
    "supervised": true,
    "port": 8601
  }
  ```

- `engineClient.ts` 的 `EngineStatus` 增加这些字段；
- `settings.pingEngine()` 保存当前实例信息，供重启前后对比。

### R3 · PWA 重启验证（必须）

- `SettingsView.restartEngineNow()`：
  - 请求重启前先读取 `/status`，记录 `before.instance_id`；
  - 请求 `/restart`；
  - 轮询 `/status`，只有满足以下两个条件才算成功：
    1. `/status` 重新在线；
    2. `instance_id !== before.instance_id`；
  - 若 12s 内一直在线但 `instance_id` 不变：判定“旧引擎未退出”，提示
    “请关闭终端后双击 start.bat”；
  - 若从未回在线：提示“引擎未重启成功，查看 start.log 或双击 start.bat”；
  - 成功后重跑体检/版本检测。
- `settings.ts` 的 `updateEngine()` 自动重启流程复用同一套“实例切换验证”，
  不能只 ping 在线。

### R4 · 终端生命周期与日志（必须）

- Windows supervisor 模式下，点重启后终端必须：
  - 立即输出 `[restart] ...` 之类可读状态；
  - 自动进入下一轮 `assist serve`；
  - 不弹出新的 cmd 窗口（除非老师明确选择手动终端模式）；
  - 不要求老师按任意键或关闭窗口。
- 正常退出/错误退出仍保留 `pause` 和 `start.log`。

### R5 · 兼容性与回退（必须）

- 若 `/status` 返回 `supervised:false`，PWA 的重启按钮应：
  - 给出明确说明；
  - 或提供“手动重启”指引；
  - 不得静默误报成功。
- `start.sh` / macOS / Linux 行为不得回退；若统一 supervisor loop，需在 Linux 上补回归。
- 端口漂移策略保留：首次启动可 8601..8649；但**PWA 主动重启必须固定原端口**。

---

## 6. 验收标准

- [ ] Windows 教师机：双击 `start.bat` 启动，PWA「🔄 重启引擎」后 5 秒内重新在线，`instance_id` 变化；
- [ ] 重启过程中不需要关闭 terminal，不需要再次双击 `start.bat`；
- [ ] 重启后仍监听原端口，不出现 8602..8649 的新监听端口；
- [ ] `netstat` 显示同一时间只有一个该端口引擎进程；
- [ ] PWA 不再“旧引擎仍在线”时误报重启成功；
- [ ] 引擎更新（D65-P4）后点「更新引擎」→ 自动重启 → `/status` 的 commit / `instance_id` 均为新版；
- [ ] 非 `start.bat` 托管的 Windows 引擎，PWA 给出手动重启指引，而不是假成功；
- [ ] 正常关闭/崩溃引擎仍能看到 `start.log` 并保留 `pause`；
- [ ] POSIX 下 `assist serve` / `start.sh` 重启行为无回归；
- [ ] `pytest engine/tests -q`、`npm run build`、`python tools/lint_bat.py`、脱敏检查通过。

---

## 7. 测试矩阵

| 场景 | 预期 |
|---|---|
| Windows `start.bat` 启动 → PWA 重启 | 同一端口，`instance_id` 变化，终端不要求手关 |
| Windows 连续重启 3 次 | 每次都成功，无旧进程残留、无端口漂移 |
| Windows 引擎更新 → 自动重启 | 新 commit 生效，PWA 不再只 ping 在线 |
| Windows 手动 `assist serve` → PWA 重启 | 明确提示“非 start.bat 托管”，不误报 |
| Windows 重启时主动杀终端 | PWA 显示离线/失败，提示重新双击 start.bat |
| 正常错误退出（如缺依赖） | 终端 pause + start.log，不无限重启 |
| POSIX `start.sh` 重启 | 同一终端/端口，行为不回归 |
| 页面上多次点重启按钮 | 按钮禁用防重复，不产生多个引擎 |
| 重启过程中 PWA 体检 | 离线时显示“重启中”，回线后自动重跑 |

---

## 8. 实施文件预估

- Windows 托管：
  - `tools/start.bat`
  - `app/public/start.bat`（与 tools 同步）
  - 若做跨平台 loop：`tools/start.sh`、`app/public/start.sh`
- Engine：
  - `engine/src/assist/serve.py`（`/restart` 平台分支、`/status` 实例字段、supervisor env）
- PWA：
  - `app/src/lib/engineClient.ts`（状态字段、重启响应类型）
  - `app/src/stores/settings.ts`（`pingEngine` 实例信息、`updateEngine` 验证）
  - `app/src/views/SettingsView.vue`（`restartEngineNow` 实例对比与文案）
- 测试：
  - `engine/tests/test_restart_protocol.py`（纯函数：平台/supervised → execv / exit75 / 409）
  - `tools/lint_bat.py` 兼容性审核
  - PWA build + 手工 Windows 验收
- 文档：
  - 实施后同步 `docs/16` §26/§27、`docs/15` 重启 FAQ。

预计工作量：协议/后端 0.5 天 + start.bat 0.5 天 + PWA 0.5 天 + Windows 真机回归 0.5 天。

---

## 9. 不在本需求内

- 不改学习通扫码逻辑（D66 另行现场测试）；
- 不改 engine 下载/解压/依赖更新逻辑；
- 不引入自定义 `assist://` 协议或浏览器拉起进程方案（D64 已否决）；
- 不要求老师学习命令行；
- 不把 PWA 重启按钮改成“关闭页面再手动双击 start.bat”的伪方案。

---

## 10. 实施记录（2026-10-09）

已按 R1–R4 落地：

- **serve 重启协议（`engine/src/assist/serve.py`）**
  - 新增 `restart_plan(platform, supervised)` 纯函数：
    - POSIX → `execv`（保持 D64 行为）；
    - Windows + `ASSIST_SUPERVISED=1` → `exit75`，由 `start.bat` supervisor loop 接管；
    - Windows 非托管 → `manual`，`/restart` 返回 409，前端明确提示手动重启。
  - `/status` 新增 `pid` / `instance_id` / `started_at` / `supervised` / `port`；
  - `serve()` 每次启动生成新的 `instance_id`。
- **Windows 启动脚本（`tools/start.bat` + `app/public/start.bat` 同步）**
  - 设置 `ASSIST_SUPERVISED=1`；
  - `[6/6]` 改为 `:ENGINE_LOOP`：
    - engine 退出码为 `75` → `echo [restart] ...` → 等 1s → 同端口重启，不进入 `pause`；
    - 其他退出码仍输出 `engine exited` + `pause`，便于看错误。
- **PWA（`engineClient.ts` / `settings.ts` / `SettingsView.vue`）**
  - `EngineStatus` 透传 `instance_id` / `pid` / `supervised` / `port`；
  - 新增 `settings.restartEngineAndWait()`：重启后必须等 **`instance_id` 真正变化** 才判定成功；
  - 重启按钮和引擎更新后的自动重启统一走该验证，避免“旧进程仍在线”被误判为成功。
- **验证**
  - `pytest engine/tests -q` → `62 passed`（新增 `test_restart_protocol.py`）；
  - `python tools/lint_bat.py` → 通过；
  - `npm run build` → 通过；
  - `npm run selfcheck:roster-fig` → ALL PASS；
  - POSIX 集成实测：`/status` 初始 `instance_id=ffhwuwdR`，`POST /restart` 后变为 `G7oonmtm`，
    同 PID、同端口、2 秒内重新在线。

- **待 Windows 真机验收**：
  - 双击 start.bat → PWA 重启 → 不需要手动关 terminal；
  - `netstat` 确认重启前后同端口只有一个监听进程；
  - `instance_id` 变化并在 15s 内回在线。
