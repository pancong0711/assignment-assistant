# D144 需求单：删除规则卡里的「为本题型生成 AI 评阅要点」开关

> 日期：2026-10-31
> 状态：**已完成**
> 关联：`docs/78-D130`（评阅规则卡）、`docs/82-D130-fix2` §3（D133 合并要点路径）、
> `docs/88-D138`（summary 资料门槛）、`docs/12`

## 0. 教师提出的问题

> 评阅规则卡里面有一个「为本题型生成 AI 评阅要点」，是怎么回事？
> 这个不是应该在 AI 作答参考答案的时候用吗？

**判断正确。** 这个开关的位置和作用对不上。

## 1. 核查结论（删除前的事实）

| 命令 | 是否读 `generateRubric` |
|---|---|
| `assist rules generate --kind X` | ✅ 读（决定是否跳过该题型） |
| `assist kb ai-solve --with-rubric` | ⚠️ 读，但**只对 `copy`/`summary` 生效** |
| **实际批阅（evaluate）** | ❌ **完全不读** |

三个问题：

1. **名不副实**：挂在「评阅规则卡」里，容易被读成"批阅这个题型时要生成要点来判分"，
   但批阅读的是 `mode` / 扣分数值 / `checklist`，与它无关；
2. **两套规则**：同一件事（生成 AI 要点）有两个入口却遵循不同规则
   （`rules generate` 全部题型受限；`ai-solve --with-rubric` 只 copy/summary 受限）；
3. **黑箱**：D138 之后 summary 还要额外满足"本章有已确认资料"，
   复选框勾了也不一定生效，文案说"允许"但实际是三重条件。

## 2. 决策（按推荐方案 A）

**删除该开关**，规则卡只回答"**怎么扣分**"。生成要点的规则改为**代码口径**：

| 题型 | 规则 |
|---|---|
| `copy` | **永不自动生成**（以原文为唯一依据，D130 口径）；需要时显式 `--force` |
| `summary` | **仅当**本章有教师确认的 `知识点清单.md`（D138 门槛不变） |
| 其它 | 允许 |

教师侧唯一入口变成：「⑦ 题库 AI 作答 → 同时生成评阅要点」。

## 3. 实施

| 位置 | 改动 |
|---|---|
| `rules.DEFAULT_RULES.types.*` | 删除 `generateRubric` 字段（7 处） |
| `rules.rubric_enabled()` | 不再读字段，改为代码判断（copy 拒绝 / summary 看资料 / 其它允许） |
| `GradingRulesCard.vue` | 删除复选框与相关样式；卡片说明补一句"生成要点请到 ⑦ 题库 AI 作答" |
| 旧配置兼容 | 残留 `generateRubric` 字段**不报错、不再生效**（有测试锁定） |

## 4. 验收

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 默认规则不再含该字段 | ✅ | `test_field_absent_from_defaults` |
| 2 | 旧配置残留该字段不报错、不生效 | ✅ | `test_legacy_config_with_field_is_tolerated` |
| 3 | **改该字段不影响批阅计分** | ✅ | `test_grading_does_not_read_the_field` |
| 4 | copy 永不自动生成 | ✅ | `test_copy_never_generates` |
| 5 | 其它题型允许 | ✅ | `test_other_kinds_allowed` |
| 6 | summary 仍需已确认资料 | ✅ | `test_summary_needs_confirmed_materials` |
| 7 | 规则卡 UI 不再出现该开关 | ✅ | build + 前端删除 |

验证：pytest **1163 passed** · build 0 error · selfcheck **30/30** · 脱敏通过。

## 5. 影响与边界

- **不改变任何既有扣分行为**（有专门测试证明计分不受影响）；
- `copy` 需要生成要点时仍可 `assist rules generate --kind copy --force`；
- 若将来要"按题型预测是否生成要点"，应放在「AI 作答」区做成**显式选项**
  （方案 B），而不是回到评阅规则卡里。
