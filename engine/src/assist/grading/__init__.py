"""AI 批阅引擎（阶段3）：transcribe → evaluate → report + journal。

X--- 迁移源（07：迁移为主，prompt 层局部重写）：
- llm.py     ← _legacy/2601playwright/src/llm/client.py（requests→httpx，key 从 workspace settings.local.json 读）
- transcribe.py ← _legacy/2601playwright/src/llm/transcriber.py（prompt 原样迁移）
- evaluate.py   ← _legacy/2601playwright/src/llm/evaluator.py（prompt 升级为绑定任务包题目+solution）
- report.py     ← _legacy/2601playwright/src/report_generator.py（MD/HTML，PNG 留到阶段4 Playwright）
- flow.py    ← _legacy/2601playwright/src/grader.py 的编排（学习通部分→阶段4 TODO）
"""

from .flow import run_task, run_step  # noqa: F401
