# D87 任务需求单：素材目录（workspace 优先）+ 水印样式库（命名/默认/与作业纸类型关联）

> 日期：2026-10-15
> 状态：已拍板，按 §6 顺序执行。
> 关联：`docs/39-D86-ai-grading-tab.md`（报告用 KaTeX/assets 解析同源）、
> `docs/04-data-model-and-privacy.md`（workspace 布局契约）、engine `paper/watermark.py`、PWA `SheetLayoutView.vue`。
> 触发：用户实测"水印编辑器缩略图路径像有误；希望样式可命名/可增删改/有默认；并可与作业纸类型关联"。

## 1. 现状与根因（2026-10-15 查证）

1. **PWA 加的图层对 PDF 完全不生效**：编辑器把图层写进**作业纸 JSON**（`pad.watermark.items`），
   而引擎出 PDF 只读 `settings.local.json → watermark`（items/三槽）+ `engine/assets/watermark/logo-*.png`；
   PWA 从不写 settings → 引擎看不到自定义图层。
2. **相对路径口径不一致**：PWA 写 `assets/watermark/<文件名>`，引擎把相对路径拼在 `assets_dir`
   （默认 `engine/assets`）下 → 实际找 `engine/assets/assets/watermark/...` → 文件不存在、图层被跳过（日志 warning）。
3. **缩略图只是 localStorage 的 dataURL**（按 basename 存，`settings.wmAssets`）：刷新/清站数据/超配额（静默 catch）
   即消失，但界面仍显示那串"路径提示"（该文件从未写盘）→ 观感"路径有误"。
4. **样式不可命名/无默认/不能与类型关联**：`watermark.style` 只有 `default|none` 两个死值。
5. workspace 里已存在 `<ws>/assets/watermark/`，但**引擎不读**；用户自带字体也没接（`register_font(workspace=None)`）。

## 2. 素材目录（已拍板：保留 `assets/`，引擎 workspace 优先）

```
<workspace>/assets/
  watermark/            # 水印图片（教师手工放/由 PWA 经引擎上传落盘）
    styles/<样式名>.json
  fonts/                # 可选：用户字体覆盖（simsun.ttc / simkai.ttf / wqy-*.ttc）
  report/               # 预留：报告模板/封面/落款 logo
```

- 语义：**教师手工维护的静态素材**；运行期上传（通知/作业附件、临时文件）**不放这里**
  （仍在 `<xxt_home>/notice-uploads`、`<ws>/tmp/`）；
- 题图继续留 `kb/fig/`（随题库走），不挪进 `assets/`；
- **解析顺序**：`--assets-dir` 显式 > `<ws>/assets`（存在 `watermark/` 或 `fonts/` 时）> `engine/assets`；
  CLI `sheet make|html|batch` 增加 `--assets-dir`；字体注册改为 `register_font(..., workspace=ws)`，优先用
  `<ws>/assets/fonts/` 覆盖。

## 3. 水印样式库（命名 / 增删改 / 默认 / 与作业纸类型关联）

### 3.1 样式文件 schema（`<ws>/assets/watermark/styles/<样式名>.json`）

```json
{
  "name": "期末版",
  "enabled": true,
  "pageText": true,
  "default": false,
  "items": [
    { "image": "watermark/logo-ddl.png", "pos": "rb", "ratio": 0.25, "alpha": 0.5 }
  ],
  "updatedAt": "2026-10-15 20:00:00"
}
```

- `items[].image`：**相对 `assets_dir`** 写 `watermark/<文件名>`（修正当前双 `assets/` 口径）；
  引擎解析时**兼容旧值**（先按 `assets_dir/image` 找，找不到再试去掉前缀 `assets/`）；
- **默认样式**：至多一个样式 `"default": true`；无则按名字 `_default`；再无 → 引擎内置三槽默认；
- 增删改：按名字创建/覆盖/重命名/删除；「设为默认」单选。

### 3.2 与作业纸类型的关联（优先级）

解析优先级（engine 与 PWA HTML 同口径）：

```
作业纸 JSON watermark.items（包内显式图层，最高）
  > 作业纸 JSON watermark.style_ref（引用命名样式，随 tag/类型走）
    > 默认样式（default=true / _default）
      > 引擎内置三槽（university/text/boat）+ 页码文字
```

- `style_ref` 随 taskpad 保存（即随"作业纸类型/tag"走）→ 实现"每种类型作业纸单独设计水印样式"；
- 不设 `style_ref` 的作业纸 → 用默认样式 → 实现"默认样式关联到全部"。

### 3.3 PWA 编辑器（SheetLayoutView 水印编辑器改造）

- 顶部加**样式下拉**：选择当前样式 + 「新建（另存为样式）/重命名/复制/删除/设为默认」；
- 图层编辑沿用现有能力（九宫格摆位/比例/透明度/排序/上传图片）；
- 图片上传：**引擎在线** → `POST /watermark/upload` 落 `<ws>/assets/watermark/`，返回相对路径；
  **离线** → 存 localStorage（`settings.wmAssets`）仅本浏览器预览有效，并明确提示；
- 样式列表：`GET /watermark/styles`（引擎）→ 缓存到 localStorage 供离线预览；编辑写回引擎（在线时）；
- 作业纸面板增加"水印样式引用（style_ref）"选择（下拉 = 本地样式列表；`（不引用，用默认样式）` 选项）。

## 4. 端点与 CLI

| 类型 | 名称 | 说明 |
|---|---|---|
| serve | `GET /watermark/styles` | 列出样式（含 default 标记）与素材文件清单 |
| serve | `POST /watermark/style` | 保存/重命名/删除/设为默认（`action` 字段） |
| serve | `POST /watermark/upload` | 图片 base64 → 落 `<ws>/assets/watermark/<文件名>` |
| CLI | `assist watermark styles` | 只读列出样式（JSON） |
| CLI | `assist watermark save --name X --file <json>` / `--set-default` / `--delete` | 样式管理 |
| CLI | `sheet make|html|batch --assets-dir <dir>` | 显式素材目录 |

## 5. 引擎消费（PDF/HTML 同口径）

- `make_pdf(assets_dir=...)`：按 §2 解析；`watermark_gen` 的 `overrides` 支持 `items` **和** `style_ref`；
- 作业纸任务包 → `layout.make_pdf` 时把 `pad.watermark`（items/style_ref）传进 `overrides`
  （当前只传 `user_cfg["watermark"]`，改为"pad 优先，user_cfg 兜底"）；
- HTML 通道（`assignment.html.j2` + PWA `sheetHtml.ts`）同样按 §3.2 优先级解析（PWA 用样式缓存）。

## 6. 分期实施（进度表）

| # | 阶段 | 交付物 | 状态 |
|---|---|---|---|
| §1 | 素材目录解析 + `--assets-dir` + workspace 字体 | `paper/assets.py`(resolve) + CLI 选项 + 单测 | ⏳ |
| §2 | 样式库读写 + 默认 + `style_ref` 解析（含旧 `assets/` 路径兼容） | `paper/watermark_styles.py` + `watermark.py`/`layout.py` 接入 + 单测 | ⏳ |
| §3 | CLI `assist watermark …` | 命令 + 单测 | ⏳ |
| §4 | serve 端点（styles/style/upload） | `serve.py` + 冒烟 | ⏳ |
| §5 | PWA 编辑器（样式下拉 + CRUD + 默认 + style_ref + 上传落盘） | `SheetLayoutView.vue` + `settings.ts` + `engineClient.ts` | ⏳ |
| §6 | 真机验证（含自定义图层 PDF 生效）+ 文档（docs/04/13/15） | 验证记录 + 文档 | ⏳ |

## 7. 验收

- PWA 上传的水印图片落到 `<ws>/assets/watermark/`，PDF 中**真实出现**该图层（不再被跳过）；
- 命名样式可新建/重命名/复制/删除/设为默认；新作业纸默认引用默认样式；
- 同一份作业纸可 `style_ref` 指向特定样式（与 tag/类型绑定），不同作业纸出不同水印；
- 旧数据（`assets/watermark/...` 路径、无 style_ref）行为兼容；
- 引擎 pytest / PWA build+selfcheck / CI 全绿。
