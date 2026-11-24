# D223 修复：题库编辑器选好图片后无法更换

> 日期：2026-11-23
> 状态：**已完成（2026-11-23）**
> 关联：`docs/164-D221`（kb 路径自动识别）
>
> 隐私：无学生数据。

---

## 0. 现场

题库编辑器里，`img_path` 已经选过图片后，再点 📷 选另一张图，
预览**仍显示旧图**，看起来“不能更换图片”。

## 1. 根因

`KbEditorView.vue :: uploadFig()`：

```ts
settings.persistFigAsset(file.name, dataUrl)   // 新图确实存进去了
if (!row.img_path) row.img_path = `fig/${file.name}`   // ← 只在“空路径”时赋值
```

- 新图以**新文件名**存进 `figAssets`；
- 但 `row.img_path` 仍是旧文件名（因为非空）→ `figThumb()` 查到的还是旧图。

即：**新图存了，但单元格没改指向**。

### 附带问题（同一处代码）

写回图片时固定拼 `kb/fig/<name>`：

```ts
await writeFileInDir(dir, `kb/fig/${file.name}`, blob)
```

若连接的是 `kb` 目录本身（D221 已允许），就会写成 `kb/kb/fig/…` —— 与 D221 同类问题。

## 2. 修复

### R1. 选图即替换该行 `img_path`

```ts
const prev = String(row.img_path || '')
row.img_path = `fig/${file.name}`      // 无条件更新
```

- 换图后 `figThumb()` 立即指向新文件 → 预览更新；
- 状态栏提示：`题图 X 已入库（img_path=fig/X；原 fig/Y 已替换）`；
- 同名文件（重新上传同名图）由 `persistFigAsset()` 覆盖，预览同样刷新。

### R2. fig 写回也用“kb 前缀自动识别”

`kbLayout.ts` 新增 `resolveKbDirPrefix(dirName, rootEntries)`：

| 已连接目录 | 前缀 | 写入路径 |
|---|---|---|
| `kb` 目录本身 | `''` | `fig/<name>` |
| workspace 根 | `'kb'` | `kb/fig/<name>` |

索引写回（D221）与图片写回（D223）现在共用同一判定。

## 3. 验收

| # | 场景 | 期望 |
|---|---|---|
| 1 | 行内已有 `img_path`，再选新图 | `img_path` 更新为新文件，预览刷新 |
| 2 | 重新上传**同名**图片 | 覆盖旧图，预览刷新 |
| 3 | 连接 workspace 根 | 写到 `kb/fig/<name>` |
| 4 | 连接 kb 目录本身 | 写到 `fig/<name>`（不再 `kb/kb/fig`） |
| 5 | 状态栏 | 说明新路径，并在替换时提示原路径 |
| 6 | 回归 | build + selfcheck 通过 |

## 4. 测试

`app/tests/selfcheck-d223-kb-fig-replace.mjs`：

- 行为：`resolveKbDirPrefix` 两种目录形态；
- 契约：`uploadFig` 不再有 `if (!row.img_path)` 守卫、无条件赋值、
  写回路径按前缀拼装；`persistFigAsset` 覆盖同名。

## 5. 说明（旧图残留）

替换后旧图片文件不会自动删除（仍在 `kb/fig/` 与本浏览器 `figAssets` 里）。
如需要清理，可手动删除 `kb/fig/` 中不再引用的图片；后续如需“一键清理未引用图片”，
可另开需求单。
