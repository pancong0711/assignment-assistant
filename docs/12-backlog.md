# 12 — 未完成工作总览（2026-09-21 · 检测反馈后重整）

> 按模块整理所有已登记未完成事项 + 今日反馈新增；推进顺序见文末。
> 与 docs/06-roadmap.md 的阶段编号互引；冲突时以本文档为准（更新时同步 06）。

## A · 阶段 4a 收尾（小、纯缝合）

- A1 LAN `--lan --token` 模式下 PWA 体检/在线 chip 带 token（engineClient 补 query）；
- A2 selfcheck 入 CI：app/tests（watermark-doctor/family/lan-selftest）在 GitHub
  Actions 跑（现在 pages.yml 只 build+deploy）；顺带加 engine pytest；
- A3 /doctor 检查项 name 定版（PWA 端按 name 归并，改名自动追加——避免歧义）；
- A4（需你配合）真实 LLM key 跑 `assist grade` 一次，回提 prompt/评分口径反馈；
- A5 预览水印与引擎打印的一致性复核（今日已修"预览不显水印"兜底与虚线，待复测）。

## B · 阶段 5（M5 补强 + 作业纸多类型个性化 + 后勤）

- B1 rainclass 签到明细分析迁 engine（`assist roster rain`）；多 sheet 成绩源；
- B2 名单↔成绩学号匹配回退（现按姓名）；
- B3 fig 题图上传 UI + 引擎写回（OPFS→workspace），题库编辑器配图闭环；
- B4 SheetJS 写回 xlsx 样式丢失 → 引擎 openpyxl 补样式；
- B5 便携引擎包（Releases：engine-portable-<platform>.zip，D5/D14）；
- B6 教师使用手册 + Pages 用户教程 + 卸载指引；手机第二屏细化（D9）；
- **B7（今日新增，重点）多类型/多层作业纸的"变体编排"**：
  目标 = 旧 2603 build_cfg_list 的网页化——按 tag 生成多份变体任务包、
  自动绑定 roster 分组（tag→任务包 映射表），一键发"每组不同的作业纸"。
  设计要点：
  1. taskpad 增加 `variant_of/组标签 field`（或独立"变体组"store）；
  2. 班级与成绩页导出时可直接生成 "tag→任务包id" 映射 JSON；
  3. 引擎 `assist sheet batch --roster tagged.xlsx` 按 tag 自动选用
     对应任务包出 PDF（每生取其 tag 对应的变体）。
- B8 Windows 实测批阅→ 反馈 prompt（需你配合，可提前）。

## C · 阶段 6（学习通，最后；D22 已拍板）

C1 登录/课程/作业浏览/下载（迁 2601 xuexitong 模块）；C2 上传=评语+图片+
自动打分（D7）+可选预览确认+三代上传策略择优；C3 grade flow download/upload
挂点补齐；C4 公告/通知（含附件）；C5 serve --https、PNG 截图。

## D · 验证/卫生

- D1 `app/dist-lan` 已移出库；确认无其他构建产物残留；
- D2 demo `sheet demo` 输出目录目前是 kb/.demo，应改走 classes/<class>/sheets/out；
- D3 bundle 拆分（SheetJS/JSZip 异步 chunk）；
- D4 Windows 实批（测试同学）。

## 推进顺序（方向）

1. **A 全清**（半天：A1/A2/A3 引擎+CI 缝合；A5 复测等你的反馈）；
2. **B1+B2+B3**（M5 精化：rainclass、学号回退、题图 UI）；
3. **B3.5 变体编排**（今日反馈 #3 的正解设计：见后文"变体方案"小节）；
4. B4/B5/B7（样式回写、便携包、手册）；
5. 阶段 6 学习通（真实账号配合一次性收尾）。

## 变体方案（B3.5 设计草案，先讨论后实施）

**目标**（对齐旧 2603 的 build_cfg_list 多套变体轮换，D23 落位阶段5）：
- 概念：一个"作业集"= N 份任务包（每份可对应不同 tag 集合/题量/版式）；
- 班级与成绩产出后，每生携带 tag → 引擎按 `tag→任务包` 映射自动选择
  变体（`assist sheet batch`），同一 tag 内题/人顺序可轮换防抄袭；
- PWA：DesignerView 增"变体组"概念（清单多选）与"按 tag 分配"面板；
  预览/导出保持现单任务包不变，仅新增"组"概念；
- 现阶段可用的操作路径（无需等开发）：
  1. 任务包清单里为每个 tag 各建一份任务包（横竖版/题量随意），
     标注在 id/标题上；
  2. 导出全部 zip 后在本机跑 `assist sheet make --task <各名册对应用包> --roster <tagged名单>`
     按班级分发；手动往复。变体编排上线后此流程自动化。
- 跨 kind 题：任务包 items 里 kind 与 tag 本就独立（你可以 browse problems
  同时 tag=copy）；若你遇到"不能实现"，多半是操作路径不直观——设计改造为
  "按 tag 提选题篮（跨 kind/章）+ 存为变体"。

## 今天的代码修正（已提交 9d4ff5d + 4021649）

| 反馈 | 修正 |
|---|---|
| 1 水印预览不显 | 预览兜底：items 空 → legacy 三槽占位（rt/lc/lb 与引擎一致）；items 有 → dataURL 真图预览 |
| 2 预览/印刷版式 | 网格语义定版：4=十字 2×2；横版 2/3=左右栏；竖版 2/3=上下行；**所有分隔线改虚线**（引擎 onPage setDash(4,3)，预览覆盖层 repeating-linear-gradient），不穿页眉页脚；预览不再画题目外框 |
| 3 多类型/变体 | 见"变体方案"（跨 kind/tag 任务包构建现可用；变体编排待实施） |
| 4 名单页排版 | 头部说明卡移除，特殊标签栏常显；导入/手动/批量/清空全部集中于此，位于产出栏之前 |
