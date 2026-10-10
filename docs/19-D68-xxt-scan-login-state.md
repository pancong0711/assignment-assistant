# D68 需求/实施记录：学习通扫码后无反应 · 登录态 JSON 与 CLI 套壳

> 状态：**代码已实施（2026-10-09），待真机扫码复测**。
> 关联：`docs/01-architecture.md`、`docs/16-xuexitong-integration.md` §20.3/§11、
> `docs/17-D66-xxt-qr-image-task.md`、站点提交 `e13d56d` 之后。
> 现场：D66 后二维码已能正常显示；手机扫码后 PWA 无状态变化。

---

## 1. 现场现象

1. 学习通选项卡点「扫码登录」；
2. 二维码能正常显示（D66 已修）；
3. 手机学习通 App 扫码后，页面一直停在“未登录/失效”或二维码态；
4. 不知道登录任务是否成功，也不知道有没有写 `xxt-storage.json`。

---

## 2. 代码核查结论

### 2.1 登录态 JSON 由谁写？

- **CLI 路径**：`assist xxt login` → `qr_login()` 内检测登录成功 → `ctx.storage_state(path=storage)` 写
  `xxt-storage.json`；随后 CLI 再跑 `check_session(storage_path)`，二次确认并回写续期。
- **PWA 修复前路径**：`POST /xxt/login/start` 直接起 `python -c "qr_login()"`，
  **没有走 CLI 套壳**。因此：
  - 它同样会在 `qr_login()` 内部写 JSON，但前提是 `_is_logged_in()` 必须返回 True；
  - 它**不会**执行 CLI 的 `check_session()` 二次确认；
  - 与 docs/16 §20.3 已拍板的“CLI 套壳 = 方案 A”不一致。

### 2.2 `_is_logged_in()` 漏了旧 capture 的教学域判定

旧 `.scratch/xxt_login_capture.py` 的 `is_logged_in()` 有两级：

1. URL 仍含 `passport`/`login` → False；
2. 如果已经到 `i.chaoxing.com` 或 `*.chaoxing.com` 教学域 → **直接 True**；
3. 否则才看 cookie `_uid`/`uid`。

而 `session.py` port 时丢了第 2 步，只保留 cookie 判定。在部分 Windows/浏览器组合里，
页面已经跳到教学域，但 cookie 可见时序不同，导致扫码后一直不触发 `logged_in` → 不写 JSON。

### 2.3 `/xxt/status` 的旧 dead 缓存会把成功登录挡住

`/xxt/status` 的 `_xxt_session_check_cached(max_age=60)` 会缓存 dead 60 秒。
PWA 在 QR 显示前已多次调用 `/xxt/status`，缓存里是 `no_storage/dead`；
扫码成功后，即使 CLI 已经写好 storage，PWA 轮询到的仍可能是旧 dead，直到 60 秒 TTL 过期。
头像缓存 `_xxt_avatar_cached(max_age=600)` 也有同样问题。

### 2.4 CLI 登录二次确认没有体现在退出码

修复前 `assist xxt login` 只要 `qr_login()` 返回 `logged_in` 就 exit 0；
即使随后 `check_session()` 返回 dead，CLI 仍算成功，PWA 看不到“登录态 JSON 不可用”。
这会让 PWA 只显示“无反应”，而不是明确报错。

---

## 3. D68 实施内容

### 3.1 PWA 登录任务改走 CLI 套壳（核心）

`engine/src/assist/serve.py` 的 `/xxt/login/start` 改为执行：

```text
<python> -m assist.cli xxt login
  --storage <xxt_home>/xxt-storage.json
  --qr <xxt_home>/xxt-qr.png
  --timeout 1800
```

- 登录态 JSON 仍由 `qr_login()` 写，但由 CLI 统一收口；
- CLI 随后跑 `check_session()` 二次确认 + storage_state 回写续期；
- 与终端 `assist xxt login` 完全同路径。

### 3.2 恢复旧 capture 的教学域判定

`session.py::_is_logged_in()` 恢复：

- 仍在 passport/login 页 → False；
- 跳到 `i.chaoxing.com` / `*.chaoxing.com` 教学域 → True；
- 否则回退 cookie `_uid`/`uid`。

### 3.3 缓存按 storage mtime 失效

`serve.py`：

- `_xxt_session_check_cached()` 与 `_xxt_avatar_cached()`：
  若 `xxt-storage.json` 的 mtime 比缓存时间新，则立即失效缓存并重跑；
- 缓存时间取“操作结束时间”和 storage mtime 的较大者，避免 check_session
  自己回写 storage 造成反复起浏览器。

### 3.4 CLI 登录退出码反映真实登录态

`assist xxt login` 现在：

- `qr_login()` 成功 → 再 `check_session()`；
- 二次确认 `verdict=alive` 才 exit 0；
- 若 dead → exit 2，PWA `/jobs` 显示失败原因，不再假装成功。

---

## 4. 验证与给现场测试的步骤

已通过：

- `pytest engine/tests -q` → **69 passed**（新增 `_is_logged_in`、CLI 退出码、缓存失效、CLI 命令回归）；
- `npm run build` → 通过；
- `python tools/lint_bat.py` → 通过。

现场复测建议：

1. 在教师机重启/更新引擎到最新提交（PWA「检测更新/更新引擎」或重新双击 start.bat）；
2. 学习通选项卡重新点「扫码登录」；
3. 手机扫码后，观察：
   - PWA 应在数秒内变为“已登录”；
   - 工作区 `.runtime/xxt/xxt-storage.json`（或 `_xxt_home` 对应目录）应出现并持续更新；
4. 若仍无反应：
   - 查看 `/xxt/login-state.json` 的 `stage`；
   - 查看 `/jobs/<job_id>` 的 stdout/stderr；
   - 把上述文件与浏览器 Network 中 `/xxt/status` 返回值发回。
