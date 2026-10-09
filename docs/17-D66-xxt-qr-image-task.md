# D66 任务需求单：学习通扫码登录二维码无法显示

> 状态：**已实施（2026-10-09），待现场真机扫码验收**。
> 说明：本文件最初用于登记原因与需求，现保留为 D66 修复实施与验收入口。
> 日期：2026-10-09
> 关联文档：`docs/16-xuexitong-integration.md`（§20.2 扫码框 → 头像框、§22.2 待办）
> 关联代码：`engine/src/assist/serve.py`、`engine/src/assist/xxt/session.py`、
> `engine/src/assist/xxt/cli.py`、`app/src/views/XxetongView.vue`、`app/src/lib/engineClient.ts`
> 影响等级：**P0（阻塞）**——学习通所有读写前置都依赖扫码登录。

---

## 1. 现象

在学习通选项卡点击「📷 扫码登录（QR）」后：

- 页面登录卡中本应出现二维码图片，实际显示为破图 / 空白 / 一直“待扫码”；
- 扫码任务可能已经启动，但教师无法看到二维码，登录流程无法完成；
- 没有明确错误文案，只表现为“图片无法显示”。

当前只能确认现象，**不能凭单次截图断定唯一根因**；下面两处代码级缺陷已足以独立造成该现象，需一并修复。

---

## 2. 代码级原因核查

### 2.1 P0-A：二维码“写入目录”和“读取目录”不一致（最可能主因）

链路如下：

1. PWA `POST /xxt/login/start`；
2. 引擎 `serve.py` 创建后台任务，设置 `XXT_STORAGE` 环境变量后启动子进程：

   ```python
   # engine/src/assist/serve.py:425-432
   env = {"XXT_STORAGE": str(_xxt_home() / "xxt-storage.json"), **os.environ}
   cmd = [_venv_python(), "-c",
          "from assist.xxt.session import qr_login;"
          "print(json.dumps(qr_login(), ensure_ascii=False))"]
   ```

3. 但 `qr_login()` 没有读取 `XXT_STORAGE`，也没有接收 `serve.py` 传入的 storage / qr 路径：

   ```python
   # engine/src/assist/xxt/session.py:131-133
   storage = Path(storage or (Path.home() / "assignment-assistant-workspace"
                              / ".runtime" / "xxt-storage.json"))
   qr_out = Path(qr_out or storage.parent / "xxt-qr.png")
   ```

   结果是二维码实际写到默认目录：

   ```text
   ~/assignment-assistant-workspace/.runtime/xxt-qr.png
   ```

4. 而 `GET /xxt/qr` 从 `_xxt_home()` 读取：

   ```python
   # engine/src/assist/serve.py:496-505
   elif u.path == "/xxt/qr":
       qr = _xxt_home() / "xxt-qr.png"
       if not qr.exists():
           self._json({"ok": False, "error": "no qr yet"}, 404)
           return
   ```

   两者不一致时，`/xxt/qr` 必然 404 或返回旧文件，`<img>` 显示破图。

**已做的只读路径验证（未联网、未启动浏览器）：**

```text
_ws()                  = ~/assignment-assistant-workspace
_xxt_home()            = <repo>/.scratch
serve 读取 qr          = <repo>/.scratch/xxt-qr.png
serve 读取 storage     = <repo>/.scratch/xxt-storage.json

qr_login 默认 storage  = ~/assignment-assistant-workspace/.runtime/xxt-storage.json
qr_login 默认 qr       = ~/assignment-assistant-workspace/.runtime/xxt-qr.png
```

当前仓库开发态因存在 `.scratch/xxt-storage.json`，`_xxt_home()` 会解析到 `.scratch/`；
`qr_login()` 却写到默认 workspace。已安装/部署态会再次变化，不一致更明显：

- `XXT_HOME` / `ASSIST_WORKSPACE` 等环境变量对 `_xxt_home()` 生效；
- `qr_login()` 只认函数参数，不认工作区环境；
- `cli.py` 的 `default_storage()` 会读 `XXT_STORAGE`，但 `serve.py` 直接调 Python 函数，绕过了 CLI 读取逻辑。

```python
# engine/src/assist/xxt/cli.py:10-14
def default_storage(ctx) -> Path:
    v = os.environ.get("XXT_STORAGE")
    if v:
        return Path(v).expanduser()
    ...
```

因此这不是偶发浏览器问题，而是**服务端两条路径契约没有统一**。

---

### 2.2 P0-B：前端 `<img>` 只加载一次，没有等待 QR 就绪，失败后不重试

当前 PWA 逻辑：

```ts
// app/src/views/XxetongView.vue:46-65
async function startScan() {
  loginHint.value = '已发起扫码任务：输入学习通手机 App 扫描下方二维码…'
  try {
    await startXxtLogin(engUrl.value, tok.value)
    pollQr()
  } catch (e) {
    loginHint.value = `启动失败：${String(e)}（检查引擎在线/playwright 安装项）`
  }
}

function pollQr() {
  const base = engUrl.value.replace(/\/+$/, '') || ''
  const tokArg = tok.value ? `?token=${encodeURIComponent(tok.value)}` : ''
  qrcode.value = `${base}/xxt/qr${tokArg}` // 注释说“每 3s 重载一次”，但实现没有
  const timer = setInterval(async () => {
    await refreshStatus()
    if (verdict.value === 'alive') { clearInterval(timer) }
  }, 3000)
}
```

问题：

1. `startXxtLogin()` 只返回 `job_id`，服务端返回时二维码可能还没生成；
2. `qrcode.value` 立即被设置为 `/xxt/qr`，浏览器只请求一次；
3. 首次请求若遇到 `404 no qr yet`，`<img>` 进入破图态后**不会自动重试**；
4. 3 秒定时器只刷新“体检状态”，并不重新赋值 `qrcode.value`，也不加 cache-busting；
5. 即使后端路径修好，上述竞态仍会让第一次打开二维码失败。

结论：**P0-A 与 P0-B 是两处独立缺陷，任一成立都会表现为“图片无法显示”。**

---

### 2.3 P1-C：旧二维码未清理，可能扫码失败但显示“正常”

`qr_login()` 一开始没有删除旧 `xxt-qr.png`。如果目录里存在上一次登录留下的二维码：

- `/xxt/qr` 会立即返回旧 PNG，页面看起来“有图”；
- 但该二维码属于旧浏览器上下文，手机扫码后当前新的扫码会话不会变成 `logged_in`；
- 教师会感觉“图片显示了但扫了没用/一直不成功”。

该问题也带来隐私风险：二维码是登录票据，长期保留在本机不应长期驻留的目录中。

---

### 2.4 P1-D：登录子进程失败对 UI 不可见

`startXxtLogin()` 返回的 `job_id` 被忽略；前端也未查询 `/jobs/<id>`。
如果 `qr_login()` 因以下原因失败：

- `playwright` 未安装 / 浏览器内核未就绪；
- `#quickCode` 选择器超时；
- 登录页 DOM 变化；
- 子进程路径 / Python 环境错误；

页面只会看到 `/xxt/qr` 404，然后停留在破图态，无法区分“还没生成 / 生成失败 / 引擎路径错误”。

### 2.5 P2-E：第三方登录页 DOM 依赖

`session.py:148` 依赖：

```python
page.wait_for_selector("#quickCode", timeout=30000)
page.locator("#quickCode").screenshot(path=str(qr_out))
```

当前本仓库 `.scratch` 中曾成功产出一张有效 PNG，说明该 selector **目前可用**；
但它属于第三方页面结构，未来改版会超时。此条不是本次“图片无法显示”的已证主因，
但应纳入错误兜底和诊断日志。

### 2.6 P2-F：Pages PWA → 本机引擎的跨源/私有网络边界（需现场 Network 证据）

线上 PWA 是 HTTPS 公网页面，引擎通常是 `http://127.0.0.1:8601`：

- `fetch` 链路已有 OPTIONS / `Access-Control-Allow-Private-Network` 处理；
- `<img>` 是 no-cors 资源，若有浏览器版本 / 策略拦截，可能表现为破图；
- 这需要现场 DevTools Network 面板确认，不能在离线环境断言。

排查时必须区分：**接口 404 / 接口有图但 PNA 拦截 / 接口返回了非 PNG**。

---

## 3. 结论

- **根因优先级**：
  1. **P0-A 服务端读写路径不一致**（代码级确定）；
  2. **P0-B 前端不等待、不重试、不刷新**（代码级确定）；
  3. P1-C 旧二维码残留；
  4. P1-D 子任务失败不可见；
  5. P2-E / P2-F 等现场证据项。
- 当前不能仅靠“看截图”判断哪一条先发生；修复时应把 P0-A/P0-B 作为同一验收闭环一起修，
  否则修完一条，另一条仍可能复现“破图”。
- 本次只读核查未启动浏览器、未访问学习通、未改动代码。

---

## 4. 修复需求（实施时按此交付）

### R1 · 统一二维码工件路径（必须）

- `serve.py` 与 `session.py` 必须共用同一个“xxt 工件根”解析：
  - 优先级建议：显式参数 > `XXT_HOME` > 开发态 `.scratch`（仅存在 storage 时）> `workspace/.runtime/xxt`；
  - `XXT_STORAGE` 继续保留为兼容变量，但要和上述根一致，不能双轨。
- `POST /xxt/login/start` 必须把目标 storage 和 QR 输出路径**显式**传给 `qr_login()`；
  或者在子进程里调用 `assist xxt login --storage <path> --qr <path>`，让 CLI 的参数链生效。
- 禁止再依赖 `qr_login()` 内部的 `Path.home()/assignment-assistant-workspace` 硬编码默认值
  作为 PWA 主路径。

### R2 · 二维码生命周期（必须）

- 每次发起新扫码前：
  - 清除/替换旧 QR PNG，避免旧票据被页面加载；
  - 先写临时文件，QR 完整生成后原子改名为最终文件，避免读到半张图；
  - 失败时写失败状态，清理半成品。
- `/xxt/qr` 在“当前任务尚未就绪”时返回 404 或明确的 `waiting` 状态；
  一旦 PNG 可用，返回 `image/png`。

### R3 · 前端等待就绪 + 重试（必须）

- 不立即把 `<img src>` 指向 `/xxt/qr`；
- 轮询 `job_id` 对应的任务状态，确认 QR 已生成后再设置 `src`；
- 首次加载失败 / 图片 `@error` 时继续重试（建议 1–2 秒间隔，带退避与最大时长）；
- 每次刷新使用 `?v=<timestamp>` 或等价 cache-busting，绕过浏览器缓存；
- 组件卸载、登录成功、用户离开学习通 tab 时清理定时器；
- 不在 3 秒状态轮询里反复请求同一个失败 URL。

### R4 · 错误可见（必须）

- 引擎侧把 `qr_login()` 的失败阶段写入任务状态，例如：
  `starting / waiting_qr / waiting_scan / logged_in / failed`；
- 前端显示明确中文文案，至少覆盖：
  - “二维码生成中…”；
  - “二维码生成失败：Playwright/浏览器内核未就绪”；
  - “登录页选择器超时，学习通可能改版”；
  - “引擎未在线 / 路径不可读”；
- 不再用破图 icon 作为唯一反馈。

### R5 · HTTP 缓存与诊断（建议）

- `/xxt/qr` 响应加 `Cache-Control: no-store`（或等价禁用缓存头）；
- 404 响应体保留可读 `error`；
- 服务端日志记录：目标路径、文件是否存在、文件字节数、任务阶段；
- 日志和状态 JSON 不得包含二维码内容、token 或 storage_state 敏感字段。

### R6 · 测试与回归（必须）

- engine 单元测试：
  - 路径解析函数在 `XXT_HOME` / 开发 `.scratch` / 默认 workspace 三种模式下返回同一路径给
    `serve.py` 与 `session.py`；
  - `qr_out` 默认值 = `storage.parent / "xxt-qr.png"` 的契约；
  - `/xxt/qr` 在无文件 / 有有效 PNG / 有半成品文件三种情况下的行为。
- 前端构建门禁：
  - `npm run build` 通过；
  - 人工场景中无破图、可重试、错误文案可见。
- 全量回归：`pytest engine/tests -q`（实施后基线以当时测试数为准）。

---

## 5. 验收标准

- [ ] 开发态（repo/.scratch 模式）点击扫码后，engine 的写入路径与 `/xxt/qr` 读取路径一致；
- [ ] 安装/部署态（默认 workspace 或自定义 `XXT_HOME`）同样一致；
- [ ] PWA 点「扫码登录」后，不再出现破图；正常网络下二维码应在 10 秒内可见；
- [ ] 二维码生成期间刷新/重试不会把页面永久卡在第一次失败的 URL 上；
- [ ] 再次点击扫码登录时，页面显示的是新二维码，不是上一次的旧 PNG；
- [ ] 手机扫码成功后，`verdict` 变为 `alive`，登录卡切换为头像/已登录态；
- [ ] Playwright / 浏览器内核 / 登录页 selector 任一步失败时，页面显示具体错误，而不是“图片无法显示”；
- [ ] `/xxt/qr` 返回 200 时 `Content-Type: image/png` 且文件是完整 PNG；无 QR 时返回可解释的 404；
- [ ] 响应/日志不暴露二维码内容、token、storage_state；
- [ ] 不改变“只扫码、无账密路径”和“学习通侧只读”边界；
- [ ] `npm run build` 与 `pytest engine/tests -q` 通过。

---

## 6. 测试矩阵建议

| 场景 | 预期 |
|---|---|
| repo 开发态，存在 `.scratch/xxt-storage.json` | 二维码写入并读取同一 `.scratch` 路径 |
| 默认 workspace 态，无 `.scratch` | 写入并读取 `workspace/.runtime/xxt/` |
| 自定义 `XXT_HOME` | 两端都使用该自定义根 |
| 连续点击两次扫码 | 第二次覆盖旧 QR，页面显示新码 |
| 引擎在线但 Playwright 未安装 | 前端显示安装提示，不是破图 |
| 学习通登录页 selector 超时 | 任务状态 failed，前端显示“可能改版” |
| `/xxt/qr` 第一次 404、第二次 200 | 前端能重试并加载成功 |
| 首次请求碰到半成品 PNG | 通过原子写 / 就绪状态避免解码失败 |
| Pages(HTTPS) → 本机引擎 | 与 `/xxt/status` 同样可联调；若被浏览器策略拦截，需有明确文案 |

---

## 7. 不在本需求内

- 不改学习通登录方式，不加入账号密码自动登录；
- 不改课程/班级/学生/作业/公告的只读提取逻辑；
- 不解除任何写操作冻结（公告发布 / 批阅回传仍按原门禁）；
- 不因第三方页面 DOM 可能变化而重写整个登录模块；
- 不做与二维码显示无关的 UI 重构。

---

## 8. 现场复现时建议补充的信息（下次在电脑前）

1. DevTools → Network，筛选 `xxt/qr`：
   - HTTP 状态码（200/404）；
   - 响应类型是否 `image/png`；
   - 是否被 CORS/PNA/mixed-content 拦截；
2. `POST /xxt/login/start` 返回的 `job_id`；
3. 引擎启动方式：仓库 `assist serve` 还是安装态 `_engine`，以及是否设置了
   `XXT_HOME` / `ASSIST_WORKSPACE`；
4. 对应目录下 `xxt-qr.png`、`xxt-storage.json`、`xxt-login-state.json` 是否存在、时间戳；
5. `xxt-login-state.json` 中 `stage` 是 `waiting_scan`、`logged_in` 还是 `timeout`。

---

## 9. 实施文件预估

- 后端：
  - `engine/src/assist/serve.py`（`/xxt/login/start`、`/xxt/qr`、`_xxt_home` 路径契约）；
  - `engine/src/assist/xxt/session.py`（`qr_login` 显式路径、清旧 QR、原子写、失败状态）；
  - `engine/src/assist/xxt/cli.py`（与 serve 共用默认路径解析）；
- 前端：
  - `app/src/views/XxetongView.vue`（QR 就绪轮询、重试、cache-busting、错误态、定时器清理）；
  - `app/src/lib/engineClient.ts`（任务状态 / QR 就绪查询 helper，如需要）；
- 测试：
  - `engine/tests/test_xxt_session.py` 或新增路径契约回归测试；
- 文档：
  - 实施后同步 `docs/16-xuexitong-integration.md` 对应状态。

**预计工作量**：后端 0.5 天 + 前端 0.5 天 + 回归与文档 0.5 天，合计约 1.5 人日。
**建议修复顺序**：R1 → R2 → R3 → R4 → 测试；R5/R6 随同批次完成。

---

## 10. 实施记录（2026-10-09）

已按本单 R1–R4/R6 落地：

- **engine 路径契约统一**：
  - `xxt/session.py` 新增 `xxt_home()` / `resolve_storage_path()` / `default_qr_path()`；
  - `serve.py` 的 `_xxt_home()` 改为复用 `xxt_home()`；
  - `/xxt/login/start` 的环境变量改为“引擎解析出的 `XXT_HOME`/`XXT_STORAGE` 覆盖外部环境”；
  - `cli.py` 的默认 storage 改为复用 `resolve_storage_path()`，CLI 与 serve 不再各写一处。
- **二维码生命周期**：
  - 启动新扫码前删除旧 `xxt-qr.png`；
  - `qr_login()` 先写 `xxt-qr.tmp.png`，再 `os.replace()` 原子替换；
  - 二维码阶段失败写入 `xxt-login-state.json` 的 `stage=failed` 与 `error`。
- **`/xxt/qr` 缓存**：成功/404 均加 `Cache-Control: no-store, no-cache, must-revalidate`。
- **PWA 等待与重试**：
  - `XxetongView.vue` 不再直接把 `<img>` 指向 `/xxt/qr`；改为 `Image()` 预加载探针，
    每 1.5s 带 `?t=<timestamp>` 重试，只有真正加载成功才把 URL 交给 `<img>`；
  - 12s 后仍未就绪时查询 `/jobs/<job_id>`，任务失败则显示具体原因；
  - `onUnmounted` 清理定时器；
  - `engineClient.ts` 新增 `fetchXxtLoginJob()`。
- **验证**：
  - `python -m pytest engine/tests -q` → `58 passed`；
  - `npm run build` → 通过（`vue-tsc -b && vite build` 0 err）。
- **待现场验收**：Windows/教师机真机扫码、Pages HTTPS → 本机引擎的 `<img>` 实际网络行为。
