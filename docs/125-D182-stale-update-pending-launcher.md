# D182 修复：陈旧 `update.pending` 导致 launcher 启动失败

> 日期：2026-11-17
> 状态：**已完成**
> 关联：`docs/22-D71-engine-launcher-two-phase-update.md`、`docs/24-D73` §14

## 0. 现场

Windows 双击 `start.bat`：

```text
[update] pending staging detected; applying before start...
[update] staging missing: ...\_engine\staging\engine\pyproject.toml
[FAIL] engine update/install failed
```

`start.log` 中 pip 安装实际成功，仅有：

```text
WARNING: Ignoring invalid distribution ~ssist-engine
```

## 1. 根因

- `_engine/update.pending` 残留，但 `_engine/staging/engine/pyproject.toml` 已不存在；
- 正常 `update_engine()` 先完整解压、校验 staging，最后才写 pending；
  因此 pending 与 staging 不一致属于上次更新中断、网盘同步清理或手工清理后的**陈旧状态**；
- 旧 `start.bat` 把 pending 当成 staging 必然存在的强假设，staging 缺失时直接
  `exit /b 1`，导致本来完整可用的当前引擎也无法启动；
- `~ssist-engine` 是 pip 中断残留，通常无害，不是本次启动失败的直接原因。

## 2. 修复

`tools/start.bat`、`app/public/start.bat`、`tools/start.sh`、`app/public/start.sh`：

当 `update.pending` 存在但 staging 缺失/不完整时：

1. 输出“stale update marker”提示；
2. 删除陈旧 `update.pending` 和 `staging`；
3. 若当前 `_engine/engine` 有完整关键文件（`pyproject.toml`、`serve.py`、
   `xxt/session.py`），跳过陈旧更新并继续启动；
4. 只有当前引擎也不完整时才失败，并提示删除 `_engine` 后重试。

这样正常现场只需替换新的 `start.bat`，无需重新下载 venv、依赖或引擎包。

## 3. 验收

- `engine/tests/test_engine_update.py` 增加启动脚本陈旧 pending 契约测试；
- `tools/lint_bat.py`：通过；
- 全量 pytest：见本次提交验证结果；
- 不改变正常 staging 更新、备份、回滚流程。
