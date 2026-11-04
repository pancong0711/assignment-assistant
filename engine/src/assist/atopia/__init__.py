"""Assistopia（D132）：AI 调用本项目工具的**安全工作区**。

模块划分：
- `registry`：工具白名单 + 分级（L0 只读 / L1 预览 / L2 写入 / L3 危险不开放）
- `runner`  ：执行器（子进程 + 超时 + 输出截断 + journal）
- `limits`  ：护栏（调用次数 / 时长 / L1 成本）
- `extensions`：`<ws>/extensions/` 覆盖加载（**只能更严**）

安全原则见 docs/81 §2/§5：默认拒绝、L3 写死不可开通、扩展只能提级。
"""
