"""flow.py — 批阅流程编排（任务包 grade 节驱动）。

迁移自 _legacy/2601playwright/src/grader.py 的 grade_batch 编排骨架：
- steps=["transcribe","evaluate","report"]（download/upload 属阶段4，留 TODO）；
- 产物落 docs/04 §1 结构：classes/<class>/grading/<task>/；
- D8：journal（journal.jsonl）记录每次执行的步骤/参数/日志，使任务包成为
  执行历史；`--rerun <step>` 从 journal 读参数单步重跑（最小实现）。

阶段入口（直接写代码的调用方）：
    run_task(task_path, ws, images_dir=..., rerun="report")
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from loguru import logger

from ..files.kb_io import read_kb
from .evaluate import evaluate_student
from .report import generate_global_report, generate_report, generate_summary_xlsx
from .transcribe import group_images, transcribe_student

STEPS = ["download", "transcribe", "evaluate", "report", "upload"]


# ---- 任务包展开：升级 resolve_items —— 同时携带参考答案 solution ----
def expand_items(ws: Path, task: dict) -> list[dict]:
    """任务包 items [{kb,chap,ids,tag}] → [{序号, content, solution, tag}]。

    展开逻辑迁移自 engine paper/task.resolve_items（同源：2603 kbtools._oneChap），
    在此增加 solution 字段（题库 solution 列）供评阅 prompt 绑定。
    """
    kb_dir = ws / "kb"
    kb_data = read_kb(kb_dir)
    out: list[dict] = []
    idx = 0
    for spec in task.get("items", []):
        kind = spec.get("kb", "problems")
        chap = spec.get("chap")
        ids = spec.get("ids")
        tag = spec.get("tag", spec.get("kb", "problems"))
        chapters = kb_data.get(kind, {})
        entries = list(chapters.get(chap, [])) if chap else \
            [e for chs in chapters.values() for e in chs]
        if ids:
            entries = [e for e in entries if str(e.get("id")) in {str(i) for i in ids}]
        for e in entries:
            idx += 1
            img = e.get("img_path")
            if img and not str(img).startswith("/"):
                img = str(kb_dir / str(img))
            out.append({"序号": idx, "content": e.get("content", ""),
                        "solution": e.get("solution", ""), "tag": tag, "img": img})
    if not out:
        logger.warning("任务包未选中任何题目")
    return out


def grading_dir(ws: Path, task: dict) -> Path:
    d = ws / task.get("class_dir", "classes") / "grading" / str(task.get("id", "task"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def journal_append(journal_file: Path, record: dict) -> None:
    """D8：每次执行追加一行运行记录（时间戳/步骤/参数/状态）。"""
    with open(journal_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def journal_records(journal_file: Path) -> list[dict]:
    if not journal_file.exists():
        return []
    out = []
    for ln in journal_file.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return out


def _paths(base: Path) -> dict[str, Path]:
    return {k: base / d for k, d in
            (("images", "images"), ("transcripts", "transcripts"),
             ("evaluations", "evaluations"), ("reports", "reports"))}


def _run_transcribe(ctx: dict, client, transcripts_dir: Path) -> list[Path]:
    images_dir: Path = ctx["images_dir"]
    groups = group_images(images_dir)
    if not groups:
        logger.warning(f"图片目录为空（无 .png/.jpg 等文件），跳过转录: {images_dir}")
        return []
    model = (ctx["task"].get("grade", {}).get("models", {}) or {}).get("transcription")
    outs = []
    for student, imgs in sorted(groups.items()):
        logger.info(f"[转录] {student}（{len(imgs)} 张）")
        outs.append(transcribe_student(client, imgs, student, transcripts_dir, model=model))
    return outs


def _run_evaluate(ctx: dict, client, evaluations_dir: Path) -> list[Path]:
    tasks_items = ctx["items"]
    model = (ctx["task"].get("grade", {}).get("models", {}) or {}).get("evaluation")
    outs = []
    for tf in sorted(ctx["transcripts_dir"].glob("[!_]*.json")):
        try:
            outs.append(evaluate_student(client, tf, tasks_items, evaluations_dir,
                                         homework_name=ctx.get("homework", ""), model=model))
            logger.info(f"[评阅] OK {tf.stem}")
        except Exception as e:  # noqa: BLE001 —— 单生失败不阻断全班
            logger.error(f"[评阅] FAIL {tf.stem}: {e}")
            journal_append(ctx["journal"], {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "run_id": ctx["run_id"], "step": "evaluate",
                "student": tf.stem, "status": "fail", "error": str(e)[:300]})
    return outs


def _run_report(ctx: dict, reports_dir: Path) -> list[Path]:
    outs = []
    for tf in sorted(ctx["transcripts_dir"].glob("[!_]*.json")):
        ef = ctx["evaluations_dir"] / f"{tf.stem}.json"
        if not ef.exists():
            logger.warning(f"[报告] skip {tf.stem}: 无评阅文件")
            continue
        outs += generate_report(tf, ef, reports_dir)
    summary = generate_summary_xlsx(ctx["evaluations_dir"], reports_dir / "summary.xlsx")
    outs.append(summary)
    g = generate_global_report(ctx["evaluations_dir"], reports_dir / "_global_report.md")
    if g:
        outs.append(g)
    return outs


def run_task(task_path: Path, ws: Path, images_dir: Path | None = None,
             rerun: str | None = None) -> dict:
    """任务包 grade 节驱动的执行入口。

    Args:
        task_path: 任务包 JSON。
        ws: workspace 根目录。
        images_dir: 学生作业图片目录（本地批阅；阶段4 download 自动填充）。
        rerun: 指定单个 step 名 → 只重跑该步（参数 Recovery 自 journal）。
    """
    task_path = Path(task_path).expanduser().resolve()
    task = json.loads(task_path.read_text(encoding="utf-8"))
    grade_cfg = task.get("grade", {}) or {}
    steps = grade_cfg.get("steps", ["transcribe", "evaluate", "report"])
    if not steps:
        raise ValueError("任务包 grade.steps 为空（=仅出作业纸，无需批阅）")

    base = grading_dir(ws, task)
    p = _paths(base)
    journal = base / "journal.jsonl"
    run_id = time.strftime("%Y%m%d-%H%M") + "-" + uuid.uuid4().hex[:6]

    # download 上传（阶段4 TODO）：学习通下载学生图片 / 批阅回传
    # TODO(stage4): "download" in steps → 从学习通拉取图片到 p["images"]
    # TODO(stage4): "upload" in steps → 按题型回传评语+图片+自动打分（D7）
    if "download" in steps:
        logger.warning("download（学习通下载）属阶段4 暂未实现，依赖 --images 本地图片目录。")

    ctx = {
        "task": task,
        "task_path": task_path,
        "homework": task.get("course", "") + " " + str(task.get("id", "")),
        "items": expand_items(ws, task),
        "images_dir": Path(images_dir).expanduser().resolve() if images_dir else p["images"],
        "transcripts_dir": p["transcripts"],
        "evaluations_dir": p["evaluations"],
        "reports_dir": p["reports"],
        "evaluations": p["evaluations"],  # alias
        "journal": journal,
        "run_id": run_id,
    }

    to_run = [rerun] if rerun else steps
    for step in to_run:
        if step not in STEPS:
            raise ValueError(f"未知 step: {step}（可选 {STEPS}）")
        record = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "run_id": run_id,
            "step": step,
            "status": "running",
            "params": {"task": str(task_path), "images_dir": str(ctx["images_dir"]),
                       "bucket": str(base)},
        }
        journal_append(journal, record)
        produced = []
        try:
            if step == "transcribe":
                # transcribe 需要有效 LLM 配置；images 为空则告警跳过
                from .llm import LLMClient
                client = LLMClient(ws=ws)
                produced = [str(x) for x in _run_transcribe(ctx, client, p["transcripts"])]
            elif step == "evaluate":
                if not any(ctx["transcripts_dir"].glob("*.json")):
                    raise RuntimeNotFoundError(ctx["transcripts_dir"])
                from .llm import LLMClient
                client = LLMClient(ws=ws)
                produced = [str(x) for x in _run_evaluate(ctx, client, p["evaluations"])]
            elif step == "report":
                produced = [str(x) for x in _run_report(ctx, p["reports"])]
            else:
                raise RuntimeError(f"step '{step}' 属阶段4（TODO），暂不实现")
        except Exception as e:
            record["status"] = "fail"
            record["error"] = str(e)[:500]
            journal_append(journal, record)
            raise
        record["status"] = "ok"
        record["outputs"] = produced
        journal_append(journal, record)
        logger.info(f"[{step}] 完成，产物 {len(produced)} 项")

    # run 汇总记录（D8：任务包 = 执行历史；任务包内 journal 数组不入库但存在于工作区副本）
    summary_rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "run_id": run_id,
                   "step": "run", "steps_done": to_run, "status": "done",
                   "bucket": str(base)}
    journal_append(journal, summary_rec)
    return summary_rec


class RuntimeNotFoundError(RuntimeError):
    """评估前置产物缺失（转录不存在）。"""


def run_step(task_path: Path, ws: Path, step: str, images_dir: Path | None = None) -> dict:
    """--rerun 单步（最小实现）：等价 run_task(rerun=step)，参数同 journal。"""
    return run_task(task_path, ws, images_dir=images_dir, rerun=step)
