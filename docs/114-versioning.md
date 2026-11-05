# D114 版本号规则（2026-11-05 定稿）

> 状态：**已生效**
> 关联：`docs/113-D169`（实现路线）、`.github/workflows/pages.yml`（版本标记发布）

## 0. 为什么定这个

教师反馈：「app 的版本也固定好久了，检查一下」。

核实结果：

| 位置 | 之前 | 问题 |
|---|---|---|
| `engine/pyproject.toml` | `0.4.0` | 自 `882e32a`（D78）后未动，中间累计 **80+ 个提交** |
| `app/package.json` | `0.1.0` | 从未升级过 |
| `docs/12-backlog.md` | 提到 v10.3 等 | 那是**另一个项目**（launcher/start 脚本）的版本，与 engine/app 无关 |

→ PWA 页面上显示的版本号长期不变，教师无法判断"我用的到底是不是最新"。

## 1. 三个版本号，各管一段（不要混用）

| 名称 | 位置 | 含义 | 谁在用 |
|---|---|---|---|
| **engine 版本** | `engine/pyproject.toml` 的 `version` | Python 引擎（CLI + serve） | CI 生成 `engine-version.json`；launcher 用它判断要不要更新 |
| **app 版本** | `app/package.json` 的 `version` | PWA 前端 | 页面显示、`/status` 回显 |
| **launcher 版本** | `tools/start.sh` / `start.bat` 内 | 启动脚本 | 仅当**启动流程本身**变化时才升（极少） |

> 历史文档里的「v10.3」等是 **launcher 版本**，不是 engine/app 版本。两者不要互相引用。

## 2. 升级规则（语义化，但务实）

采用 `MAJOR.MINOR.PATCH`，但**不追求严格语义化**（这个项目的用户只有教师本人）：

| 变化 | 版本位 | 例子 |
|---|---|---|
| 破坏性变更（数据格式不兼容、需手工迁移） | MAJOR | `0.5.0 → 1.0.0` |
| 新功能 / 新需求单落地（D 系列完成） | MINOR | `0.4.0 → 0.5.0` |
| 纯修复 / 文档 | PATCH | `0.5.0 → 0.5.1` |

**engine 与 app 同步升**（同一个需求单通常两边都动），保持一致便于排查。

## 3. 什么时候必须升

- **每个"批次（B1/B2/B3…）完成并推送"时升 MINOR**；
- 只有文档/注释改动时**不升**；
- 升版本时**同时更新** `README.md` 顶部的版本行。

## 4. 发布链路（自动，无需手工）

```
engine/pyproject.toml version
        ↓ (CI: .github/workflows/pages.yml)
app/dist/dl/engine-version.json  {"engine_version":"0.5.0","commit":"..."}
        ↓ (launcher)
start.sh / start.bat 比对本地与远程版本 → 有差异才提示更新
```

**所以**：只要改 `pyproject.toml` 的 `version` 并推送，launcher 就能发现新版本。

## 5. 本次升级记录

| 日期 | engine | app | 内容 |
|---|---|---|---|
| 2026-11-05 | `0.4.0 → 0.5.0` | `0.1.0 → 0.5.0` | D166 转义+知识点 JSON 化；D168 B1 快照 / B2 统计 / B3 可视化 |
