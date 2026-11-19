"""D86 §6：把批阅结果落成"本地批阅草稿"（供 PWA 人工批阅栏查看/修改/一键上传）。

产物来源：`classes/<dir>/grading/<task>/{evaluations,transcripts,reports}`
写入：`<xxt_home>/grade-drafts/<classId>/<workId>.json`（D85 存储，键=workAnswerId→姓名）
- AI 草稿：score=total_score、comment=feedback_md（纯文本）、images=[报告 PNG base64]
- 支持 `kind="ai"|"human"`：报告标注不同（人工报告用于"教师自己写的批阅"）
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

from loguru import logger


def _cut_markdown(text: str) -> str:
    """把 Markdown 批语收敛成"适合直接贴进平台的纯文本"（去重格式符，保留公式）。"""
    out = []
    for line in str(text or "").splitlines():
        t = line.rstrip()
        t = t.replace("**", "").replace("__", "")
        if t.startswith(("- ", "* ")):
            t = "· " + t[2:]
        out.append(t)
    return "\n".join(out).strip()


def save_drafts_from_grading(ws, *, class_id: str, work_id: str, task_id: str,
                             class_dir: str = "", kind: str = "ai",
                             with_report_png: bool = True, katex_dir=None,
                             home=None) -> dict:
    """读批阅产物 → 写本地批阅草稿（键优先用 plan 里的 workAnswerId，回落姓名）。"""
    from ..xxt import grade_store
    from .flow import grading_dir
    from .report import build_report_md, render_report_png

    ws = Path(ws)
    resolved_class_dir = str(class_dir or "").strip().strip("/") or f"classes/{class_id}"
    task = {"id": str(task_id), "class_dir": resolved_class_dir}
    base = grading_dir(ws, task)
    ev_dir, tr_dir = base / "evaluations", base / "transcripts"
    if not ev_dir.is_dir():
        return {"ok": False, "error": f"无评阅产物：{ev_dir}"}

    # plan（可选）：拿 workAnswerId / tag
    wa_by_name: dict[str, str] = {}
    try:
        from . import inputs as _inputs
        plan = _inputs.load_plan(ws, task_id, class_dir) or {}
        for s in (plan.get("students") or []):
            if s.get("name"):
                wa_by_name[str(s["name"])] = str(s.get("workAnswerId") or "")
    except Exception:  # noqa: BLE001
        pass

    written = []
    for f in sorted(ev_dir.glob("[!_]*.json")):
        try:
            ev = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        student = str(ev.get("student") or f.stem)
        key = wa_by_name.get(student) or student
        score = ev.get("total_score")
        comment = _cut_markdown(ev.get("feedback_md") or "")
        images = []
        if with_report_png:
            tf = tr_dir / f"{f.stem}.json"
            if tf.is_file():
                try:
                    md = build_report_md(tf, f)
                    sub = f"{student}" + (f" · tag {ev.get('tag')}" if ev.get("tag") else "")
                    png = render_report_png(md, base / "reports" / f"{f.stem}.png",
                                            kind=kind, title=f"{student} 批阅报告",
                                            subtitle=sub, katex_dir=katex_dir)
                    if png and Path(png).is_file():
                        images.append({"name": f"{f.stem}-report.png",
                                       "data_b64": base64.b64encode(Path(png).read_bytes()).decode()})
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"报告 PNG 生成失败（{student}）：{str(exc)[:120]}")
        # D92-R2：写入**双套**结构；AI 产物落 ai 套（人工审核另写 human/修订，不覆盖此基线）
        ai_set = {"score": score, "comment": comment, "reportImages": images or []}
        # D126-FIX：AI 套同时带上转写原文。`run_task` 的 transcribe 步已写过一次，
        # 但"先生成报告再回读落草稿"（如 refill/重算）这条路径不经过那里 →
        # 逐生审核会只剩批语、没有转写。合并写入（save_draft_sets 只并新增字段），
        # 已有转写不会被空值覆盖。
        _tf = tr_dir / f"{f.stem}.json"
        if _tf.is_file():
            try:
                _t = json.loads(_tf.read_text(encoding="utf-8"))
                from .transcribe import transcript_to_markdown
                _md = transcript_to_markdown(_t).strip()
                if _md:
                    ai_set["transcript"] = _md
                    ai_set["transcriptModel"] = str(_t.get("model") or "")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"读取转写失败（{student}）：{str(exc)[:120]}")
        if str(kind) == "human":
            # D119：按 (ws, class_dir, task_id) 写入新布局 —— 不同作业批次互不覆盖
            rep = grade_store.save_draft_sets(
                home, class_id, work_id, key, human={**ai_set, "used": True},
                human_mode="replace", student=student, tag=ev.get("tag") or "",
                ws=ws, class_dir=resolved_class_dir, task_id=str(task_id))
        else:
            rep = grade_store.save_draft_sets(
                home, class_id, work_id, key, ai=ai_set,
                student=student, tag=ev.get("tag") or "",
                ws=ws, class_dir=resolved_class_dir, task_id=str(task_id))
        written.append({"student": student, "key": key, "ok": rep.get("ok"),
                        "score": score, "images": len(images)})
    return {"ok": bool(written), "count": len(written), "drafts": written,
            "file": str(grade_store.draft_file(ws, class_id, work_id,
                                               class_dir=resolved_class_dir,
                                               task_id=str(task_id), home=home) or "")}

def build_draft_report(d: dict) -> "tuple[str, str]":
    """D175：由**一份已归一草稿**生成 (markdown, kind)。

    报告预览（保存前先看结果）与批量生成共用同一函数 —— 预览必须是"将来真正
    发出去的那份"，不能另写一套拼接逻辑。
    """
    from .report import _mode_report_md
    d = d if isinstance(d, dict) else {}
    return _mode_report_md(student=str(d.get("student") or ""),
                           ai=d.get("ai") or {}, human=d.get("human") or {},
                           human_mode=d.get("humanMode") or "none",
                           revision=d.get("revision") or {},
                           revised=bool(d.get("revised")))


def student_name_map(ws, *, class_id: str, work_id: str, task_id: str = "",
                     class_dir: str = "", plan: "dict | None" = None) -> dict:
    """D199：草稿键（workAnswerId）→ **学生姓名** 的映射。

    现场问题：草稿若没有 `student` 字段，报告会以 `wa_2001` 之类的键命名，
    版本索引里记录的也是键而不是姓名 → 按逐生审核名单核对时“少了几个人”。

    来源优先级：调用方 plan → 批阅下载清单 `students.json` → plan.json。
    只读，不写盘。
    """
    out: dict[str, str] = {}
    def _put(wa, name):
        wa, name = str(wa or "").strip(), str(name or "").strip()
        if wa and name:
            out[wa] = name
    for s in ((plan or {}).get("students") or []):
        if isinstance(s, dict):
            _put(s.get("workAnswerId"), s.get("name"))
    try:
        from . import inputs as _inputs
        _d, rev = _inputs.read_review_students(class_id, work_id)
        for s in rev:
            _put(s.get("workAnswerId"), s.get("name"))
    except Exception:  # noqa: BLE001 —— 只读兜底，失败不影响生成
        pass
    if not out:
        try:
            from . import inputs as _inputs2
            _pl = _inputs2.load_plan(ws, task_id, class_dir) or {}
            for s in (_pl.get("students") or []):
                if isinstance(s, dict):
                    _put(s.get("workAnswerId"), s.get("name"))
        except Exception:  # noqa: BLE001
            pass
    return out


def _draft_richness(d: dict) -> int:
    """D195：同名学生多份草稿时，挑“内容更完整”的那份（用于报告生成）。

    权重：人工套已使用(8) > 有批语(4) > 有分数(2) > 有转写/图片(1)。
    """
    d = d if isinstance(d, dict) else {}
    score = 0
    h = d.get("human") or {}
    a = d.get("ai") or {}
    if h.get("used"):
        score += 8
    if str(h.get("comment") or "").strip() or str(a.get("comment") or "").strip():
        score += 4
    if h.get("score") is not None or a.get("score") is not None:
        score += 2
    if str(a.get("transcript") or "").strip() or (h.get("reportImages") or a.get("images")):
        score += 1
    return score


def _reports_root(ws, class_dir: str, class_id: str, task_id: str) -> Path:
    return (Path(ws) / (class_dir or f"classes/{class_id}") / "grading"
            / (task_id or "task") / "reports")


def _progress_path(out_root: Path) -> Path:
    return out_root / ".progress.json"


def read_report_progress(ws, *, class_id: str, work_id: str, task_id: str = "",
                         class_dir: str = "") -> dict:
    """D194：读取上一次报告生成进度（中断后可据此显示“已生成 X/Y，可继续”）。

    只读；文件不存在时 `{ok: True, exists: False}`。
    """
    root = _reports_root(ws, class_dir, class_id, task_id)
    p = _progress_path(root)
    if not p.is_file():
        return {"ok": True, "exists": False, "dir": str(root)}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"ok": True, "exists": False, "dir": str(root)}
        data.update({"ok": True, "exists": True, "dir": str(root)})
        return data
    except Exception as exc:  # noqa: BLE001 —— 坏进度文件不影响主流程
        return {"ok": True, "exists": False, "dir": str(root),
                "warn": f"进度文件损坏：{str(exc)[:120]}"}


def _write_progress(out_root: Path, data: dict) -> None:
    """尽力而为地写进度（失败不影响报告生成本身）。"""
    try:
        from ..filelock import atomic_write_text
        atomic_write_text(_progress_path(out_root),
                          json.dumps(data, ensure_ascii=False, indent=1))
    except Exception:  # noqa: BLE001
        pass


def report_scope_report(ws, *, class_id: str, work_id: str, task_id: str = "",
                        class_dir: str = "", home=None,
                        students: "list[str] | None" = None) -> dict:
    """D195：生成报告前的**范围核对**（只读，不渲染任何东西）。

    回答教师实际遇到的三个问题：
      1. 这次会为哪些学生生成报告（= 有草稿的学生）；
      2. 平台名单里有、但没有草稿的学生有哪些（→ 表格有行、却不会有报告）；
      3. 同一学生是否在草稿里有多个键（→ 旧版本会生成重复报告/重复姓名）。

    `students` 传平台名单姓名（可选）；不给则只报告草稿侧统计。
    """
    from ..xxt import grade_store
    ws = Path(ws)
    if home is None:
        from ..xxt.session import xxt_home
        home = xxt_home()
    data = grade_store.read_drafts(home, class_id, work_id, ws=ws,
                                   class_dir=str(class_dir or f"classes/{class_id}"),
                                   task_id=str(task_id))
    by_student: dict[str, list[str]] = {}
    for k, raw in data.items():
        d = grade_store.normalize_draft(raw if isinstance(raw, dict) else {})
        stu = str(d.get("student") or k).strip() or str(k)
        by_student.setdefault(stu, []).append(str(k))
    with_draft = sorted(by_student)
    duplicates = {s: ks for s, ks in by_student.items() if len(ks) > 1}
    listed = [str(x).strip() for x in (students or []) if str(x).strip()]
    missing = sorted(set(listed) - set(with_draft)) if listed else []
    extra = sorted(set(with_draft) - set(listed)) if listed else []
    return {
        "ok": True, "taskId": str(task_id), "classDir": str(class_dir or f"classes/{class_id}"),
        "draftCount": len(data), "studentCount": len(with_draft),
        "students": with_draft,
        "duplicateKeys": duplicates,
        "listedCount": len(listed),
        "missingDraft": missing,          # 平台有、无草稿 → 不会有报告
        "notInList": extra,               # 有草稿、平台名单没有
        "hint": ("部分学生没有草稿（未跑 AI 批阅/未保存人工批阅），点「一键生成」只会为有草稿的学生出报告；"
                 + ("另有 %d 名学生在草稿里有多个键，已自动按姓名合并。" % len(duplicates)
                    if duplicates else "")),
    }


def render_reports_from_drafts(ws, *, class_id: str, work_id: str, task_id: str = "",
                               class_dir: str = "", home=None, katex_dir=None,
                               with_report_png: bool = True,
                               reason: str = "", only: "list[str] | None" = None,
                               resume: bool = False) -> dict:
    """D92-R2：按**已保存的双套草稿**逐生生成报告 PNG（人工在前 + 【附件】AI + 修订标红）。

    - 读 <xxt_home>/grade-drafts/<classId>/<workId>.json → normalize_draft；
    - 按 {构成 × 修订} 生成 md/html/png；写回草稿 human.reportImages（覆盖旧报告图）。
    - D193：同时登记**内容哈希版本**（`reports/.versions/index.json`）并把版本号写进草稿
      `human.report`；`reason` 记录本次生成原因（三键/强制重做/手动生成等）。
    - D194：**逐生原子、可中断、可续做**：
      * 每完成一名学生就写 `.progress.json`（done/total/pending/状态）；
      * 单人失败不中断全班（记入 `failed` 并在结果里返回），其余继续；
      * `resume=True` → 跳过“已有报告图且进度未标记需重做”的学生；
        内容哈希版本幂等，重复渲染**内容没变也不会产生新版本**；
      * `only=[学生…]` → 只重做指定学生。
    """
    import base64
    from pathlib import Path
    from ..xxt import grade_store
    from .report import (_mode_report_md, report_html_from_md, html_to_png)
    from . import report_versions

    ws = Path(ws)
    if home is None:
        from ..xxt.session import xxt_home
        home = xxt_home()
    # D119：新布局优先，旧布局回落
    data = grade_store.read_drafts(home, class_id, work_id, ws=ws,
                                   class_dir=str(class_dir or f"classes/{class_id}"),
                                   task_id=str(task_id))
    if not data:
        return {"ok": False, "error": "无本地批阅草稿（先跑一次 AI 批阅或保存人工批阅）"}
    out_root = _reports_root(ws, class_dir, class_id, task_id)
    out_root.mkdir(parents=True, exist_ok=True)
    only_set = {str(x).strip() for x in (only or []) if str(x).strip()}
    # D195：同一学生可能在草稿里有**两个键**（按 workAnswerId 写 + 按姓名写，历史遗留）。
    # 旧实现按 key 遍历 → 同一人生成两份报告、写同一个 `<学生>.png` 互相覆盖，
    # 版本索引也重复；前端表格还会出现“重复姓名”。
    # 这里按**学生姓名**合并：保留内容更完整的一份（人工套 > 有批语 > 有分数 > 有转写），
    # 并记下所有键，便于回写时同步到各个键。
    name_map = student_name_map(ws, class_id=class_id, work_id=work_id,
                               task_id=str(task_id),
                               class_dir=str(class_dir or f"classes/{class_id}"))
    merged: "dict[str, tuple[str, dict, list[str]]]" = {}
    for k, raw in data.items():
        d0 = grade_store.normalize_draft(raw if isinstance(raw, dict) else {})
        # D199：姓名优先；草稿没写 student 时用 workAnswerId 反查姓名，绝不用键当报告名
        stu = str(d0.get("student") or "").strip() or name_map.get(str(k)) or str(k)
        if stu != str(d0.get("student") or "").strip():
            d0 = {**d0, "student": stu}
        if only_set and not (stu in only_set or str(k) in only_set):
            continue
        prev = merged.get(stu)
        if prev is None:
            merged[stu] = (str(k), d0, [str(k)])
        else:
            keep_key, keep_d, keys = prev
            if _draft_richness(d0) > _draft_richness(keep_d):
                keep_key, keep_d = str(k), d0
            merged[stu] = (keep_key, keep_d, keys + [str(k)])
    pending = [(stu, {"__key": kk, "__keys": keys, "__draft": dd})
               for stu, (kk, dd, keys) in merged.items()]
    total = len(pending)
    merged_keys = {stu: row["__keys"] for stu, row in pending}
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    progress = {"ok": True, "state": "running", "startedAt": started_at,
                "updatedAt": started_at, "reason": str(reason or ""),
                "classId": class_id, "workId": work_id, "taskId": task_id,
                "total": total, "done": [], "failed": [], "skipped": [],
                "mode": "resume" if resume else "full"}
    _write_progress(out_root, progress)
    done = []
    failed = []
    skipped = []
    for idx, (student, bundle) in enumerate(pending, 1):
        key = str(bundle.get("__key") or student)
        d = bundle.get("__draft") or {}
        sibling_keys = [x for x in (bundle.get("__keys") or [key]) if x != key]
        # D194：续做时，已有报告图且本次不是“强制重做”→ 跳过（避免重复渲染/重复进版本）
        prev_report = ((d.get("human") or {}).get("report") or {})
        if resume and not only_set and prev_report.get("version") \
                and (out_root / f"{student}.png").is_file():
            skipped.append({"key": key, "student": student,
                            "reason": "已有报告（续做跳过）",
                            "version": prev_report.get("version")})
            progress["skipped"] = skipped
            progress["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _write_progress(out_root, progress)
            continue
        try:
            md, kind = _mode_report_md(student=student, ai=d.get("ai") or {},
                                       human=d.get("human") or {},
                                       human_mode=d.get("humanMode") or "none",
                                       revision=d.get("revision") or {},
                                       revised=bool(d.get("revised")))
            title = f"{student} 批阅报告"
            # D193：固定“最新”文件名（前端零改动），版本信息放 .versions/index.json
            base = out_root / f"{student}"
            md_file = base.with_suffix(".md"); md_file.write_text(md, encoding="utf-8")
            html_file = base.with_suffix(".html")
            html_text = report_html_from_md(md, kind=kind, title=title, katex_dir=katex_dir)
            html_file.write_text(html_text, encoding="utf-8")
            imgs = []
            produced: list[Path] = [md_file, html_file]
            if with_report_png:
                png = html_to_png(html_text, base.with_suffix(".png"))
                if png and Path(png).is_file():
                    produced.append(Path(png))
                    imgs.append({"name": f"{student}-report.png",
                                 "data_b64": base64.b64encode(Path(png).read_bytes()).decode()})
            # D193 §3：登记内容哈希版本（内容未变不产生新版本；历史进 .versions/）
            ver = report_versions.record(
                out_root, student, md, kind=kind,
                score=(d.get("human") or {}).get("score")
                if (d.get("human") or {}).get("score") is not None
                else (d.get("ai") or {}).get("score"),
                reason=str(reason or "render_reports_from_drafts"),
                files=produced)
            # 报告图回写人工套（供上传）；不动 ai 基线
            # D175-FIX：必须写带 scope 的**同一份**草稿（此前漏传 ws/class_dir/task_id
            # → 落到旧布局 `<xxt_home>/grade-drafts/<classId>/<workId>.json`，
            # 与刚读的 `grading/<taskId>/drafts/` 不是同一份 → 报告预览永远"未生成"）。
            human_patch: dict = {}
            if imgs:
                human_patch["reportImages"] = imgs
            # D193：版本号与上传清单共用同一口径，教师可直接对照
            human_patch["report"] = {
                "version": ver["version"], "tag": ver["tag"],
                "sha256": ver["sha256"], "generatedAt": ver["entry"]["at"],
                "changed": ver["changed"], "file": f"{student}.png", "kind": kind,
            }
            for kk in [key] + sibling_keys:
                grade_store.save_draft_sets(home, class_id, work_id, kk,
                                            human=human_patch,
                                            student=student,
                                            ws=ws, class_dir=str(class_dir or f"classes/{class_id}"),
                                            task_id=str(task_id))
            done.append({"key": key, "student": student, "kind": kind,
                         "revised": bool(d.get("revised")), "png": bool(imgs),
                         "version": ver["version"], "tag": ver["tag"],
                         "changed": ver["changed"]})
        except Exception as exc:  # noqa: BLE001 —— D194：单人失败不拖垮全班
            logger.warning(f"报告生成失败（{student}）：{exc}")
            failed.append({"key": key, "student": student,
                           "error": str(exc)[:300]})
        # D194：每完成一人就落盘进度（中断后可从进度看出做到哪、谁失败了）
        progress.update({
            "done": [x["student"] for x in done],
            "failed": failed,
            "skipped": skipped,
            "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "state": "running",
            "current": student,
            "processed": idx,
        })
        _write_progress(out_root, progress)
    finished = time.strftime("%Y-%m-%d %H:%M:%S")
    progress.update({"state": "partial" if failed else "done",
                     "finishedAt": finished, "current": "",
                     "done": [x["student"] for x in done],
                     "failed": failed, "skipped": skipped})
    _write_progress(out_root, progress)
    return {"ok": bool(done) and not failed,
            "partial": bool(failed) and bool(done),
            "count": len(done), "reports": done, "dir": str(out_root),
            "failed": failed, "skipped": skipped,
            "total": total,
            "hint": ("部分学生报告生成失败：" + "、".join(x["student"] for x in failed)
                     + "；可直接再点「一键生成批阅报告」续做（已完成的不重复渲染）")
            if failed else "",
            "versionsFile": str(out_root / report_versions.VERSIONS_DIR
                                / report_versions.INDEX_NAME)}


def save_transcripts_to_drafts(ws, *, class_id: str, work_id: str, task_id: str,
                               class_dir: str = "", transcripts_dir=None,
                               plan: "dict | None" = None) -> int:
    """D126：把转录产物写入批阅草稿的 `ai.transcript`（仅转录也能在逐生审核里看到）。

    只填空缺的 transcript 字段，**不影响**已有的分数/批语；返回写入条数。

    D126-FIX：`plan` 可由调用方直接传入。草稿 key 必须是 **workAnswerId**
    （前端 `drafts[students[].key]` 按它取），而 plan 未落盘时 `load_plan()` 读不到，
    过去会静默退化成用姓名当 key → 写了草稿但逐生审核依旧空白。
    """
    from pathlib import Path
    from ..xxt import grade_store

    if not (class_id and work_id):
        return 0
    tdir = Path(transcripts_dir) if transcripts_dir else None
    if tdir is None or not tdir.is_dir():
        return 0
    # 学生名 → workAnswerId：优先用调用方传入的 plan（run_task 的 plan 不一定落盘）
    if plan is None:
        try:
            from . import inputs as _inputs
            plan = _inputs.load_plan(ws, task_id, class_dir) or {}
        except Exception:  # noqa: BLE001
            plan = {}
    wa_by_name: dict[str, str] = {}
    for st in ((plan or {}).get("students") or []):
        if st.get("name"):
            wa_by_name[str(st["name"])] = str(st.get("workAnswerId") or "")

    n = 0
    for tf in sorted(tdir.glob("[!_]*.json")):
        try:
            t = json.loads(tf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        student = str(t.get("student") or tf.stem)
        key = wa_by_name.get(student) or student
        from .transcribe import transcript_to_markdown
        text = transcript_to_markdown(t).strip()
        if not text:
            continue
        rep = grade_store.save_draft_sets(
            None, class_id, work_id, key,
            ai={"transcript": text, "transcriptModel": str(t.get("model") or "")},
            student=student, ws=Path(ws), class_dir=class_dir, task_id=task_id)
        if rep.get("ok"):
            n += 1
    return n
