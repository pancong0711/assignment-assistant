# D69 需求/实施记录：引擎更新依赖安装 rc=2 与 uv/pip 回退

> 状态：**代码已实施（2026-10-09），待 Windows 真机复测**。
> 关联：`docs/16-xuexitong-integration.md` §27（D65-P4 引擎更新/一键安装）、
> `docs/14-va-vb-plan.md` VA-1，以及 D65 的 start.bat 依赖安装路径。
> 现场输出关键句：
> `$ uv pip install -e D:\...\_engine\engine --python ... --index-url ...`
> `✗ 依赖重装失败（rc=2）`

---

## 1. 先澄清一个关键概念

PWA「更新引擎」的流程是：

1. 从 Pages 下载 `engine-main.zip` 到本地；
2. 解压到 `<workspace>\_engine\engine`；
3. 对这个**本地目录**执行 editable install：
   `pip/uv pip install -e <local engine dir>`；
4. 安装过程中，pip/uv 需要从 **Python 包索引**（默认 PyPI）解析并安装
   `click/openpyxl/reportlab/loguru/pillow/pypdf/httpx/jinja2` 等第三方依赖。

因此：

- **`assist-engine` 本体不是从 PyPI 下载的**，`-e <本地目录>` 已指明它来自 GitHub Pages 下载的 zip；
- 输出中的 `--index-url https://pypi.tuna.tsinghua.edu.cn/simple` 是用于**第三方依赖**的清华 PyPI 镜像；
- 之前没有在 PyPI 发布 engine 包，不代表这个命令写错；但它也不该因为“没发布”而失败。

真正的故障点是：**uv 安装依赖失败（rc=2）且 update_engine 没有回退到 venv pip**。

---

## 2. 代码差异分析

### 2.1 start.bat 的稳定路径

`tools/start.bat` 的依赖安装是：

```bat
"%VPIP%" install -e "%ENGINE_DIR%" --index-url "%UV_DEFAULT_INDEX%"
```

直接使用 **workspace venv 内的 pip.exe**，不依赖系统 `uv`。
这条路径已经在 Windows 教师机上验证可用。

### 2.2 一键修复（D65-P1）

`installer_for("deps")` 的实现是：

- 有 `uv` 时用 `uv pip install -e ... --python <venv> --cache-dir ...`；
- 无 uv 时用 `py -m pip install -e ...`。

它**没有**回退；如果系统 uv 与当前 Windows/路径/版本不兼容，就会直接失败。

### 2.3 update_engine 的旧实现

`engine_update.update_engine()` 旧逻辑：

```python
if shutil.which("uv"):
    cmd = ["uv", "pip", "install", "-e", str(engine_dir),
           "--python", py, "--index-url", idx]
else:
    cmd = [py, "-m", "pip", "install", "-e", str(engine_dir), "-i", idx]
subprocess.run(cmd, ...)
```

问题：

- 有 uv 时**只走 uv**，失败即终止；
- 使用了显式 `--index-url`，与一键修复/uv 0.12 的推荐口径不完全一致；
- uv 失败输出可能为空或未被前端完整展示，老师只看到 `rc=2`；
- 没有像 start.bat 一样回到 venv pip。

---

## 3. D69 修复内容

### 3.1 统一安装 helper

`engine_update.py` 新增：

- `_dep_install_commands(ws, engine_dir)`：
  - 有 uv：`uv pip install -e <engine_dir> --python <venv python> --cache-dir <cache>`；
  - 始终追加 venv pip 回退：
    `<venv python> -m pip install -e <engine_dir> -i <mirror> --disable-pip-version-check --no-input`。
- `_install_engine_editable(ws, engine_dir, emit)`：
  - 逐条执行；
  - uv 失败 → 自动 pip 回退；
  - 每次输出 stdout+stderr 最近 40 行，rc 不再静默；
  - 回退成功时显示“uv 安装失败，已用 venv pip 回退成功”。

### 3.2 一键修复 deps 共用同一逻辑

`serve.py` 的 `/install/deps` 改为 special job：

- 调用 `_install_engine_editable(_ws(), _ENGINE_ROOT, emit)`；
- 与 PWA 引擎更新、start.bat 的 venv pip 路径收敛。

> 注意：`uv` 仍优先尝试，保留 uv 的速度与缓存优势；失败不再阻塞更新。

---

## 4. 验证

- `pytest engine/tests -q` → **71 passed**
  - 新增：uv 命令不含弃用 `--index-url`；uv 失败后自动 pip 回退；旧版本检测/CLI 回归保持。
- `python tools/lint_bat.py` → 通过。
- `npm run build` 不涉及前端改动；前端已有 jobs/SSE 输出通道。

---

## 5. 现场复测建议

1. PWA 强刷到最新提交；
2. 设置中心重新点「更新引擎」；
3. 正常应看到：
   - `$ uv pip install ...`；
   - 若 uv 失败，自动出现：
     `$ <venv python> -m pip install -e ... -i https://pypi.tuna.tsinghua.edu.cn/simple ...`
     `⚠ uv 安装失败，已用 venv pip 回退成功`；
   - 最终 `✓ 引擎文件已更新；需要重启引擎后生效`；
4. 若 pip 也失败，前端应显示最近 40 行完整 stderr，可继续定位索引/网络/权限问题。

---

## 6. 边界

- 不改变“从 Pages 下载 zip → 本地 editable 安装”的既有架构；
- 不要求 assist-engine 发布到 PyPI；
- 不改变 start.bat 的依赖安装路径；
- 后续若要彻底取消 uv 依赖，可再把 `_dep_install_commands` 中 uv 优先级去掉，但当前保留 uv 缓存收益。
