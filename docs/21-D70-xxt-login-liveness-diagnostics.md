# D70 实施记录：学习通扫码等待期浏览器存活检查 + 过程输出

> 状态：**已被 D71-1 修正（2026-10-09）**。D70 的 `_page_alive` 把导航异常误判为死亡；
> D71 已改为导航类 exception 视为存活/重试。
> 关联：`docs/19-D68-xxt-scan-login-state.md`、`docs/17-D66-xxt-qr-image-task.md`。
> 现场：D68 后 `xxt-login-state.json` 长期停在 `waiting_scan`，`url` 始终是 passport；
> terminal / PWA 都看不到实时过程信息。

---

## 1. 问题判断

从状态文件可以确定：

- 二维码生成成功；
- CLI 子进程还活着，`_last_diag` 在更新；
- 但 `_is_logged_in()` 从未返回 True；
- 因此没有写 `xxt-storage.json`，PWA 无登录态可读。

代码上存在两个盲区：

1. **浏览器/页面可能已死，但轮询循环还在继续**
   - `page.url` 可能返回缓存值；
   - `page.context.cookies()` 抛出的断连异常被 `_is_logged_in()` 捕获并返回 False；
   - 外层继续每 15s 写 `waiting_scan`，看起来像“正常等待”。

2. **URL 先判，cookie 判断不可达**
   - 旧 `_is_logged_in()` 先判断 `passport/login`，直接 return False；
   - 如果扫码后 cookie 已出现 `_uid/uid`、但 URL 还没跳转，就永远检测不到。

另外，serve 子进程此前用 `subprocess.run(capture_output=True)`，
扫码等待期间 stdout/stderr 一直不转发，terminal 和 `/jobs` 都是空白。

---

## 2. D70 实施内容

### 2.1 浏览器档位与存活检查

`session.py`：

- 新增 `_launch_labeled()`，返回 `(browser, 档位标签)`；
  - `_launch()` 保留原接口，内部委托 `_launch_labeled()`。
- 新增 `_page_alive(page)`：
  - 真实执行 `page.evaluate("() => 1")`；
  - 浏览器/页面断开时返回 `(False, error)`，不再静默。
- `_cookie_names(page)`：
  - 只取 cookie 名（不取值），最多 30 个，用于脱敏诊断。

`qr_login()` 循环中：

- 每次 sleep 后先做 `_page_alive()`；
- 若页面/browser 已关闭：
  - 写 `stage="failed"`；
  - 记录 `browser`、`browser_connected`、`page_closed`、`cookies`、`error`；
  - 任务立即终结，不再假等 30 分钟。
- 每 15s 的 `waiting_scan` 状态追加：
  - `browser`
  - `browser_connected`
  - `page_closed`
  - `cookies`（仅名字）

### 2.2 登录判定顺序调整

`_is_logged_in()` 改为：

1. 先看 cookie 名，若出现 `_uid` / `uid` → 直接 True；
2. 再判断是否到 `i.chaoxing.com` / `*.chaoxing.com` 教学域；
3. 最后才用 passport/login URL 兜底判 False。

真伪仍由后续 `page.goto("https://i.chaoxing.com/")` + CLI `check_session()` 二次确认。

### 2.3 serve 子进程实时输出

`serve.py` `/xxt/login/start` worker：

- 由 `subprocess.run(capture_output=True)` 改为 `subprocess.Popen`；
- `stdout=PIPE, stderr=STDOUT, text=True, bufsize=1`；
- 单独 reader 线程逐行读取：
  - `q_.put(line)` → `/jobs` 可查；
  - `print(f"[xxt-login] {line}", flush=True)` → terminal / start.log 实时可见；
- 保留 2300s 超时与强制终止。

### 2.4 状态文件同步落盘 + stdout

`qr_login._write()` 每次更新：

- 写 `xxt-login-state.json`；
- 同时 `print(payload)`，输出到 CLI stdout。

因此现在扫码等待期间，terminal / start.log 应能看到类似：

```json
{
 "stage": "waiting_scan",
 "url": "https://passport2.chaoxing.com/login?...",
 "browser": "msedge",
 "browser_connected": true,
 "page_closed": false,
 "cookies": ["JSESSIONID", "retainroute"]
}
```

下一次诊断可直接看 cookie 名是否出现 `UID` / `_uid`。

---

## 3. 验证

- `pytest engine/tests -q` → **72 passed**；
- 新增/调整测试：
  - `_is_logged_in` 在 passport URL + `_uid` 时应判真；
  - passport URL 无 `_uid` 仍判假；
  - 教学域无 cookie 仍判真。

---

## 4. 现场复测建议

1. 更新 engine 到最新提交并重启；
2. 发起扫码；
3. 观察 terminal / start.log：
   - 是否持续输出 `[xxt-login] {...}`；
   - `browser_connected` / `page_closed` 是否变化；
   - `cookies` 是否在扫码后出现 `UID` / `_uid`；
4. 观察 `xxt-login-state.json`：
   - 若出现 `stage="failed"` + `browser/page closed` → 浏览器进程确实提前退出；
   - 若出现 `UID/_uid` 但 PWA 仍未登录 → 继续查 storage 写入/PWA 状态；
   - 若始终没有 `UID/_uid` → 问题在扫码流程本身或学习通风控。
