# D82 任务需求单：kb 多文件读取 / 题目排序 / 插图参数 / 作业草稿修复 / 上传试跑 / batch API

> 日期：2026-10-14
> 状态：需求整合；按下面顺序实现/验证。
> 关联：`docs/31-D79...`、`docs/32-D80...`、`docs/33-D81...`、`docs/05-D3`（kb）、`docs/04 §1`（taskpad）。

## A. kb 编辑器目录读取与示例命名

### A1. 现状

- 「连接本地题库目录」当前只用于**写回**（句柄写 `kb/<kind>.xlsx`）；
- 不读取目录下已有 xlsx；
- 教师常把多个 xlsx 放在 `workspace/kb/`，希望直接全部读入。

### A2. 目标

- 连接 workspace 后自动扫描 `kb/*.xlsx`，按 kind 读入所有可识别文件；
- 支持多 xlsx 同时存在；
- exact 文件名优先于示例文件；
- 兼容示例命名：
  - `problems-example.xlsx`
  - `example-problems.xlsx`
  - 其他 kind 同理。

### A3. 示例导出命名

- 示例数据导出文件名改为 `<kind>-example.xlsx`；
- engine `read_kb` 识别：
  - exact `problems.xlsx` 优先；
  - 若只有 `problems-example.xlsx`，按 `problems` 读取（示例降级）。

## B. 作业纸题目顺序可调

- 目标：教师可调整 items 内顺序或 ids 内题目顺序；
- 交互：鼠标拖拽 + 上移/下移按钮（拖拽在移动端不可靠，按钮保底）；
- 数据：修改 `taskpad.items[].ids` 顺序（或 items 顺序）；
- 预览/HTML/PDF/批量通道按新顺序输出；
- 需要 undo/本地持久化。

## C. 作业纸插图大小与位置参数

- 现状：`paper/layout._fitted_image` 自动按 frame 缩放，无独立参数；
- 目标：
  - 每题可配置插图缩放比例/最大宽高；
  - 默认置于题目右上角；
  - 提供按钮/下拉调整图片位置（右上/左上/居中/自定义）；
  - 参数写入 taskpad item 或 kb row（需定 schema，如 `img_scale` / `img_pos`）。
- 预览与引擎 PDF/HTML 三端同参数。

## D. 新建作业草稿 PWA 失败排查

- 已真机验证 engine `work-create` CLI 成功；
- PWA 侧测试“没有新建成功”，可能原因：
  - 白名单未开启；
  - 目录/文件夹参数；
  - 作业列表缓存未刷新；
  - job 输出未正确展示。
- 计划：
  - PWA 创建后强制刷新当前文件夹；
  - 显示 job 完整输出/错误；
  - 新建成功后自动选中新草稿；
  - 复查 whitelist 与 folder 参数。

## E. 上传试跑（仅目标班）

- 目标：目标班 `大学物理知识点拾遗（by pc） / 默认班级`；
- 先确认该班作业列表（是否只有 1 份）；
- 将其中一份作业作为 **期末补交** 场景；
- 生成评语，尝试上传到该作业；
- 全程白名单 `xxt.write_allowlist`；
- 先 dry-run + 截图 + 二次确认，再真正上传。

## F. 晚间批阅协作与 batch API

### F1. 两步批阅

- transcribe：视觉模型（图片 → 转录）；
- evaluate：文本推理模型（转录 + solution → 评分/评语）；
- report：本地生成 Markdown/HTML/汇总。

### F2. 两套模型

- `settings.local.json` `llm` 段支持：
  - `base_url` / `api_key`
  - `transcription_model`（视觉）
  - `evaluation_model`（文本）
- 如两套模型来自不同 provider，需要扩展为 per-step base_url/api_key：
  - `llm.transcription.base_url/api_key/model`
  - `llm.evaluation.base_url/api_key/model`
  - 兼容旧扁平字段。

### F3. batch API

- 目标：提供一般调用 + batch 调用两套；
- 设计抽象：

```text
LLMClient.chat(...)           # 一般调用
LLMClient.batch_submit(...)   # 批量提交
LLMClient.batch_poll(...)     # 轮询
LLMClient.batch_fetch(...)    # 取回
```

- taskpad 可设 `grade.batch: true` 或 `grade.batch_mode`；
- transcribe/evaluate 支持批量提交与结果回收；
- provider 适配：
  - OpenAI 兼容 `/batches`（若 provider 支持）
  - 阿里云 DashScope batch 接口（待确认具体端点）
  - 不支持 batch 时回退普通调用。

## 实施顺序

1. D82-A kb 多文件读取 + 示例命名；
2. D82-D 新建作业草稿 PWA 修复；
3. D82-B 题目顺序拖拽；
4. D82-C 插图参数；
5. D82-F batch API（晚间前完成一般/批调用骨架）；
6. D82-E 晚间上传试跑。

## 验收

- 连接 workspace 后自动读入 kb 下全部 xlsx；
- 示例导出名为 `*-example.xlsx`；
- PWA 能成功新建草稿并选中；
- 题目顺序、插图大小/位置可调且三端一致；
- batch/普通两种 LLM 调用可用；
- 上传仅落在白名单班级。
