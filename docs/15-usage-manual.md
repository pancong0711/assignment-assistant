# 15 — 使用说明（教师手册 · 方案 A：app 内嵌"使用说明"选项卡 + docs 同源）

> 当前状态：独立「使用说明」选项卡已上线；本文件保留方案记录与快速上手，详细图文手册仍需继续补全（B6）。

## R2 方案确认 —— 使用说明全新的独立"帮助"选项卡

- **顶部引导卡**（快速上手 3 步：`下载 start.bat → 移动到 workspace 目录 → 双击`）；
- 每项**选项卡分栏**为"常见任务"段，帮助卡内含"**跳转到该页**"链接；
- 具体路径 = 各选项卡（设置中心/题库/版式/内容/班级与标签/学习通/导入导出）内嵌简短 help 卡（带 badge "💡 在帮助页有详细说明"）；
- **总体原则**：
  - 不重复信息（每页只保留所属流程的 3 行速查提示）；
  - 详细说明集中在**帮助选项卡**（设置中心"?", 题库编辑器"❓"等多个入口均可跳转）；
  - 由引擎联调/批阅/学习通等有引擎依赖的功能交互（不需要时按钮置灰说明）；
- 教师手册 docs/15 与 app 内嵌帮助互链，只在需要时点更多；
- **文档最终统一**到"docs/15 使用说明"（教师视角，LIVE 页面顺序 + 全流程演示截图占位）。


2026-09-28 · 用户拍板 D38 方案 A：app 内嵌使用说明独立选项卡（App.vue 8 项导航）

---

# D38 选项卡扩展（2026-09-28 · 用户拍板）

- 「使用说明」独立选项卡启用（HelpView.vue）：快速上手 3 步 + 各选项卡速查 + PRINT QA/FAQ；docs/15（本文件）为长文档/教师手册的同源入口；静态可用（不依赖引擎）；
- 硬编码审计：orientation/per_page/页眉页脚 D30 范内的"硬编码"收敛点（taskpad.ts/JSON 为准，动态 aspectivity，docs/05-D30）；
- 版本兼容：引擎 bat v9/v10 (PYTHON-FIRST) 与 PWA HTML 主通道**互链完成**
  （start 脚本自动启动引擎 + PWA；教师零解耦、零 ENGINE 干预）。

---

# 2026-10-07 · 快速上手与 CLI 备份（随 D58 更新）

## 1. 一键启动

1. 从设置中心或 Pages 下载 `start.bat`（Windows）/ `start.sh`（macOS/Linux）；
2. 放到你希望作为 workspace 的资料目录，双击（macOS/Linux 用 `bash start.sh`）；
3. 脚本会自动创建 `.runtime/`、安装依赖、启动 `assist serve` 并打开
   `http://127.0.0.1:8601/`。删除 workspace 目录即整体卸载。

## 2. 常规网页流程

1. **题库编辑器**：导入/编辑 `problems.xlsx`、`copy.xlsx`、`translation.xlsx`；
2. **作业纸设计**：①版式 → ②内容 → ③预览/清单 → ④输出与交付；
   可打印浏览器版、下载整班 HTML、导出 JSON/zip；
3. **班级与标签**：导入点名册/成绩源 → 多列勾选与权重 → 重算 → 打 tag →
   整班分层预览（参考答案/水印/页码开关）；
4. **批阅**：准备学生图片目录 → 用 CLI 或后续 serve 触发 → 产出转录/评阅/报告；
5. 任意选项卡页内下滑后，右下角「↑ 顶部」可一键回到页首。

## 3. 可选依赖

- **KaTeX**：已随 PWA 打包，网页预览/打印无需安装；CLI 离线化时在设置中心
  「安装到 workspace」，并用 `assist sheet html --katex local`；
- **TinyTeX**：设置中心「TinyTeX（LaTeX 渲染，可选）」卡检测/联网安装；
  安装包不入仓库，装到 `<workspace>/.runtime/tex`；CLI 备份：
  `assist tex status` / `assist tex install`。

## 4. CLI 备份命令速查（AI agent 友好）

| 目标 | 网页入口 | CLI 备份 |
|---|---|---|
| 环境体检 | 设置中心 | `assist doctor` |
| 题库统计/导出/快照/样式写回 | 题库编辑器 | `assist kb stats/export/snapshot/write --input <json>` |
| 单份作业纸 HTML/PDF | 作业纸设计输出 | `assist sheet html --task …` / `assist sheet make --task …` |
| 按 tag 批量作业纸 | 变体编排 | `assist sheet batch --roster … --pads … --map …` |
| 成绩打 tag | 班级与标签 | `assist roster tag --roster … --score … --out …` |
| 雨课堂签到 | 班级与标签（导入源） | `assist roster rain --files … --out …` |
| 本地图片批阅 | 批阅页 | `assist grade --task … --images …` |
| TinyTeX | 设置中心 | `assist tex status/install` |

> 约定（D58）：后续 PWA 新功能必须同步提供/登记 CLI 等价命令；CLI 是 PWA
> 不可用时的稳定备份与 AI agent 接口，优先保持文本/JSON 可解析输出。

---

# 2026-10-07 · D61 网格布局速查

- 版式卡新增「每页题数 N + 行 × 列」：
  - 默认 `ceil(N/2) × 2`；N=1 特例 `1×1`；
  - 竖版按行优先（左→右、上→下），横版按列优先（上→下、左→右）；
  - `rows×cols ≥ N`，多余格留空；容量不足会提示并要求调大；
  - 「按 N 重置默认」= 回到 `ceil(N/2)×2`；「均匀方阵」= 自动选最接近方阵的因子对；
- 旧任务包无 `grid_rows/grid_cols` 时继续按旧语义渲染，不强制迁移；
- 三端同口径：PWA 预览 / `assist sheet html` / `assist sheet make|batch` PDF。
