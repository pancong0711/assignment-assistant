"""d63 T1：`assist xxt` 命令组（check/login）。由 assist/cli.py 注册进主 cli。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import click


def default_storage(ctx) -> Path:
    """沿用 session.resolve_storage_path，保证 CLI / serve 路径契约一致。"""
    from .session import resolve_storage_path
    return resolve_storage_path(None)


def _journal(kind: str, *, params=None, result: str = "ok", error: str = "") -> None:
    """D74-9：CLI 直跑也写全局操作记录；被 serve 套壳时跳过，避免 PWA 侧重复记。"""
    import os
    if os.environ.get("ASSIST_NO_JOURNAL"):
        return
    try:
        from . import journal
        journal.log_event(kind, source="cli", params=params or {}, result=result, error=error)
    except Exception:  # noqa: BLE001
        pass


def register(group: click.Group) -> None:
    @group.command("install")
    def xxt_install():
        """联网安装 playwright+完整版内核（本地包优先；下载源 npmmirror/azureedge/官方）。"""
        from .installer import install_playwright
        rc = install_playwright(lambda line: click.echo(line))
        raise SystemExit(0 if rc == 0 else 1)

    @group.command("check")
    @click.option("--storage", "storage", default=None,
                  type=click.Path(dir_okay=False), help="storage_state JSON（默认 env XXT_STORAGE 或 xxt_home()/xxt-storage.json）")
    @click.option("--json-out", "json_out", default=None, type=click.Path(dir_okay=False),
                  help="体检报告落盘路径（可选）")
    @click.option("--html-out", "html_out", default=None, type=click.Path(dir_okay=False),
                  help="工作台页面存档（可选）")
    def xxt_check(storage, json_out, html_out):
        """会话体检：三信号判活；alive 则 storage_state 回写续期。退出码 0=alive 2=dead。"""
        from .session import check_session
        rep = check_session(storage or default_storage(None), json_out, html_out)
        _journal("xxt_check", result="ok" if rep.get("verdict") == "alive" else "fail",
                 error=str(rep.get("verdict") or "unknown"))
        click.echo(json.dumps({k: v for k, v in rep.items() if k != "markers"} |
                              {"markers": rep.get("markers")}, ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("verdict") == "alive" else 2)

    @group.command("extract")
    @click.option("--targets", "targets", default=None, type=click.Path(exists=True, dir_okay=False),
                  help="目标清单 JSON（round-1 schema: courses[].classes[]）；与 --all 二选一")
    @click.option("--all", "extract_all", is_flag=True, default=False,
                  help="扫描当前账户全部课程/班级并提取（D72；无需 targets 文件）")
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False))
    @click.option("--out-dir", "out_dir", default=None, type=click.Path(file_okay=False))
    @click.option("--archive-dir", "archive_dir", default=None, type=click.Path(file_okay=False))
    @click.option("--roster-dir", "roster_dir", default=None, type=click.Path(file_okay=False),
                  help="与--roster-labels 配套：学习通-25C1-<班>-0621.xlsx 所在目录")
    @click.option("--roster-label", "roster_labels", multiple=True,
                  help="差集基准班级标签（可多次；命中班级名子串即启用名册差集）")
    @click.option("--skip-notices", is_flag=True, default=False, help="跳过通知抓取")
    def xxt_extract(targets, extract_all, storage, out_dir, archive_dir,
                    roster_dir, roster_labels, skip_notices):
        """只读提取 run（T9/D72）：体检前置→逐班直达导航+evaluate直读→JSON+存档；POST 全拦截。"""
        import json as _json
        from . import layout
        from .extract_run import run_extract
        if not extract_all and not targets:
            raise click.UsageError("必须提供 --targets，或使用 --all 扫描账户全部课程/班级")
        if extract_all and targets:
            raise click.UsageError("--all 与 --targets 不能同时使用")
        spec = {"courses": []}
        if targets:
            spec = _json.loads(Path(targets).read_text(encoding='utf-8'))
        rep = run_extract(spec.get('courses', []),
                          storage=storage or default_storage(None),
                          out_dir=out_dir or layout.runs_dir(),
                          archive_dir=archive_dir or layout.pages_dir(),
                          roster_dir=roster_dir,
                          roster_labels=set(roster_labels or []),
                          skip_notices=skip_notices,
                          discover_all=extract_all)
        summary = {'run_id': rep.get('run_id'), 'ts_end': rep.get('ts_end'),
                   'failures': rep.get('failures'),
                   'classes': sum(len(c.get('classes', [])) for c in rep.get('courses', [])),
                   'works': sum(len(c2.get('works', [])) for c in rep.get('courses', [])
                                for c2 in c.get('classes', []))}
        _journal("xxt_extract",
                 params={"mode": "all" if extract_all else "targets",
                         "run_id": summary['run_id'], "classes": summary['classes'],
                         "works": summary['works'],
                         "failures": len(summary['failures'] or [])},
                 result="ok" if not summary['failures'] else "fail",
                 error=str((summary['failures'] or [{}])[0].get('detail', ''))[:200])
        click.echo(_json.dumps(summary, ensure_ascii=False, indent=1))
        click.echo(f"out={rep.get('out', '(failed)')}")
        raise SystemExit(0 if not rep.get('failures') else 1)

    @group.command("discover")
    @click.option("--out", "out", default=None, type=click.Path(dir_okay=False),
                  help="发现结果 JSON 输出（默认 xxt_home()/targets.json）")
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False))
    @click.option("--archive-dir", "archive_dir", default=None, type=click.Path(file_okay=False))
    def xxt_discover(out, storage, archive_dir):
        """只读发现「我教的课」课程/班级清单（D72 targets 模式；不提取、不写操作）。"""
        from . import layout
        from .extract_run import discover_targets
        rep = discover_targets(storage or default_storage(None),
                               archive_dir or layout.pages_dir())
        out_path = Path(out) if out else layout.targets_json()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # D74-3：成功发现前先把当前快照归档，供 diff 对比；默认保留最近 5 份
        if rep.get("ok") and out_path.resolve() == layout.targets_json().resolve():
            from . import targets as _targets
            _targets.archive_current(keep=5)
        out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        if rep.get("ok"):
            summary = {
                "ok": True,
                "discovered_at": rep.get("discovered_at"),
                "courses": len(rep.get("courses") or []),
                "classes": sum(len(c.get("classes") or []) for c in rep.get("courses") or []),
                "out": str(out_path),
            }
            _journal("xxt_discover", params={"courses": summary["courses"],
                                             "classes": summary["classes"]})
            click.echo(json.dumps(summary, ensure_ascii=False, indent=1))
            raise SystemExit(0)
        _journal("xxt_discover", result="fail", error=str(rep.get("error") or "")[:200])
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        raise SystemExit(2)

    @group.command("discover-works")
    @click.option("--targets", "targets", required=True, type=click.Path(exists=True, dir_okay=False))
    @click.option("--out", "out", default=None, type=click.Path(dir_okay=False),
                  help="发现结果 JSON 输出（默认 xxt_home()/targets/works.json）")
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False))
    @click.option("--archive-dir", "archive_dir", default=None, type=click.Path(file_okay=False))
    def xxt_discover_works(targets, out, storage, archive_dir):
        """只读发现选中班级的作业清单（D74-4；不进 mark、不抓名单）。"""
        from . import layout
        from .extract_run import discover_works
        spec = json.loads(Path(targets).read_text(encoding="utf-8"))
        rep = discover_works(spec.get("courses", []), storage or default_storage(None),
                             archive_dir or layout.pages_dir())
        out_path = Path(out) if out else layout.works_json()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        if rep.get("ok"):
            summary = {
                "ok": True,
                "discovered_at": rep.get("discovered_at"),
                "courses": len(rep.get("courses") or []),
                "classes": sum(len(c.get("classes") or []) for c in rep.get("courses") or []),
                "works": sum(len(cl.get("works") or []) for c in rep.get("courses") or []
                             for cl in c.get("classes") or []),
                "out": str(out_path),
            }
            _journal("xxt_discover_works", params={"classes": summary["classes"],
                                                   "works": summary["works"]})
            click.echo(json.dumps(summary, ensure_ascii=False, indent=1))
            raise SystemExit(0)
        _journal("xxt_discover_works", result="fail", error=str(rep.get("error") or "")[:200])
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        raise SystemExit(2)

    @group.command("review-probe")
    @click.option("--course", "course_id", required=True)
    @click.option("--class", "class_id", required=True)
    @click.option("--work", "work_id", required=True)
    @click.option("--sample", default=1, type=int, help="打开前 N 个学生详情页做侦察")
    @click.option("--out", "out", default=None, type=click.Path(dir_okay=False))
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False))
    @click.option("--fallback", is_flag=True, default=False, help="使用旧版 review 页 URL")
    @click.option("--allow-post", "allow_post", multiple=True, help="额外放行的只读 POST URL 子串（可多次）")
    def xxt_review_probe(course_id, class_id, work_id, sample, out, storage, fallback, allow_post):
        """只读侦察学生作答页：记录被拦截的非 GET 请求与图片/批语字段命中。"""
        from . import layout
        from .review_download import probe_review
        rep = probe_review(storage or default_storage(None), course_id, class_id, work_id,
                           sample=sample, use_fallback=fallback, allow_post=list(allow_post))
        out_path = Path(out) if out else (
            layout.pages_dir() / f"review-probe-{time.strftime('%Y%m%d-%H%M%S')}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        _journal("xxt_review_probe",
                 params={"classId": class_id, "workId": work_id,
                         "students": len(rep.get("students") or []),
                         "aborted": len(rep.get("aborted") or [])},
                 result="ok" if rep.get("ok") else "fail",
                 error=str(rep.get("error") or "")[:200])
        click.echo(json.dumps({"ok": rep.get("ok"), "out": str(out_path),
                               "students": len(rep.get("students") or []),
                               "aborted": rep.get("aborted") or [],
                               "details": rep.get("details") or [],
                               "error": rep.get("error")}, ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("ok") else 2)

    @group.command("review-download")
    @click.option("--course", "course_id", required=True)
    @click.option("--class", "class_id", required=True)
    @click.option("--work", "work_id", required=True)
    @click.option("--course-name", default="", help="用于友好文件名/报告展示")
    @click.option("--class-name", default="", help="用于友好文件名/报告展示")
    @click.option("--work-name", default="", help="用于友好文件名/报告展示")
    @click.option("--limit", default=0, type=int, help="只下载前 N 个学生（0=全部）")
    @click.option("--months", default=6, type=int, help="下载后自动清理超过 N 个月的旧批阅图片")
    @click.option("--allow-post", "allow_post", multiple=True, help="放行的只读 POST URL 子串（可多次）")
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False))
    @click.option("--fallback", is_flag=True, default=False, help="使用旧版 review 页 URL")
    def xxt_review_download(course_id, class_id, work_id, course_name, class_name, work_name,
                            limit, months, allow_post, storage, fallback):
        """只读下载作答图片 + 两栏批语（作业批语/题目批语），写 students.json。"""
        from . import layout
        from .review_download import download_review
        home = layout.pages_dir().parent
        rep = download_review(storage or default_storage(None), home,
                              course_id, class_id, work_id,
                              course_name=course_name, class_name=class_name,
                              work_name=work_name, limit=limit, months=months,
                              allow_post=list(allow_post), use_fallback=fallback)
        _journal("xxt_review_download",
                 params={"classId": class_id, "workId": work_id,
                         "students": rep.get("students"), "images": rep.get("images"),
                         "aborted": rep.get("aborted")},
                 result="ok" if rep.get("ok") else "fail",
                 error=str(rep.get("error") or "")[:200])
        click.echo(json.dumps({k: rep.get(k) for k in
                               ("ok", "classId", "workId", "students", "images",
                                "aborted", "manifest", "out_dir", "error", "pruned")},
                              ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("ok") else 2)

    @group.group("run")
    def xxt_run():
        """run 管理（D73-9）：导入旧 run JSON，使其在 PWA 可见。"""

    @xxt_run.command("import")
    @click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=False))
    @click.option("--scan", "scan_dir", default=None, type=click.Path(exists=True, file_okay=False),
                  help="扫描该目录下的 xxt-*.json 批量导入")
    def xxt_run_import(paths, scan_dir):
        """把旧 run / targets JSON 规范化导入 xxt_home()/runs/（只读复制，不触网）。"""
        from .legacy import import_run_file, scan_legacy_run_files
        files = [Path(p) for p in paths]
        if scan_dir:
            files += scan_legacy_run_files(scan_dir)
        seen, ordered = set(), []
        for f in files:
            key = str(f.resolve())
            if key not in seen:
                seen.add(key)
                ordered.append(f)
        if not ordered:
            raise click.UsageError("请提供文件路径，或使用 --scan <目录>")
        results, failed = [], []
        for f in ordered:
            try:
                results.append(import_run_file(f))
            except Exception as e:  # noqa: BLE001
                failed.append({"file": str(f), "error": str(e)[:200]})
        _journal("xxt_run_import",
                 params={"files": len(ordered), "imported": len(results), "failed": len(failed)},
                 result="ok" if not failed else "fail",
                 error=(failed[0]["error"] if failed else ""))
        click.echo(json.dumps({"ok": not failed, "imported": results, "failed": failed},
                              ensure_ascii=False, indent=1))
        raise SystemExit(1 if failed else 0)

    @xxt_run.command("list")
    def xxt_run_list():
        """列出当前 runs/ 中可见的 run（含刚导入的旧数据）。"""
        from . import layout
        rows = []
        for f in layout.run_json_files():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            rows.append({
                "run_id": d.get("run_id") or f.stem,
                "imported": bool(d.get("imported")),
                "ts_end": d.get("ts_end"),
                "classes": sum(len(c.get("classes") or []) for c in d.get("courses") or []),
                "works": sum(len(cl.get("works") or []) for c in d.get("courses") or []
                             for cl in c.get("classes") or []),
            })
        click.echo(json.dumps(rows, ensure_ascii=False, indent=1))

    @group.command("login")
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False),
                  help="storage_state JSON 目标（覆盖旧值）")
    @click.option("--qr", "qr", default=None, type=click.Path(dir_okay=False),
                  help="二维码 png 输出（默认与 storage 同目录 xxt-qr.png）")
    @click.option("--timeout", "timeout", default=1800, type=int, help="扫码等待秒数（默认 1800）")
    def xxt_login(storage, qr, timeout):
        """扫码登录（headless 出二维码图片，教师手机扫码）→ 保存会话 storage。"""
        from .session import check_session, qr_login
        storage_path = storage or default_storage(None)
        rep = qr_login(storage_path, qr, timeout=timeout, )
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        ok = rep.get("verdict") == "logged_in"
        if ok:
            # D68：PWA 通过 CLI 套壳调用时，必须确认 storage JSON 真的可用；
            # 二次体检 dead 则返回 2，让 PWA 作业状态显示失败而不是假装登录成功。
            rep2 = check_session(storage_path)
            click.echo(json.dumps({"post_login_check": rep2}, ensure_ascii=False, indent=1))
            ok = rep2.get("verdict") == "alive"
        _journal("xxt_login", result="ok" if ok else "fail",
                 error=str(rep.get("verdict") or rep.get("stage") or "")[:200])
        raise SystemExit(0 if ok else 2)
