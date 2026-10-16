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
4. **AI 辅助批阅**：顶部「AI 辅助批阅」选项卡 → ① LLM 设置 / ② 班级↔作业纸目录映射 / ③ 开始 AI 批阅 → ④ 逐生审核 → ⑤ 一键生成报告 → ⑥ 一键上传（含打分）；
   （离线：页内「高级 / 离线（CLI 指引）」折叠块，或 CLI `assist grade …`）；
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


# 2026-10-08 晚 · 引擎启动口径更新（D64 §26 start.bat-first，随 §26.2 决议）

## 一键启动（修订）

- 首推：**双击 start.bat**（Windows）/ `bash start.sh`——反复双击不重复下载，
  二次启动 3–5 秒（缓存详 docs/16 §26.3）；端口若跳到 8601..8649 以地址栏为准；
- PWA 已装引擎：**不用回终端**——设置中心体检卡旁「🔄 重启引擎」
  （D67：Windows 下请用 start.bat 启动，由它托管 supervisor loop，同端口自动重启；
  若手动从终端跑 `assist serve`，PWA 会明确提示关闭终端后双击 start.bat，不再误报成功）；
- Pages 使用前提：本机引擎已由上二者任一方式起着；Chrome 的
  Private Network Access 拦截已由引擎预检头部豁免（docs/16 §26.1 #4）；
- 安装类操作（如 playwright 联网安装、TinyTeX）建议在 start.bat 自开的
  本地同源页做——进度流（SSE）不经任何跨源关卡。


# 2026-10-09 · D65 浏览器获取/安装速查

- 安装 Playwright 时，**本机浏览器优先**：
  1. `XXT_CHROME` 指定路径；
  2. 本机 Edge；
  3. 本机 Chrome；
  4. 本机 Chromium；
  5. 以上都没有，才下载 Playwright 完整版 chromium。
- 本机浏览器可用时：**不下载 chromium-headless-shell，也不装 195MB 级完整内核**。
- 必须下载时：默认只准备**完整版 chromium**（`--no-shell`），不把 headless shell 当必需项。
- 下载源按实测镜像降级：`cdn.npmmirror.com` → `playwright.azureedge.net` → `registry.npmmirror.com` → 官方 dry-run URL。
- 全部镜像失败时的备用方案：设置中心 → Playwright 卡 → 「浏览器内核直下」：
  1. 点「获取直下清单」；
  2. 复制任意一个可用链接，浏览器下载 zip；
  3. 把 zip 放入页面显示的「收包目录」；
  4. 回到该卡点「从收包目录安装 / 复查内核」——由 PWA 触发安装，不需要手工解压或建标记文件。
- 旧版 `engine/` 目录不会再让 start.bat 跳过更新；只有显式 `ASSIST_ENGINE_LOCAL=1` 才复用工作区/仓库本地引擎。
- start.bat 采用**快速缓存启动**：本地 `_engine` 可用时直接启动，不重复下载。
- 版本检测/引擎更新的主入口 = PWA 设置中心「检测更新 / 更新引擎」（D65-P4，已落地）：
  1. 点「检测更新」→ 只拉取很小的 `engine-version.json`，对比本地 `_engine\engine-version.json`；
  2. 相同 → 显示“已是最新”，不下载；
  3. 不同 → 出现「更新引擎」按钮；点击后才下载 `engine-main.zip`、重装依赖；
  4. 更新成功后 PWA 自动调用 `/restart`；start.bat/start.sh 在旧引擎停止后执行安装并启动新引擎；
  5. 若更新/安装失败，终端会显示 `[FAIL]`，请查看 `start.log`；已安装版本会尽量回滚。
- CLI 等价：`assist engine version` / `assist engine update --check` / `assist engine update`。
- start.bat 保持快速缓存启动；过渡版启动时版本对比可按 P4 口径后续简化。



# 2026-10-15 · AI 辅助批阅 / 人工批阅 / 上传（D84–D88）

## 1. 先配 LLM（一次即可）

顶部导航「**AI 辅助批阅**」选项卡 → **① LLM 设置**：
（D88 起：原「学习通」页内折叠面板已迁出，独立成选项卡 `#/grading`；页内「高级 / 离线（CLI 指引）」折叠块保留选作业纸 JSON + 选本地图片 → CLI 命令，离线可用。）

1. 填 **provider 名称 / base_url / api_key**（如阿里云百炼兼容模式
   `https://dashscope.aliyuncs.com/compatible-mode/v1`）→ 点「保存 provider」；
   - key **只在本地保存**（`workspace/settings.local.secrets.json`，权限 0600），
     页面只显示 `sk-****1234`；**日志与操作记录绝不记 key**；
   - 若要评阅走 batch，勾选「支持 batch」。
2. **转写段** 勾选 provider + 填**多模态模型名**；**评阅段** 勾选 provider + 填**文本模型名**；
   模型名「填写即记录」，下次可从下拉直接选。两段可用不同 provider。
3. 点各段「保存」。

## 2. 建关联：学习通班级 ↔ 作业纸目录

选项卡 **② 班级 ↔ 作业纸目录**：为每个班级填 workspace 目录（如 `classes/化工25`）→「保存映射」。
- 该映射存 `settings.local.json → xxt.class_map`，供 CLI 与 PWA 共用；
- 目录里应有**带 tag 名单**（`classes/<dir>/roster/*.xlsx`，含 `tag` 列）与
  **作业包**（`tasks/<id>.taskpad.json`，每个 tag 一份）；
- 提示：一个班的多份成绩单是**多源加权**的，导入新成绩单只会**新增源**，不会覆盖旧源。

## 3. 跑一次 AI 批阅（选项卡六区：①设置 ②映射 ③任务 ④逐生审核 ⑤报告 ⑥上传）

前置：该作业已用「⬇ 下载」拉过作答/批语（批阅图片）。

选项卡 **③ 任务**（开始 AI 批阅）：选作业 → 选作业包（taskpad）→ 选模式 → 点「▶ 开始 AI 批阅」：

- **优化模式（默认）**：把该生 tag 对应的**题目/参考答案**与作答转录一起给 LLM，省 token；
- **brute-force 模式**：把**作业纸原件/题目**与作答一起给 LLM，先做**题号/姓名一致性核对**，
  缺答案时让 LLM 自己先作答再比对（最费 token，但简单直接）；
- 结果自动写入**本地批阅草稿**（分数 + 批语 + 报告图片），**不会直接提交**到平台。

## 4. 逐生审核与修改

「批阅图片」→ 该作业行「逐生预览」→ 右栏 **人工批阅**：

- 分数默认 **100**、批语默认空（AI 的批语/分数会预填，可直接改）；
- 输入即存本地 + 「💾 保存到本地」；支持 **LaTeX**（`$...$`，上传时会渲染成图片）；
- 「📄 一键生成批阅报告」会把草稿重新出成**报告图**（A4 宽、长图；AI/人工标注不同）；
  选项卡 ⑤「报告」亦可对全批复用此入口（AI 报告 / 人工报告，版式相同、仅标注不同）。

## 5. 上传（回传平台）

- 单人：**演练上传**（只填不提交，可看截图/读回）→ **上传并提交**；
- 全部：选项卡 ⑥ 上传（或逐生预览里）的 **「⬆⬆ 上传全部批阅（含打分）」** →
  只上传**已批阅**的学生；未批阅的会提示「尚余 N 名学生未完成批阅」；
  平台已「已批阅」的默认跳过，用**「强制覆盖上传全部」**才覆盖。

**覆盖语义**：再次上传是**整段替换**批语 + 覆盖分数（不是追加）。

## 6. batch（可选，省钱）

- 选项卡 ① LLM 设置里把「评阅段」勾上 batch（provider 需支持）；
- 或 CLI：`assist llm batch --task tasks/<id>.taskpad.json` → 生成 JSONL 与
  `BATCH-README.txt`（含上传/创建/轮询/下载命令）；
- 真正提交 `--submit`；失败会打印 **HTTP 状态 + 响应原文 + 批次 id**，把这段发回即可排查。

## 7. 常见问题

| 现象 | 处理 |
|---|---|
| 提示「写操作白名单拒绝」 | 到「发布-学习通」勾选该班级；注意 workspace 是否一致 |
| 上传报「已批阅」 | 属幂等保护；确认后可用「强制覆盖上传」 |
| AI 无结果 | 先确认已「⬇ 下载」；再确认两段 provider/模型已保存、key 可用 |
| 简答题加不上（新建作业） | 已支持「更多」兜底；若仍失败把报错（含步骤名+截图路径）发回 |

### 密钥安全须知（D87）

- **本机使用最安全**：默认引擎只监听 `127.0.0.1`，key 不出本机。
- **不要用 `--lan` 在不可信网络操作**：LAN 模式是明文 HTTP（仅一次性 token 鉴权），同网段可抓包，
  此时不要输入/使用 API key。
- **workspace 放云盘时**：请在同步规则里**排除 `settings.local.secrets.json`**，否则 key 会随之上云。
- **不要在公共/共享电脑填 key**：输入瞬间浏览器 DevTools→Network 可见。
- 提交代码前可手跑 `bash tools/check-secrets.sh`（CI 也会跑）：拦已知厂商前缀 + 异形高熵 key + 真实姓名。

---

# 2026-10-15 · 水印样式库 / 素材目录（D87）

## 1. 素材目录（workspace 优先）

教师手工维护的静态素材统一放 **`<workspace>/assets/`**：

```
<workspace>/assets/
  watermark/                 # 水印图片 + styles/<样式名>.json
  fonts/                     # 可选：用户字体覆盖（simsun.ttc / simkai.ttf / wqy-*.ttc）
  report/                    # 预留：报告模板/封面/落款
```

- 解析顺序：`--assets-dir` 显式 > `<ws>/assets`（存在 `watermark/` 或 `fonts/` 时）> 引擎内置 `engine/assets`；
  字体注册优先用 `<ws>/assets/fonts/` 覆盖内置字体。
- CLI `sheet make|html|batch` 均支持 `--assets-dir <dir>` 显式指定。
- 题图仍在 `kb/fig/`（随题库走）；运行期上传（通知/作业附件、临时文件）不放 `assets/`。

## 2. 水印样式库（设计页「水印编辑器」）

**「版式」页 → ① 版式与头部 → 水印编辑器** 顶部新增「D87 命名样式库」区：

1. **作业纸引用样式**：下拉选一个命名样式（`style_ref`），随作业纸（类型/tag）保存；
   「（不引用，用默认样式）」= 走默认样式 → 内置三槽。
2. **编辑/管理**：下方图层编辑（上传图片 / 九宫格摆位 / 大小 / 透明度 / 排序）后：
   - **另存为样式**：把当前图层存成命名样式，并让本作业纸引用它；
   - **复制到本作业纸**：把所选样式的图层拷进作业纸内联 items（脱离 `style_ref`）；
   - **重命名 / 设为默认 / 删除**：样式管理（默认样式至多一个）。
3. **图片上传**：引擎在线时经 `POST /watermark/upload` 落到 `<ws>/assets/watermark/`，
   图层 `image` 写相对素材目录的 `watermark/<文件名>`；**离线**时 dataURL 仅本浏览器预览有效
   （界面明确提示，需把图片手工放到 `<ws>/assets/watermark/` 引擎才会读）。

**生效优先级**（引擎与 PWA 同口径）：

```
作业纸 watermark.items（内联图层，最高）
  > watermark.style_ref（引用命名样式，随类型/tag 走）
    > 默认样式（default=true / _default）
      > 引擎内置三槽 + 页码文字
```

## 3. CLI（只读/批量脚本）

```bash
assist watermark styles -w <ws>                      # 列出样式（JSON）+ 素材文件清单
assist watermark save --name 期末版 --file s.json     # 新建/覆盖样式（可 --set-default）
assist watermark rename --old A --new B
assist watermark set-default --name 期末版
assist watermark delete --name A
assist sheet make --task t.taskpad.json --assets-dir <dir>   # 显式素材目录
```

## 4. 常见问题

| 现象 | 处理 |
|---|---|
| 出 PDF/HTML 水印不显示自定义图 | 确认图片在 `<ws>/assets/watermark/`（或 `--assets-dir` 指向处）；旧路径 `assets/watermark/x` 引擎已兼容 |
| 作业纸引用的样式不存在 | 引擎回落默认样式并告警；到「水印编辑器」确认样式已保存/名字一致 |
| 离线上传的图刷新后消失 | 属预期（仅 dataURL 本地预览）；引擎在线重传即落盘 |
