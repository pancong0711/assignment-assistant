# D172 需求单：tag 审计（转写题目 ↔ 作业纸题目 / roster 比对）

> 日期：2026-11-06
> 状态：**全部完成**（2026-11-06，engine/app 0.6.0）
> 交付：`grading/tag_audit.py`（纯 Python 匹配器）+ CLI 3 条 + HTTP 4 条 + 逐生审核「🛡 审计 tag」列
> + 历史副本/撤销 + 规则卡 `tagAudit` + `xxt verify-names`
> 关联：`docs/112-D168`（快照/统计口径）、`docs/113-D169`（路线/架构）、
> `docs/115-D170`、`docs/116-D171`、`docs/109-D166`（知识点 JSON 化）、`docs/12`

---

## 0. 教师原话

> 我们想在 ai 批阅部分增加一个 **ai 审计 tag**，相当于将每个学生的作答内容转写后的题目提取出来，
> 和作业包里的题目进行对比，找出实际 tag，因为现在的情况是出现了**作业包和 roster 没有关联**的情况，
> 而随着我们 engine 版本升级，新的作业包关联了 roster、**旧的 roster 已被覆盖无法关联到旧作业包上**，
> 所以推出一个 tag 审计功能比较合理。
> 可以将审计结果也列在逐生审核里，**单独一列，与 tag 列并列**，相当于检查，
> **tag 审核列与 tag 列值不同的行需突出**，方便教师检查。
> 题目内容与作业包中作业纸中的题目内容对比时，应设计好对比方法（语义空间？bge 算法？），
> 有可能不会逐字相同，因为转写可能存在误差，且学生在作答的过程中可能会用笔标记题目中的要素，
> 也会造成转写误差。先写好需求单，有无需要讨论的。

---

## 1. 问题定位（先讲清楚「为什么需要」）

### 1.1 现状的事实链

| 环节 | 事实（已核代码） |
|---|---|
| 判 tag 用在哪 | `flow._run_evaluate` → `_plan_items_for(ctx, 学生名)`：按**学生姓名**去 `plan.students[].questions` 取题 |
| plan 从哪来 | 前端 `AiGradingPanel` 用当前 roster/作业包装配后传给引擎（或引擎读 `tasks/*.taskpad.json`） |
| 历史可复现手段 | 只有 `roster-tags/<packId>.json`（D168-B1），**首次批阅即冻结**；但 **`packId` 必填**才锁定 |
| 缺口 | ① 旧作业包若当时没有快照 → 现在按**今天的 roster tag** 装配 → tag 已变，题目错配；<br>② roster 被覆盖后，**旧包的「学生→tag」事实丢失**；<br>③ 转写里的题目与选中的作业纸不一致时，**引擎不报警**（`question_match` 只在评阅 prompt 里、且结论随分数一起被“跳过已完成”忽略） |

结论：**「实际 tag」需要一条独立于当前 roster 的证据链**——从**学生真的做了哪张作业纸**反推 tag。
这正是教师说的「审计」。

### 1.2 为什么不能只靠“当前 roster + 当前作业包”

- 当前 roster 是**可变真源**，旧批次的 tag 分配本来就找不回来；
- 学生实际作答里**必然写着题号与题干**（作业纸生成时就印上了），这是**唯一没被覆盖的事实**；
- 所以审计 = **作答转写里的题目 → 匹配作业包内的作业纸 → 得到该生实际 tag**。

> ⚠️ 与 D168 口径一致：审计结果是**证据、不是结论**。任何“修正 tag”都必须教师确认后才写盘
> （见 §4.4），且**不自动改 `roster-tags` 快照**。

---

## 2. 对比方法设计（教师最关心的部分）

### 2.1 候选方案与事实核查

| 方案 | 在本项目的现实性 | 判定 |
|---|---|---|
| **BGE / sentence-transformers 等本地向量** | 需要额外 ~400MB 模型权重 + PyTorch，且离线课堂机器常见无网；引擎当前依赖树里没有 | ❌ 不进主依赖（可作为可选 extra 的远期项） |
| 云端 embedding API | 又多一路 provider/额度/密钥，且与“省额度”方向相悖 | ❌ 不做 |
| **纯 Python 字面匹配**（去噪 + 字符 n-gram） | **零依赖、秒级、可解释**；能给出「哪个题的哪几段对上了」的精确定位 | ✅ **主路径** |
| LLM 语义判定 | 语义最准，但慢、贵、不可解释，且题目错配时模型容易“脑补” | ❌ **不做**（教师 D2b 裁定：转写已完成、题目内容已有，纯编程即可） |

**核心判断**：这不是“找到语义最近的文章”，而是**在 N 张已知作业纸里做选择题**。
N 通常 ≤ 6，题目文本差异主要来自 **OCR 噪声**（笔迹标记、错字、漏字、公式变形）和
**学生没抄全**。**字符级 n-gram 重合度**对这种噪声极其鲁棒，向量模型反而可能把
“动量守恒”和“能量守恒”判得很近（这正是我们**最需要区分**的）。因此：

> **唯一算法：字符 n-gram + 数值常量（引擎内纯 Python，零模型调用）**。
> 审计因此可离线、可批量、秒级、**同输入必得同输出**。

### 2.2 两阶段算法（引擎实现，前端只渲染）

#### 阶段 A：从转写里抽出「学生看到的题目」（纯 Python）

转写 JSON 已是结构化 `items[]`（`id/markdown/...`，D127 起）。对每份转写：

1. 按题切块：转写里的 `第N题` / `N.` / `（N）` 等**题号锚点**切分（复用现有 transcript 解析，不新增模型调用）；
2. 每块再拆成「题干段」与「作答段」：
   - 含“已知/求/如图/一质量为/试问”等题干特征 + 位于该块前部 → 题干段；
   - 其余/含“解：”“=”“由…得” → 作答段（**只用于佐证，不参与匹配打分的分母**）；
3. 若 `question_match.evidence`（D127 已有字段）非空 → 直接作为「学生抄写的题目」强证据。

> 关键：**绝大多数情况下学生把题目原样抄在作业纸上/作答区**，OCR 后题干的字面重合度会很高。

#### 阶段 B：候选集打分（字符 n-gram + 选项归一）

候选集 = **当前作业包内全部作业纸**的题目（`packPads` → 每张 `items[]` 的 `content`）。
若教师选了单个作业纸，则候选集 = 该包其余作业纸 + 该作业纸（并标注“同包”）。

对「学生题块 × 候选题」打一个 **S ∈ [0,1]**：

```
准备（两侧同口径）：
  1) 去噪：删掉 LaTeX 命令但保留其内容（如 `\frac{a}{b}` → `a b`）、下标上标符号、标点空白统一；
     —— 用既有 sanitize/termnorm 能力，**不新增依赖**
  2) 学生侧额外忽略：圈画标记、下划线、方框、涂改符（OCR 常表现为 \_ __ □ △ • 以及孤立单字符）
  3) 去停用词：题干里的“如图”“已知”“求”“试求”“（本小题满分X分）”

相似度：
  bigram = 2 字符 n-gram 的 Dice 系数（两侧都做，取 max(bigram, trigram)）
  number = 题干中**数值常量**（含单位）的重合率（物理题的核心区分特征）
  S = 0.65*bigram + 0.35*number        # 权重在规则卡里可调
```

**题块 → 作业纸**：用二分图最优分配（题块数 ≤ 10，**暴力排列 / 匈牙利算法**都行，纯 Python），
作业纸得分 = 已分配题目的 S 之和 / 题块数。得分第二名的差距 = `margin`。

#### 阶段 C：三档判定（无兜底）

| S（全部题块的平均） | margin | 判定 | 界面 |
|---|---|---|---|
| ≥ 0.75 | ≥ 0.15 | **高置信** | 绿 |
| 0.45–0.75 | — | **需人工确认** | 黄（列出“最可能 / 次可能”及逐题对照） |
| < 0.45 或 margin < 0.05 | — | **无法判定** | 灰（列 Top2 + 原因） |

**低置信不找模型兜底**（v2 删除）：一律在界面展示 Top2 + 逐题对照，
由教师**看图判断**——这本来就是本功能的目的（“方便教师检查”）。

**新增一档：题块缺失**（教师 D1）
> 作业纸都带题目。若学生某题**连题干都没抄** → 该题块**不参与打分的分母**，
> 记为 `linkMissing`，并在那行标 `?`；只有**全部题块都缺失**才判 `unknown`。
> （不把“没抄题”当成“tag 错”的证据——那是学生习惯问题，不是分错班。）

### 2.3 为什么纯编程够用（回答教师 D2b）

| 担心 | 事实 |
|---|---|
| “题目内容会不会认不出” | 转写 JSON 已是**结构化 `items[]`**（D127 起），题干是**文本**，不再是图片 |
| “OCR 有误差怎么办” | 字符 n-gram + 数值常量对错字/漏字/圈画**天然鲁棒**（§9 有噪声验收） |
| “要不要语义模型” | 候选只有**同包 2–6 张**作业纸，是**选择题**而非开放检索；层间差异恰恰在**数值/条件**，字面方法更准 |
| “会不会很慢” | 每人 6 题 × 6 张纸 = 36 次比较，纯 Python 毫秒级；全班 40 人 < 1 秒 |

### 2.4 为什么这是「审计」而不是「再猜一次」

- 审计**只比对题干**，不看作答对错 → 不会被分数污染；
- 输出**逐题对照表**（哪一题对上了哪一题、S 值、差异片段）→ 教师可 30 秒核完；
- 审计**不改任何东西**，除非教师显式点击（§4.4）。

---

## 3. 数据与落盘（D169 铁律：能力在引擎）

### 3.1 命令

```bash
assist grade audit-tags \
  --class-dir classes/<班级> \
  --pack-id <packId> \
  [--students 姓名1,姓名2]     # 只审计这些学生（与逐生补批同口径）
  [--min-score 0.75]
```

**全程不调用模型**（教师 D2b）：只需 `transcripts/*.json` + 作业包题目。

### 3.2 产物

```
classes/<班>/grading/<packId>/audit/
  audit.json            # 全班汇总（唯一真源，前端只读这个）
  <学生>.<题块号>.json   # 可选：单生明细（体量大时按需写）
```

`audit.json` 结构（草案）：

```jsonc
{
  "ok": true,
  "packId": "...", "generatedAt": "...",
  "method": "ngram+number-v1",
  "papers": [{"padId": "...", "tag": "提高", "questionCount": 6}],
  "students": [
    {
      "name": "张三", "number": "2023...",
      "rosterTag": "基础",            // 来自 roster-tags 快照（冻结值）；无快照时 null
      "currentRosterTag": "提高",     // 来自今天的 roster（可能已变）；无则 null
      "auditTag": "提高",             // 匹配到的作业纸 tag（= 实际 tag）
      "auditPadId": "pad-xxx",
      "confidence": "high",           // high | medium | low
      "score": 0.83, "margin": 0.21,
      "verdict": "match | mismatch | unknown",   // match = auditTag == rosterTag
      "reason": "6 题全部对上提高层作业纸；与 roster tag 不符",
      "pairs": [
        {"q": 1, "paperQ": 1, "score": 0.91, "studentStem": "…前 60 字…",
         "paperStem": "…前 60 字…", "diff": ["第2句缺少…"]}
      ],
      "alternatives": [{"padId": "...", "tag": "基础", "score": 0.52}],
      "resolution": null,             // 教师确认后写 {at, action, from, to, by}（§7.3）
      "linkMissing": [4],             // 这些题块**没抄题干**（不计入分母，标 ?）
    }
  ],
  "summary": {"match": 32, "mismatch": 3, "unknown": 2,
              "byRosterTag": {"提高": {"ok": 20, "bad": 2}}}
}
```

**必须成对出现的失败标记**：`unknown` 绝不写 0 分、绝不写 `match`；
前端灰色 + 原因（和 D168 “提交率必须与失误率成对”同精神）。

### 3.3 HTTP 接口（`serve.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/grade/audit-tags` | 启动审计（job 化：复用现有 job 轮询） |
| GET | `/grade/audit-tags?packId=&classDir=` | 读 `audit.json`（不存在 → `{ok:false,missing:true}`） |

⚠️ **注册位置**：GET 必须追加到 `do_GET`（D171 已经踩过两次“只读接口写在 do_POST → 前端 GET 302 到 Pages”的坑）。

### 3.4 与快照的关系（关键设计决定）

- **不写** `roster-tags/<packId>.json`（那是教师权威，审计不许篡改）；
- 审计**优先读**该快照作为 `rosterTag`（历史真相），再读今天 roster 作为 `currentRosterTag`
  → 教师能一眼看到「当时的 tag / 现在的 tag / 实际做的作业纸」三方对照。

---

## 4. 界面（PWA 逐生审核）

### 4.1 新增一列

```
| 学生 | tag | 🛡 审计 tag | AI 状态 | AI 分 | 人工 | 报告模式 | 操作 |
```

- `审计 tag` 列内容：`提高 ⚠️`（不一致 → **整行浅红底 + 左侧 3px 红边**）；
  一致 → 绿 `✓ 基础`；无法判定 → 灰 `? ` + 悬停原因；
- 未审计 → `—`（灰） + 列头「运行审计」按钮。

### 4.2 交互

- 列头按钮「🛡 运行 tag 审计」→ 二次确认（**说明：只读转写，不调模型；低置信兜底才调**）→ job 进度写入行内（沿用 D154/D171 的 `rowMsg`）；
- 点击某行审计单元格 → **明细弹窗**：
  - 顶部三格：`roster tag` / `当前 roster tag` / `实际（审计）tag`；
  - 逐题对照表（学生题干 vs 作业纸题干，S 值，差异片段高亮）；
  - 「应用审计 tag」按钮（见 §4.4）；
- 提供「只显示不一致」过滤器（便于教师快速处理）。

### 4.3 与「报告 / 草稿」的关系

- 审计结果**不进批阅报告**（避免家长/学生看到“可能分错班”这类内部信息）；
- 但**导出**侧提供 `audit.json` 下载（教师留档）。

### 4.4 「应用审计 tag」= 显式、可回滚

点击后走**引擎**命令（不在前端改 roster）：

```
POST /grade/audit-tags/apply  { classDir, packId, students:[{name, tag}] }
```

- 先展示影响面：`将把 3 名学生从「基础」改为「提高」；其已批阅结果不会自动重算`；
- 写 `roster-tags/<packId>.json` 的**补丁**（`source="audit-apply"` + `previousTag` 留痕），
  **不覆盖**已有快照的其它字段；
- 同时可选「重新批阅这 3 名学生」（显式勾选，默认**不勾**）；
- **写前自动存 `roster-tags/_history/<packId>__<时间戳>.json`**（`reason=audit-apply`），
  撤销入口见 §10.1。

---

> ⚠️ §5 为 v1 草案，**已由 §8 取代**（v1 的 T7「LLM 兜底」与「忽略名单」均已删除）。
> 保留原文仅作讨论留痕。

### 5.1 v1 草案（已被 §8 取代，仅留档）

| 批次 | 项 | 交付物 |
|---|---|---|
| A（P0） | `T1` 字符 n-gram 匹配器 + 题块切分 + 二分图分配 | `grading/tag_audit.py`（纯 Python，可单测） |
| A | `T2` `assist grade audit-tags` 命令 + `audit.json` 落盘 | CLI |
| A | `T3` 单测：OCR 噪声（漏字/错字/公式变体/圈画标记）、同包 3 层作业纸区分、全错配样例 | pytest |
| B（P1） | `T4` `/grade/audit-tags` POST/GET（GET 在 do_GET！） | serve |
| B | `T5` 前端「🛡 审计 tag」列 + 不一致高亮 + 明细弹窗 | `AiGradingPanel.vue` |
| B | `T6` selfcheck 断言（列存在、不一致行有 class、GET 走 do_GET） | `npm run selfcheck` |
| C（P2） | `T7` LLM 低置信兜底（每生 ≤1 次，可关） | `grading/tag_audit.py` + prompts |
| C | `T8` 「应用审计 tag」补丁写快照 + 可选重批 | CLI + serve + 前端 |
| C | `T9` 规则卡新增 `tagAudit` 段（权重/阈值可调，不写死在代码） | `rules.py` |

> 规则卡（教师原则：“阈值不许写死”）：`tagAudit = {minScore:0.75, margin:0.15, bigramWeight:0.65, numberWeight:0.35}`（**无** `llmFallback`：纯编程，见 §6 D2b）。

---

## 6. 教师裁决（v2 已定，直接照此实施）

| # | 问题 | 教师决定 | 对本需求单的影响 |
|---|---|---|---|
| **D1** | 学生没抄题干 | 「作业纸上应该都带题目；没有题目就不是正规打印 → 标 **? / unknown**」 | 审计**不猜**：题块缺失/无法定位题干 → `unknown`；不因为“学生只写解”而判错配 |
| **D2** | 候选集范围 | 「**只在当前选好的作业包**内比对，**不做跨包**」 | 候选集 = `packPads`；跨包比对从路线图移除 |
| **D2b** | 是否用 AI | 「转写已完成、题目内容已有，**应该不需要 AI**，可用编程完成，是不是？」 | ✅ **确认：不需要模型**。§2.2 的两阶段纯 Python 算法即全部（原 T7「LLM 兜底」**删除**） |
| **D3** | 不一致是否阻断 | 「**不阻断**批阅，只高亮」 | 高亮 + 明细；批阅流程完全不变 |
| **D4** | 不一致的含义 & 处理顺序 | 「指**审核 tag** 与 **roster 关联 tag** 不一致；先调 tag 再 AI 批阅；调整相当于改历史，**应记录到 tag 的 json 文件里**」 | 采用 §4.4 的**补丁式写入 + 留痕**（`previousTag` / `source` / `journal`）；UI 明确提示“改历史” |
| **D5** | 忽略名单 | 「**不需要**」 | 删除 `ignored[]`；全班一律审计 |

> D2b 的直接后果：**审计与 AI 完全解耦**——它只吃「转写 JSON + 作业包题目」，输出 JSON。
> 这也意味着它可以**离线、批量、秒级**跑，且结果**完全可复现**（同一输入必得同一输出）。

---

## 7. 教师提出的新流程（v2 主线，已采纳）

教师原话（整理）：

> 图片是通过 PWA 下载的、文件名也是我们的代码生成的，解析相当于逆过程，所以**提交人员名单可以确定**；
> 确定之后去原本关联的 roster 里找 tag；**现在增加一步 tag 核对**（是否专门写一个核对 tag 的 JSON 文件？）；
> **核对无误 → 按之前方式 AI 批阅**；**有疑问 → 教师改 tag（一键改 / 逐人改）→ 用新 tag 和对应题目再批阅**。

### 7.1 流程（正式版）

```
① 提交名单确立（已有能力，权威性来自 students.json + 文件名规则）
        │  ⚠ 注意：不是"从图片名反推姓名"，见 §7.2
        ▼
② 取 tag：roster-tags/<packId>.json 快照优先 → 否则今天 roster（标 source 以示区别）
        │
        ▼
③ 🛡 tag 审计（**纯 Python，无模型**）：转写题目 ↔ 该作业包内各作业纸题目
        │  产出 audit/<packId>.json（§7.3）
        ├── 一致（match） ─────────────────────────► ④ 按原方式 AI 批阅（完全不变）
        │
        └── 不一致 / 无法判定（mismatch / unknown）
                    │
                    ▼
            教师在三格对照里确认
                    │
                    ├─ 改 tag（逐人 / 一键全班同改）
                    │      → 写 roster-tags/<packId>.json（补丁 + previousTag 留痕）
                    │      → 同时写 audit 的 resolved 记录
                    ▼
            ④ 用**新 tag 对应的作业纸题目** AI 批阅
```

**审计是独立工序、不是批阅的一步**：它可单独跑、可反复跑、可只跑部分人；
批阅按钮与引擎参数**一律不变**（不新增 `--audit` 之类的耦合开关）。

### 7.2 关于「提交名单」的一个纠正（重要，先说清）

教师的推理有一半对：

| 说法 | 判定 | 事实（已核代码） |
|---|---|---|
| 图片由 PWA 下载 → 文件名由我们代码生成 → 可逆解析 | ✅ 对 | `review.image_filename()` = `{学生名}_{班级}+{作业}_p{页码}.jpg`，**确定性可逆** |
| 因此“提交人员名单”可确定 | ⚠️ **只能作为交叉校验** | 真正的权威来源是 `pages/review/<classId>/<workId>/students.json`（由页面 `JS_REVIEW` + `parse_work_answer_id` 生成）。`build_plan` 就是读它（`read_review_students`） |

**所以不需要新造一套“从文件名反推姓名”的机制**；但需要补一个**校验**：
`students.json` 的姓名集合 vs 文件名解析出的姓名集合 → 不一致就报出来（这正是教师担心的那类风险）。
本需求单把它作为 **T10（轻量）**：`assist xxt review verify-names`（只读、不调模型、不写盘）。

### 7.3 专门写一个「核对 tag 的 JSON」文件？—— **建议：是，但分两层**

教师问：是否专门写一个核对 tag 的 JSON？**建议这样做**，但要把「证据」与「权威」分开：

| 文件 | 角色 | 谁写 | 谁读 |
|---|---|---|---|
| `classes/<班>/roster-tags/<packId>.json` | **权威**（批阅依据） | 引擎（快照 / 教师确认后的补丁） | `flow._write_grade_snapshots` |
| `classes/<班>/grading/<packId>/audit/tags-audit.json` | **证据**（审计结论 + 逐题对照 + 处置记录） | 引擎（纯 Python） | 前端审计列 / 明细弹窗 / 导出 |

理由：
- 混成一个文件会让“证据”污染“权威”（D168 已明确快照是唯一批阅依据）；
- 分开后可以**反复审计**（每次覆盖 audit 文件、保留 `history[]`），而快照只在教师确认时**打补丁**；
- 两者用 `packId` 关联，`audit.json` 里记录 `appliedAt/appliedBy`（教师确认动作）以便追溯。

`tags-audit.json` 结构（在 §3.2 基础上升级）：

```jsonc
{
  "ok": true, "packId": "...", "classDir": "classes/...", "generatedAt": "...",
  "engine": "ngram-v1",                     // 算法版本，便于口径变更后辨认
  "submittedSource": "students.json",       // 提交名单来源
  "students": [ /* 每人一条，见 §3.2 */ ],
  "summary": {"match": 36, "mismatch": 2, "unknown": 1},
  "history": [                              // 每次重跑追加摘要（不无限增长：保留最近 20 次）
    {"at": "...", "match": 36, "mismatch": 2, "unknown": 1}
  ]
}
```

**处置记录写在哪**：写 `tags-audit.json` 的 `students[].resolution`，**同时**写
`roster-tags/<packId>.json` 的补丁（真正的生效点），并在 `grading/<packId>/journal.jsonl`
追加一条 `{"step":"audit-tags-apply", ...}`。三处一致才算“改完了”。

```jsonc
// audit 文件里每人的处置
"resolution": {"at": "...", "action": "apply-audit-tag",
               "from": "基础", "to": "提高", "by": "teacher"}
```

### 7.4 一键改 vs 逐人改

| 操作 | 说明 |
|---|---|
| **逐人改**（主路径） | 明细弹窗里「应用审计 tag（提高）」→ 单人确认 |
| **一键改**（批量） | 列表勾选多行 → 「应用选中行的审计 tag」；**只对 `mismatch` 且 `confidence=high` 的行默认可勾**（medium/unknown 默认置灰，可手动放开） |
| **一键全班同改** | ❌ 不做（同包内不同层作业纸本来就该混着，全改会毁数据） |
| 安全阀 | 应用前必须显示：`将改 N 人：基础→提高 2 人；其已有转写/评阅结果**不变**（如需重批请勾选）` |

### 7.5 改完 tag 之后怎么批

- **默认不自动重批**（改 tag ≠ 重批）；
- 应用后该行显示「tag 已更新，建议重新批阅」提示，并提供行内 `转写+批阅`（← D171 已有按钮，带强制重做勾选）；
- 引擎侧**无需新能力**：批阅本来就按 `roster-tags` 快照取题（D168-B1），所以**补丁生效后下一次批阅自动用新题目**。

---

## 8. 需求分解（v3 最终批次）

| 批次 | 项 | 交付物 |
|---|---|---|
| A（P0，纯 Python） | `T1` 题块切分 + 字符 n-gram/数值常量打分 + 二分图最优分配 | `grading/tag_audit.py` |
| A | `T2` `assist grade audit-tags`（`--class-dir --pack-id [--students]`）→ `audit/tags-audit.json` | CLI |
| A | `T3` 单测：OCR 噪声（漏字/错字/公式变体/圈画符）、同包三层相似题靠数值区分、题块缺失→`unknown`、跨包不作候选 | pytest |
| B（P1） | `T4` `/grade/audit-tags` POST 跑审计 + GET 读结果（**GET 必须登记在 `do_GET`**） | `serve.py` |
| B | `T5` 前端 `🛡 审计 tag` 列 + 不一致整行高亮 + 明细弹窗（逐题对照） | `AiGradingPanel.vue` |
| B | `T6` selfcheck：列存在 / 不一致行带 class / GET 路由在 do_GET | selfcheck |
| C（P1，写入） | `T7` 「应用审计 tag」：逐人 + 勾选批量；补丁写 `roster-tags`（`previousTag`/`source=audit-apply`）+ audit `resolution` + journal | CLI + serve + 前端 |
| C | `T8` 应用后提示「建议重新批阅」，复用 D171 行内 `转写+批阅` | 前端 |
| C | `T7b` 快照写入前**自动存 `_history/`** + 「撤销最后一次审计修改」 | `snapshots.py` + serve + 前端 |
| C | `T7c` roster 历史副本命名：`history/roster__<packId>__<ts>.xlsx`（写 roster 时附加） | `roster_io.py` |
| D（P2，可选） | `T9` 规则卡新增 `tagAudit`（`minScore/margin/bigramWeight/numberWeight`） | `rules.py` |
| D | `T10` `xxt review verify-names`：`students.json` 姓名 ↔ 文件名解析姓名交叉校验 | `xxt/` + CLI |

> 明确删除（v2）：~~T7 LLM 兜底~~（教师确认不需要 AI）、~~忽略名单~~、~~跨包比对~~。
> 评测集（§9）里原本的“LLM 裁决准确率”相应删掉。

---

## 9. 验收标准（v3）

1. **无噪声**数据集（`example` 例题库构造）→ 命中 **100%**；
2. 加 OCR 噪声（删 5% 字符 / 换 3% 字符 / 插圈画符）→ 命中 **≥ 90%**，
   且错判必须落在 `unknown`（**不允许“自信地判错”**，这条是红线）；
3. 同包三层、题干高度相似（同章不同参数）→ 靠**数值常量**区分正确；
4. 题块缺失 / 学生未抄题 / 转写损坏 → `unknown` + 可读原因，**进程不崩**；
5. **全程不调模型**（用 mock 断言：审计路径无 `LLMClient` 调用）；
6. 同一输入两次运行 → `tags-audit.json` 的判定部分**逐字节相同**（可复现）；
7. 应用 tag 后：`roster-tags/<packId>.json` 有 `previousTag` + `source=audit-apply`，
   audit 有 `resolution`，journal 有记录；重复应用同值 → 幂等（不重复写）；
8. **未转写**学生：审计列 `未转写`（灰、不可勾），汇总 `skippedNotTranscribed` 有值，**不混入** `unknown`；
9. **撤销**：应用审计 tag → 撤销 → `roster-tags/<packId>.json` 与改动前**逐字节相同**（除 `generatedAt` 等元信息）；
10. 每次覆盖快照前 `_history/` 里必有一份；写 roster 时若有 packId，`roster/history/` 里产生带 packId 的副本；
11. 四道门：pytest / build / selfcheck / 脱敏。

---

## 10. N1–N3 裁决（v3 已定）

| # | 教师回应 | 落地 |
|---|---|---|
| **N1** | 「改错需要可**撤销**，这也是我们作记录历史的原因」+ 新信息：**每个作业包生成后都可能关联一个 roster，其中 tag 是变动的**（例如 translation 组按比例随机点选） | ① 应用审计 tag 前**自动存历史副本**，提供「撤销最后一次审计修改」；② **roster 与快照的命名必须带时间戳 + 关联作业包名**（§10.1） |
| **N2** | 「**未转写不可进行 tag 审核**」 | 未转写 → 审计列显示 **`未转写`（灰，不可勾）**，一键审计自动跳过，汇总单列 `skippedNotTranscribed`；**不冒充 `unknown`**、不写进 audit 的判定数 |
| **N3** | 「没看懂什么是正规打印标 ?」（我上一轮表述含糊） | 见下方 §10.2 **澄清**：**不新增任何“正规打印”判定**，`?` 只表示“这一题的题干没找到”，与作业纸是否正规无关 |

### 10.1 roster / 快照的命名（教师新要求：时间戳 + 关联作业包名）

**问题事实**（已核代码）：

- `files/roster_io.write_roster` 每次都写**同一个** `roster/roster.xlsx`，只把旧的备份成
  `roster.xlsx.old-<YYYYmmdd-HHMMSS>`——**备份名里没有“当时关联的是哪个作业包”**；
- `grading/snapshots.write_tags_snapshot` 写 `roster-tags/<packId>.json`，**无时间戳**
  （同名就会被 `force=True` 覆盖，之前的历史只剩下一次改动的 `previousTag`）。

而教师的场景是：**同一份 roster，每生成一个作业包，translation 组会被重新等距点选/换人**，
于是「这个包当初是谁、什么 tag」绝不等于「今天的 roster」。**这正是审计要能对齐的东西。**

**设计**：

| 文件 | 命名 | 说明 |
|---|---|---|
| roster 主文件 | `roster/roster.xlsx` | 保持不动（唯一可写真源，前端依赖原路径） |
| roster 历史副本 | `roster/history/roster__<packId>__<YYYYmmdd-HHMMSS>.xlsx` | **每次写 roster 时若已知当前关联 packId，则额外存一份**；未知则 `roster__noPack__<ts>.xlsx` |
| 旧式备份 | `roster.xlsx.old-<ts>` | **保留**（兼容旧脚本），但不再作为审计依据 |
| tag 快照（权威） | `roster-tags/<packId>.json` | 不变（批阅按 packId 取） |
| 快照历史副本 | `roster-tags/_history/<packId>__<YYYYmmdd-HHMMSS>.json` | **每次写/改快照前自动存一份**（含 `reason`: `first-freeze` / `audit-apply` / `manual`） |

**「撤销最后一次审计修改」**：UI 列出该包 `_history/` 下 `reason=audit-apply` 的记录 →
选一条 → 用它的内容回写 `roster-tags/<packId>.json`（**同样先存一份当前状态**，防“撤销了又不满意”）。

> 命名用 **`__`（双下划线）分隔**、时间戳放末尾的原因：`packId` 可能含中文与空格，
> 用双下划线可无歧义切分；`list_*` 的实现按 `rsplit("__", 1)` 解出时间戳。

### 10.2 澄清：N3 的「正规打印」不是新功能

我上一轮写：「作业纸都带题目 … 没题目 → 标 ?」，用词让教师误解了。**准确说法只有一句**：

> 审计逐题比对时，若**学生这一题的转写里找不到题干文字**（学生没抄题 / OCR 把题干弄丢了），
> 这一题记为 `linkMissing`，列表里显示 `?`。

它**不是**在判断“这份作业是不是我们正规打印的作业纸”，也不产生任何“非正规”标记。
整份缺失导致无法下结论时，判定为 `unknown`，原因是「未定位到题干」。

另外教师原话「如果没有题目，则不是正规作业纸打印，可标记问号或 unknown」——其中「不是正规打印」
这一**因果判断引擎不做**：引擎只能看到「转写里没有题干」，看不到「这张纸是不是我们打的」。
真正的“是不是这个包的纸”，判据是**其他题的匹配得分**（全部对不上 → `unknown`，附 Top2 供教师看）。

### 10.3 N1 额外带来的一个修复（顺手，必做）

`write_tags_snapshot` 现在 `force=False` 时**静默跳过**、`force=True` 时**直接覆盖**。改为：

1. 覆盖前**必存** `_history/<packId>__<ts>.json`（理由见 §10.1）；
2. 返回结构里带 `historyPath`，前端「应用审计 tag」的回执显示“已存历史副本”；
3. `journal.jsonl` 追加一条 `{"step":"snapshot-write","reason":...,"history":...}`。

---

## 11. 实测验收结果（2026-11-06，A 批完成）

三层作业纸（同章同题、只差参数）× 每种 40 个随机种子：

| 噪声类型 | 命中率 | unknown | **误报 mismatch** |
|---|---|---|---|
| 无噪声 | **100.0%** | 0 | **0** |
| 随机删字 5% | **100.0%** | 0 | **0** |
| 删 10% + 插 10%（模拟笔迹被识别成字） | **100.0%** | 0 | **0** |
| 截断后 30% | **100.0%** | 0 | **0** |
| 组合（删 8% + 插 8% + 截 20%）+ `__` 下划线标记 | **100.0%** | 0 | **0** |
| 极端（删 20% + 截 50%） | 98.3% | 2 | **0** |

**误报 mismatch 恒为 0** —— 这是本功能的红线：宁可 `unknown`，绝不把没做错的学生标红。

### 实测中发现并修复的两个真实缺陷（对抗测试的价值）

| # | 缺陷 | 现象 | 修复 |
|---|---|---|---|
| 1 | `_verdict` 只要 `score≥minScore` 就给 `medium`，而 `mismatch` 接受 `medium` | 同包三层**只差一位参数**时 margin 仅 0.05，却把学生**自信地**判成另一层并标红 | `mismatch` **只允许 `high`**；`medium` 一律 `unknown` 并写明「领先不足 0.15」 |
| 2 | `match` 不看置信度 | 分数 0.09（完全不像）但 Top1 恰好同 tag → 报绿 | `low` 时即使同 tag 也判 `unknown`（"碰巧对上"不算证据） |

### 另修的覆盖率问题

原公式 `cov = min(1, 学生题数/纸题数)` 是**单向**的：学生只抄了第 1 题 → 与「只印 1 题的短卷」完美匹配。
改为双向（两个方向都取 min 再平均），并保留 `final = S × (0.6 + 0.4·cover)`。

---

## 12. 与既有文档的接口

- D168 §3（快照）：本需求**补丁式**写快照，`source` 新增 `audit-apply`；
- D169（架构铁律）：审计算法在**引擎**（CLI 与 PWA 同源），前端只渲染；写盘只在引擎；
- D171（批阅三键/强制重做）：本需求**不改**批阅按钮语义；
- 版本：新能力 → **engine/app 版本 0.6.0**（按 `docs/114-versioning.md`）。


---

## 13. 实施记录（2026-11-06）

### 13.1 交付清单

| 项 | 文件 / 命令 | 状态 |
|---|---|---|
| T1 匹配器（题块切分 + n-gram/数值打分 + 背靠背最优分配） | `engine/src/assist/grading/tag_audit.py` | ✅ |
| T2 CLI | `assist grading audit-tags` / `apply-audit-tags` / `undo-audit-tags` | ✅ |
| T3 单测 | `engine/tests/test_d172_tag_audit.py`（**48 项**） | ✅ |
| T4 HTTP | `GET /grade/audit-tags`（**在 `do_GET`**）、`POST .../run|apply|undo` | ✅ |
| T5 前端审计列 + 整行高亮 + 明细弹窗 | `AiGradingPanel.vue` | ✅ |
| T6 selfcheck | `app/tests/selfcheck-d172-tag-audit.mjs` | ✅ |
| T7 逐人/批量应用 + 补丁式写快照 | `apply_audit_tags()` | ✅ |
| T7b 历史副本 + 撤销 | `roster-tags/_history/<packId>__<ts>.json`、`undo-audit-tags` | ✅ |
| T7c roster 历史命名 | `roster/history/roster__<packId>__<ts>.xlsx` | ✅ |
| T8 应用后提示重新批阅 | 复用 D171 行内「转写+批阅」 | ✅ |
| T9 规则卡 `tagAudit` | `rules.tag_audit_cfg()` + 校验（越界/未知字段/权重和为 0） | ✅ |
| T10 姓名交叉校验 | `assist xxt verify-names` | ✅ |

### 13.2 端到端实测（3 名学生）

| 学生 | roster tag | 实际做题 | 审计结论 | 说明 |
|---|---|---|---|---|
| 张三 | 提高 | 基础卷（**含 3% OCR 噪声**） | `基础` / high / **mismatch** 0.8978 | 正确标红 |
| 李四 | 提高 | 提高卷 | `提高` / high / match 1.0 | 正确标绿 |
| 王五 | 基础 | **未转写** | — | 进 `skippedNotTranscribed`，**不冒充 unknown** |

### 13.3 实施中又发现并修掉的 4 个缺陷

| # | 缺陷 | 后果 | 修复 |
|---|---|---|---|
| 3 | `papers_of()` 不可重入（两种形状都往这传） | CLI 走 `--pads` 时题干被二次归一变空 → **分数全 0** | 归一幂等（同时认 `stem` 与 `content`），加回归测试 |
| 4 | `apply` 的备份没记 `source` | 撤销时找不回“被审计改过的状态” | 副本增加 `snapshotSource`（这份副本本身是哪个来源）；撤销回写时剔除历史元字段 |
| 5 | `undo` 会把 `snapshotSource` 写进正式快照 | 快照被污染 | 回写前剔除全部 `_META` 字段 |
| 6 | `validate_rules` 不校验顶层 `tagAudit` | 规则卡写 `minScore: 5` 也能存进去 | 补校验（范围/未知字段/权重和 > 0） |

### 13.4 版本

`engine` / `app` → **0.6.0**（按 `docs/114-versioning.md`）。
