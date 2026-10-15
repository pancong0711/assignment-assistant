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
    @click.option("--append", "append_run_id", default=None,
                  help="D79：把本次提取追加到已有 run（同班覆盖、新班追加）")
    @click.option("--skip-notices", is_flag=True, default=False, help="跳过通知抓取")
    def xxt_extract(targets, extract_all, storage, out_dir, archive_dir,
                    roster_dir, roster_labels, append_run_id, skip_notices):
        """只读提取 run（T9/D72）：体检前置→逐班直达导航+evaluate直读→JSON+存档；POST 全拦截。"""
        import json as _json
        from . import layout
        from .extract_run import run_extract
        if not extract_all and not targets:
            raise click.UsageError("必须提供 --targets，或使用 --all 扫描账户全部课程/班级")
        if extract_all and targets:
            raise click.UsageError("--all 与 --targets 不能同时使用")
        if append_run_id and not targets:
            raise click.UsageError("--append 必须与 --targets 一起使用")
        spec = {"courses": []}
        if targets:
            spec = _json.loads(Path(targets).read_text(encoding='utf-8'))
        if append_run_id:
            from .extract_run import append_extract
            rep = append_extract(str(append_run_id), spec.get('courses', []),
                                 storage=storage or default_storage(None),
                                 out_dir=out_dir, archive_dir=archive_dir,
                                 roster_dir=roster_dir,
                                 roster_labels=set(roster_labels or []),
                                 skip_notices=skip_notices)
            click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
            _journal("xxt_extract_append",
                     params={"run_id": rep.get("run_id"), "source_run": rep.get("source_run"),
                             "appended": len(rep.get("appended") or [])},
                     result="ok" if rep.get("ok") else "fail",
                     error=str(rep.get("error") or "")[:200])
            raise SystemExit(0 if rep.get("ok") else 2)
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
    @click.option("--mode", "mode", default="missing",
                  type=click.Choice(["full", "missing", "comments-only"]),
                  help="full=全量；missing=只补缺失（默认）；comments-only=只刷新批语/分数，不重下作答图")
    @click.option("--allow-post", "allow_post", multiple=True, help="放行的只读 POST URL 子串（可多次）")
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False))
    @click.option("--fallback", is_flag=True, default=False, help="使用旧版 review 页 URL")
    def xxt_review_download(course_id, class_id, work_id, course_name, class_name, work_name,
                            limit, months, mode, allow_post, storage, fallback):
        """只读下载作答图片 + 两栏批语（作业批语/题目批语），写 students.json。"""
        from . import layout
        from .review_download import download_review
        home = layout.pages_dir().parent
        rep = download_review(storage or default_storage(None), home,
                              course_id, class_id, work_id,
                              course_name=course_name, class_name=class_name,
                              work_name=work_name, limit=limit, months=months, mode=mode,
                              allow_post=list(allow_post), use_fallback=fallback)
        _journal("xxt_review_download",
                 params={"classId": class_id, "workId": work_id,
                         "students": rep.get("students"), "images": rep.get("images"),
                         "aborted": rep.get("aborted")},
                 result="ok" if rep.get("ok") else "fail",
                 error=str(rep.get("error") or "")[:200])
        click.echo(json.dumps({k: rep.get(k) for k in
                               ("ok", "classId", "workId", "students", "images", "mode",
                                "aborted", "manifest", "out_dir", "error", "pruned")},
                              ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("ok") else 2)

    @group.command("notice-attachments")
    @click.option("--limit", default=200, type=int)
    def xxt_notice_attachments(limit):
        """列出可发布为通知附件的作业纸 PDF（workspace/classes/**/sheets/**/*.pdf）。"""
        from .notice import list_notice_attachments
        rows = list_notice_attachments(None, limit=limit)
        click.echo(json.dumps({"ok": True, "items": rows}, ensure_ascii=False, indent=1))

    @group.command("notice-send")
    @click.option("--spec", "spec_path", default=None, type=click.Path(exists=True, dir_okay=False),
                  help="JSON spec：targets/title/bodyHtml/attachments；适合 serve/PWA 套壳")
    @click.option("--target", "target_pairs", multiple=True,
                  help="courseId:classId[:className]，可多次；与 --spec 二选一")
    @click.option("--title", default="", help="通知标题")
    @click.option("--body", default="", help="通知正文（纯文本自动转段落）")
    @click.option("--body-html", default="", help="通知正文 HTML")
    @click.option("--attachment", "attachments", multiple=True,
                  help="workspace 下 pdf/doc/docx 路径，可多次")
    @click.option("--send", is_flag=True, default=False,
                  help="真正发送；缺省为 dry-run（只填表/上传附件并截图）")
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False))
    def xxt_notice_send(spec_path, target_pairs, title, body, body_html, attachments, send, storage):
        """发布学习通课程通知（D77 写操作；默认 dry-run，白名单限制）。"""
        from .notice import normalize_targets, send_notice_from_spec
        if spec_path:
            spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
        else:
            targets = []
            for pair in target_pairs:
                parts = str(pair).split(":", 2)
                if len(parts) < 2:
                    raise click.UsageError("--target 格式应为 courseId:classId[:className]")
                cid, kid = parts[0].strip(), parts[1].strip()
                cname = parts[2].strip() if len(parts) > 2 else ""
                kname = kid
                found = False
                for c in targets:
                    if c["courseId"] == cid:
                        c["classes"].append({"classId": kid, "name": kname})
                        found = True
                        break
                if not found:
                    targets.append({"courseId": cid, "courseName": cname,
                                    "classes": [{"classId": kid, "name": kname}]})
            spec = {"targets": targets, "title": title,
                    "bodyHtml": body_html or body, "attachments": list(attachments)}
        rep = send_notice_from_spec(spec, send=bool(send), storage=storage)
        _journal("xxt_notice_send",
                 params={"mode": rep.get("mode"), "sent": rep.get("sent"),
                         "courses": rep.get("courses"), "classes": rep.get("classes"),
                         "attachments": rep.get("attachments"), "receipt": rep.get("receipt")},
                 result="ok" if rep.get("ok") else "fail",
                 error=str(rep.get("error") or "")[:200])
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("ok") else 2)

    @group.command("work-list")
    @click.option("--course", "course_id", required=True)
    @click.option("--class", "class_id", required=True)
    @click.option("--cpi", default="0")
    @click.option("--directory-id", "directory_id", default="0", help="作业库文件夹 ID（0=根目录）")
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False))
    def xxt_work_list(course_id, class_id, cpi, directory_id, storage):
        """只读列出作业库条目（含未发布草稿）。"""
        from .work import list_works
        rep = list_works(storage or default_storage(None), course_id, class_id, cpi, directory_id)
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("ok") else 2)

    @group.command("work-publish")
    @click.option("--course", "course_id", required=True)
    @click.option("--class", "class_id", required=True)
    @click.option("--work-library-id", "work_library_id", required=True)
    @click.option("--cpi", required=True)
    @click.option("--start", "start_time", default="")
    @click.option("--end", "end_time", default="")
    @click.option("--allow-late", is_flag=True, default=False)
    @click.option("--late-deadline", "late_deadline", default="")
    @click.option("--redo-times", default=0, type=int)
    @click.option("--send", is_flag=True, default=False, help="真正发布；缺省 dry-run")
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False))
    def xxt_work_publish(course_id, class_id, work_library_id, cpi, start_time, end_time,
                         allow_late, late_deadline, redo_times, send, storage):
        """发布作业设置（D79-C；默认 dry-run，白名单限制）。"""
        from .work import publish_work
        rep = publish_work(storage or default_storage(None), course_id, class_id,
                           work_library_id, cpi=cpi, start_time=start_time,
                           end_time=end_time, allow_late=allow_late,
                           late_deadline=late_deadline, redo_times=redo_times, send=send)
        _journal("xxt_work_publish",
                 params={"courseId": course_id, "classId": class_id,
                         "workLibraryId": work_library_id, "mode": rep.get("mode"),
                         "redo": redo_times, "allowLate": bool(allow_late)},
                 result="ok" if rep.get("ok") else "fail",
                 error=str(rep.get("error") or rep.get("responseText") or "")[:200])
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("ok") else 2)

    @group.command("work-folders")
    @click.option("--course", "course_id", required=True)
    @click.option("--class", "class_id", required=True)
    @click.option("--cpi", default="0")
    def xxt_work_folders(course_id, class_id, cpi):
        """只读列出作业库文件夹（用于文件夹设置）。"""
        from .work import list_folders
        rep = list_folders(default_storage(None), course_id, class_id, cpi)
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))

    @group.command("work-detail")
    @click.option("--course", "course_id", required=True)
    @click.option("--class", "class_id", required=True)
    @click.option("--cpi", required=True)
    @click.option("--work-library-id", "work_library_id", required=True)
    def xxt_work_detail(course_id, class_id, cpi, work_library_id):
        """只读读取作业标题与简答题干。"""
        from .work import work_detail
        rep = work_detail(default_storage(None), course_id, class_id, cpi, work_library_id)
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))

    @group.command("work-create")
    @click.option("--course", "course_id", required=True)
    @click.option("--class", "class_id", required=True)
    @click.option("--cpi", required=True)
    @click.option("--title", required=True)
    @click.option("--stem", "stem_html", required=True, help="简答题干（纯文本或 HTML）")
    @click.option("--directory-id", "directory_id", default="0", help="作业库文件夹 ID（默认根目录）")
    @click.option("--attach", "attachments", multiple=True,
                  help="D83-7：附件本地路径（图片/pdf/doc 等，可多次；内嵌进那道简答题正文；按通知扩展名白名单校验）")
    def xxt_work_create(course_id, class_id, cpi, title, stem_html, directory_id, attachments):
        """新建 1 道简答题草稿（可带附件；白名单限制）。"""
        from .work import create_work
        from ..workspace import find_workspace
        rep = create_work(default_storage(None), course_id, class_id, cpi, title, stem_html,
                          directory_id, list(attachments), find_workspace(None))
        _journal("xxt_work_create",
                 params={"courseId": course_id, "classId": class_id, "title": title,
                         "directoryId": directory_id, "workLibraryId": rep.get("workLibraryId"),
                         "attachments": rep.get("attachments") or []},
                 result="ok" if rep.get("ok") else "fail",
                 error=str(rep.get("error") or "")[:200])
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("ok") else 2)

    @group.command("work-folder-create")
    @click.option("--course", "course_id", required=True)
    @click.option("--class", "class_id", required=True)
    @click.option("--cpi", required=True)
    @click.option("--directory-id", "directory_id", default="0", help="父文件夹 ID（0=根目录）")
    @click.option("--title", required=True)
    def xxt_work_folder_create(course_id, class_id, cpi, directory_id, title):
        """在作业库创建文件夹（白名单限制）。"""
        from .work import create_folder
        rep = create_folder(default_storage(None), course_id, class_id, cpi, directory_id, title)
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("ok") else 2)

    @group.command("work-copy")
    @click.option("--course", "course_id", required=True)
    @click.option("--class", "class_id", required=True)
    @click.option("--cpi", required=True)
    @click.option("--directory-id", "directory_id", default="0")
    @click.option("--work-library-id", "work_library_id", required=True)
    @click.option("--title", required=True, help="副本新标题（建议 原名-副本-时间戳）")
    def xxt_work_copy(course_id, class_id, cpi, directory_id, work_library_id, title):
        """复制作业为副本并重命名（白名单限制）。"""
        from .work import copy_work
        rep = copy_work(default_storage(None), course_id, class_id, cpi, directory_id,
                        work_library_id, title)
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("ok") else 2)

    @group.command("mark-submitted")
    @click.option("--course", "course_id", required=True)
    @click.option("--class", "class_id", required=True)
    @click.option("--cpi", default="0")
    @click.option("--work", "work_id", required=True,
                  help="作业 workId（也可传 workLibraryId，自动归一；mark 页只认 workId）")
    @click.option("--student", required=True, help="学生姓名（在批阅列表内精确匹配）")
    @click.option("--score", default=0.0, type=float, help="设为已交时填的分数（默认 0，作补交标记）")
    @click.option("--confirm-send", "send", is_flag=True, default=False,
                  help="真正点「确定」（默认 dry-run：只填弹窗不提交）")
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False))
    def xxt_mark_submitted(course_id, class_id, cpi, work_id, student, score, send, storage):
        """D84 §3：把某「未交」学生设为已交（补交/测试用；默认 dry-run，白名单限制）。"""
        from .grade_upload import mark_submitted
        from ..workspace import find_workspace
        rep = mark_submitted(storage=default_storage(None), course_id=course_id,
                             class_id=class_id, cpi=cpi, work_id=work_id, student=student,
                             score=score, send=bool(send), workspace=find_workspace(None))
        _journal("xxt_mark_submitted",
                 params={"courseId": course_id, "classId": class_id, "workId": work_id,
                         "student": student, "mode": rep.get("mode")},
                 result="ok" if rep.get("ok") else "fail",
                 error=str(rep.get("error") or "")[:200])
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("ok") else 2)

    @group.command("grade-upload")
    @click.option("--course", "course_id", required=True)
    @click.option("--class", "class_id", required=True)
    @click.option("--cpi", default="0")
    @click.option("--work", "work_id", required=True,
                  help="作业 workId（也可传 workLibraryId，自动归一；mark 页只认 workId）")
    @click.option("--student", default="", help="学生姓名（与 --work-answer-id 二选一）")
    @click.option("--work-answer-id", "work_answer_id", default="", help="直接指定 workAnswerId")
    @click.option("--comment", default="", help="作业批语（纯文本自动转段落；也可直接给 HTML）")
    @click.option("--comment-image", "comment_images", multiple=True,
                  help="评语图片（workspace 内 jpg/png 等，可多次）")
    @click.option("--question-comment", "question_comments", multiple=True,
                  help="题目批语（按题序，可多次）")
    @click.option("--score", "total_score", type=float, default=None, help="总分（#tmpscore）")
    @click.option("--question-score", "question_scores", multiple=True,
                  help='每题分，逗号分隔（如 "10,20,30"），可多次')
    @click.option("--confirm-send", "send", is_flag=True, default=False,
                  help="真正提交批阅（默认 dry-run：只填入并读回校验）")
    @click.option("--force", is_flag=True, default=False, help="已批阅也覆盖提交")
    @click.option("--task", "task_path", default=None, type=click.Path(exists=True, dir_okay=False),
                  help="任务包 JSON：从批阅产物（evaluations）装配批语/分数")
    @click.option("--all", "all_students", is_flag=True, default=False,
                  help="对产物内全部学生上传（默认仅 --student 指定的一人）")
    @click.option("--from-drafts", "from_drafts", is_flag=True, default=False,
                  help="D85：上传本地人工批阅草稿（<xxt_home>/grade-drafts）；可配 --student 只传一人")
    @click.option("--storage", "storage", default=None, type=click.Path(dir_okay=False))
    def xxt_grade_upload(course_id, class_id, cpi, work_id, student, work_answer_id,
                         comment, comment_images, question_comments, total_score,
                         question_scores, send, force, task_path, all_students,
                         from_drafts, storage):
        """D84 §2：批阅页上传批语（文字+图片）/分数并提交（默认 dry-run，白名单限制）。"""
        from .grade_upload import upload_grade
        from .marking import parse_question_scores
        from .notice import safe_attachment_path
        from ..workspace import find_workspace
        ws = find_workspace(None)
        imgs: list[str] = []
        for raw in comment_images:
            pth = safe_attachment_path(raw, ws)
            if pth is None:
                raise click.UsageError(f"评语图片被拒绝（需在 workspace 内且格式在白名单）：{raw}")
            imgs.append(str(pth))
        scores: list[float] = []
        for spec in question_scores:
            scores.extend(parse_question_scores(spec))
        # D85 §3：--from-drafts → 读本地人工批阅草稿（图片落 workspace 临时目录后走 --comment-image）
        if from_drafts:
            from . import grade_store
            from .session import xxt_home
            from .grade_upload import drafts_to_payloads
            drafts = grade_store.read_drafts(xxt_home(), class_id, work_id)
            payloads = drafts_to_payloads(drafts, only=student)
            if not payloads:
                click.echo(json.dumps({"ok": False, "error": "本地无该作业的批阅草稿",
                                       "hint": "先在逐生预览的『人工批阅』栏填写并保存到本地",
                                       "keys": sorted((drafts or {}).keys())},
                                      ensure_ascii=False, indent=1))
                raise SystemExit(2)
            tmp_dir = ws / "tmp" / "grade-uploads" / time.strftime("%Y%m%d-%H%M%S")
            reps = []
            for pl in payloads:
                imgs: list[str] = []
                for i, img in enumerate(pl.get("images") or []):
                    data = str(img.get("data_b64") or "")
                    if not data:
                        continue
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    ext = Path(str(img.get("name") or "img.png")).suffix or ".png"
                    fp = tmp_dir / f"{pl['key']}-{i + 1}{ext}"
                    try:
                        import base64
                        fp.write_bytes(base64.b64decode(data.split(",")[-1]))
                        imgs.append(str(fp))
                    except Exception as exc:  # noqa: BLE001
                        reps.append({"ok": False, "error": f"草稿图片解码失败：{exc}"})
                rep = upload_grade(storage=default_storage(None), course_id=course_id,
                                   class_id=class_id, cpi=cpi, work_id=work_id,
                                   student=str(pl["key"]),
                                   comment=str(pl.get("comment") or ""), comment_images=imgs,
                                   total_score=pl.get("score"), question_scores=None,
                                   send=bool(send), force=bool(force), workspace=ws)
                rep["draftKey"] = pl["key"]
                reps.append(rep)
                if len(payloads) > 1:
                    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
            summary = reps[0] if len(reps) == 1 else {
                "ok": all(x.get("ok") for x in reps), "count": len(reps),
                "okCount": sum(1 for x in reps if x.get("ok")), "results": reps}
            _journal("xxt_grade_upload",
                     params={"courseId": course_id, "classId": class_id, "workId": work_id,
                             "mode": summary.get("mode"), "fromDrafts": True,
                             "count": len(reps)},
                     result="ok" if summary.get("ok") else "fail",
                     error=str(summary.get("error") or "")[:200])
            click.echo(json.dumps(summary, ensure_ascii=False, indent=1))
            raise SystemExit(0 if summary.get("ok") else 2)

        # §4：--task 时从批阅产物装配（评语=feedback_md、分数=total/per_question）
        targets: list[dict] = [{}]
        if task_path:
            from .grade_upload import build_upload_payloads, find_payload
            payloads = build_upload_payloads(ws, task_path)
            if all_students:
                targets = payloads
            elif student:
                hit = find_payload(payloads, student)
                targets = [hit] if hit else []
            else:
                raise click.UsageError("--task 需配合 --student 或 --all")
            if not targets:
                click.echo(json.dumps({"ok": False, "error": f"批阅产物中未找到学生：{student}",
                                       "payloads": [x["student"] for x in payloads]},
                                      ensure_ascii=False, indent=1))
                raise SystemExit(2)

        reps: list[dict] = []
        for tgt in targets:
            stu = student or str(tgt.get("student") or "")
            rep = upload_grade(storage=default_storage(None), course_id=course_id,
                               class_id=class_id, cpi=cpi, work_id=work_id, student=stu,
                               work_answer_id=work_answer_id,
                               comment=comment or str(tgt.get("comment") or ""),
                               comment_images=imgs, question_comments=list(question_comments),
                               total_score=(total_score if total_score is not None
                                            else tgt.get("total_score")),
                               question_scores=(scores or tgt.get("question_scores") or None),
                               send=bool(send), force=bool(force), workspace=ws)
            reps.append(rep)
            if len(targets) > 1:
                click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        rep = reps[0] if len(reps) == 1 else {
            "ok": all(x.get("ok") for x in reps), "count": len(reps),
            "okCount": sum(1 for x in reps if x.get("ok")),
            "results": reps}
        _journal("xxt_grade_upload",
                 params={"courseId": course_id, "classId": class_id, "workId": work_id,
                         "student": student or work_answer_id, "mode": rep.get("mode"),
                         "score": total_score, "images": len(imgs),
                         "task": task_path, "all": bool(all_students)},
                 result="ok" if rep.get("ok") else "fail",
                 error=str(rep.get("error") or "")[:200])
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
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
