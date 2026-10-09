# D71 任务需求单（定稿 · 待实施）：扫码导航竞态 + 引擎两阶段自更新 + launcher/engine 边界

> 状态：**已实施（2026-10-09），待 Windows 真机复测**。
> 拍板：launcher/engine 采用**契约级一步解耦**——start.bat 作为稳定 launcher，
> engine 包内提供稳定适配层 `run_engine`；首轮不另拆独立 `_launcher` 产物。
> 关联：`docs/18-D67-engine-restart-terminal-task.md`、
> `docs/19-D68-xxt-scan-login-state.md`、`docs/20-D69-engine-update-dep-install.md`、
> `docs/21-D70-xxt-login-liveness-diagnostics.md`。
> 来源：2026-10-09 教师机扫码实测 + PWA「更新引擎」WinError 5 实测。

---

## 1. 事件一：扫码后 `stage=failed`，但其实是成功登录

### 1.1 现场状态

```json
{
 "stage": "failed",
 "browser": "msedge",
 "browser_connected": true,
 "page_closed": false,
 "url": "https://passport2.chaoxing.com/login?fid=&newversion=true&refer=https%3A%2F%2Fi.chaoxing.com",
 "cookies": [
  "DSSTASH_LOG", "JSESSIONID", "UID", "_d", "_uid",
  "cx_p_token", "p_auth_token", "roleEnc", "uf", "xxtenc"
 ],
 "error": "browser/page closed before scan: Page.evaluate: Execution context was destroyed, most likely because of a navigation"
}
```

### 1.2 结论：这不是扫码失败，是 D70 存活检查误杀

- `browser_connected=true`、`page_closed=false`：浏览器进程和页面都活着；
- cookies 已出现 `UID` / `_uid` / `p_auth_token`：学习通已完成登录；
- 真正错误是 `Page.evaluate: Execution context was destroyed`：
  - 扫码成功后页面发生跳转；
  - 旧 JS execution context 被销毁；
  - D70 新增的 `_page_alive()` 正好在这瞬间执行 `page.evaluate("() => 1")`；
  - 代码把“页面在导航”误判为“浏览器/page 已关闭”；
  - 于是写了 `stage=failed` 并提前结束。

### 1.3 前面的成功经验为什么没有这个问题

旧 `.scratch/xxt_login_capture.py` 的成功循环里：

- 只做 `urlparse(page.url)`；
- 只做 `page.context.cookies()`；
- **没有在等待循环里执行 `page.evaluate()`**。

旧成功日志也明确记录过：

```json
{"ts": "2026-10-07 20:32:05", "stage": "waiting_scan",
 "url": "https://i.chaoxing.com/base?t=...",
 "cookies": [..., "UID", "_uid", ...]}

{"ts": "2026-10-07 20:32:15", "stage": "logged_in",
 "url": "https://i.chaoxing.com/base?t=..."}
```

所以“扫码后页面肯定要跳转”这个事实，旧代码是通过 URL/cookie 轮询自然接住的；
**D70 引入的 evaluate 存活检查创造了新的竞态，不是旧经验失效。**

---

## 2. 事件二：PWA「更新引擎」WinError 5

### 2.1 现场

```text
Attempting uninstall: assist-engine
Found existing installation: assist-engine 0.1.0
Uninstalling assist-engine-0.1.0:
ERROR: Could not install packages due to an OSError:
[WinError 5] 拒绝访问。:
...\.runtime\venv\scripts\assist.exe
```

### 2.2 根因

- 当前 engine 进程由 `venv\Scripts\assist.exe serve` 启动；
- pip/uv 更新 `assist-engine` 时要替换 `Scripts\assist.exe`；
- Windows 不允许覆盖正在运行的 `.exe`；
- 于是 WinError 5。

这不是 PyPI 问题，也不是 uv 问题；uv 同样会撞锁。

---

## 3. 方案比较

### 方案 A：start.bat 改 `python -m assist.cli serve`

- 优点：运行进程变 `python.exe`，`assist.exe` 不再被锁。
- 缺点：start.bat 与 `assist.cli` 内部接口强耦合；engine CLI 一旦变化，
  外部 start.bat 可能直接失效；仍是在 engine 运行时做安装，存在半安装风险。
- 结论：短期 workaround，不是长期方案。

### 方案 B：start.bat supervisor 两阶段更新（推荐）

1. PWA 只下载并解压到 staging，不覆盖运行中的 `_engine`；
2. 写 `update.pending`；
3. PWA 调用 `/restart`；
4. 旧 engine 退出（退出码 75，沿用 D67 协议）；
5. start.bat supervisor 检测 pending；
6. 在 engine 已停止、`assist.exe` 已释放时执行 pip/uv 安装；
7. 安装成功后启动新 engine；
8. 失败则回滚旧版本并显示错误。

优点：

- 彻底避免 Windows exe 锁；
- 满足“依赖变化时先安装再启动”；
- 与 D67 supervisor loop 天然衔接。

### 方案 C：独立 detached updater

- PWA 启动一个独立 updater；它等待旧 engine 退出，再安装并启动。
- 优点：不依赖 start.bat 在运行；
- 缺点：Windows 进程/控制台/日志管理复杂，建议作为以后兜底，不作为首期。

---

## 4. launcher 与 engine 的边界（讨论重点）

用户的判断是正确的：这里应该拆成两个层。

### 4.1 engine

- 我们项目自身的 Python 包/CLI：`assist`、`assist serve`、业务代码；
- 更新频繁；
- 由 PWA 下载 `engine-main.zip` 更新；
- 不应该承担“更新自己”的职责。

### 4.2 launcher

- 稳定、少改、外部存在的启动/监督/安装体；
- 职责：
  - 准备 Python/venv；
  - pip/uv 安装依赖；
  - 启动 engine；
  - supervisor loop（D67 已有）；
  - 检测 pending 更新，在 engine 停止后执行安装；
  - 失败回滚；
- 它可以就是 start.bat 的一部分/角色，也可以抽出 `launcher.bat`；
- **不应由 PWA 在运行中替换 launcher 自己**；
- 它的对外契约要尽量稳定。

### 4.3 稳定适配层（D71 拍板：契约级一步解耦）

为避免外部 launcher 硬编码 engine 内部 `assist.cli serve`：

- **launcher = start.bat / start.sh**：稳定外部层，负责 Python/venv、依赖安装、
  supervisor loop、pending 更新、回滚；不 import engine 包。
- **engine 适配层 = `_engine\engine\run_engine.bat` / `run_engine.sh`**：
  属于 engine 包，随 engine 更新；内部再决定使用 `python -m assist.cli serve`
  还是其他当前 CLI 入口。
- 外部 start.bat 只通过稳定路径调用 `run_engine`；
- 这样 `assist.cli` 变化时，只改 engine 内的适配层，外部 start.bat 不需要改。

**为什么首轮不拆独立 `_launcher` 产物：**

- 独立 `_launcher` 会增加第二条更新通道、版本 skew 和 bootstrap 复杂度；
- start.bat 已经天然位于 engine 更新目标之外，能承担 launcher 角色；
- 当前核心痛点是“外部 launcher 硬编码 engine 内部入口”和“运行时安装锁”，
  契约级解耦 + 两阶段更新即可解决；
- 如果以后 launcher 逻辑显著膨胀，或需要独立自动更新，再从 start.bat 中抽
  `_launcher` 也不迟。

---

## 5. D71 需求条目

### D71-1 扫码导航竞态修复（必须）

- 不再把 `Page.evaluate: Execution context was destroyed` 判成浏览器死亡；
- 存活判断优先级：
  1. `browser.is_connected()`；
  2. `page.is_closed()`；
  3. 只有两项为真/不可恢复时才是真失败；
- 页面导航类异常 → 等待下一轮，继续 `_is_logged_in()`；
- 验收：扫码后出现 `UID/_uid` 时必须进入 `logged_in`。

### D71-2 两阶段更新流程（必须）

- PWA 更新只做 staging：下载、解压、校验、写 pending；
- 不在 engine 运行时改 venv；
- 旧 engine 退出后由 launcher 执行安装；
- 安装成功后启动新 engine；
- 安装失败保留旧 engine 可回滚。

### D71-3 launcher/engine 契约级解耦（必须，一步定版）

- **launcher = start.bat / start.sh**，保持稳定；
- engine 包内提供稳定适配层：
  - `_engine\engine\run_engine.bat`
  - `_engine\engine\run_engine.sh`
- launcher 只调用 `run_engine`，不硬编码 `assist.cli serve`；
- `run_engine` 随 engine 更新，内部适配当时 CLI；
- PWA 不替换 launcher 自身；
- 首轮不拆独立 `_launcher` 产物；如未来 launcher 复杂化再演进。

### D71-4 staging / pending / rollback（必须）

- 下载包、解压目录、目标版本 commit；
- `update.pending` 状态机；
- 安装失败/启动失败处理；
- 旧版本保留路径与回滚策略。

### D71-5 过程输出（必须）

- PWA 显示更新阶段：下载/解压/等待重启/安装/启动/失败；
- start.bat/terminal 同步输出；
- 失败时输出完整 stderr 最近 N 行，不再静默。

---

## 6. 待拍板问题

1. launcher 是继续留在 `start.bat` 内，还是抽 `launcher.bat`？
2. engine 适配层用 `_engine\run_engine.bat`，还是 `python -m assist.launcher`？
3. 更新包是否保留旧 `_engine` 备份，以及回滚触发条件？
4. 非 start.bat 启动的 engine，PWA 更新按钮如何提示与降级？
5. 当前已经半安装的教师机，先按“停 engine → 双击 start.bat”恢复，是否同步写进用户手册？

---

## 7. 拍板结论（2026-10-09）

1. **D71-1 按“导航异常不判死、cookie 优先、存活只作辅助”实施**；
2. **D71-2 采用方案 B**：PWA 只 staging + pending + 触发 `/restart`；
   旧 engine 停止后由 start.bat 安装，再启动新 engine；
3. **D71-3 采用契约级一步解耦**：
   - launcher = start.bat / start.sh（稳定，不 import engine）；
   - engine 适配层 = `_engine\engine\run_engine.bat|sh`（随 engine 更新）；
   - 首轮不拆独立 `_launcher`；
4. **D71-4** staging 目录、pending 状态机、旧版本备份/回滚为必做；
5. **D71-5** PWA / terminal 全阶段过程输出为必做；
6. 有头浏览器不在本单范围内。

---

## 8. 当前处置建议（过渡恢复）

- 扫码：先修 D71-1，不碰浏览器档位；
- 更新：按方案 B 设计，launcher 稳定 + engine 可更新 + `run_engine` 适配；
- `assist.exe` 锁定：属于两阶段更新要解决的问题，不通过方案 A 长期绕过；
- 有头浏览器：本轮不讨论。

---

## 9. 实施记录（2026-10-09）

### 9.1 D71-1 扫码导航竞态

- `session.py::_page_alive(browser, page)` 改为三态语义：
  - `browser.is_connected() == False` → 真失败；
  - `page.is_closed() == True` → 真失败；
  - `Page.evaluate: Execution context was destroyed / navigation` → 视为“正在跳转”，继续等待；
- `qr_login()` 循环顺序改为**先 `_is_logged_in()`，再做存活检查**；
- 回归测试：导航异常不再判死；browser disconnected 仍判死。

### 9.2 D71-3 launcher/engine 契约级解耦

- 新增 engine 适配层：
  - `engine/run_engine.bat`
  - `engine/run_engine.sh`
- `start.bat` / `start.sh` 不再直接运行 `assist.exe serve`；
- 改为路径稳定调用：
  - `%ENGINE_DIR%\run_engine.bat <venv python> <workspace> <port>`
  - `$ENGINE_DIR/run_engine.sh <venv python> <workspace> <port>`
- 旧 engine 缺少适配层时保留迁移 fallback（`python -m assist.cli serve`），
  仅用于首轮升级，不改变长期契约。

### 9.3 D71-2/4 两阶段更新

- `engine_update.update_engine()` 改为**只 staging**：
  - 下载/解压到 `_engine\staging`；
  - 写 `_engine\update.pending`；
  - 不再在运行中的 engine 里 pip/uv 安装；
- `start.bat` / `start.sh` 增加 pending 处理：
  - 检测 `_engine\update.pending`；
  - 旧 engine 已停止后：
    - 备份当前 `_engine\engine` → `engine.bak`；
    - 从 staging 覆盖新版本；
    - 执行 pip 安装；
    - 成功：写 `engine-version.json`，清理 pending/staging/backup；
    - 失败：恢复 `engine.bak`，重装旧版本，pending 改名 `update.pending.failed`；
- `restart_plan()` 统一：
  - 有 supervisor（start.bat/start.sh）时，Windows/POSIX 都返回 `exit75`；
  - 无 supervisor 时，Windows → `manual`，POSIX → `execv`。

### 9.4 D71-5 过程输出

- PWA 更新日志：改为“更新包已暂存，正在请求重启并由 launcher 安装……”；
- start.bat / start.sh 输出 `[update] ...`、`[FAIL] ...` 阶段信息；
- 安装失败时 start.bat 保留 `start.log` tail / pause 提示。

### 9.5 验证

- `pytest engine/tests -q` → **77 passed**；
- `python tools/lint_bat.py` → 通过；
- `bash -n tools/start.sh` → 通过；
- `npm run build` → 通过（PWA 更新文案变更）。

### 9.6 过渡恢复（当前已经半安装的机器）

当前教师机如果已被 D69/D70 的失败更新弄成半安装状态，按以下处理：

1. 关闭正在运行 engine 的 terminal，确认 `assist.exe` 进程退出；
2. 双击最新 `start.bat`；
3. start.bat 会重新执行 venv pip 安装；若 `_engine` 已是新版本则直接修复；
4. 后续 PWA「更新引擎」将走 staging + pending + supervisor 安装。
