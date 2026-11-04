# D163 需求单：课堂资料页可用性（可新建/可上传）+ 翻译题题号不换行

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/102-D155`（特征名管理）、`docs/90-D143`（翻译题号）、`docs/12`

## 0. 教师反馈

1. **课堂资料选项卡基本是空的** —— 请确认 PWA 代码；
2. **translation 题号（如 `2.`）后另起一行**才开始"请翻译以下内容"，
   而其它题型题号与题目在同一行。

## 1. 课堂资料页为空：三个原因（已核实）

### 1.1 没有「新建特征名」入口（主因）

`list_chaps()` 只列**已有 `_source/` 子目录**的目录：

```python
return sorted(p.name for p in root.iterdir()
              if p.is_dir() and (p / SOURCE).is_dir())
```

而 PWA 从来没有"新建特征名"的按钮 → 空 workspace 下页面只有一句"还没有任何资料"，
教师**无从下手**（只能手工去文件系统建目录）。

**修复**：
- 新增 `POST /materials/create` + `materials.ensure_chap()`；
- 资料页顶部加「＋ 新建资料文件夹」（输入特征名如 `26C1`）；
- 空态改为**三步引导**（新建 → 上传 → 抽取/建议/确认）。

### 1.2 上传按钮只在"选中章节后"才出现

上传控件在右侧「原件」区，条件是 `v-if="cur"`（必须先在左侧点选一个章节）。
没选中时右侧完全不渲染 → 看起来"没有上传键"。

**缓解**：空态引导里明确写"选中它后，在右侧「原件」区点上传"。

### 1.3 手建目录但缺 `_source/` 不会被列出

这是 `list_chaps()` 的既有口径（只认有 `_source/` 的）。
用「新建资料文件夹」走 `ensure_chap()` 会自动建 `_source/` 与 `_extract/`。

## 2. translation 题号换行（已核实并修复）

`read_translation()` 生成的 content 以**换行开头**：

```python
tmp = f"请翻译以下内容：\n{saying} (by {author}"
```

渲染时「2.」后面接 `\n` → 正文另起一行。对比 `SUMMARY_CONTENT` 是**单行**。

**修复**（引擎与 PWA **同口径**）：
```python
tmp = f"请翻译以下内容：{saying} (by {author}"
```
```ts
let content = `请翻译以下内容：${name} (by ${author}`
```

「并回答：…」部分仍在第二行（保留原结构）。

> ⚠️ 注意：已导出的作业纸是旧格式；新导出的才会同行。
> 若需要"旧作业纸也重排"，重新生成即可（内容未变，只是换行位置）。

## 3. 验收

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 空 workspace 能新建特征名目录 | ✅ | `test_ensure_chap_creates_and_lists` |
| 2 | 新建后出现在列表里（页面有内容） | ✅ | 同上 |
| 3 | 非法特征名被拒 | ✅ | `test_illegal_feature_name_rejected` |
| 4 | 翻译题 content 不以换行开头 | ✅ | `test_translation_content_does_not_start_with_newline` |
| 5 | 题号与"请翻译以下内容"同行 | ✅ | 同上（断言首行前缀） |
| 6 | "并回答"仍在第二行 | ✅ | `test_translation_content_still_has_second_line` |
| 7 | pytest / build / selfcheck / 脱敏 | ✅ | **1284 passed** · 0 error · **35/35** |

## 4. 未做

- 若需要"旧作业纸重排题号"，重新生成即可（未加批量重排命令）；
- 「课堂资料 → 从 Atopia 复制」仍属 D150 规划。
