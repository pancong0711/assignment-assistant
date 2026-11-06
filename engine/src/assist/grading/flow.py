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


class GradingInputError(RuntimeError):
    """D118：批阅输入不满足前提（如 plan 模式下没有任何学生作答图）。

    与 RuntimeNotFoundError（评估前置产物缺失）区分：本类是**输入侧**问题，
    CLI/serve 应把它作为"可读的业务错误"呈现，而不是异常堆栈。
    """

STEPS = ["download", "transcribe", "evaluate", "report", "upload"]


# ---- 任务包展开：升级 resolve_items —— 同时携带参考答案 solution ----
def expand_items(ws: Path, task: dict) -> list[dict]:
    """任务包 items [{kb,chap,ids,tag}] → [{序号, content, solution, tag}]。

    展开逻辑迁移自 engine paper/task.resolve_items（同源：2603 kbtools._oneChap），
    在此增加 solution 字段（题库 solution 列）供评阅 prompt 绑定。

    D89-N3：solution **实时从 kb/solutions/<qid>.json 取最新置顶版**（无版本库时回落 xlsx 列）。
    """
    from ..files.solutions import effective_solution
    from .rules import normalize_kind
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
        # D110：保留 (chap, entry) 配对，答案按作用域取，避免跨章同号串答案
        pairs = ([(chap, chapters.get(chap, []))] if chap
                 else list(chapters.items()))
        if ids:
            from ..paper.task import item_id_matches
            want = [str(i) for i in ids]
            pairs = [(c, [e for e in es if item_id_matches(str(c), want, e.get("id"))])
                     for c, es in pairs]
        for cname, entries in pairs:
            for e in entries:
                idx += 1
                img = e.get("img_path")
                if img and not str(img).startswith("/"):
                    img = str(kb_dir / str(img))
                qid = str(e.get("id") or "")
                fallback = str(e.get("solution", "") or "")
                eff = (effective_solution(ws, qid, fallback, kb=kind, chap=cname)
                       if qid else {"text": fallback})
                # D105：批阅 prompt 用纯文本（text_plain），md+html 仅用于显示
                sol_text = str(eff.get("text_plain") or eff.get("text") or fallback)
                out.append({"序号": idx, "content": e.get("content", ""),
                            "solution": sol_text, "tag": tag, "img": img,
                            # D127：题库「关联知识点」列 → 评阅时的知识点提示
                            "related": str(e.get("related") or ""),
                            # D130-T0：**题目来源**（题库表名）→ 决定评阅范式与扣分算法。
                            # 此前 `kind = spec.get("kb")` 已算出却没写入输出，评阅端拿不到。
                            "kb": str(e.get("kb") or kind),
                            "kind": normalize_kind(str(e.get("kb") or kind)),
                            "chap": str(cname or "")})
    if not out:
        logger.warning("任务包未选中任何题目")
    return out


def grading_key(task: dict) -> str:
    """D127：批阅产物目录名 —— **作业包 id 优先**。

    作业包是唯一作业批次载体（单张作业纸也入包）；同一包内不同 tag 的作业纸
    必须落在**同一目录**，否则转写/评阅/草稿会随作业纸分裂。
    无 `pack_id` 时回退旧的作业纸 id（兼容历史任务包，由迁移命令处理）。
    """
    pk = str(task.get("pack_id") or "").strip()
    if pk:
        return pk
    return str(task.get("id", "task"))


def grading_scope_id(task: dict, plan: "dict | None" = None) -> str:
    """D127-FIX：批阅**作用域 id**（= 草稿/转写/评阅/报告目录键）。

    必须与 `grading_dir()` 的口径**完全一致**，否则会出现
    「写在 grading/<padId>/drafts、却按 grading/<packId>/drafts 去读」→
    逐生审核显示"暂无转写内容"，而文件夹里明明有 json。
    优先级：plan.packId > task.pack_id > task.id（历史兼容）。
    """
    pk_plan = str(((plan or {}).get("packId") or "")).strip()
    if pk_plan:
        return pk_plan
    return grading_key(task)


def grading_dir(ws: Path, task: dict) -> Path:
    """批阅产物目录：`<ws>/<class_dir>/grading/<packId>/`（D127）。

    D121：**拒绝** class_dir 为空/为 `"classes"` 的调用——旧实现会拼出
    `<ws>/grading/`（空串塌掉）或 `<ws>/classes/grading/`（回退值）两个假目录。
    """
    class_dir = str(task.get("class_dir") or "").strip().strip("/")
    if not class_dir or class_dir == "classes":
        raise ValueError(
            f"批阅产物目录不合法：class_dir={class_dir!r}。"
            f"必须是具体班级目录（如 classes/化工25）；"
            f"请先在「AI 辅助批阅」② 区完成学习通班级 ↔ 本地班级目录的关联。"
        )
    d = Path(ws) / class_dir / "grading" / grading_key(task)
    # 兜底：结果必须在 <ws>/classes/ 之下
    root = (Path(ws).resolve() / "classes")
    try:
        d.resolve().relative_to(root)
    except Exception:  # noqa: BLE001
        raise ValueError(
            f"批阅产物目录越界：{d}（应位于 {root} 之下）。class_dir={class_dir!r}"
        ) from None
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
    plan = ctx.get("plan") or {}
    # D118：plan 模式下"一名学生都没图片"是**明确的可诊断状态**（通常是还没在学习通
    # 下载作答图），不能静默退回 `images_dir` 去 iterdir 一个不存在的目录
    # （Windows 上会抛 [WinError 3] …\images）。
    if plan:
        plan_groups = _plan_student_images(ctx)
        if plan_groups:
            groups = plan_groups
            logger.info(f"[转录] plan 模式：{len(groups)} 名学生")
        else:
            n_stu = len(plan.get("students") or [])
            from ..xxt import layout as _xxt_layout
            real_dir = _xxt_layout.pages_dir() / "review" / str(
                (plan.get("classId") or ctx.get("class_id") or "<classId>")) / str(
                plan.get("workId") or ctx.get("work_id") or "<workId>")
            msg = (f"plan 模式下没有任何学生图片（名单 {n_stu} 人，0 人有图）："
                   f"请先在「作业预览-学习通」对该作业点「⬇ 下载作答/批语」，再重跑 AI 批阅。"
                   f"（作答原件应位于：{real_dir}）")
            logger.error(msg)
            raise GradingInputError(msg)
    else:
        images_dir = ctx.get("images_dir")
        if not images_dir:
            raise GradingInputError(
                "未提供作答图片来源：请在「作业预览-学习通」下载作答图后重跑，"
                "或显式传 --images <已存在的图片目录>（手工批阅）。")
        images_dir = Path(images_dir)
        if not images_dir.is_dir():
            raise GradingInputError(
                f"指定的作答图目录不存在：{images_dir}。"
                f"请改用「作业预览-学习通」下载的目录（<workspace>/.runtime/xxt/pages/review/<班级>/<作业>/）。")
        groups = group_images(images_dir)
        if not groups:
            logger.warning(f"图片目录为空（无 .png/.jpg 等文件），跳过转录: {images_dir}")
            return []

    # D157：**强制重跑**时才覆盖已有转写；否则保留（省额度）。
    # 但这会让"两次结果一样"——所以默认在 UI 上明确标注"历史结果"。
    if not ctx.get("force"):
        _before = len(groups)
        groups = {stu: imgs for stu, imgs in groups.items()
                  if not (transcripts_dir / f"{stu}.json").is_file()}
        if _before != len(groups):
            logger.info(f"[转录] 跳过 {_before - len(groups)} 名已有转写的学生"
                        f"（要重跑请用「强制重跑」）")
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
    failed_n = int(report.get("failed") or 0)
    if failed_n:
        names = [str(it.get("id") or "") for it in (report.get("items") or [])
                 if not it.get("ok")][:5]
        detail = "；".join(sorted({str(it.get("error") or "")[:120]
                                  for it in (report.get("items") or []) if not it.get("ok")}))[:300]
        msg = (f"转录有 {failed_n}/{report.get('total')} 名学生失败（{'、'.join(names)}"
               + ("…" if failed_n > 5 else "") + f"）：{detail}")
        if not ctx.get("allow_partial"):
            # D125：默认**中止**——带着残缺数据跑评阅只会产出错误的报告
            raise GradingInputError(
                msg + "。请先修复上述错误后重跑，或加 `--allow-partial` 明知残缺仍继续。")
        logger.warning(f"[转录] {msg}（--allow-partial：继续后续步骤）")
    return [Path(it["out"]) for it in (report.get("items") or []) if it.get("ok") and it.get("out")]


def _write_grade_snapshots(ws, task: dict, plan: dict) -> dict:
    """D168：批阅时落两种快照（失败只告警，绝不影响批阅）。

    **返回「锁定 tag 后」的 plan**：若快照已存在，学生 tag 一律以快照为准
    （否则 roster 变更会让"保证可复现"落空）。

    1. `roster-tags/<packId>.json` —— 学生→tag 映射（**首次批阅即冻结**）；
       已存在则**不覆盖**（防批阅中途 roster 变更改掉历史依据）；
    2. `grading/<packId>/submissions.json` —— 谁交了、交了几张图。
    """
    from . import snapshots as _snap
    class_dir = str(task.get("class_dir") or "").strip()
    pack_id = str((plan or {}).get("packId") or task.get("pack_id") or "")
    if not class_dir or not pack_id:
        logger.debug("[快照] class_dir/pack_id 缺失，跳过 D168 快照")
        return plan
    students = [s for s in ((plan or {}).get("students") or []) if isinstance(s, dict)]
    if not students:
        return plan
    # 1) roster-tags：只在**没有**快照时补写（source 标 auto-at-grade）
    try:
        cur = _snap.read_tags_snapshot(ws, class_dir, pack_id)
        if cur.get("missing"):
            _snap.write_tags_snapshot(
                ws, class_dir, pack_id,
                [{"name": s.get("name"), "number": s.get("number"),
                  "tag": s.get("tag")} for s in students],
                source=_snap.SOURCE_AUTO_GRADE)
        else:
            diff = _snap.diff_against_roster(ws, class_dir, pack_id)
            if diff.get("changed"):
                logger.warning(
                    f"[快照] 作业包 {pack_id} 的 roster 与快照不一致"
                    f"（新增 {len(diff.get('added') or [])}、"
                    f"移出 {len(diff.get('removed') or [])}、"
                    f"tag 变更 {len(diff.get('tagChanged') or [])}）——"
                    f"本次仍按**快照**的 tag 批阅以保证可复现；"
                    f"如需按新名单，请在「班级与标签」刷新快照")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[快照] roster-tags 写入失败：{str(exc)[:160]}")
    # 2) submissions：每次批阅都刷新（本次实际处理的作答）
    try:
        _snap.write_submissions(
            ws, class_dir, pack_id,
            [{"name": s.get("name"), "number": s.get("number"),
              "tag": s.get("tag"), "images": s.get("images") or []}
             for s in students],
            source="plan")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[快照] submissions 写入失败：{str(exc)[:160]}")
    # 3) 按快照锁定 tag（关键：保证"再次批阅同一包"的依据不变）
    locked = _snap.read_tags_snapshot(ws, class_dir, pack_id)
    if not locked.get("ok"):
        return plan
    by_num: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for s in (locked.get("students") or []):
        num = str(s.get("number") or "").strip()
        nm = str(s.get("name") or "").strip()
        if num:
            by_num[num] = str(s.get("tag") or "")
        if nm:
            by_name[nm] = str(s.get("tag") or "")
    out_students = []
    changed = 0
    for s in students:
        num = str(s.get("number") or "").strip()
        nm = str(s.get("name") or "").strip()
        snap_tag = by_num.get(num) if num and num in by_num else by_name.get(nm)
        if snap_tag is not None and snap_tag != str(s.get("tag") or ""):
            changed += 1
            s = {**s, "tag": snap_tag}
        out_students.append(s)
    if changed:
        logger.info(f"[快照] 按 roster-tags/{pack_id}.json 锁定 {changed} 名学生的 tag")
    return {**plan, "students": out_students}


def _only_students(ctx: dict) -> "set[str]":
    """D156：本次只处理哪些学生（`--students` / plan 已被裁到这些人）。

    为空 = 不限（全部）。
    """
    return {str(x) for x in (ctx.get("only_students") or []) if str(x).strip()}


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
    """D127：**每生只用其 tag 对应作业纸的题目**评阅。

    题目取不到时**跳过该生并写诊断**，绝不回退到"整份任务包题目"或让模型自己猜题目——
    静默回退会导致用错作业纸评阅（跨批次串题），且老师无从察觉。
    """
    tasks_items = ctx["items"]
    model = (ctx["task"].get("grade", {}).get("models", {}) or {}).get("evaluation")
    only = _only_students(ctx)
    outs = []
    for tf in sorted(ctx["transcripts_dir"].glob("[!_]*.json")):
        # D156：**只评阅指定学生**（此前进度只过滤了转写，评阅会扫描整个
        # transcripts 目录 → 出现"批张紫涵却报张松"的困惑）。
        if only and tf.stem not in only:
            logger.debug(f"[评阅] 跳过 {tf.stem}（不在本次指定名单）")
            continue
        # D157：默认跳过"已有评阅结果"的学生（省额度）；强制重跑时覆盖。
        _ev = evaluations_dir / f"{tf.stem}.json"
        if _ev.is_file() and not ctx.get("force"):
            logger.info(f"[评阅] 跳过 {tf.stem}（已有评阅结果；要重跑请用「强制重跑」）")
            outs.append(_ev)
            continue
        items = _plan_items_for(ctx, tf.stem) if ctx.get("plan") else None
        if ctx.get("plan") and not items:
            # D127：plan 模式下必须能定位该生对应作业纸的题目
            msg = (f"学生「{tf.stem}」没有可用的作业纸题目（tag 未匹配到当前作业包内的作业纸，"
                   f"或该生不在带 tag 名单里）。已跳过评阅，请检查："
                   f"① 该生 tag 是否已在作业包中绑定作业纸；② 名单是否已导入并打 tag。")
            logger.error(f"[评阅] SKIP {tf.stem}: {msg}")
            _diag(ctx, step="evaluate", student=tf.stem, error=msg)
            journal_append(ctx["journal"], {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "run_id": ctx["run_id"], "step": "evaluate",
                "student": tf.stem, "status": "fail", "error": msg[:300]})
            continue
        try:
            outs.append(evaluate_student(client, tf, items or tasks_items, evaluations_dir,
                                         homework_name=ctx.get("homework", ""), model=model,
                                         ws=ctx.get("ws")))
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
    # D126-B：教师总结报告（易错知识点汇总 + 共现 + 得分率）——只给教师，不上传
    try:
        from .teacher_report import generate as _gen_teacher
        tr = _gen_teacher(ctx["evaluations_dir"], reports_dir,
                          title=str(ctx.get("homework") or ""),
                          subtitle=str((ctx.get("plan") or {}).get("classDir") or ""))
        if tr.get("ok"):
            outs.append(Path(tr["md"]))
            outs.append(Path(tr["stats"]))
    except Exception as exc:  # noqa: BLE001 —— 教师报告失败不影响学生报告
        logger.warning(f"[教师报告] 生成失败（不影响学生报告）：{str(exc)[:160]}")
    return outs


def _persist_transcripts(ws, task: dict, plan: "dict | None", transcripts_dir) -> int:
    """D126：把转录产物写入批阅草稿（`ai.transcript`），供逐生审核对照原图。

    D126-FIX：必须在**转录步刚结束、且部分失败中止之前**调用。
    原先只在 step 循环之后调用，而 `_run_transcribe` 在"部分失败且未加
    `--allow-partial`"时会抛 `GradingInputError` → 已成功学生的转写永远写不进
    草稿；而"仅转录"恰恰是最需要看到转写的场景，且部分失败是最常见的情形。
    """
    if not plan:
        return 0
    try:
        from .drafts import save_transcripts_to_drafts
        n = save_transcripts_to_drafts(
            ws, class_id=str(plan.get("classId") or ""),
            work_id=str(plan.get("workId") or ""),
            task_id=grading_scope_id(task, plan),
            class_dir=str(plan.get("classDir") or ""),
            transcripts_dir=transcripts_dir,
            plan=plan)
        if n:
            logger.info(f"[草稿] 已写入 {n} 份转写内容（供逐生审核对照原图）")
        return n
    except Exception as exc:  # noqa: BLE001 —— 写草稿失败不影响批阅结果
        logger.warning(f"[草稿] 写入转写内容失败（不影响批阅结果）：{str(exc)[:160]}")
        return 0


def run_task(task_path: Path, ws: Path, images_dir: Path | None = None,
             rerun: str | None = None, plan: "dict | None" = None,
             mode: str = "", class_dir: str = "", allow_partial: bool = False,
             students: "list[str] | None" = None, force: bool = False) -> dict:
    """任务包 grade 节驱动的执行入口。

    Args:
        task_path: 任务包 JSON。
        ws: workspace 根目录。
        images_dir: 学生作业图片目录（本地批阅；阶段4 download 自动填充）。
        rerun: 指定单个 step 名 → 只重跑该步（参数 Recovery 自 journal）。
        class_dir: D124：班级目录（`classes/<班级>`）。**优先级最高**。
        students: D148：**只处理这些学生**（逐生补批）。为空=全部。
        force: D157：强制重跑（即使已存在转写/评阅也重新生成；默认 False）。
            用途：`--limit` 只批了前 N 名后，可对漏掉的学生单独补批，
            不必整批重跑（否则已批过的学生要重新转写/评阅，浪费额度）。

    D124（关键修复）：PWA 传来的 taskpad 里**没有** `class_dir`（它存在浏览器 localStorage），
    而 `grading_dir()` 需要它。此前 cli 只把它给了 `plan`，没写回 `task` →
    批阅一进来就报 `class_dir=''`。现在的取值优先级：
        参数 class_dir > plan.classDir > task.class_dir
    三者都没有 → 明确报错（而不是走到 grading_dir 才崩）。
    """
    task_path = Path(task_path).expanduser().resolve()
    task = json.loads(task_path.read_text(encoding="utf-8"))
    # D124：注入 class_dir（参数 > plan > task），保证 grading_dir 拿到真实班级目录
    effective_class_dir = (str(class_dir or "").strip()
                           or str((plan or {}).get("classDir") or "").strip()
                           or str(task.get("class_dir") or "").strip())
    if effective_class_dir:
        task["class_dir"] = effective_class_dir
    # D127-FIX：**作用域键注入**（与 class_dir 同口径）。
    # 作业包模式的批阅目录必须是 grading/<packId>/，而 task（taskpad）本身没有 pack_id，
    # 只有 plan 里有。此前漏了这一步 → 目录落到 grading/<padId>/，
    # 而前端按 packId 读草稿 → "能转写但逐生审核看不到"。
    _plan_pack = str(((plan or {}).get("packId") or "")).strip()
    if _plan_pack and not str(task.get("pack_id") or "").strip():
        task["pack_id"] = _plan_pack
    grade_cfg = task.get("grade", {}) or {}
    # D127：默认**不再包含 report**——报告是人工审核之后的独立工序
    #       （「📄 一键生成批阅报告」），不应随批阅自动跑、更不该反复生成。
    steps = grade_cfg.get("steps", ["transcribe", "evaluate"])
    if not steps:
        raise ValueError("任务包 grade.steps 为空（=仅出作业纸，无需批阅）")
    # 兼容历史任务包（存了 report 步骤）：静默忽略，避免"批阅顺带出报告"的旧行为。
    steps = [x for x in steps if str(x) != "report"] or ["transcribe", "evaluate"]

    base = grading_dir(ws, task)
    p = _paths(base)
    # D148：逐生补批 —— 只保留指定学生（必须在 plan 装配之后、任何 IO 之前）
    want_students = [str(x).strip() for x in (students or []) if str(x).strip()]
    if want_students and isinstance(plan, dict):
        _all = plan.get("students") or []
        _keep = [s for s in _all if str(s.get("name")) in set(want_students)]
        _missing = [n for n in want_students
                    if not any(str(s.get("name")) == n for s in _all)]
        plan = {**plan, "students": _keep}
        logger.info(f"[批阅] 只处理指定学生 {len(_keep)} 人"
                    + (f"；plan 中找不到：{_missing}" if _missing else ""))
    # D127：落包快照 —— 事后可核对"这个批阅目录当时用的是哪些作业纸/题目"
    try:
        _snap = {"packId": str(plan.get("packId") or task.get("pack_id") or "") if plan else
                 str(task.get("pack_id") or ""),
                 "taskId": str(task.get("id") or ""),
                 "classDir": str(task.get("class_dir") or ""),
                 "pads": [{"padId": s.get("padId") or "", "tag": s.get("tag") or "",
                           "questionCount": len(s.get("questions") or [])}
                          for s in ((plan or {}).get("students") or [])],
                 "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S")}
        (base / "pack.json").write_text(json.dumps(_snap, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 —— 快照失败不影响批阅
        logger.warning(f"[pack] 写入 pack.json 失败：{str(exc)[:120]}")
    # D168：roster-tags 快照 + 作答名单（docs/112-D168 §3）——**保证历史可复现**
    # 注意：返回**锁定 tag 后**的 plan（快照存在时以快照为准）
    plan = _write_grade_snapshots(ws, task, plan)
    journal = base / "journal.jsonl"
    run_id = time.strftime("%Y%m%d-%H%M") + "-" + uuid.uuid4().hex[:6]

    # download 上传（阶段4 TODO）：学习通下载学生图片 / 批阅回传
    # TODO(stage4): "download" in steps → 从学习通拉取图片到 p["images"]
    # TODO(stage4): "upload" in steps → 按题型回传评语+图片+自动打分（D7）
    if "download" in steps:
        logger.warning("download（学习通下载）属阶段4 暂未实现，依赖 --images 本地图片目录。")

    ctx = {
        "ws": ws,
        "task": task,
        "task_path": task_path,
        "homework": task.get("course", "") + " " + str(task.get("id", "")),
        "items": expand_items(ws, task),
        # D119：**不再**默认指向 `<ws>/<class>/grading/<task>/images`（该目录无任何写入方，
        # 是 D118 那个 WinError 3 的来源）。只有显式传 --images 的"手工批阅"才用它。
        "images_dir": Path(images_dir).expanduser().resolve() if images_dir else None,
        "transcripts_dir": p["transcripts"],
        "evaluations_dir": p["evaluations"],
        "reports_dir": p["reports"],
        "evaluations": p["evaluations"],  # alias
        "journal": journal,
        "run_id": run_id,
        "plan": plan,
        # D156：本次只处理这些人（逐生补批）；D157：强制重跑
        "only_students": [str(x).strip() for x in (students or []) if str(x).strip()],
        "force": bool(force),
        "mode": (str(mode) or (plan or {}).get("mode") or "optimized"),
        "diag": base / "diagnostics.jsonl",
        "report_kind": (plan or {}).get("reportKind") or "ai",
        "concurrency": int((grade_cfg.get("concurrency") or 3)),
        # D125：转录部分失败是否继续（默认 False = 中止）
        "allow_partial": bool(allow_partial),
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
                # D136：**每份作业 = 一个对话**（一次批阅 N 份 → N 个 session），
                # 由 `_run_transcribe` 逐份设置；这里只在单份场景兜底。
                _session_per_student(client, ctx)
                try:
                    produced = [str(x) for x in _run_transcribe(ctx, client, p["transcripts"])]
                    _accum_usage(ctx, "transcribe", client)
                finally:
                    # D126-FIX：**必须放在 finally**——`_run_transcribe` 在"部分失败且未加
                    # `--allow-partial`"时会直接 raise，若写在下一行就永远执行不到，
                    # 已成功学生的转写也就永远进不了草稿（"仅转录"最常见的情形）。
                    _persist_transcripts(ws, task, plan, ctx["transcripts_dir"])
            elif step == "evaluate":
                if not any(ctx["transcripts_dir"].glob("*.json")):
                    raise RuntimeNotFoundError(ctx["transcripts_dir"])
                from .llm import LLMClient
                client = LLMClient(ws=ws)
                # D136：同 transcribe —— 按学生切分会话（见 _session_per_student）
                _session_per_student(client, ctx)
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

    # D126：兜底再写一次（幂等，只覆盖 transcript 字段）——覆盖「只重跑转录」等
    # 不经过上面 transcribe 分支的路径。主路径已在转录成功后立即写入（见 D126-FIX）。
    if plan and "transcribe" in to_run:
        _persist_transcripts(ws, task, plan, ctx["transcripts_dir"])

    # D86 §6：批阅完成后把结果落成"本地批阅草稿"（PWA 人工批阅栏可直接查看/修改/一键上传）
    #
    # D171-T2：**这一步不能静默失败**。教师反馈「审核里看不到 AI 批语、状态还是已转写」，
    # 根因就是这里：`plan` 缺 classId/workId 时整段被跳过，或写失败只 warning，
    # 于是 evaluations/*.json 有产物、草稿库却没有 → PWA 状态判定（要求 ai.comment+ai.score）
    # 永远停在「已转写」。
    draft_rep = _persist_evaluations_to_drafts(ws, task, plan, ctx)
    # 只在**真的出错**时记 fail；"没有 plan"（CLI 直接跑）属正常路径，不写 journal
    if draft_rep.get("error") or (draft_rep.get("skipped") and plan):
        journal_append(journal, {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "run_id": run_id,
            "step": "drafts", "status": "fail",
            "error": str(draft_rep.get("error") or draft_rep.get("skipped"))[:300]})
        logger.error(f"[草稿] 未写入本地批阅草稿：{draft_rep.get('error') or draft_rep.get('skipped')}"
                     f"（这会导致 PWA 逐生审核看不到 AI 批语）")

    # run 汇总记录（D8：任务包 = 执行历史；任务包内 journal 数组不入库但存在于工作区副本）
    summary_rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "run_id": run_id,
                   "step": "run", "steps_done": to_run, "status": "done",
                   "bucket": str(base), "usage": ctx.get("usage") or {}}
    journal_append(journal, summary_rec)
    return summary_rec


def _persist_evaluations_to_drafts(ws, task: dict, plan: "dict | None", ctx: dict) -> dict:
    """D171-T2：把 `evaluations/*.json` 落进本地批阅草稿库（PWA 逐生审核的数据源）。

    返回 {"ok", "count"} 或 {"skipped"/"error": 原因} —— **调用方必须检查**，
    因为跳过会让教师"看不到 AI 批语"却没有任何提示。
    """
    if not plan:
        return {"skipped": "没有 plan（未走 PWA 批量批阅路径）"}
    cid = str((plan.get("classId") or "")).strip()
    # D171-T2：workId 可能只在 task 里（serve 用 --work 传入），这里兜底
    wid = str((plan.get("workId") or task.get("workId")
               or task.get("work_id") or "")).strip()
    if not cid or not wid:
        return {"skipped": f"缺少 classId/workId（classId={cid!r}, workId={wid!r}）"
                           "—— 无法定位草稿库，PWA 将看不到 AI 批语"}
    try:
        from .drafts import save_drafts_from_grading
        saved = save_drafts_from_grading(
            ws, class_id=cid, work_id=wid,
            task_id=grading_scope_id(task, plan),
            class_dir=str(plan.get("classDir") or ""),
            kind=str(ctx.get("report_kind") or "ai"))
    except Exception as exc:  # noqa: BLE001 —— 仍不阻断批阅，但要**明确报错**
        return {"error": f"写入草稿失败：{str(exc)[:200]}"}
    if not saved.get("ok"):
        return {"error": f"写入草稿失败：{saved.get('error') or '未知原因'}"}
    logger.info(f"[草稿] 已写入本地批阅草稿 {saved.get('count')} 份"
                f"（kind={ctx.get('report_kind')}）")
    return {"ok": True, "count": saved.get("count")}


def _session_per_student(client, ctx) -> None:
    """D136：批阅会话粒度 = **每份作业一个**（docs/86 §2）。

    批量场景下一次批阅 N 份 → N 个 session，而不是"全局固定一个"
    （那会让 opencode-go 的路由把无关作业归成一坨），
    也不是"每次请求换新"（那会丢掉 prompt 缓存收益）。
    """
    try:
        names = sorted(p.stem for p in Path(ctx["transcripts_dir"]).glob("*.json"))
    except Exception:  # noqa: BLE001
        names = []
    tag = names[0] if len(names) == 1 else f"batch{len(names)}"
    try:
        client.set_session_id(f"grade-{tag}")
    except Exception:  # noqa: BLE001
        pass


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
