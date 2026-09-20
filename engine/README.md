# assist-engine

assignment-assistant 的 Python 引擎：作业纸设计 + AI 批阅（CLI 超集，05-D1）。

## 安装（把引擎环境收纳进 workspace，见 docs/05-D14）

```bash
# 任意平台先确认有 uv（推荐）：curl -LsSf https://astral.sh/uv/install.sh | sh
cd <仓库>/engine
assist bootstrap --workspace <你的workspace路径>   # 建 kb/classes/exports + .runtime/venv
# 未安装 assist 命令前的第一步：
uv venv --python 3.13 <workspace>/.runtime/venv
UV_PROJECT_ENVIRONMENT=<workspace>/.runtime/venv uv pip install -e .
```

数据（题库/名单/作业/批阅）全部存于 workspace；卸载只需删除 workspace 目录。
引擎在 workspace 里的缓存（uv cache、Playwright 内核）同样收纳在 `.runtime/`。

## 命令速览

```bash
assist doctor                          # 环境体检（绿黄红）
assist kb stats                        # 题库统计（kb/*.xlsx 为 source of truth）
assist kb export                       # 导出 JSON 副本（kb/export/）
assist kb snapshot                     # 快照到 kb/.history/<ts>/
assist sheet make --task <任务包.json> --roster <名单.xlsx>   # 每生一份 PDF（横/竖版+水印）
assist sheet demo                      # 合成数据 demo
assist grade --task <任务包.json> --images <目录>   # 阶段3：转录→评阅→报告
assist serve                           # 阶段4：Companion 本地引擎
```

任务包 schema 见 docs/04 §1；字体策略见 docs/05-D15。

## 约定

- 数据红线：任何真实题库/学生数据/密钥不进 workspace 之外的版本库（tools/check-secrets.sh 兜底）。
- 迁移来源注释：迁自 _legacy/2603paperDesign 或 2601playwright 的模块在文件头注明。
