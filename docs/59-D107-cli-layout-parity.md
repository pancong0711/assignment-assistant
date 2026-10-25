# D107 任务需求单：CLI 排版能力对等（让 AI 全流程可用）

> 日期：2026-10-25
> 状态：**实施中**
> 关联：`docs/56-D103`（预排版 autoLayout）、`docs/57-D105`、`docs/58-D106`

## 1. 问题：核心能力只有 PWA 有

| 功能 | PWA | CLI |
|---|---|---|
| AI 作答 / 答案版本管理 | ✅ | ✅ |
| **生成 `layout_result`（预排版）** | ✅ 浏览器测量 | ❌ **无法产生** |
| 作业纸 HTML/PDF | ✅ | ✅（但依赖 PWA 先产出 layout_result） |

后果：**纯 CLI / AI 工作流无法出完整作业纸**，必须人工先打开 PWA。

## 2. 方案：把测量也做成 CLI 能力（复用已有 Playwright）

引擎已依赖 Playwright（`grading/report.py:html_to_png` 在用），因此：

```bash
assist sheet layout --task <task.json>   # 新增：测量并写入 layout_result
```

### 算法单一实现（避免双实现漂移）

- 把 `app/src/lib/autoLayout.ts` **打包成 ES module**（esbuild，构建期产物随引擎分发）；
- CLI 用 Playwright 打开空白页 → `page.evaluate()` 导入该 bundle →
  在页面内用真实 DOM 测量（含 KaTeX）→ 调用 `autoLayout()` → 回写 `layout_result`；
- **PWA 与 CLI 跑同一份 JS**，结果逐字一致。

### 为什么不等同重写 Python 版

Python 无法精确测量浏览器排版（字体、断行、KaTeX），重写必然与 PWA 漂移，
违背 R7「PWA 与 CLI 一致」。

## 3. 任务分解

| # | 任务 | 文件 |
|---|---|---|
| T1 | 打包 `autoLayout.ts` + `measureLayout.ts` 为可被页面导入的 bundle | `engine/tools/build-layout-bundle.mjs`（新增）、`pyproject.toml` 打包资源 |
| T2 | `assist sheet layout`：起 headless 页 → 测量 → 写回 taskpad json | `engine/src/assist/paper/layout_measure.py`（新增）、`cli.py` |
| T3 | `sheet html` / `sheet make` 在缺 `layout_result` 且带答案时**自动触发测量**（可 `--no-measure` 关闭） | `paper/htmlfile.py`、`paper/task.py` |
| T4 | CI：bundle 产物存在性校验；测量结果与 PWA 一致性冒烟 | `.github/workflows`、`engine/tests/` |

## 4. 回滚

`assist sheet layout` 为纯新增；自动测量可用 `--no-measure` 关闭，
退回「读已有 layout_result，没有则旧网格」。

---

## 5. 实施记录（待填）

## 5. 实施记录（2026-10-25）

### 5.1 完成项

| # | 内容 | 文件 |
|---|---|---|
| T1 | 前端算法打包脚本（esbuild → `layout_bundle.mjs`，322KB） | `engine/tools/build-layout-bundle.mjs`（新增） |
| T2 | `assist sheet layout --task`：Playwright 起空白页 → Blob 注入 bundle → 真实测量 → 写回 `layout_result` | `paper/layout_measure.py`（新增）、`cli.py` |
| T3 | `sheet html` 缺 `layout_result` 且带答案时**自动测量**并原地写回；`--no-measure` 可关 | `paper/htmlfile.py`、`cli.py` |
| T4 | 测试：命令存在、不可用降级、已有结果复用、bundle 存在与导出符号 | `tests/test_d107_layout_measure.py` |

### 5.2 关键实现细节

- **`file://` 动态 import 受限** → 用 `Blob` + `URL.createObjectURL` 注入 bundle 源码，
  页面内 `import(blobUrl)`；
- **浏览器路径可配**：`ASSIST_CHROMIUM_PATH`（CI 无 `playwright install` 时用）；
- **KaTeX 未就绪降级**：CDN 不可达时按源码测高并记 warning，不阻断流程；
- **失败不阻断出图**：测量异常 → warning + 回退旧网格。

### 5.3 端到端验证（纯 CLI，零 PWA）

```
assist sheet layout --task t.json   → ok, pages=1, 写入 layout_result
assist sheet html   --task t.json   → data-cell= 存在 / q-cont 存在 / display:grid 存在
```

自动触发验证：缺 `layout_result` → 出图时自动测量并写回；`--no-measure` → 不写回、回退旧网格。

### 5.4 验证

| 项 | 结果 |
|---|---|
| engine pytest（新增 D107 6 例） | **565 passed** |
| 全量耗时 | 30s（修正：测试默认加 `--no-measure`，避免每个用例都起浏览器） |
