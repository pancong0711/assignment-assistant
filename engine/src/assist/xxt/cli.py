"""d63 T1：`assist xxt` 命令组（check/login）。由 assist/cli.py 注册进主 cli。"""
from __future__ import annotations

import json
from pathlib import Path

import click


def default_storage(ctx) -> Path:
    """沿用 session.resolve_storage_path，保证 CLI / serve 路径契约一致。"""
    from .session import resolve_storage_path
    return resolve_storage_path(None)


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
        click.echo(_json.dumps(summary, ensure_ascii=False, indent=1))
        click.echo(f"out={rep.get('out', '(failed)')}")
        raise SystemExit(0 if not rep.get('failures') else 1)

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
        raise SystemExit(0 if ok else 2)
