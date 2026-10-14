# D81 任务需求单：班级发布判定缓存 + Workspace/kb 管理 + 体检项清理

> 日期：2026-10-14
> 状态：需求确认，按下面顺序逐一实现。
> 关联：`docs/31-D79...`、`docs/32-D80...`、`docs/04-data-model-and-privacy.md`（workspace/kb 契约）。

## 1. 作业“是否在本班发布过”改为按班级判断 + 本地缓存

### 1.1 目标

- 同一作业在 A 班发布过，不影响在 B 班发布；
- 只拒绝“同一作业 + 同一班级”重复发布；
- 判断优先读本地缓存，避免每次长时间打开学习通。

### 1.2 数据来源

班级作业列表：

```text
/mooc2-ans/work/list?courseid=&clazzid=&cpi=
```

页面中的作业项带：

```html
viewWork('workLibraryId','workId','classId')
```

### 1.3 缓存设计

- key：`xxt-class-works-cache-v1:<courseId>:<classId>`
- 内容：

```json
{
  "at": 179...,
  "items": [
    { "workLibraryId": "...", "workId": "...", "title": "..." }
  ]
}
```

- TTL：30 天；
- 发布成功/手动刷新后更新缓存；
- 平台查询失败时回退到本地 `work-publishes/index.json`。

### 1.4 判定规则

发布前：

1. 查目标班缓存；
2. 命中且包含该 `workLibraryId` → 拒绝；
3. 未命中/过期 → 实时拉班级作业列表；
4. 仍失败 → 用本地 index 兜底；
5. 只存在其他班级 → 允许发布。

移除 `workUsed=true` 的全局拒绝逻辑。

## 2. Workspace / 题库管理卡（设置中心）

### 2.1 背景

bootstrap 向导初始化后消失，后续缺少 workspace/kb 管理入口；体检只显示“存在”，不显示路径。

### 2.2 设计

设置中心新增「Workspace / 题库管理」卡：

- 显示：
  - 当前 workspace 完整路径；
  - kb 路径（`<workspace>/kb`）；
  - 是否默认路径；
  - 是否存在；
  - 现有 `*.xlsx` 列表与数量；
- 操作：
  - 「创建默认题库」（bootstrap 骨架）；
  - 「刷新」；
  - 「迁移旧题库到这里」：
    - 用户选择旧 kb 目录；
    - 复制所有 `*.xlsx`、`fig/`、`.history/`、`export/` 到 `<workspace>/kb/`；
    - 不覆盖同名文件（或先备份）；
  - 路径仍以 `<workspace>/kb` 为唯一运行契约。

### 2.3 接口

- `GET /xxt/workspace/info`
- `POST /xxt/workspace/bootstrap`
- `POST /xxt/kb/migrate`（PWA 目录句柄读取文件后上传，或引擎端复制 workspace 相对路径）

## 3. 体检项清理

### 3.1 uv

- 定位：可选/维护工具；缺失时用 pip 回退；start.sh/start.bat 仍继续安装 uv。
- 状态：
  - 有 uv → 绿色；
  - 无 uv → 灰色/黄色，不是红色故障。
- 修复：新增“用 pip 安装 uv”按钮，快速执行：

```text
python -m pip install --user uv
```

- start 脚本行为保持不变（继续安装 uv）。

### 3.2 TeX / xelatex

- 当前问题：
  - doctor 返回 id `xelatex`；
  - Settings 占位/卡片使用 key `tex`；
  - 导致出现两个 TeX 检查项与匹配失败。
- 统一为**一个可选检查项**：

```text
xelatex：仅用于 LaTeX 样题渲染；缺失自动降级
```

- 状态：可用绿色，缺失黄色/灰色；不作为红色故障。
- 项目 LaTeX 使用口径：
  - 主 PDF = reportlab；
  - HTML/预览/打印 = KaTeX；
  - xelatex 仅 `render_sample` 可选样题。

### 3.3 kb 检查

- 改为扫描 `<workspace>/kb/*.xlsx`；
- 详情显示完整路径、xlsx 数量；
- 不再只判断 `problems.xlsx`。

## 4. 实施顺序

1. 班级发布判定 + 缓存（engine + PWA）；
2. Workspace/kb 管理卡（engine info/bootstrap/migrate + PWA）；
3. 体检 uv 降级 + pip 修复按钮；
4. TeX 检查合并；
5. kb 检查改为全 xlsx + 路径显示。

## 5. 验收

- 同一作业可在不同班级分别发布；
- 同一作业同一班重复发布被拒绝；
- 班级作业状态读取优先走本地缓存，刷新按钮可强制实时；
- 设置中心可看到 workspace/kb 完整路径并创建/迁移整个题库；
- uv 缺失显示黄灰并可用 pip 修复；start 脚本仍装 uv；
- 只保留一个 xelatex 可选检查项；
- `check-secrets` 与测试通过。

## 6 · 实施进度（2026-10-14）

- 班级发布判定：已改为按 `courseId+classId+workLibraryId` 判断；
  - `list_class_works` 解析班级作业列表 `viewWork(libraryId, workId, classId)`；
  - 同班重复发布硬拒绝；跨班允许；
  - `work-list` 返回的 `publishedClasses` 由平台班级列表实时填充；
  - 本地 `work-publishes/index.json` 继续作兜底。
- Workspace/kb 管理：engine 新增
  - `GET /workspace/info`；
  - `POST /workspace/bootstrap`；
  - `POST /kb/migrate`（复制全部 xlsx + fig/.history/export）；
  - PWA 设置中心新增「Workspace / 题库管理」卡。
- 体检项：
  - uv 缺失改为黄色（可选·依赖安装加速），修复按钮用 pip 安装 uv；
  - `kb_init` 修复命令改为 bootstrap 骨架；
  - TeX 占位 key 与 doctor 对齐为 `xelatex`，只保留一个可选检查；
  - kb 检查改为扫描全部 `*.xlsx`，详情显示完整路径与数量。
- 测试：`engine/tests` 145 passed；`npm run build` 通过。
