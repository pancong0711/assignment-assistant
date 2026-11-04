# D137 需求单：PWA ↔ CLI 能力对齐（provider 请求头编辑 / 资料页三个动作 / Atopia 护栏可改）

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/86-D136`（provider 请求头）、`docs/79-D131`（资料页只读的原因）、
> `docs/81-D132`（护栏硬顶）、`docs/12`

## 0. 背景与核对结果

对 `serve.py` 的 HTTP 接口与 `engineClient.ts` 的调用做逐项比对后，
**日常动线基本已对齐**（题库/AI 作答/LLM 配置/学习通全链路/规则卡/教师报告/
趋势/作业包/水印/备份/资料上传与回收站）。

真正的缺口分三类：

### A. 该补
| # | 缺口 |
|---|---|
| A1 | provider 的 `headers` / `user_agent` PWA 只读展示，**不能编辑**（D136 刚加的配置项） |
| A2 | 资料页的「抽取 / AI 建议 / 确认生效」只有 CLI 命令提示，教师需切终端 |

### B. 不该给 PWA 编程入口（L3 删除/迁移/升级类，沿用既有口径）
`atopia reset`、`migrate-grading-dir --apply`、`workspace clean-migrated --apply`、
`engine update`。

### C. 现状合理，不补
`sheet make/batch/html`（PWA 浏览器端自生成，更快且离线可用）、
`prompt save/list`（`/prompts/ai-solve` 已覆盖）、
`kb export/normalize/snapshot`（维护性，可由 Atopia 代劳）、
`roster tag/rain`（PWA 有独立成绩链路）。

另发现 1 个真实不一致：

- **B1**：`AtopiaPanel` **只显示**护栏，CLI 有 `limits --set` 可改 → 教师须切 CLI。

## 1. 任务清单

### A1 provider 请求头 / user-agent 可编辑（优先级 1）

- provider 配置区新增「高级请求头（仅按需）」折叠块：
  - `user-agent` 单行输入；
  - `headers` 多行 `name=value`（每行一条）；
- 保存前**二次确认**，弹窗列出"以下请求头将随每次调用发送到该 provider"；
- 复用引擎白名单：`Authorization`/`Host`/`Cookie` 等由引擎拒绝，
  **拒绝原因原样显示**（不静默丢弃）；
- 文案说明：只有 provider 明确要求时才填（如 opencode-go 的 `x-opencode-session`）。

### B1 Atopia 护栏可改（优先级 2）

- `AtopiaPanel` 护栏区加编辑（`maxCallsPerSession` 等四项）；
- 二次确认 + 显示硬顶（`HARD_CAPS`）；
- 超硬顶时引擎拒绝，原因显示出来。

### A2 资料页三个动作（优先级 3）

| 动作 | 接口 | 级别 | 成本 |
|---|---|---|---|
| 抽取 | `POST /materials/extract` | 无 LLM | 免费 |
| AI 建议 | `POST /materials/suggest` | L1（花模型钱） | 需提示 |
| 确认生效 | `POST /materials/confirm` | 写生效清单 | **必须二次确认** |

**「确认生效」的安全口径（D131 原意不放松）**：

1. 弹窗必须**展示将写入的完整清单内容**（术语 + 逻辑关系），教师看清才点；
2. 必须**教师显式点击**，不接受自动/脚本触发；
3. 记 `confirmed_by=teacher:pwa`（与 Atopia L2 口径一致）；
4. 已有生效 `.md` 时默认**不覆盖**，需显式勾"覆盖"（对应 CLI `--force`）。

## 2. 验收标准

1. PWA 可编辑 provider `headers`/`user_agent` 并落盘（重载后仍在）；
2. 填 `Authorization=...` → 保存被拒且**显示原因**；
3. PWA 可改 Atopia 护栏；超硬顶被拒并显示原因；
4. 资料页可「抽取」并看到状态变为"已抽取"；
5. 资料页可「AI 建议」并看到"待确认"；
6. 「确认生效」**弹窗展示清单全文**，确认后状态变"✅ 已生效"；
7. 已有生效清单时默认不覆盖，需显式勾选；
8. 全链路记 journal（含 `confirmed_by`）；
9. pytest / build / selfcheck / 脱敏 全绿。

## 3. 风险

| 风险 | 缓解 |
|---|---|
| PWA 一键改写云 provider 的鉴权头 | 白名单（引擎侧强校验）+ 二次确认显示实际内容 |
| 「确认生效」被误点，改了 summary 批阅依据 | 弹窗展示全文 + 默认不覆盖 + journal |
| AI 建议按钮误触花掉额度 | 按钮显式标注"会调用模型"；不自动触发 |

## 4. 实施记录（2026-10-31 完成）

### A1 provider 请求头 / user-agent 可编辑

- serve `/llm/provider` 透传 `headers` / `user_agent`；
- `AiGradingPanel` ① 区新增折叠块「⚙️ 高级：自定义请求头 / user-agent」：
  - `user-agent` 单行；`headers` 多行 `name=value`（`#` 开头为注释）；
  - **保存前二次确认**弹窗，列出"以下请求头将随每次调用发送"；
  - 点「编辑」时回填已存请求头；
  - 表格新增"请求头"列（项数 + 是否设了 UA），一眼看出哪些 provider 配了。
- 白名单仍由引擎 `providers.validate_headers` 强校验，PWA 只是入口。

### B1 Atopia 护栏可改

- serve `POST /atopia/limits`（复用 `limits.write_limits`，超硬顶直接拒绝）；
- `AtopiaPanel` 新增「护栏」编辑区：四项数值 + 显示硬顶 + **二次确认**
  （弹窗只列"改动的项：旧值 → 新值"，避免看一屏没用的）。

### A2 资料页三个动作

| 动作 | 接口 | 安全口径 |
|---|---|---|
| ① 抽取 | `POST /materials/extract` | 无 LLM、免费 |
| ② AI 建议知识点 | `POST /materials/suggest` | 前端**先确认会调模型** |
| ③ 确认生效 | `GET /materials/suggest-preview` + `POST /materials/confirm` | 见下 |

「确认生效」按 D131 原意**不放松**：
1. 先取 `suggest-preview`，弹窗展示 `render_knowledge_md()` 的**全文**
   （与最终写入同一渲染函数 → 不会"看到的≠生效的"）；
2. `POST /materials/confirm` **缺 `confirm` 字段直接 403**（不接受脚本静默触发）；
3. 已有生效 `.md` 时默认拒绝覆盖，需教师勾选"覆盖"才传 `force`；
4. 写 journal（`confirm_knowledge` 自带），PWA 侧传 `confirmed_by=teacher:pwa`。

### 测试

- `test_d137_pwa_parity.py`（11 项）：provider 头写入/拒绝/重载、护栏写入/超硬顶/
  未知项、抽取、确认（不覆盖 / force 覆盖 / 无建议报错）、预览与写入同源；
- `run-d137-parity-browser.sh`（真实浏览器 + 真实引擎）：
  资料页①抽取 → ③确认弹窗**展示术语全文** → 生效；Atopia 护栏改 66 并落盘；
  provider `x-opencode-session` 可写、`Authorization` 被拒。

## 5. 验收对照

| # | 标准（§2） | 结果 | 证据 |
|---|---|---|---|
| 1 | PWA 可编辑 provider headers/UA 并落盘 | ✅ | `test_provider_headers_saved_via_save_provider` + 浏览器 |
| 2 | 填 Authorization → 被拒且显示原因 | ✅ | `test_provider_headers_reject_authorization_via_api` + 浏览器 |
| 3 | PWA 可改护栏；超硬顶被拒并显示原因 | ✅ | `test_limits_writable` / `test_limits_reject_over_hard_cap` + 浏览器 |
| 4 | 资料页可抽取并显示"已抽取" | ✅ | `test_extract_chap` + 浏览器 |
| 5 | 资料页可 AI 建议（会提示成本） | ✅ | 前端 `window.confirm` 提示 + 接口 |
| 6 | 确认弹窗展示清单全文，确认后生效 | ✅ | `dialog.showsTerms` + `mdCreated` |
| 7 | 已有清单默认不覆盖，需显式勾选 | ✅ | `test_confirm_creates_md_and_does_not_overwrite` |
| 8 | 全链路记 journal（含 confirmed_by） | ✅ | `confirm_knowledge` 内 `_journal`；PWA 传 `teacher:pwa` |
| 9 | pytest / build / selfcheck / 脱敏 | ✅ | 1113 passed · 0 error · 28/28 · 通过 |

## 6. 未做（明确不做，见 §0 B 类）

`atopia reset`、`migrate-grading-dir --apply`、`workspace clean-migrated --apply`、
`engine update` —— 均为 L3 删除/迁移/升级类，刻意不给 PWA 一键入口。
