# D186 需求单：summary 题目提示与评阅口径适度放宽

> 日期：2026-11-18
> 状态：**已完成**
> 关联：`docs/79-D131-materials-and-summary-grading.md`、
> `docs/83-D134-atopia-workspace-and-summary-grading.md`、
> `docs/119-D176-question-kind-pipeline.md`

## 0. 教师反馈

总结题题干提示应改为：

> 列出主要概念/定理/定律，包括定义/公式、示意图等，指出概念之间的关系，
> 如 xx 求导/积分可得到 xxx。

同时评阅提示词需要略微调整：

- summary 题需要画出示意图；
- 题目描述中的斜杠 `/` 表示“或”；
- 不必同时写定义的文字描述和公式，有些定义从公式来看比较直接；
- 概念、定理、定律不要求全部写到，因为部分课堂内容可能没有定理/定律；
- 适当放宽批阅尺度，不要过于严苛。

## 1. 修复内容

### 1.1 学生题干模板

`engine/src/assist/paper/compose.py` 与 `app/src/lib/taskpad.ts` 同步改为：

```text
请总结课堂内容，并画出示意图。（提示：列出主要概念/定理/定律，
包括定义/公式、示意图等，指出概念之间的关系，如xx求导/积分可得到xxx。）
```

### 1.2 评阅提示词

- `ANALYSIS_PROMPT` 的总结题视角：
  - 主要概念/定理/定律覆盖主要内容即可，不要求列全；
  - 定义文字或公式任一即可，`/` 表示或；
  - 概念关系（如求导/积分关系）纳入“知识点与概念”判断；
  - 明确要求画出示意图；
  - 课程内容没有定理/定律时不因此判错，尺度适当放宽。
- `KIND_OUTPUT_SCHEMA_HINT["summary"]`：
  - 明确 `covered` 三项的宽松判定口径；
  - 说明公式/定义二选一，不要求同时出现；
  - 概念关系不单独增加扣分项；
  - `knowledge_missing` 只列明显遗漏的主要点，不要求穷尽。
- `summary_fallback_block()`、`summary_knowledge_block()`、`rule_summary()` 同步调整口径。

### 1.3 不变项

- 不改变 `covered` 的三项 key，避免影响现有计分结构；
- 不修改评分规则数值、题库、作业纸生成算法；
- 不新增依赖。

## 2. 验收

- summary 题干在引擎和 app 两端完全一致；
- prompt 含“/ 表示或”“不要求列全”“没有定理/定律不判错”“需要示意图”等约束；
- summary fallback / materials 两个路径口径一致；
- 相关 summary、D93、D130、D131、D134、D155 测试通过；
- 全量 pytest 与前端 build 通过。

## 3. 验收结果

- D186 目标测试：`5 passed`；
- summary 相关回归（D93/D130/D131/D134/D155）：`122 passed`；
- 全量 pytest（deselect 一个既有 Playwright 报告渲染超时用例）：
  `1689 passed`；
- 前端 build：通过；
- 脱敏检查、启动脚本 lint、`git diff --check`：通过。
