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

    D89-N3：solution **实时从 kb/solutions/<qid>.json 取最新置顶版**（无版本库时回落 xlsx 列）。
    """
    from ..files.solutions import effective_solution
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
            qid = str(e.get("id") or "")
            fallback = str(e.get("solution", "") or "")
            eff = effective_solution(ws, qid, fallback) if qid else {"text": fallback}
            out.append({"序号": idx, "content": e.get("content", ""),
                        "solution": eff.get("text", fallback), "tag": tag, "img": img})
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


def _diag(ctx: dict, **fields) -> None:
    """D86：诊断信息落盘（provider/模型/mode/错误原文），便于教师把它发回来排查。"""
    import json as _json
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "taskId": (ctx.get("task") or {}).get("id"),
           "mode": ctx.get("mode") or "optimized", "run_id": ctx.get("run_id")}
    row.update({k: v for k, v in fields.items() if v is not None})
    try:
        with open(ctx["diag"], "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _plan_student_images(ctx: dict) -> "dict[str, list]":
    """plan 模式下 学生→图片 路径（绝对路径直接可用）。"""
    from pathlib import Path as _P
    out: dict = {}
    for stu in ((ctx.get("plan") or {}).get("students") or []):
        imgs = [_P(x) for x in (stu.get("images") or [])]
        if stu.get("name") and imgs:
            out[str(stu["name"])] = imgs
    return out


def _run_transcribe(ctx: dict, client, transcripts_dir: Path) -> list[Path]:
    """D98-B4：改为 batch（items 逐条独立 + 并发 + 执行报告）。

    - 每名学生一个 item（同生多页在 images 内，同一次请求）；
    - 单生失败**标记该条并继续**其余（用户裁决 6），不再整批中断；
    - 报告写 `<grading>/batch-report.json`。
    """
    from .items import normalize_items
    from .transcribe import transcribe_batch

    model = (ctx["task"].get("grade", {}).get("models", {}) or {}).get("transcription")
    plan_groups = _plan_student_images(ctx) if ctx.get("plan") else {}
    if plan_groups:
        groups = plan_groups
        logger.info(f"[转录] plan 模式：{len(groups)} 名学生")
    else:
        images_dir: Path = ctx["images_dir"]
        groups = group_images(images_dir)
        if not groups:
            logger.warning(f"图片目录为空（无 .png/.jpg 等文件），跳过转录: {images_dir}")
            return []

    items = normalize_items([
        {"id": student, "question": "请转录这份物理作业图片", "images": [str(p) for p in imgs]}
        for student, imgs in sorted(groups.items())
    ])
    concurrency = int(ctx.get("concurrency") or 3)
    report = transcribe_batch(client, items, transcripts_dir, model=model,
                              concurrency=concurrency,
                              emit=lambda line: logger.info(f"[转录] {line}"))
    for it in report.get("items") or []:
        if not it.get("ok"):
            _diag(ctx, step="transcribe", student=it.get("id"), error=it.get("error"),
                  images=it.get("images") or [])
    if report.get("failed"):
        logger.warning(f"[转录] {report['failed']}/{report['total']} 名学生失败（已标记，继续后续步骤）")
    return [Path(it["out"]) for it in (report.get("items") or []) if it.get("ok") and it.get("out")]


def _plan_items_for(ctx: dict, student: str) -> "list[dict] | None":
    """plan 模式下该生的题目（转成 evaluate 期望的 {序号,content,solution,tag} 形状）。"""
    for stu in ((ctx.get("plan") or {}).get("students") or []):
        if str(stu.get("name")) != student:
            continue
        out = []
        for i, q in enumerate(stu.get("questions") or [], start=1):
            out.append({"序号": q.get("no") or i, "content": q.get("content") or "",
                        "solution": q.get("solution") or "", "tag": stu.get("tag") or ""})
        return out or None
    return None


def _run_evaluate(ctx: dict, client, evaluations_dir: Path) -> list[Path]:
    tasks_items = ctx["items"]
    model = (ctx["task"].get("grade", {}).get("models", {}) or {}).get("evaluation")
    outs = []
    for tf in sorted(ctx["transcripts_dir"].glob("[!_]*.json")):
        items = _plan_items_for(ctx, tf.stem) if ctx.get("plan") else None
        try:
            outs.append(evaluate_student(client, tf, items or tasks_items, evaluations_dir,
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
        kind = "human" if str(ctx.get("report_kind") or "").startswith("human") else "ai"
        outs += generate_report(tf, ef, reports_dir, kind=kind,
                                subtitle=str((ctx.get("plan") or {}).get("classDir") or ""))
    summary = generate_summary_xlsx(ctx["evaluations_dir"], reports_dir / "summary.xlsx")
    outs.append(summary)
    g = generate_global_report(ctx["evaluations_dir"], reports_dir / "_global_report.md")
    if g:
        outs.append(g)
    return outs


def run_task(task_path: Path, ws: Path, images_dir: Path | None = None,
             rerun: str | None = None, plan: "dict | None" = None,
             mode: str = "") -> dict:
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
        "plan": plan,
        "mode": (str(mode) or (plan or {}).get("mode") or "optimized"),
        "diag": base / "diagnostics.jsonl",
        "report_kind": (plan or {}).get("reportKind") or "ai",
        "concurrency": int((grade_cfg.get("concurrency") or 3)),
    }
    if plan:
        students = (plan.get("students") or [])
        logger.info(f"plan 模式：{len(students)} 名学生（mode={ctx['mode']}，"
                    f"tags={plan.get('tags')}）")

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
                _accum_usage(ctx, "transcribe", client)
            elif step == "evaluate":
                if not any(ctx["transcripts_dir"].glob("*.json")):
                    raise RuntimeNotFoundError(ctx["transcripts_dir"])
                from .llm import LLMClient
                client = LLMClient(ws=ws)
                produced = [str(x) for x in _run_evaluate(ctx, client, p["evaluations"])]
                _accum_usage(ctx, "evaluate", client)
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

    # D86 §6：批阅完成后把结果落成"本地批阅草稿"（PWA 人工批阅栏可直接查看/修改/一键上传）
    if plan:
        cid = str((plan.get("classId") or "")).strip()
        wid = str((plan.get("workId") or "")).strip()
        if cid and wid:
            try:
                from .drafts import save_drafts_from_grading
                saved = save_drafts_from_grading(ws, class_id=cid, work_id=wid,
                                                 task_id=str(task.get("id") or "task"),
                                                 class_dir=str(plan.get("classDir") or ""),
                                                 kind=str(ctx.get("report_kind") or "ai"))
                logger.info(f"[草稿] 已写入本地批阅草稿 {saved.get('count')} 份（kind={ctx.get('report_kind')}）")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[草稿] 写入本地草稿失败（不影响批阅结果）：{str(exc)[:160]}")

    # run 汇总记录（D8：任务包 = 执行历史；任务包内 journal 数组不入库但存在于工作区副本）
    summary_rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "run_id": run_id,
                   "step": "run", "steps_done": to_run, "status": "done",
                   "bucket": str(base), "usage": ctx.get("usage") or {}}
    journal_append(journal, summary_rec)
    return summary_rec


def _accum_usage(ctx: dict, step: str, client) -> None:
    """D98：把本步 client 的 token 用量并入 ctx（最终写入 run summary / journal）。"""
    try:
        u = client.usage_summary() if hasattr(client, "usage_summary") else {}
    except Exception:  # noqa: BLE001
        u = {}
    if not u:
        return
    usage = ctx.setdefault("usage", {})
    step_u = usage.setdefault(step, {"prompt_tokens": 0, "completion_tokens": 0,
                                     "total_tokens": 0, "calls": 0})
    for k in ("prompt_tokens", "completion_tokens", "total_tokens", "calls"):
        step_u[k] = int(step_u.get(k, 0)) + int(u.get(k, 0) or 0)
    usage["total"] = {k: sum(int((v or {}).get(k, 0) or 0) for v in usage.values()
                             if isinstance(v, dict))
                      for k in ("prompt_tokens", "completion_tokens", "total_tokens", "calls")}


class RuntimeNotFoundError(RuntimeError):
    """评估前置产物缺失（转录不存在）。"""


def run_step(task_path: Path, ws: Path, step: str, images_dir: Path | None = None,
             **kwargs) -> dict:
    """--rerun 单步（最小实现）：等价 run_task(rerun=step)，参数同 journal。"""
    return run_task(task_path, ws, images_dir=images_dir, rerun=step, **kwargs)
