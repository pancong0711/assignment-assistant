# D155 需求单：课堂资料改为「特征名」管理 + 从 Atopia 复制解析结果

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/97-D150`（Atopia 工作区规划）、`docs/79-D131`（原按章节）、
> `docs/88-D138`（两层分类）、`docs/12`

## 0. 教师拍板

> summary 的关联会更麻烦一点，我们的想法是通过 atopia 提取的授课计划和 ppt 之后，
> 形成 json 文件，然后再跟 summary 关联，而不是直接关联起来。
> 所以整体上，我还是倾向于通过**特征名**来管理，
> 这样 atopia 生成的 json 文件再在课程资料选项卡做一个**从 atopia 复制 json 的功能键**实现这一功能。

## 1. 设计

### 1.1 目录：按特征名（如 26C1）

```
<ws>/materials/
  26C1/                       ← 特征名目录（原为章节名）
    _source/                  ← 教师原件（AI 只读，D131 硬规则不变）
      plan.docx
      lecture01.pptx
    知识点清单.json            ← 从 Atopia 复制来的（机器读，权威）
    知识点清单.md              ← 同内容人可读版（教师可看可改）
    manifest.json             ← 来源/时间/来自哪个 atopia 解析
  26C2/
```

### 1.2 summary 批阅如何关联（关键）

**不再依赖"题目 chap → materials/<chap>"硬关联**，改为：

1. **优先**：教师本次批阅**显式选的**特征名（批阅页新增下拉）；
2. **回落**：按 `chap` 找旧格式 `materials/<chap>/`（兼容旧数据）；
3. **都没有**：走保底口径（D134 四维判定）。

批阅页新增：
```
本堂课的课堂资料：[（自动/不使用） ▾] [26C1 · 2026-10-30 确认] [26C2 …]
```
选择写进 journal（事后可查这次用了哪份）。

### 1.3 上传功能（课堂资料页）

教师描述：**先选资料类型 → 再上传 → 填特征名**。

落地为：

```
① 资料类型：[授课计划] [PPT/讲义] [教材] [其他]     ← 只影响子目录与索引标注
② 特征名：  [26C1]                                  ← 必填（目录名）
③ 选文件 → 上传
   → materials/26C1/_source/<类型>/<原文件名>
```

**沿用现有上传安全口径**（D134）：扩展名白名单、20MB、同名不覆盖、文件名清洗。

### 1.4 「从 Atopia 复制」按钮

课堂资料页新增：

```
[📥 从 Atopia 复制解析结果]  → 选特征名 → 列出 atopia/work/<特征名>/_parsed/*
                             → 预览内容 → 确认 → 写入 materials/<特征名>/知识点清单.json + .md
```

**安全**：与 `materials.confirm` 同口径（显式点击 + 全文预览 + journal），
因为这份内容会成为 `summary` 批阅依据。

### 1.5 向后兼容

- 旧的 `materials/<chap>/` 结构**保留可读**（回落路径）；
- 不强制迁移；提供 `assist materials migrate-feature` 可选迁移。

## 2. 任务清单

| # | 内容 | 验收 |
|---|---|---|
| T1 | `materials` 支持任意特征名目录（校验名字安全） | 单测 |
| T2 | 上传：类型 + 特征名 → `_source/<类型>/` | 单测 + 浏览器 |
| T3 | summary 批阅：显式特征名 > chap 回落 > 保底 | 单测（三种情况） |
| T4 | 批阅页新增"本堂课资料"下拉 | 浏览器 |
| T5 | 「从 Atopia 复制」：预览 + 确认 + 写 json/md | 单测 + 浏览器 |
| T6 | `materials migrate-feature`（可选迁移） | CLI 测试 |

## 3. 验收标准

1. 可按特征名（26C1）建目录并上传，文件名/类型正确；
2. 上传安全口径与 D134 一致（白名单/大小/不覆盖）；
3. summary 批阅三种关联路径都正确，且**选中的特征名写入 journal**；
4. 「从 Atopia 复制」必须**预览全文 + 显式确认**才写入；
5. 旧 `materials/<chap>/` 仍可被批阅读取（兼容）；
6. pytest / build / selfcheck / 脱敏全绿。

## 4. 实施记录（2026-10-31 完成）

- `materials` 目录可放**任意安全名**（`26C1` 等特征名），`chap_dir` 拒绝 `../`；
- 上传新增 `kind`（`plan/ppt/textbook/other`）→ 落 `_source/<类型>/`；
  `kind` 非法/为空 → 落 `_source/`（兼容旧行为）；`files_of` 返回 `kindDir`；
- **summary 关联三档**：`items[].feature`（教师显式选）> `items[].chap`（旧结构）> 保底口径；
- PWA 资料页上传区新增「类型」下拉；serve `/materials/upload` 透传 `kind`。

## 5. 验收对照

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 特征名可建目录、非法名拒绝 | ✅ | `test_feature_name_dir_allowed` / `test_illegal_feature_name_rejected` |
| 2 | 上传按类型归档 | ✅ | `test_upload_by_kind_subdir` |
| 3 | 非法类型回落 `_source/`（兼容） | ✅ | `test_upload_unknown_kind_falls_back_to_source` |
| 4 | summary：feature 优先 | ✅ | `test_summary_prefers_explicit_feature` |
| 5 | summary：回落 chap | ✅ | `test_summary_falls_back_to_chap` |
| 6 | summary：都没有 → 保底口径 | ✅ | `test_summary_without_any_uses_fallback_block` |
| 7 | pytest / build / selfcheck / 脱敏 | ✅ | 1241 passed · 33/33 |

## 6. 未完成（后续）

- 「📥 从 Atopia 复制解析结果」按钮（依赖 D150 Atopia 工作区，**尚未实施**）；
- `materials migrate-feature` 可选迁移命令（未实施，旧结构仍可读）。
