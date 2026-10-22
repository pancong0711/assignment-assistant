"""assist CLI — 统一命令组（合并两个旧项目 cli.py 的 cmd 结构，05-D1：CLI 超集）。

当前（阶段1）：bootstrap / doctor / kb / sheet。serve 与 grade 为后面阶段占位。
"""

import json
import os
import shutil
import pathlib
from pathlib import Path

import click
from loguru import logger

from . import __version__


def _setup(verbose: bool, ws: "Path | str | None" = None):
    """workspace 归一（兼容 Path/str —— S2a 联调发现的预存在 str bug）。"""
    from .log import setup_logging
    from .workspace import apply_runtime_env, find_workspace
    setup_logging(verbose)
    ws_path = find_workspace(ws) if ws is not None else find_workspace()
    apply_runtime_env(ws_path)
    return ws_path


@click.group()
@click.help_option("-h", "--help")
@click.version_option(__version__, "--version", prog_name="assist")
@click.option("--verbose", is_flag=True, help="DEBUG 级日志")
@click.pass_context
def cli(ctx, verbose):
    """assignment-assistant 引擎命令组。"""
    ctx.obj = {"verbose": verbose}


@cli.command()
@click.option("--workspace", "-w", default=None, help="workspace 路径（默认自动查找）")
@click.option("--no-sync", is_flag=True, help="只建目录，不安装依赖")
@click.pass_obj
def bootstrap(obj, workspace, no_sync):
    """初始化/修复 workspace，并把引擎环境装进 workspace/.runtime（05-D14）。"""
    from .bootstrap import bootstrap as _bootstrap
    _bootstrap(workspace, sync_deps=not no_sync, quiet=obj.get("verbose") is False)


@cli.command()
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（含 LLM/agent 能力探测）")
@click.option("--report", "report_path", flag_value="", default=None,
              help="生成完整自检报告（不填值=写到 <ws>/selfcheck-report.json；也可给路径）")
@click.pass_obj
def doctor(obj, workspace, verbose, as_json, report_path):
    """环境体检 + LLM 能力探测（D98-B2）：依赖 / API / command / batch / agent CLI。

    agent 执行 skill 前应读 `--json` 的 `capabilities.recommendedPath` 决定走哪条路径：
    `api`（有 key）| `command`（有 CLI/type=command）| `subagent-or-manual`（都没有）。
    """
    import importlib
    from .workspace import find_workspace, load_workspace_settings
    ws_path = _setup(verbose or obj.get("verbose"), workspace)
    checks = []
    for mod, label in [("openpyxl", "openpyxl"), ("reportlab", "reportlab"),
                       ("loguru", "loguru"), ("httpx", "httpx"), ("PIL", "pillow")]:
        try:
            importlib.import_module(mod)
            checks.append((label, "green"))
        except ImportError:
            checks.append((label, "red"))
    uv_ok = "green" if shutil.which("uv") else "red"
    checks.append(("uv", uv_ok))
    try:
        from .paper.latex import check_xelatex
        checks.append(("xelatex(可选)", "green" if check_xelatex(ws_path) else "yellow"))
    except ImportError:
        checks.append(("xelatex(可选)", "red"))
    cfg = load_workspace_settings(ws_path)
    checks.append(("settings.local.json", "green" if (ws_path / "settings.local.json").exists() else "yellow"))
    checks.append(("kb/problems.xlsx", "green" if (ws_path / "kb" / "problems.xlsx").exists() else "yellow"))
    # D98-B2：LLM/agent 能力探测
    from .grading.providers import capabilities
    caps = capabilities(ws_path)

    # D98：完整自检报告（环境/配置/能力/数据/产物 + 根因与修复建议）
    if report_path is not None:
        from .selfcheck import build_report, format_human, write_report
        rep = build_report(ws_path)
        out = (Path(report_path).expanduser() if str(report_path)
               else (ws_path / "selfcheck-report.json"))
        write_report(rep, out)
        if as_json:
            click.echo(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            click.echo(format_human(rep))
            click.echo(f"\n报告已写入：{out}")
        raise SystemExit(0 if rep["summary"]["ok"] else 1)

    if as_json:
        click.echo(json.dumps({
            "checks": [{"name": n, "status": st} for n, st in checks],
            "capabilities": caps,
        }, ensure_ascii=False, indent=2))
        return
    rows = ["项        状态", "-" * 24] + [f"{n:<10}{'✓' if s == 'green' else ('!' if s == 'yellow' else '✗')} ({s})" for n, s in checks]
    click.echo("\n".join(rows))
    bad = [n for n, s in checks if s == "red"]
    if bad:
        click.echo(f"缺失：{bad}。安装：assist bootstrap")
    # 能力摘要（人读）
    click.echo("")
    click.echo("LLM 能力：")
    click.echo(f"  api(有 key)     : {'✓ ' + ', '.join(caps['api']['providers']) if caps['api']['available'] else '✗ 未配置'}")
    click.echo(f"  command(CLI回环): {'✓ ' + ', '.join(caps['command']['providers']) if caps['command']['available'] else '✗ 未配置'}")
    click.echo(f"  batch           : {'✓ ' + ', '.join(caps['batch']['providers']) if caps['batch']['available'] else '✗ 不可用'}")
    clis = caps["agentCli"]
    click.echo(f"  agent CLI       : {'✓ ' + ', '.join(c['name'] for c in clis) if clis else '✗ 未检测到'}")
    click.echo(f"  推荐路径        : {caps['recommendedPath']}")
    for w in caps.get("warnings") or []:
        mark = "⚠" if w.get("level") == "warn" else "·"
        click.echo(f"  {mark} {w.get('message')}")


@cli.group(help="引擎版本检测/在线更新（D65-P4；更新后需重启引擎）")
def engine():
    pass


@engine.command("version")
@click.option("--workspace", "-w", default=None, help="workspace 路径（默认自动查找）")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（默认人类可读）")
def engine_version(workspace, as_json):
    """对比本地 engine 与 Pages 上发布的最新版本。"""
    ws = _setup(False, workspace)
    from .engine_update import check_engine_update
    info = check_engine_update(ws)
    if as_json:
        click.echo(json.dumps(info, ensure_ascii=False, indent=2))
        return
    local, remote = info.get("local") or {}, info.get("remote") or {}
    click.echo(f"本地：{local.get('engine_version', '?')} commit={str(local.get('commit') or '')[:12]} path={local.get('_path', '')}")
    if info.get("ok"):
        click.echo(f"远端：{remote.get('engine_version', '?')} commit={str(remote.get('commit') or '')[:12]} source={info.get('remote_url')}")
        click.echo("更新：有可用更新" if info.get("update_available") else "更新：已是最新")
    else:
        click.echo(f"远端不可达：{info.get('error') or '未知错误'}")
        raise SystemExit(1)


@engine.command("status")
@click.option("--workspace", "-w", default=None, help="workspace 路径（默认自动查找）")
@click.option("--json", "as_json", is_flag=True, help="输出完整 JSON（默认人类可读）")
def engine_status(workspace, as_json):
    """引擎状态：本地/远端版本 + 两阶段更新现场（pending/staging/failed）。

    供 AI/脚本判断「更新卡在哪一步」：仅暂存(pending) 说明还需 launcher 重启安装。
    """
    ws = _setup(False, workspace)
    from .engine_update import update_status
    st = update_status(ws)
    if as_json:
        click.echo(json.dumps(st, ensure_ascii=False, indent=2))
        return
    loc = st.get("local") or {}
    rem = st.get("remote") or {}
    click.echo(f"本地：{loc.get('engine_version', '?')} commit={str(loc.get('commit') or '')[:12]}")
    if st.get("ok"):
        click.echo(f"远端：{rem.get('engine_version', '?')} commit={str(rem.get('commit') or '')[:12]}")
    else:
        click.echo(f"远端不可达：{st.get('error') or '未知错误'}")
    click.echo(f"更新阶段：{st.get('stage')}（pending={st.get('pending')} "
               f"staging={st.get('staging')} failed={st.get('failed')}）")
    click.echo(f"提示：{st.get('hint')}")


@engine.command("restart")
@click.option("--workspace", "-w", default=None, help="workspace 路径（默认自动查找）")
@click.option("--port", default=8601, show_default=True, help="本地 serve 端口")
@click.option("--token", default="", help="lan 模式的访问 token（如已开启）")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON")
def engine_restart(workspace, port, token, as_json):
    """重启**正在运行的**本地 serve（POST /restart）。

    CLI 自己是短命进程，无法"重启自身"；本命令用于让已运行的 serve 重新拉起
    （例如 `assist engine update` 暂存了新版本后触发安装）。若 serve 未运行，会明确报错。
    """
    import urllib.error
    import urllib.request
    _setup(False, workspace)
    url = f"http://127.0.0.1:{port}/restart" + (f"?token={token}" if token else "")
    body = b"{}"
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            rep = json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        rep = {"ok": False, "status": e.code, "error": f"HTTP {e.code}", "detail": detail}
    except Exception as e:  # noqa: BLE001
        rep = {"ok": False, "error": f"无法连接本地 serve（127.0.0.1:{port}）：{str(e)[:160]}",
               "hint": "先启动 `assist serve`；若是 start.bat/start.sh 托管，重启会由 launcher 接管"}
    if as_json:
        click.echo(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        click.echo("重启请求已受理" if rep.get("ok") else f"重启失败：{rep.get('error')}")
        if rep.get("hint"):
            click.echo(f"提示：{rep['hint']}")
    raise SystemExit(0 if rep.get("ok") else 2)


@engine.command("update")
@click.option("--workspace", "-w", default=None, help="workspace 路径（默认自动查找）")
@click.option("--check", is_flag=True, help="只检测、不下载")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（受 --verbose 日志转到 stderr）")
def engine_update_cmd(workspace, check, as_json):
    """检测并按需更新 engine（只暂存，需 launcher 重启安装）；--json 便于脚本/AI 解析。"""
    ws = _setup(False, workspace)
    from .engine_update import check_engine_update, update_engine, update_status
    if check:
        info = check_engine_update(ws)
        click.echo(json.dumps(info, ensure_ascii=False, indent=2))
        raise SystemExit(0 if info.get("ok") else 1)
    lines: list[str] = []

    def _emit(line: str) -> None:
        lines.append(str(line))
        if not as_json:
            click.echo(line)

    rc = update_engine(ws, _emit)
    st = update_status(ws)
    # 与 serve 的 install_engine_update 同口径记 journal（失败可回溯）。
    try:
        from .xxt import journal as _j
        _j.log_event("engine_update", source="cli",
                     params={"rc": rc, "stage": st.get("stage")},
                     result="ok" if rc == 0 else "fail",
                     error=("" if rc == 0 else "\n".join(lines[-5:])[:300]))
    except Exception:  # noqa: BLE001
        pass
    if as_json:
        click.echo(json.dumps({"ok": rc == 0, "rc": rc, "stage": st.get("stage"),
                               "pending": st.get("pending"), "lines": lines,
                               "hint": st.get("hint")}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if rc == 0 else 1)


@cli.group(help="TeX/TinyTeX 可选依赖（网络安装，仓库不含安装包，D58）")
def tex():
    pass


@tex.command("status")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def tex_status(obj, workspace, verbose):
    """检查 xelatex；优先系统 PATH，其次 workspace/.runtime/tex（TinyTeX）。"""
    from .paper.tinytex import find_xelatex
    ws = _setup(verbose or obj.get("verbose"), workspace)
    x = find_xelatex(ws)
    if x:
        click.echo(f"xelatex: {x}")
    else:
        click.echo("xelatex: 未安装（可选依赖）")
        click.echo(f"安装 TinyTeX（网络下载到 {ws / '.runtime' / 'tex'}）：assist tex install --workspace {ws}")


@tex.command("install")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_context
def tex_install(ctx, workspace, verbose):
    """下载并安装 TinyTeX 到 workspace/.runtime/tex（不把安装包放进仓库）。"""
    from .paper.tinytex import install_tinytex
    ws = _setup(verbose or ctx.obj.get("verbose"), workspace)
    rc = install_tinytex(ws, click.echo)
    if rc != 0:
        ctx.exit(rc)


@cli.group(help="题库管理（kb xlsx 为主数据，JSON 为导出副本，05-D3）")
def kb():
    pass


def _kb_dir(ws):
    d = ws / "kb"
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
    return d


@kb.command("stats")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_stats(obj, workspace, verbose):
    """统计题库章节与题目数量。"""
    from .files import read_kb
    # P0 附带修复：此前未把 --workspace 传给 _setup，-w 被忽略（落到默认 workspace）。
    kb_dir = _kb_dir(_setup(verbose or obj.get("verbose"), workspace))
    kb_data = read_kb(kb_dir)
    rows = []
    for kind, chapters in kb_data.items():
        for chap, entries in chapters.items():
            rows.append((kind, chap, len(entries)))
    if not rows:
        click.echo("题库为空（kb/ 下无 xlsx）。生成默认题库请用 PWA 体检页的"
                   "「创建题库」（引擎端点 /install/kb_init），或把题库 xlsx 放入 kb/。")
        return
    click.echo(f"{'kind':>12} {'chapter':>10} count")
    click.echo("-" * 34)
    for r in rows:
        click.echo(f"{r[0]:>12} {r[1]:>10} {r[2]:>5}")
    click.echo(f"合计条目: {sum(r[2] for r in rows)}")


@kb.command("export")
@click.option("--fmt", "fmt", type=click.Choice(["json"]), default="json")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_export(obj, fmt, workspace, verbose):
    """导出 JSON 副本到 kb/export/（AI 阅读/diff 基准，不入库）。

    `--fmt` 目前只支持 json（保留参数以便将来扩展 csv/md）。
    """
    from .files import read_kb, write_json
    ws = _setup(verbose or obj.get("verbose"), workspace)
    if fmt != "json":
        raise click.ClickException(f"暂不支持的导出格式：{fmt}（当前仅 json）")
    out = write_json(ws / "kb", read_kb(ws / "kb"))
    click.echo(f"已导出 → {out}")


@kb.command("write")
@click.option("--input", "input_path", required=True, type=click.Path(exists=True, dir_okay=False),
              help="JSON 文件：--kind 时={chap:[条目]}；缺省时={kind:{chap:[条目]}}（同 kb export）")
@click.option("--kind", default=None, help="只写一个 kind（problems/copy/...），JSON 顶层直接为 chapters")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_write(obj, input_path, kind, workspace, verbose):
    """样式保留写回 xlsx（B4）：openpyxl 只改 cell.value，保留字体/边框/列宽；写前自动快照。"""
    import re
    from .files import snapshot as snap
    from .files import write_chapters_preserving
    from .files.kb_io import validate_sheet_name
    ws = _setup(verbose or obj.get("verbose"), workspace)
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise click.ClickException("JSON 顶层必须是对象")
    if kind:
        targets = {kind: payload}
    else:
        targets = {k: v for k, v in payload.items() if isinstance(v, dict)}
    if not targets:
        raise click.ClickException("没有可写入的 kind 数据")
    kb_dir = _kb_dir(ws)
    for k, chapters in targets.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(k)):
            raise click.ClickException(f"非法 kind：{k}")
        if not all(isinstance(v, list) for v in chapters.values()):
            raise click.ClickException(f"{k} 的 chapters 值必须是条目数组")
        # P0：章节名 = Excel sheet 名，写前先给出可读错误（而非 openpyxl 堆栈）。
        for sheet in chapters:
            err = validate_sheet_name(sheet)
            if err:
                raise click.ClickException(f"{k} 的章节名非法：{err}")
        snap(kb_dir, [str(k)])
        out = write_chapters_preserving(kb_dir / f"{k}.xlsx", chapters)
        click.echo(str(out))


@kb.command("snapshot")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_snapshot(obj, workspace, verbose):
    """手动把 kb/*.xlsx 快照到 kb/.history/。"""
    from .files import snapshot as snap
    ws = _setup(verbose or obj.get("verbose"), workspace)
    made = snap(ws / "kb")
    click.echo(f"快照 {len(made)} 个文件")


@kb.command("ai-solve")
@click.option("--kb-kind", "kb_kind", default="problems", help="题库 kind（problems/copy/qa…）")
@click.option("--chap", default="", help="章节 sheet 名（如 chap10）；缺省=整库")
@click.option("--ids", default="", help="题号（逗号分隔）；缺省=该章全部")
@click.option("--model", default="", help="覆盖模型名（缺省取评阅段配置）")
@click.option("--pin", is_flag=True, help="作答后置顶为新生效答案（默认不置顶，不抢原答案）")
@click.option("--apply", is_flag=True, help="真正写回 kb/solutions/（缺省 dry-run 只预览）")
@click.option("--concurrency", default=3, type=int, show_default=True, help="并发题数")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_ai_solve(obj, kb_kind, chap, ids, model, pin, apply, concurrency, workspace, verbose):
    """D89-N5：对题库题目做 AI 作答（**不覆盖**原答案，新增版本；默认 dry-run）。"""
    from .grading import solve as solve_mod
    ws = _setup(verbose or obj.get("verbose"), workspace)
    id_list = [x.strip() for x in str(ids).split(",") if x.strip()]
    targets = solve_mod.list_targets(ws, kb_kind, chap, id_list)
    if not targets:
        raise click.ClickException("未选中任何题目（检查 --kb-kind/--chap/--ids）")
    res = solve_mod.solve_targets(ws, targets, model=model, apply=apply, pin=pin,
                                  dry_run=True, concurrency=concurrency)
    if res.get("dryRun"):
        click.echo(json.dumps({"dryRun": True, "planned": res["planned"],
                               "ids": [p["id"] for p in res.get("plans", [])]},
                              ensure_ascii=False, indent=2))
        click.echo("（dry-run：加 --apply 才真正作答并写回 kb/solutions/）")
        return
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))


# ---------------- D89 solution 多版本库 ----------------

@kb.command("catalog")
@click.option("--no-content", is_flag=True, help="不返回题目内容（仅 id）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_catalog(obj, no_content, workspace, verbose):
    """D92：只读列出题库目录（kind/章节/题号[+内容]，供下拉）。"""
    from .files.kb_io import catalog as _catalog
    ws = _setup(verbose or obj.get("verbose"), workspace)
    click.echo(json.dumps(_catalog(ws / "kb", with_content=not no_content),
                          ensure_ascii=False, indent=2))


@kb.group("solution")
def kb_solution():
    pass


@kb_solution.command("list")
@click.option("--qid", default=None, help="指定题目 id；缺省列出全部")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_solution_list(obj, qid, workspace, verbose):
    """列出题目答案版本库（JSON）。"""
    from .files import solutions as sol
    ws = _setup(verbose or obj.get("verbose"), workspace)
    data = sol.read_solutions(ws, qid) if qid else {"items": sol.list_solutions(ws)}
    click.echo(json.dumps(data or {"ok": False, "error": f"无版本库：{qid}"},
                          ensure_ascii=False, indent=2))


@kb_solution.command("add")
@click.option("--qid", required=True)
@click.option("--text", default=None, help="答案文本（或 --file）")
@click.option("--file", "file_", default=None, help="从文件读答案文本")
@click.option("--source", default="human", type=click.Choice(["human", "ai"]))
@click.option("--model", default="", help="AI 作答的模型名（source=ai 时建议填）")
@click.option("--kb", default="", help="题库 kind（problems/copy…）")
@click.option("--chap", default="")
@click.option("--pin", is_flag=True, help="追加后立即置顶（设为生效答案）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_solution_add(obj, qid, text, file_, source, model, kb, chap, pin, workspace, verbose):
    """追加一版答案（**不覆盖**已有版本）。"""
    from .files import solutions as sol
    ws = _setup(verbose or obj.get("verbose"), workspace)
    body = text if text is not None else (
        Path(file_).expanduser().read_text(encoding="utf-8") if file_ else "")
    res = sol.add_version(ws, qid, body, source=source, model=model, kb=kb, chap=chap, pin=pin)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "追加失败")


@kb_solution.command("pin")
@click.option("--qid", required=True)
@click.option("--version", "version_id", required=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_solution_pin(obj, qid, version_id, workspace, verbose):
    """把某版本置顶（设为生效答案，其余取消置顶）。"""
    from .files import solutions as sol
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = sol.pin_version(ws, qid, version_id)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "置顶失败")


@kb_solution.command("rm")
@click.option("--qid", required=True)
@click.option("--version", "version_id", required=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_solution_rm(obj, qid, version_id, workspace, verbose):
    """删除某版本。"""
    from .files import solutions as sol
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = sol.remove_version(ws, qid, version_id)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "删除失败")


@cli.group(help="作业纸生成（竖版/横版 A4）")
def sheet():
    pass


@sheet.command("demo")
@click.option("--out", "-o", default="kb/.demo", help="输出目录")
@click.option("--orientation", type=click.Choice(["portrait", "landscape"]), default="landscape")
@click.option("--no-watermark", is_flag=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def sheet_demo(obj, out, orientation, no_watermark, workspace, verbose):
    """用合成数据（假学生）产出示例作业纸 pdf（不写真实学生信息）。"""
    import tempfile

    from PIL import Image as PILImage
    from . import ASSIST_ROOT
    from .paper import make_pdf
    ws = _setup(verbose or obj.get("verbose"), workspace)
    out_dir = (ws / "classes" / "_demo" / "sheets" / "out").resolve()
    # 合成两张"题干图"（视频/截图占位），不含任何真实数据
    figs = []
    for i in range(1, 3):
        fn = ws / "kb" / "fig" / f".demo_{i}.png"
        fn.parent.mkdir(parents=True, exist_ok=True)
        PILImage.new("RGB", (1200, 900), (245, 246, 248)).save(fn)
        figs.append(str(fn))
    students = [
        {"name": "学生A", "number": "2026xxxx01", "class": "classA"},
        {"name": "学生B", "number": "2026xxxx02", "class": "classB"},
    ]
    items_of = lambda i: [(f"题干占位（stage1 demo）：请写出第{i+1}题的过程。", figs[i % 2], "distinguish", "1."),
                          ("第二题（无图占位）：练习书写规范。", None, "copy", "2.")]
    files = make_pdf(
        students, items_of, ws / out_dir, orientation,
        assets_dir=ASSIST_ROOT / "assets",
        title="大学物理-作业纸(demo)", watermark=not no_watermark,
    )
    for f in files:
        click.echo(str(f))


@sheet.command("html")
@click.option("--task", "task_path", required=True, help="任务包 JSON 路径")
@click.option("--roster", "roster_path", default=None,
              help="点名册 xlsx（姓名/学号/班级/tag 列；缺省=合成 学生A/B 演示名单）")
@click.option("--out", "-o", default=None,
              help="输出 html 路径（缺省 classes/<class>/sheets/html/<任务包id>.html）")
@click.option("--no-watermark", is_flag=True)
@click.option("--no-solution", is_flag=True, help="不含参考答案行（docs/13 D43-A1 parity，与 PWA「显示参考答案」未勾同语义）")
@click.option("--katex", "katex_mode", default="cdn", type=click.Choice(["cdn", "local"], case_sensitive=False),
              help="公式资源引用：cdn（缺省，现状）或 local（../katex/ 相对引用——配合设置中心「安装到 workspace」的 sheets/katex/ 离线渲染，docs/13 D53-G3）")
@click.option("--students", "students_mode", default="roster", type=click.Choice(["roster", "sample", "blank"], case_sensitive=False),
              help="名单口径：roster（缺省，--roster 及合成名单）；sample（合成 学生A/B 2 份模板样例）；blank（单份空白模板：页眉学籍三空位）")
@click.option("--assets-dir", "assets_dir", default=None,
              help="显式素材目录（水印图/字体）；缺省 workspace 优先，回落 engine/assets（D87）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def sheet_html(obj, task_path, roster_path, out, no_watermark, no_solution, students_mode, katex_mode, assets_dir, workspace, verbose):
    """按任务包生成整班自包含 HTML（浏览器打印主通道，docs/14 §VB-1/2/3 / 05-D30）。

    单文件承载整班多页：每生分页块（page-break-after）、@page A4 横/竖版、
    per_page 2/3/4 网格、题图与水印 base64 内嵌、KaTeX CDN 渲染 $..$ 公式。
    浏览器打开 → Ctrl/Cmd+P（A4/边距=无/页眉页脚=关/背景图形=开）→ 打印或存 PDF。
    与 PWA「打印浏览器版」共用同一模板（D1 超集铁律，docs/14 §VB 验收 4）。
    """
    from .paper.htmlfile import sheet_html_from_task
    # _setup 的显式 workspace 需为 Path（字符串会在 runtime_env 的 ws / ".runtime" 处炸）
    ws = _setup(verbose or obj.get("verbose"), Path(workspace) if workspace else None)
    fn, n_stu, n_pages = sheet_html_from_task(
        Path(task_path).expanduser().resolve(), ws,
        out_path=Path(out).expanduser().resolve() if out else None,
        roster_path=roster_path, no_watermark=no_watermark,
        include_solution=not no_solution, students_mode=students_mode.lower(),
        katex_mode=katex_mode.lower(),
        assets_dir=Path(assets_dir).expanduser().resolve() if assets_dir else None)
    click.echo(str(fn))
    click.echo(f"学生 {n_stu} 人 · 页块 {n_pages} 个（浏览器打开后 Ctrl/Cmd+P 打印；"
               "KaTeX 走 CDN，离线时公式按源码降级显示）"
               + ("" if not no_solution else "；本文件不含参考答案（--no-solution）")
               + ("" if students_mode.lower() == "roster" else f"；名单口径 --students {students_mode.lower()}"))


@sheet.command("make")
@click.option("--task", "task_path", required=True, help="任务包 JSON 路径")
@click.option("--roster", "roster_path", default=None, help="点名册 xlsx（缺省找 classes/<class>/roster/）")
@click.option("--out", "-o", default=None, help="输出目录（缺省 classes/<class>/sheets/out）")
@click.option("--no-watermark", is_flag=True)
@click.option("--assets-dir", "assets_dir", default=None,
              help="显式素材目录（水印图/字体）；缺省 workspace 优先，回落 engine/assets（D87）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def sheet_make(obj, task_path, roster_path, out, no_watermark, assets_dir, workspace, verbose):
    """按任务包生成每生一份作业纸 PDF（xlsx 名单驱动）。"""
    from .paper import sheets_from_task
    from .workspace import load_workspace_settings
    ws = _setup(verbose or obj.get("verbose"), workspace)
    files = sheets_from_task(
        Path(task_path).expanduser().resolve(), ws,
        out_dir=Path(out).expanduser().resolve() if out else None,
        no_watermark=no_watermark,
        roster_path=str(roster_path) if roster_path else None,
        user_cfg=load_workspace_settings(ws),
        assets_dir=assets_dir,
    )
    for f in files:
        click.echo(str(f))


# ---------------- D90 LLM Playground ----------------

@cli.group("playground", help="D90：LLM Playground（单次调用 + 附件 + 记录管理）")
def playground_grp():
    pass


@playground_grp.command("ask")
@click.option("--question", "-q", required=True, help="提问文本")
@click.option("--attach", "attachments", multiple=True, help="附件路径（图片/pdf/docx/txt，可多次）")
@click.option("--provider", default="", help="provider 名（缺省=评阅段配置）")
@click.option("--model", default="", help="模型名（缺省=provider/评阅段配置）")
@click.option("--folder", default="默认", help="归入的记录文件夹")
@click.option("--no-save", is_flag=True, help="不写入记录")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def playground_ask(obj, question, attachments, provider, model, folder, no_save, workspace, verbose):
    """单次调用大模型（无多轮上下文）；结果落 <ws>/playground/records/。"""
    from .playground import ask as pga
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = pga.ask(ws, question=question, provider=provider, model=model,
                  attachments=list(attachments), folder=folder, save=not no_save)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "调用失败")


@playground_grp.command("batch")
@click.option("--questions-file", default="", help="每行一个问题的文本文件（与 --items 二选一）")
@click.option("--items", "items_path", default=None, type=click.Path(exists=True, dir_okay=False),
              help="items JSON：每条自带 question+images（D98；各条互不共享）")
@click.option("--attach", "attachments", multiple=True, help="全局附件（仅非 items 模式）")
@click.option("--provider", default="")
@click.option("--model", default="")
@click.option("--folder", default="默认")
@click.option("--workers", default=3, type=int, show_default=True, help="并发数")
@click.option("--combine", is_flag=True, default=False,
              help="合并为一次请求（附件只发一遍，省 token；问题很多时慎用）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def playground_batch(obj, questions_file, items_path, attachments, provider, model, folder,
                     workers, combine, workspace, verbose):
    """批量发送：默认逐条独立；--combine 合并省 token；--items 每条自带图+文。"""
    from .playground import ask as pga
    ws = _setup(verbose or obj.get("verbose"), workspace)
    if items_path:
        from .grading.items import load_items_file
        try:
            items = load_items_file(items_path)
        except Exception as exc:  # noqa: BLE001
            raise click.ClickException(f"items 文件非法：{exc}")
        res = pga.batch_items(ws, items=items, provider=provider, model=model,
                              folder=folder, workers=workers)
    else:
        if not questions_file:
            raise click.UsageError("需要 --questions-file 或 --items")
        qs = [ln.strip() for ln in
              Path(questions_file).expanduser().read_text(encoding="utf-8").splitlines()
              if ln.strip()]
        res = pga.batch(ws, questions=qs, provider=provider, model=model,
                        attachments=list(attachments), folder=folder, combine=combine,
                        workers=workers)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "批量失败")


@playground_grp.command("records")
@click.option("--folder", default="", help="只列该文件夹")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def playground_records(obj, folder, workspace, verbose):
    """列出记录（含文件夹）。"""
    from .playground import store as pgs
    ws = _setup(verbose or obj.get("verbose"), workspace)
    recs = pgs.list_records(ws)
    if folder:
        recs = [r for r in recs if str(r.get("folder")) == folder]
    click.echo(json.dumps({"ok": True, "folders": pgs.list_folders(ws), "records": recs},
                          ensure_ascii=False, indent=2))


@playground_grp.command("move")
@click.option("--ids", required=True, help="记录 id（逗号分隔）")
@click.option("--folder", required=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def playground_move(obj, ids, folder, workspace, verbose):
    """把记录移动到文件夹。"""
    from .playground import store as pgs
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = pgs.move_records(ws, [x.strip() for x in ids.split(",") if x.strip()], folder)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))


@playground_grp.command("rm")
@click.option("--id", "rid", required=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def playground_rm(obj, rid, workspace, verbose):
    """删除一条记录。"""
    from .playground import store as pgs
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = pgs.delete_record(ws, rid)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "删除失败")


@playground_grp.group("folders")
def playground_folders():
    pass


@playground_folders.command("list")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def playground_folders_list(obj, workspace, verbose):
    from .playground import store as pgs
    ws = _setup(verbose or obj.get("verbose"), workspace)
    click.echo(json.dumps({"ok": True, "folders": pgs.list_folders(ws)}, ensure_ascii=False, indent=2))


@playground_folders.command("new")
@click.option("--name", required=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def playground_folders_new(obj, name, workspace, verbose):
    from .playground import store as pgs
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = pgs.add_folder(ws, name)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))


@playground_folders.command("rm")
@click.option("--name", required=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def playground_folders_rm(obj, name, workspace, verbose):
    from .playground import store as pgs
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = pgs.delete_folder(ws, name)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "删除失败")


# ---------------- D89 作业包（pack） ----------------

@cli.group("pack", help="D89：作业包（一次分层作业全部作业纸的集合）")
def pack_grp():
    pass


@pack_grp.command("list")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def pack_list(obj, workspace, verbose):
    """列出 workspace 下的作业包（JSON）。"""
    from .packs import list_packs
    ws = _setup(verbose or obj.get("verbose"), workspace)
    click.echo(json.dumps({"ok": True, "packs": list_packs(ws)}, ensure_ascii=False, indent=2))


@pack_grp.command("show")
@click.option("--id", "pid", required=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def pack_show(obj, pid, workspace, verbose):
    """读取单个作业包。"""
    from .packs import read_pack
    ws = _setup(verbose or obj.get("verbose"), workspace)
    d = read_pack(ws, pid)
    click.echo(json.dumps(d or {"ok": False, "error": f"作业包不存在：{pid}"},
                          ensure_ascii=False, indent=2))
    if not d:
        raise click.ClickException(f"作业包不存在：{pid}")


@pack_grp.command("save")
@click.option("--id", "pid", required=True, help="作业包 id")
@click.option("--file", "file_", required=True, help="作业包 JSON 文件（含 name/term/class_dir/pads）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def pack_save(obj, pid, file_, workspace, verbose):
    """新建/覆盖作业包。"""
    from .packs import save_pack
    ws = _setup(verbose or obj.get("verbose"), workspace)
    data = json.loads(Path(file_).expanduser().read_text(encoding="utf-8"))
    res = save_pack(ws, pid, data)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "保存失败")


@pack_grp.command("delete")
@click.option("--id", "pid", required=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def pack_delete(obj, pid, workspace, verbose):
    """删除作业包（不影响作业纸本身）。"""
    from .packs import delete_pack
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = delete_pack(ws, pid)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "删除失败")


# ---------------- D87 水印样式库（命名样式/默认/style_ref） ----------------

@cli.group("watermark", help="D87：水印样式库（命名样式 CRUD / 默认 / 素材目录）")
def watermark_grp():
    pass


def _wm_assets_dir(ws, explicit):
    """CLI 水印命令统一解析素材目录（explicit > <ws>/assets > engine/assets）。"""
    from .paper.assets import resolve_assets_dir
    d, src = resolve_assets_dir(ws=ws, explicit=explicit)
    return d, src


@watermark_grp.command("styles")
@click.option("--assets-dir", "assets_dir", default=None, help="显式素材目录（缺省 workspace 优先）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def watermark_styles(obj, assets_dir, workspace, verbose):
    """只读列出命名样式（含 default 标记）与素材文件清单（JSON 输出）。"""
    from .paper.watermark_styles import list_styles
    ws = _setup(verbose or obj.get("verbose"), workspace)
    ad, src = _wm_assets_dir(ws, assets_dir)
    wm_dir = ad / "watermark"
    files = sorted(p.name for p in wm_dir.glob("*") if p.is_file()) if wm_dir.is_dir() else []
    click.echo(json.dumps({
        "assets_dir": str(ad), "source": src,
        "styles": list_styles(ad), "files": files,
    }, ensure_ascii=False, indent=2))


@watermark_grp.command("save")
@click.option("--name", required=True, help="样式名（1..40 字符，不含路径分隔符）")
@click.option("--file", "file_", default=None, help="样式 JSON 文件（含 items/enabled/pageText）；缺省空样式")
@click.option("--set-default", "make_default", is_flag=True, help="同时设为默认样式（单选）")
@click.option("--assets-dir", "assets_dir", default=None)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def watermark_save(obj, name, file_, make_default, assets_dir, workspace, verbose):
    """新建/覆盖命名样式（可 --set-default 设为默认）。"""
    from .paper.watermark_styles import save_style
    ws = _setup(verbose or obj.get("verbose"), workspace)
    ad, _src = _wm_assets_dir(ws, assets_dir)
    data = {}
    if file_:
        data = json.loads(Path(file_).expanduser().read_text(encoding="utf-8"))
    res = save_style(ad, name, data, make_default=make_default)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "保存失败")


@watermark_grp.command("delete")
@click.option("--name", required=True)
@click.option("--assets-dir", "assets_dir", default=None)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def watermark_delete(obj, name, assets_dir, workspace, verbose):
    """删除命名样式。"""
    from .paper.watermark_styles import delete_style
    ws = _setup(verbose or obj.get("verbose"), workspace)
    ad, _src = _wm_assets_dir(ws, assets_dir)
    res = delete_style(ad, name)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "删除失败")


@watermark_grp.command("rename")
@click.option("--old", "old", required=True)
@click.option("--new", "new", required=True)
@click.option("--assets-dir", "assets_dir", default=None)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def watermark_rename(obj, old, new, assets_dir, workspace, verbose):
    """重命名命名样式（默认标记跟随）。"""
    from .paper.watermark_styles import rename_style
    ws = _setup(verbose or obj.get("verbose"), workspace)
    ad, _src = _wm_assets_dir(ws, assets_dir)
    res = rename_style(ad, old, new)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "重命名失败")


@watermark_grp.command("set-default")
@click.option("--name", required=True)
@click.option("--assets-dir", "assets_dir", default=None)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def watermark_set_default(obj, name, assets_dir, workspace, verbose):
    """把某样式设为默认（其余取消 default）。"""
    from .paper.watermark_styles import set_default
    ws = _setup(verbose or obj.get("verbose"), workspace)
    ad, _src = _wm_assets_dir(ws, assets_dir)
    click.echo(json.dumps(set_default(ad, name), ensure_ascii=False, indent=2))


# ---------------- M5 成绩管理（docs/05-D17/D18） ----------------

@cli.group(help="M5 成绩管理：点名册/多源成绩导入 → 打分层 tag → 导出带 tag 名单")
def roster():
    pass


def _parse_scores(specs):
    """--score 可多份，格式 "[family:]文件[:列[:权重]]"（D19 成绩适配层）。

    family ∈ exam / xuexitong_assignment / xuexitong_stat / rainclass / custom；
    family 缺省按 custom（列自动识别/手选）。"""
    from .roster.scores import ADAPTERS, read_source
    rows = []
    for spec in specs:
        family = None
        head = spec.split(":", 1)
        if len(head) == 2 and head[0] in ADAPTERS:
            family, spec = head[0], head[1]  # 去掉 family 前缀再解析 文件:列:权重
        parts = spec.rsplit(":", 2)
        if len(parts) == 3:
            try:
                fn, col, weight = parts[0], parts[1], float(parts[2])
            except ValueError:
                fn, col, weight = spec, "", 1.0
        elif len(parts) == 2:
            try:
                fn, col, weight = parts[0], "", float(parts[1])
            except ValueError:
                fn, col, weight = parts[0], parts[1], 1.0
        else:
            fn, col, weight = spec, "", 1.0
        p = Path(fn).expanduser().resolve()
        if family and family != "custom":
            rows = rows + read_source({"family": family, "file": str(p),
                                       "weight": weight,
                                       **({"col": col} if col else {})})
        else:
            rows = rows + read_source({"family": "custom", "file": str(p),
                                       "cols": col or None, "weight": weight})
    return rows


@roster.command("tag")
@click.option("--roster", "roster_fn", required=True, help="点名册 xlsx（姓名/学号/班级）")
@click.option("--score", "score_specs", multiple=True,
              help='成绩源，格式 "xlsx:列[:权重]"，可多份；列空则自动识别')
@click.option("--ratios", default=None, help='分组比例 JSON（缺省用 D18 默认模板），如 {"qa":0.3,...}')
@click.option("--special", default=None, help='人工覆盖 JSON，如 {"punish":["学生A"]}')
@click.option("--out", "-o", required=True, help="输出带 tag 名单 xlsx 路径")
@click.option("--no-weight-normalize", is_flag=True, help="不按权重归一（默认加权均值）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def roster_tag(obj, roster_fn, score_specs, ratios, special, out, no_weight_normalize, workspace, verbose):
    """M5：多源成绩 → 学生打分层 tag → 带 tag 名单 xlsx（sheet make --roster 直接可用）。"""
    import json as _json
    from .files.roster import read_roster
    from .roster import (DEFAULT_GROUP_CFG, merge_scores, tag_students,
                         tag_summary, tagged_xlsx)
    _setup(verbose or obj.get("verbose"), workspace)
    students = read_roster(Path(roster_fn).expanduser().resolve())
    if not students:
        raise click.ClickException(f"名单为空: {roster_fn}")
    score_rows = _parse_scores(list(score_specs))
    merged = merge_scores(students, score_rows, weight_normalize=not no_weight_normalize)
    group_cfg = DEFAULT_GROUP_CFG
    if ratios:
        group_cfg = [{"group_name": k, "group_ratio": v} for k, v in _json.loads(ratios).items()]
    special_cfg = _json.loads(special) if special else None
    rows = tag_students(students, merged, group_cfg=group_cfg,
                        special_tag_cfg=special_cfg)
    tagged = tagged_xlsx(Path(out).expanduser().resolve(), rows)
    click.echo(str(tagged))
    click.echo(_json.dumps(tag_summary(rows), ensure_ascii=False, indent=1))


@cli.command()
@click.option("--workspace", "-w", default=None)
@click.option("--host", default=None, help="绑定地址（缺省 127.0.0.1；--lan 时自动 0.0.0.0）")
@click.option("--port", default=8601, show_default=True)
@click.option("--lan", is_flag=True, help="开放局域网（0.0.0.0，自动生成 ?token= 防蹭网）")
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def serve(obj, workspace, host, port, lan, verbose):
    """本地引擎 HTTP 服务（阶段4a）：/doctor 体检 + /status + 托管 app/dist-lan。"""
    from .serve import serve as _serve
    _serve(workspace, host=host or ("0.0.0.0" if lan else "127.0.0.1"), port=port, lan=lan)


@sheet.command("batch")
@click.option("--roster", "roster_fn", required=True, help='带 tag 名单 xlsx（assist roster tag 产出）')
@click.option("--pads", "task_files", multiple=True, required=True, help="任务包 JSON（一个 tag 一份；可多份）")
@click.option("--map", "map_specs", multiple=True,
              help='显式映射 JSON：--map \'{"tag": "任务包文件名"}\'（可多次，key=tag value=文件名）')
@click.option("--default", "default_pad", default=None, help="未知 tag 的兜底任务包 id")
@click.option("--class-dir", default=None, help="班级子目录（缺省 classes/，产物落在其 sheets/batch/<tag>/）")
@click.option("--out", "-o", default=None, help="直接指定输出根目录")
@click.option("--assets-dir", "assets_dir", default=None,
              help="显式素材目录（水印图/字体）；缺省 workspace 优先，回落 engine/assets（D87）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def sheet_batch(obj, roster_fn, task_files, map_specs, default_pad, class_dir, out,
                assets_dir, workspace, verbose):
    """D23 变体编排：整班按 tag 自动选任务包生成作业纸（每生一份，tag 分组分目录）。

    任务包绑定 tag 规则：`target_tag` 字段优先，否则 items 中唯一 tag 即视为归属
    （混合 tag 的包用 --map 显式映射；PWA batch zip 内 batch.json 的 mapping 与
    其同口径）。注意 --map 语义 = JSON 字典（与实现一致；帮助文案与参数对齐校
    准见 docs/13 §S2c）。"""
    from .paper.batch import batch_sheets
    ws_path = _setup(verbose or obj.get("verbose"), workspace)
    mapping = {}
    import json as _j
    for m in map_specs:
        if m in _j.loads(m or "{}"):
            raise click.ClickException('--map 格式应为 JSON 字典，如 --map \'{"qa": "2026xxxx.taskpad.json"}\'')
        for k, v in _j.loads(m).items():
            mapping[k] = v
    files = batch_sheets(
        Path(roster_fn).expanduser().resolve(),
        [Path(f).expanduser().resolve() for f in task_files],
        ws_path, class_dir=class_dir,
        out_root=Path(out).expanduser().resolve() if out else None,
        mapping=mapping, default_pad=default_pad,
        assets_dir=assets_dir)
    for f in files:
        click.echo(str(f))


@roster.command("rain")
@click.option("--files", "files", multiple=True, required=True, help="雨课堂汇总表 xlsx（可多份，多表聚合）")
@click.option("--out", "-o", required=True, help="输出 xlsx 路径")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def roster_rain(obj, files, out, workspace, verbose):
    """雨课堂签到明细汇总（固定格式 family=rainclass，文档 docs/05-D19/B1）。"""
    import json as _j
    from .roster.rain import parse_rainclass, summarize, to_xlsx
    _setup(verbose or obj.get("verbose"), workspace)
    per = []
    for f in files:
        per += parse_rainclass(Path(f).expanduser().resolve())
    summary = summarize(per)
    click.echo(str(to_xlsx(Path(out).expanduser().resolve(), summary)))
    click.echo(_j.dumps(summary.get("rows", [])[:5], ensure_ascii=False, indent=1))


@cli.command("grade-drafts")
@click.option("--task", "task_path", required=True, help="任务包 JSON（定位 grading 产物）")
@click.option("--class", "class_id", required=True, help="学习通班级 ID（草稿键用）")
@click.option("--work", "work_id", required=True, help="学习通 workId")
@click.option("--class-dir", "class_dir", default="", help="workspace 班级目录（缺省 classes/<classId>）")
@click.option("--kind", type=click.Choice(["ai", "human"]), default="human",
              help="报告标注（ai=AI 批阅报告 / human=人工批阅报告）")
@click.option("--no-report", "no_report", is_flag=True, default=False, help="不生成报告 PNG")
@click.option("--workspace", "-w", default=None)
def grade_drafts(task_path, class_id, work_id, class_dir, kind, no_report, workspace):
    """D86 §6：把批阅产物写成本地批阅草稿（含报告 PNG），供 PWA 审核/一键上传。"""
    from .workspace import find_workspace
    from .grading.drafts import save_drafts_from_grading
    ws = find_workspace(workspace)
    task = json.loads(Path(task_path).expanduser().read_text(encoding="utf-8"))
    task_id = str(task.get("id") or "task")
    cdir = class_dir or str(task.get("class_dir") or f"classes/{class_id}")
    rep = save_drafts_from_grading(ws, class_id=class_id, work_id=work_id, task_id=task_id,
                                   class_dir=cdir, kind=kind,
                                   with_report_png=not no_report)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    raise SystemExit(0 if rep.get("ok") else 2)


@cli.command("grade-render")
@click.option("--class", "class_id", required=True, help="学习通班级 ID")
@click.option("--work", "work_id", required=True, help="学习通 workId")
@click.option("--task-id", "task_id", default="", help="任务 id（报告产物目录用）")
@click.option("--class-dir", "class_dir", default="")
@click.option("--no-png", is_flag=True, default=False, help="不生成报告 PNG（仅 md/html）")
@click.option("--workspace", "-w", default=None)
def grade_render(class_id, work_id, task_id, class_dir, no_png, workspace):
    """D92：按**已保存的双套草稿**逐生生成报告（人工在前+【附件】AI+修订标红）。"""
    from .workspace import find_workspace
    from .grading.drafts import render_reports_from_drafts
    ws = find_workspace(workspace)
    rep = render_reports_from_drafts(ws, class_id=class_id, work_id=work_id,
                                     task_id=task_id, class_dir=class_dir,
                                     with_report_png=not no_png)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    if not rep.get("ok"):
        raise click.ClickException(rep.get("error") or "生成失败")


@cli.command("render")
@click.option("--md", "md_file", default="", help="Markdown 报告文件（正式报告）")
@click.option("--text", "text", default="", help="批语纯文本（轻量批语图）")
@click.option("--out", "out_path", required=True, help="输出 PNG 路径")
@click.option("--kind", type=click.Choice(["ai", "human"]), default="ai")
@click.option("--title", default="")
@click.option("--subtitle", default="", help="如：学生A · 大学物理")
@click.option("--katex-dir", "katex_dir", default="", help="自托管 KaTeX 目录（缺省自动探测）")
def render(md_file, text, out_path, kind, title, subtitle, katex_dir):
    """D86 §5：把 Markdown 报告 / 批语文本渲染成 PNG（A4 宽 / 小四 / 长图，KaTeX 公式）。"""
    from .grading import report as _rep
    kd = Path(katex_dir).expanduser() if katex_dir else None
    if md_file:
        md = Path(md_file).expanduser().read_text(encoding="utf-8")
        png = _rep.render_report_png(md, out_path, kind=kind, title=title or "批阅报告",
                                     subtitle=subtitle, katex_dir=kd)
    elif text:
        png = _rep.render_comment_png(text, out_path, kind=kind, title=title,
                                      subtitle=subtitle, katex_dir=kd)
    elif md_file == "" and text == "":
        raise click.UsageError("需要 --md 或 --text")
    click.echo(str(png) if png else "（未渲染：playwright/浏览器不可用，已跳过 PNG）")
    raise SystemExit(0 if png else 2)


@cli.group("llm", help="D86：LLM provider / 两段式配置（key 只掩码回显，绝不入日志）")
def llm():
    pass


@llm.command("config")
@click.option("--migrate", is_flag=True, default=False, help="把旧 llm.base_url/api_key/model 迁移为 provider")
@click.option("--workspace", "-w", default=None)
def llm_config(migrate, workspace):
    """D86 §2：查看（掩码）/迁移 LLM provider 与两段式配置。"""
    from .workspace import find_workspace
    from .grading import providers
    ws = find_workspace(workspace)
    rep = {}
    if migrate:
        rep["migrate"] = providers.migrate_legacy(ws)
    rep["config"] = providers.public_config(ws)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))


@llm.command("provider")
@click.option("--action", type=click.Choice(["list", "set", "delete", "stage"]), default="list")
@click.option("--name", default="", help="provider 名称")
@click.option("--type", "provider_type", default="",
              type=click.Choice(["", "api", "command"]),
              help="api=HTTP+key；command=回环外部 agent CLI（无 key 场景，D98-B3）")
@click.option("--cmd", "cmd", multiple=True,
              help="command 型命令（可多次；支持 {model} 占位，如 --cmd opencode --cmd run）")
@click.option("--input-mode", "input_mode", default="", type=click.Choice(["", "stdin"]),
              help="命令输入方式（当前只支持 stdin 传 JSON）")
@click.option("--output-mode", "output_mode", default="",
              type=click.Choice(["", "stdout-json", "stdout-text"]),
              help="命令输出方式（缺省 stdout-json）")
@click.option("--timeout", "timeout_s", default=None, type=int, help="command 超时秒（缺省 300）")
@click.option("--supports-images/--no-supports-images", "supports_images", default=None,
              help="该 command 后端是否支持图片（缺省未标记）；转录段用它时会告警")
@click.option("--base-url", "base_url", default="")
@click.option("--api-key", "api_key", default=None, help="留空=不改；--clear-key 显式清除")
@click.option("--clear-key", is_flag=True, default=False)
@click.option("--batch", "batch_support", is_flag=True, default=False, help="该 provider 支持 batch")
@click.option("--model", default="", help="模型名（会记入该 provider 的模型历史）")
@click.option("--stage", default="", type=click.Choice(["", "transcription", "evaluation"]))
@click.option("--workspace", "-w", default=None)
def llm_provider(action, name, provider_type, cmd, input_mode, output_mode, timeout_s,
                 supports_images, base_url, api_key, clear_key, batch_support, model, stage,
                 workspace):
    """D86 §2：provider 管理（list/set/delete/stage）。key 只掩码回显，绝不入日志。

    D98-B3：`--type command --cmd ...` 可配置"回环外部 agent CLI"（无 API key 也能转录/批阅）。
    """
    from .workspace import find_workspace
    from .grading import providers
    ws = find_workspace(workspace)
    if action == "list":
        rep = {"ok": True, "config": providers.public_config(ws)}
    elif action == "delete":
        rep = providers.delete_provider(ws, name)
    elif action == "stage":
        rep = providers.set_stage(ws, stage, provider=name, model=model,
                                  batch=(True if batch_support else None))
    else:
        key_arg = "" if clear_key else api_key
        rep = providers.save_provider(
            ws, name, base_url=base_url, api_key=key_arg,
            batch_support=(True if batch_support else None), model=model,
            provider_type=provider_type, cmd=list(cmd) if cmd else None,
            input_mode=input_mode, output_mode=output_mode, timeout_s=timeout_s,
            supports_images=supports_images)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    raise SystemExit(0 if rep.get("ok") else 2)


@llm.command("batch")
@click.option("--task", "task_path", default="", help="任务包 JSON（用 plan+转录生成 batch 输入）")
@click.option("--jsonl", "jsonl_path", default="", help="已有 JSONL（或不传而用 --task 生成）")
@click.option("--provider", "provider_name", default="", help="provider 名称（缺省取 evaluation 段）")
@click.option("--limit", default=0, type=int, help="只取前 N 名学生")
@click.option("--submit", is_flag=True, default=False, help="真正提交（默认只生成 JSONL + 说明）")
@click.option("--poll", "poll_id", default="", help="轮询批次状态 <batch_id>")
@click.option("--download", "download_id", default="", help="下载结果 <output_file_id>")
@click.option("--out", "out_path", default="", help="下载结果落盘路径")
@click.option("--apply", "apply_results", is_flag=True, default=False,
              help="把下载/batch 结果 JSONL 回灌为 evaluations/*.json（D98-B6）")
@click.option("--results", "results_path", default="", help="--apply 的输入 JSONL（缺省用 --out）")
@click.option("--workspace", "-w", default=None)
def llm_batch(task_path, jsonl_path, provider_name, limit, submit, poll_id, download_id,
              out_path, apply_results, results_path, workspace):
    """D86 §7：LLM batch（Aliyun/OpenAI 兼容）——默认 dry-run（生成 JSONL + 说明）。

    D98-B6：`--apply` 把下载的 batch output JSONL **回灌**为评阅产物（补齐原断裂链路）。
    失败会输出完整诊断（HTTP 状态/响应原文/URL/批次 id），便于回传排查。
    """
    from .workspace import find_workspace
    from .grading import llm_batch as B, providers as P
    ws = find_workspace(workspace)
    if poll_id:
        click.echo(json.dumps(B.poll(ws, provider_name, poll_id), ensure_ascii=False, indent=1))
        return
    if download_id:
        got = B.download(ws, provider_name, download_id,
                         out_path or "batch-results.jsonl")
        click.echo(json.dumps(got, ensure_ascii=False, indent=1))
        if not (apply_results and got.get("ok")):
            return
        results_path = results_path or got.get("out") or ""
    if apply_results:
        if not results_path:
            raise click.UsageError("--apply 需要 --results <jsonl>（或配合 --download/--out）")
        if not task_path:
            raise click.UsageError("--apply 需要 --task <任务包> 以定位 evalications 目录")
        from .grading.flow import grading_dir, _paths
        task = json.loads(Path(task_path).expanduser().read_text(encoding="utf-8"))
        base = grading_dir(ws, task)
        paths = _paths(base)
        task_id = str(task.get("id") or "task")
        rep = B.apply_results(ws, results_path, evaluated_dir=paths["evaluations"],
                              transcripts_dir=paths["transcripts"],
                              homework_name=str(task.get("course") or "") + " " + task_id,
                              model="")
        click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("ok") else 2)
    if not jsonl_path:
        if not task_path:
            raise click.UsageError("需要 --jsonl 或 --task")
        plan = B.plan_batch_items(ws, task_path, provider_name=provider_name, limit=limit)
        if not plan["items"]:
            click.echo(json.dumps({"ok": False, "error": "没有可批的转录文件（先跑 transcribe，"
                                                        "或用 --xxt-class 装配 plan）"},
                                  ensure_ascii=False, indent=1))
            raise SystemExit(2)
        jsonl_path = str(Path(plan["dir"]) / "batch" / "evaluate-batch.jsonl")
        B.build_jsonl(plan["items"], jsonl_path, model=plan["model"])
        provider_name = provider_name or plan["provider"]
    prov = next((x for x in P.list_providers(ws, mask=True) if x["name"] == provider_name), None)
    if prov is None:
        click.echo(json.dumps({"ok": False, "error": f"provider 不存在：{provider_name}"},
                              ensure_ascii=False, indent=1))
        raise SystemExit(2)
    # 说明文件用内部视图（需要 base_url/batch_support，不含 key 也可），但输出只用掩码
    readme = B.write_instructions(Path(jsonl_path), provider=prov)
    click.echo(json.dumps({"ok": True, "mode": "submit" if submit else "dry-run",
                           "jsonl": str(jsonl_path), "readme": str(readme),
                           "provider": B.provider_public(prov)},
                          ensure_ascii=False, indent=1))
    if submit:
        click.echo(json.dumps(B.submit(ws, provider_name, jsonl_path), ensure_ascii=False,
                              indent=1))


@cli.command()
@click.option("--task", "task_path", required=True, help="任务包 JSON 路径（grade 节驱动）")
@click.option("--pads-dir", "pads_dir", default=None,
              help="D89：作业包目录（*.taskpad.json，按 tag 自动匹配多名学生；缺省=用 <ws>/tasks/）")
@click.option("--images", "images_dir", default=None, help="学生作业图片目录（文件名=学生名或学号-题号）")
@click.option("--rerun", "rerun", default=None,
              type=click.Choice(["download", "transcribe", "evaluate", "report", "upload"]),
              help="单步重跑（指定 step 名，只重跑该步）")
@click.option("--xxt-class", "xxt_class", default="",
              help="D86：学习通班级 <courseId>:<classId>（用 class_map 解析 class_dir 并装配 plan）")
@click.option("--work", "work_id", default="", help="D86：学习通 workId（批阅下载目录定位用）")
@click.option("--plan", "plan_path", default="", help="D86：已有批阅任务清单 plan.json（或用 --xxt-class 现装配）")
@click.option("--mode", "mode", default="", type=click.Choice(["", "optimized", "brute"]),
              help="D86：optimized（默认，给题目/答案）| brute（先自己作答再比对）")
@click.option("--tags", "tags", default="", help="D86：只批阅这些 tag（逗号分隔）")
@click.option("--limit", "limit", default=0, type=int, help="D86：只处理前 N 名学生（0=全部）")
@click.option("--dry-plan", "dry_plan", is_flag=True, default=False, help="只装配并打印 plan 摘要，不调 LLM")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def grade(obj, task_path, pads_dir, images_dir, rerun, xxt_class, work_id, plan_path, mode, tags,
          limit, dry_plan, workspace, verbose):
    """AI 批阅：transcribe → evaluate → report（阶段3；download/upload 属阶段4）。

    任务包 grade.steps 驱动；journal 运行记录写入
    classes/<class>/grading/<task>/journal.jsonl（05-D8）；
    LLM 配置读 workspace（`assist llm provider --action set|stage`；key 绝不入日志）。

    D86：`--xxt-class <courseId>:<classId> [--work <workId>]` 会用
    `xxt.class_map` + 带 tag 名单 + `<ws>/tasks/*.taskpad.json` + 批阅下载目录
    装配「批阅任务清单」（plan.json），并按学生 tag 取题目/参考答案。
    """
    import json as _json
    from .grading.flow import run_task, run_step
    from .grading import inputs as _inputs
    ws = _setup(verbose or obj.get("verbose"), workspace)
    tp = Path(task_path).expanduser().resolve()
    task = _json.loads(tp.read_text(encoding="utf-8"))
    task_id = str(task.get("id") or "task")

    plan = None
    if plan_path:
        plan = _inputs.load_plan(ws, Path(plan_path).stem) or _json.loads(
            Path(plan_path).read_text(encoding="utf-8"))
    elif xxt_class:
        cid, _, kid = str(xxt_class).partition(":")
        from .xxt import classmap
        resolved = classmap.resolve_class_dir(ws, cid, kid, str(task.get("class") or ""))
        class_dir = resolved.get("classDir") or str(task.get("class_dir") or "classes")
        tag_list = [t.strip() for t in str(tags).split(",") if t.strip()]
        plan = _inputs.build_plan(ws, task_id=task_id, class_dir=class_dir,
                                  class_id=kid, work_id=work_id, mode=(mode or "optimized"),
                                  tags=tag_list,
                                  tasks_dir=Path(pads_dir).expanduser().resolve() if pads_dir else None)
        if limit and plan.get("students"):
            plan["students"] = plan["students"][:limit]
        _inputs.save_plan(ws, class_dir, plan)
    if dry_plan or (plan and dry_plan):
        click.echo(_json.dumps(_inputs.plan_summary(plan or {}), ensure_ascii=False, indent=1))
        return

    kwargs = {"images_dir": images_dir} if images_dir else {}
    if plan:
        kwargs["plan"] = plan
        if mode:
            kwargs["mode"] = mode
    rec = run_step(tp, ws, rerun, **kwargs) if rerun else run_task(tp, ws, **kwargs)
    click.echo(f"完成 run_id={rec['run_id']} steps={rec['steps_done']}\n产物目录={rec['bucket']}")
    usage = rec.get("usage") or {}
    if usage.get("total"):
        t = usage["total"]
        click.echo(f"token 用量：prompt={t.get('prompt_tokens', 0)} "
                   f"completion={t.get('completion_tokens', 0)} "
                   f"total={t.get('total_tokens', 0)} calls={t.get('calls', 0)}"
                   "（provider 未返回 usage 时可能为 0）")


@cli.group("grade-plan", help="D98-B7：无 LLM 的清单/收作业（兜底；程序不调模型）")
def grade_plan_grp():
    pass


@grade_plan_grp.command("xxt-plan")
@click.option("--task", "task_path", required=True, help="任务包 JSON")
@click.option("--xxt-class", "xxt_class", required=True, help="<courseId>:<classId>")
@click.option("--work", "work_id", default="", help="学习通 workId")
@click.option("--pads-dir", "pads_dir", default=None, help="作业包目录（按 tag 匹配）")
@click.option("--tags", "tags", default="")
@click.option("--workspace", "-w", default=None)
def grade_plan_xxt(task_path, xxt_class, work_id, pads_dir, tags, workspace):
    """生成转录任务清单（每生一条；程序不调模型，正文由 agent 完成）。"""
    from .grading import inputs as _inputs
    from .grading.plan_collect import build_task_list, plan_items_from_plan
    from .grading.transcribe import TRANSCRIPTION_PROMPT
    from .workspace import find_workspace
    ws = find_workspace(workspace)
    task = json.loads(Path(task_path).expanduser().read_text(encoding="utf-8"))
    task_id = str(task.get("id") or "task")
    cid, _, kid = str(xxt_class).partition(":")
    from .xxt import classmap
    resolved = classmap.resolve_class_dir(ws, cid, kid, str(task.get("class") or ""))
    class_dir = resolved.get("classDir") or str(task.get("class_dir") or "classes")
    tag_list = [t.strip() for t in str(tags).split(",") if t.strip()]
    plan = _inputs.build_plan(ws, task_id=task_id, class_dir=class_dir, class_id=kid,
                              work_id=work_id, mode="optimized", tags=tag_list,
                              tasks_dir=Path(pads_dir).expanduser().resolve() if pads_dir else None)
    _inputs.save_plan(ws, class_dir, plan)
    base = ws / class_dir / "grading" / task_id
    items = plan_items_from_plan(ws, task_id=task_id, class_dir=class_dir,
                                 transcripts_out=base / "transcripts")
    if not items:
        raise click.ClickException("没有可转录的学生（检查 class-map / 作业下载 / tags）")
    rep = build_task_list(items=items, out_dir=base / "plan-collect", kind="transcribe",
                          prompt_template="{question}\n\n请转录这些图片：\n{images}",
                          system=TRANSCRIPTION_PROMPT)
    click.echo(json.dumps({"ok": True, "notice": rep["notice"], "total": rep["total"],
                           "taskList": str(base / "plan-collect" / "task-list.json"),
                           "transcriptsDir": str(base / "transcripts")},
                          ensure_ascii=False, indent=1))


@grade_plan_grp.command("collect")
@click.option("--task-list", "task_list_path", required=True, help="plan 产出的 task-list.json")
@click.option("--results-dir", "results_dir", required=True, help="agent 写回结果的目录")
@click.option("--kind", default="transcribe", type=click.Choice(["transcribe", "evaluate"]))
def grade_plan_collect(task_list_path, results_dir, kind):
    """校验 agent 写回的结果并生成 batch-report.json（程序不调模型）。"""
    from .grading.plan_collect import collect
    tl = json.loads(Path(task_list_path).expanduser().read_text(encoding="utf-8"))
    rep = collect(task_list=tl, results_dir=Path(results_dir).expanduser(), kind=kind)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    raise SystemExit(0 if rep.get("failed") == 0 else 1)


@cli.group(help="学习通对接（D63 T1；登录/体检为可选依赖 playwright）")
def xxt():
    """学习通会话与只读提取。"""

from .xxt.cli import register as _register_xxt  # noqa: E402
_register_xxt(xxt)


# ---------------- 机读错误：AI/脚本调用 CLI 时不要吃 traceback ----------------
# 约定（docs/13 P1.5）：未处理异常默认打印 traceback（保持人读体验）；
# 但设 `ASSIST_JSON_ERRORS=1` 或加全局 `--json-errors` 时，改为向 stderr 输出一行
# 结构化 JSON：{"ok": false, "error": "...", "type": "...", "exitCode": N}。
# 退出码约定：click UsageError=2、ClickException=1、其它未处理异常=1。

def _json_errors_enabled() -> bool:
    import os
    return str(os.environ.get("ASSIST_JSON_ERRORS") or "").strip().lower() in ("1", "true", "yes")


def _emit_json_error(exc: BaseException, exit_code: int) -> None:
    import sys
    payload = {"ok": False, "error": str(exc) or exc.__class__.__name__,
               "type": exc.__class__.__name__, "exitCode": exit_code}
    sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main():
    """CLI entry：包一层异常处理，支持 ASSIST_JSON_ERRORS 机读错误（便于 AI agent 调）。"""
    json_mode = _json_errors_enabled()
    try:
        cli.main(args=None, standalone_mode=False, obj={})
    except click.ClickException as exc:
        if json_mode:
            _emit_json_error(exc, exc.exit_code)
            raise SystemExit(exc.exit_code)
        exc.show()
        raise SystemExit(exc.exit_code)
    except click.Abort:
        if json_mode:
            _emit_json_error(RuntimeError("aborted"), 130)
            raise SystemExit(130)
        raise
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 —— 顶层兜底：任何未处理异常
        if json_mode:
            _emit_json_error(exc, 1)
            raise SystemExit(1)
        raise


if __name__ == "__main__":
    main()
