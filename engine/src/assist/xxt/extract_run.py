"""D63 T9：从 targets JSON（round-1 同构：courses[].classes[]）跑全量只读提取 run。

与 .scratch/xxt_extract_full.py 同语义（该 driver 被本函数吸收为正式实现）；
会话体检前置（verdict≠alive 直接失败退出）；roster 差集仅对在 roster_labels 内命中的班；
输出：<out_dir>/<run_id>.json + HTML 存档；端到端 POST 拦截（ReadOnlyExtractor route 层）。
"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path


def discover_targets(storage: "Path | str", archive_dir: "Path | str") -> dict:
    """D72 targets 模式：只读发现「我教的课」课程/班级清单，不写 run、不提取。

    返回：{ok, discovered_at, courses:[{name,courseId,classes:[{name,classId}]}], steps, hint?}
    """
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    from .extractor import ReadOnlyExtractor
    storage = Path(storage)
    archive_dir = Path(archive_dir)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead",
                "hint": chk.get("hint", "请先 assist xxt login")}
    courses: list[dict] = []
    steps: list[dict] = []
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        ext = ReadOnlyExtractor(ctx, page, archive_dir)
        ext.run_id = "xxt-discover"
        for c in ext.discover_courses() or []:
            cid = str(c.get("courseId") or "")
            if not cid:
                continue
            classes = []
            for cl in ext.discover_classes(cid) or []:
                kid = str(cl.get("classId") or "")
                if kid and kid != "0":
                    classes.append({"name": str(cl.get("name") or kid)[:80], "classId": kid})
            courses.append({
                "name": str(c.get("name") or cid)[:80],
                "courseId": cid,
                "classes": classes,
            })
        steps = ext.steps
        browser.close()
    return {"ok": True, "discovered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "courses": courses, "steps": steps}


def discover_works(targets: "list[dict] | None", storage: "Path | str",
                   archive_dir: "Path | str") -> dict:
    """D74-4：对选中班级惰性发现作业清单（只读 work/list，不进入 mark）。

    targets: courses[].classes[]（classes 里可带 name/classId/cpi）。
    返回 courses[].classes[].works[]（name/workId/pending/submitted/unsubmitted/answer_window）。
    """
    from playwright.sync_api import sync_playwright
    from .session import check_session, _launch
    from .extractor import ReadOnlyExtractor
    storage = Path(storage)
    archive_dir = Path(archive_dir)
    chk = check_session(storage)
    if chk.get("verdict") != "alive":
        return {"ok": False, "error": "session dead",
                "hint": chk.get("hint", "请先 assist xxt login")}
    out_courses: list[dict] = []
    steps: list[dict] = []
    with sync_playwright() as pw:
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        ext = ReadOnlyExtractor(ctx, page, archive_dir)
        ext.run_id = "xxt-discover-works"
        for course in targets or []:
            cid = str(course.get("courseId") or "")
            if not cid:
                continue
            cpi = str(course.get("cpi") or "0")
            rec = {"name": str(course.get("name") or cid), "courseId": cid,
                   "cpi": cpi, "classes": []}
            for cl in course.get("classes") or []:
                kid = str(cl.get("classId") or "")
                label = str(cl.get("name") or kid)
                if not kid:
                    continue
                try:
                    info = ext.list_works(cid, kid, cpi=cpi)
                    rec["classes"].append({
                        "name": label, "classId": kid,
                        "cpi": info.get("cpi") or cpi,
                        "works": info.get("works") or [],
                        "empty_confirmed": bool(info.get("empty_confirmed")),
                    })
                except Exception as e:  # noqa: BLE001
                    rec["classes"].append({"name": label, "classId": kid, "cpi": cpi,
                                           "works": [], "error": str(e)[:200]})
            out_courses.append(rec)
        steps = ext.steps
        browser.close()
    return {"ok": True, "discovered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "courses": out_courses, "steps": steps}


def run_extract(targets: "list[dict] | None", storage: "Path | str",
                out_dir: "Path | str", archive_dir: "Path | str",
                roster_dir: "Path | str | None" = None,
                roster_labels: "set[str] | None" = None,
                skip_notices: bool = True,
                discover_all: bool = False) -> dict:
    from playwright.sync_api import sync_playwright
    from .session import check_session
    from .extractor import ReadOnlyExtractor, anchor_check, unsubmitted_diff
    storage = Path(storage)
    out_dir, archive_dir = Path(out_dir), Path(archive_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    roster_dir = Path(roster_dir) if roster_dir else None
    roster_labels = roster_labels or set()
    run_id = f"xxt-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    chk = check_session(storage)
    rep: dict = {'run_id': None, 'mode': 'readonly',
                 'ts_start': time.strftime('%Y-%m-%d %H:%M:%S'),
                 'session': {'checked_at': chk['ts'], 'verdict': chk['verdict'],
                             'storage': str(storage)},
                 'courses': [], 'failures': []}
    if chk['verdict'] != 'alive':
        rep['failures'].append({'kind': 'not_extracted', 'detail': 'session dead',
                                'hint': chk.get('hint', '请先 assist xxt login')})
        return rep
    with sync_playwright() as pw:
        from .session import _launch
        browser = _launch(pw, headless=True)
        ctx = browser.new_context(storage_state=str(storage),
                                  viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
        page = ctx.new_page()
        # D73-11：HTML 存档按 run 归档到 pages/runs/<run_id>/，便于随 run 删除
        ext = ReadOnlyExtractor(ctx, page, archive_dir,
                                html_dir=Path(archive_dir) / "runs" / run_id)
        ext.run_id = run_id
        # D72：--all 时先在真会话里发现课程/班级，再走同一套逐班提取逻辑。
        if discover_all:
            try:
                discovered = []
                for course in ext.discover_courses() or []:
                    classes = ext.discover_classes(course["courseId"]) or []
                    discovered.append({
                        "name": course.get("name") or course["courseId"],
                        "courseId": course["courseId"],
                        "classes": classes,
                    })
                targets = discovered
                rep['target_source'] = 'discover'
                if not discovered:
                    rep['failures'].append({
                        'kind': 'not_extracted',
                        'detail': 'discover found 0 courses/classes',
                    })
            except Exception as e:  # noqa: BLE001
                targets = []
                rep['target_source'] = 'discover'
                rep['failures'].append({
                    'kind': 'not_extracted',
                    'detail': f'discover failed: {str(e)[:200]}',
                })
        else:
            rep['target_source'] = 'provided'
        for course in (targets or []):
            cid = course['courseId']
            head = ext.goto_work_list(cid)
            cpi = head.get('cpi') or '0'
            rec = {'name': course.get('name', cid), 'courseId': cid,
                   'cpi': cpi, 'classes': []}
            rep['courses'].append(rec)
            for cl in course.get('classes', []):
                label, class_id = cl['name'], cl['classId']
                # D74-4：classes[].works 为空/缺省 = 该班全部作业；有值 = 只提取选中 workId
                work_ids = None
                raw_works = cl.get('works')
                if isinstance(raw_works, list):
                    work_ids = {str(w.get('workId') if isinstance(w, dict) else w)
                                for w in raw_works if (w.get('workId') if isinstance(w, dict) else w)}
                    if not work_ids:
                        work_ids = None
                roster_label = next((k for k in roster_labels if k in label), None)
                roster = []
                try:
                    cls_rec = ext.extract_class(cid, class_id, cpi=cpi, work_ids=work_ids)
                    cls_rec['name'] = label
                    if roster_label and roster_dir:
                        fn = roster_dir / f'学习通-25C1-{roster_label}-0621.xlsx'
                        from .master_roster import parse_stat_export, annotate_years
                        roster = parse_stat_export(fn)['students']
                        annotate_years(roster)
                    cls_rec['roster'] = {'total': len(roster) if roster else None}
                    if not skip_notices:
                        cls_rec['notices'] = ext.extract_notices(cid, class_id)
                    else:
                        cls_rec['notices'] = []
                    for w in cls_rec.get('works', []):
                        if roster:
                            d = unsubmitted_diff(roster, w)
                            w['unsubmitted_names'] = d['unsubmitted_names']
                            w['sub_not_in_roster'] = d['sub_not_in_roster']
                        else:
                            w['unsubmitted_names'] = []
                        w['anchor'] = anchor_check(w, len(roster) if roster else None)
                    if cls_rec['status'] == 'not_extracted':
                        rep['failures'].append({'scope': 'class', 'ref': class_id,
                                                'kind': 'not_extracted', 'detail': label})
                except Exception as e:  # noqa: BLE001
                    cls_rec = {'name': label, 'classId': class_id,
                               'status': 'not_extracted', 'works': [], 'roster': {'total': None},
                               'notes': [str(e)[:250]]}
                    rep['failures'].append({'scope': 'class', 'ref': class_id,
                                            'kind': 'not_extracted', 'detail': label,
                                            'archive': f'v2-list-{class_id}.html'})
                rec['classes'].append(cls_rec)
        browser.close()
    rep['ts_end'] = time.strftime('%Y-%m-%d %H:%M:%S')
    rep['run_id'] = run_id
    rep['steps'] = ext.steps          # D63 批次三 §23.1：导航过程事件（PWA 过程框数据源）
    fn = out_dir / f'{run_id}.json'
    fn.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')
    rep['out'] = str(fn)  # 不入 PDF/远程，仅运行回执
    # D74-9/T：run 工件容量控制（50MB / 1000 条，先到先删最旧）
    try:
        from .layout import prune_runs
        rep['pruned'] = prune_runs(out_dir.parent)
    except Exception:  # noqa: BLE001
        rep['pruned'] = None
    return rep
