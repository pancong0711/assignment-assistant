"""D98-B7：`grade plan/collect` —— 无 LLM 的"清单/收作业"通道（兜底，非默认）。

用途（docs/51 §7.4）：**没有 API key、也没有 command/subagent**时，让 agent（或教师）
自己完成 LLM 部分，程序只负责：

1. `plan`：按 plan/图片生成每位学生的**任务清单**（任务 id、图片绝对路径、输出路径、
   **填好的提示词**），写成 `agent-tasks/*.md` + `task-list.json`；不调模型；
2. `collect`：读取 agent 写回的 `transcripts/<id>.json`（或 evaluations），
   做**结构校验**、生成 `batch-report.json`（谁交、谁缺、谁格式错）。

**必须向用户说明"现在发生了什么"**：输出明确列出"正文由 agent 自己做、程序只校验"。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .items import ItemsError, normalize_items
from ..filelock import atomic_write_text


def build_task_list(*, items: list[dict], out_dir: Path, kind: str,
                    prompt_template: str, system: str = "") -> dict:
    """生成任务清单：`task-list.json` + 每生一个 `agent-tasks/<id>.md`。"""
    out_dir = Path(out_dir)
    tasks_dir = out_dir / "agent-tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for it in items:
        prompt = prompt_template.replace("{id}", str(it.get("id") or "")) \
                                 .replace("{images}", "\n".join(it.get("images") or [])) \
                                 .replace("{question}", str(it.get("question") or ""))
        md = "\n".join([
            f"# {kind} 任务：{it.get('id')}",
            "",
            f"- 图片（本任务专属，**不要**读其它学生的图）：{len(it.get('images') or [])} 张",
            *[f"  - `{p}`" for p in (it.get("images") or [])],
            f"- 输出文件（必须写入）：`{it.get('outputPath')}`",
            "",
            "## 提示词",
            "```",
            prompt,
            "```",
            "",
            "## 输出格式",
            "写一个 JSON 文件，至少包含 `{\"markdown\": \"...\", \"quality\": {...}}`"
            "（转录）或 schema 指定的评阅结构（评阅）。",
        ])
        p = tasks_dir / f"{it.get('id')}.md"
        atomic_write_text(p, md)
        tasks.append({**it, "prompt": prompt, "taskFile": str(p)})
    report = {
        "kind": kind, "mode": "plan-collect",
        "notice": "程序**不调用任何模型**：正文需由 agent/教师完成，程序只校验与算分。",
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(tasks), "tasks": tasks,
    }
    atomic_write_text(out_dir / "task-list.json",
                      json.dumps(report, ensure_ascii=False, indent=1))
    return report


_REQUIRED_TRANSCRIPT = ("markdown",)


def collect(*, task_list: dict, results_dir: Path, kind: str = "transcribe") -> dict:
    """校验 agent 写回的结果，生成 batch-report.json。

    - transcribe：每任务读 `results_dir/<id>.json`，要求有 `markdown`；
    - 缺文件/JSON 坏/缺字段 → 该条 fail（不中断）。
    """
    results_dir = Path(results_dir)
    items = []
    ok_n = 0
    for t in (task_list.get("tasks") or []):
        iid = str(t.get("id"))
        f = results_dir / f"{iid}.json"
        if not f.is_file():
            items.append({"id": iid, "status": "fail", "error": "结果文件缺失"})
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            items.append({"id": iid, "status": "fail", "error": f"JSON 解析失败：{exc}"})
            continue
        if kind == "transcribe":
            missing = [k for k in _REQUIRED_TRANSCRIPT if not str(data.get(k) or "").strip()]
            if missing:
                items.append({"id": iid, "status": "fail",
                              "error": f"缺少字段：{missing}"})
                continue
        ok_n += 1
        items.append({"id": iid, "status": "ok", "out": str(f)})
    report = {
        "kind": kind, "mode": "plan-collect",
        "finishedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(items), "ok": ok_n, "failed": len(items) - ok_n,
        "items": items,
    }
    atomic_write_text(results_dir.parent / "batch-report.json",
                      json.dumps(report, ensure_ascii=False, indent=1))
    return report


def plan_items_from_plan(ws: Path, *, task_id: str, class_dir: str,
                         transcripts_out: Path) -> list[dict]:
    """由批阅 plan.json 生成转录 items（每生一条，图片来自 plan.students[].images）。"""
    from . import inputs as _inputs
    plan = _inputs.load_plan(ws, task_id, class_dir) or {}
    raw = []
    for s in (plan.get("students") or []):
        if not s.get("name"):
            continue
        raw.append({"id": str(s["name"]), "question": "", "images": list(s.get("images") or []),
                    "meta": {"tag": s.get("tag"), "workAnswerId": s.get("workAnswerId")}})
    items = normalize_items(raw) if raw else []
    for it in items:
        it["outputPath"] = str(Path(transcripts_out) / f"{it['id']}.json")
    return items
