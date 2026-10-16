"""D90：LLM Playground —— 单次调用大模型做试验（无多轮对话上下文）。

- extract：附件（图片/文档）→ 文本或 data-url；
- ask：问题（+附件）→ 一次 LLM 调用 → 回复；
- store：问题与答案本地留档 + 文件夹/记录管理（<ws>/playground/）。

复用 D86 provider/两段式与 key 安全；不新增依赖（pdf 用 pypdf，docx 用 zip+xml）。
"""
