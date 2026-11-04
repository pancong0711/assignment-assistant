"""assist CLI — 统一命令组（合并两个旧项目 cli.py 的 cmd 结构，05-D1：CLI 超集）。

当前（阶段1）：bootstrap / doctor / kb / sheet。serve 与 grade 为后面阶段占位。
"""

import json
import os
import shutil
import time
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
    # D119-L3：把当前 workspace 绑定给 xxt_home()，避免它隐式用 find_workspace(None)
    # 解析到别的 workspace（跨工作区串数据）。
    try:
        from .xxt.session import bind_workspace
        bind_workspace(ws_path)
    except Exception:  # noqa: BLE001 —— 绑定失败不影响主流程
        pass
    # D134：把 D132 期的 <ws>/assistopia/ 与 <ws>/extensions/ 幂等迁到 <ws>/atopia/
    # （进程内只做一次；只读环境/失败都不阻断主流程）
    try:
        from .atopia import paths as _ap
        _ap.ensure_migrated(ws_path)
    except Exception:  # noqa: BLE001
        pass
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


@kb.command("normalize")
@click.option("--write", "do_write", is_flag=True,
              help="把补齐后的题号写回 xlsx（默认只报告）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_normalize(obj, do_write, workspace, verbose):
    """D111：题库题号全局唯一化（自动加章节前缀 `<chap>-<id>`）。

    默认只报告（dry-run）：列出将要改名的题号与冲突；加 --write 才落盘
    （写前自动 kb/.history 快照，保留单元格样式）。
    """
    from .files import read_kb, snapshot as snap
    from .files import write_chapters_preserving
    from .files.kb_io import find_duplicate_ids, normalize_question_ids
    ws = _setup(verbose or obj.get("verbose"), workspace)
    kb_dir = _kb_dir(ws)
    workbook = read_kb(kb_dir)          # 读入已自动补前缀（内存态）
    report = {"ok": True, "write": do_write, "kinds": {}}
    total_changed = 0
    for kind, chapters in workbook.items():
        dups = find_duplicate_ids(chapters)
        changed = sum(1 for c in chapters.values() for e in c
                      if str(e.get("id") or "") != str(e.get("id") or "").strip())
        sample = [str(e.get("id")) for c in list(chapters.values())[:1] for e in c[:5]]
        report["kinds"][kind] = {"chapters": len(chapters),
                                 "duplicates": dups, "sample_ids": sample}
        total_changed += len(dups)
        if dups:
            continue
        if do_write:
            snap(kb_dir, [kind])
            write_chapters_preserving(kb_dir / f"{kind}.xlsx", chapters)
    report["conflicts"] = total_changed
    click.echo(json.dumps(report, ensure_ascii=False, indent=1))
    if total_changed:
        raise click.ClickException(
            f"{total_changed} 个题号在加章节前缀后仍然重复，请人工处理后再运行")


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
@click.option("--pin/--no-pin", default=True,
              help="作答后置顶为新生效答案（默认置顶；--no-pin 只追加版本、不抢原答案）")
@click.option("--apply", is_flag=True, help="真正写回 kb/solutions/（缺省 dry-run 只预览）")
@click.option("--concurrency", default=3, type=int, show_default=True, help="并发题数")
@click.option("--requirement", "requirement", default="",
              help="教师额外作答要求（可选，如「请画出示意图」「输出为 HTML 文档」）；"
                   "会作为「优先满足」附加到每题 prompt")
@click.option("--requirement-template", "requirement_template", default="",
              help="D108：套用提示词模板（id）；优先于 --requirement，见 assist prompt list")
@click.option("--all", "all_questions", is_flag=True,
              help="D110：显式确认「整库作答」。未给 --chap 且未给 --ids 时必须加此开关，"
                   "避免空选择被误解成整库而误刷全库答案")
@click.option("--with-rubric/--no-with-rubric", "with_rubric", default=False,
              help="D133：同时生成「评阅要点 + 知识点」（带该题型规则摘要），"
                   "写入同一版本。**默认不置顶**，教师确认后才生效")
@click.option("--pin-rubric", is_flag=True,
              help="配合 --with-rubric：生成后**直接置顶**（默认不置顶，需教师确认）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_ai_solve(obj, kb_kind, chap, ids, model, pin, apply, concurrency, requirement,
                requirement_template, all_questions, with_rubric, pin_rubric,
                workspace, verbose):
    """D89-N5/D100：对题库题目做 AI 作答（**不覆盖**原答案，新增版本并默认置顶；默认 dry-run）。"""
    from .grading import solve as solve_mod
    ws = _setup(verbose or obj.get("verbose"), workspace)
    id_list = [x.strip() for x in str(ids).split(",") if x.strip()]
    # D110：防"误刷全库"——完全没有限定范围时必须显式 --all。
    # 此前 --ids 为空且 --chap 为空 = 整个题库，一次误点即可覆盖整库答案。
    if not id_list and not str(chap or "").strip() and not all_questions:
        raise click.ClickException(
            "未指定范围：请用 --chap 指定章节、或 --ids 指定题号；"
            "确实要对**整个题库**作答请显式加 --all")
    targets = solve_mod.list_targets(ws, kb_kind, chap, id_list)
    if not targets:
        raise click.ClickException("未选中任何题目（检查 --kb-kind/--chap/--ids）")
    # D108：模板优先；无模板则用单次输入
    from .files.prompts import requirement_text
    req_text = requirement_text(ws, requirement_template, requirement)
    # D133：带要点时**默认不置顶**（未确认的要点不该抢生效答案，D130 验收 5）；
    # 教师要"生成即生效"需显式 --pin-rubric。
    eff_pin = bool(pin)
    if with_rubric and not pin_rubric:
        eff_pin = False
    if kb_kind in ("copy", "summary") and with_rubric:
        from .grading.rules import rubric_enabled
        # D134-T5a：summary 只有在**本章已有教师确认资料**时才生成要点，
        # 与 `rules generate` 同口径（避免同一条口径在两个入口不一致）。
        ok = (rubric_enabled(ws, kb_kind, chap=str(chap or ""))
              if kb_kind == "summary" else rubric_enabled(ws, kb_kind))
        if not ok:
            why = ("本章还没有教师确认的课堂资料知识点清单" if kb_kind == "summary"
                   else "以原文为唯一依据")
            click.echo(f"提示：{kb_kind} 本次不生成 AI 评阅要点（{why}），"
                       f"只生成参考解答；批阅时 summary 会走保底口径。", err=True)
            with_rubric = False
    res = solve_mod.solve_targets(ws, targets, model=model, apply=apply, pin=eff_pin,
                                  dry_run=True, concurrency=concurrency,
                                  requirement=req_text, with_rubric=with_rubric)
    if res.get("dryRun"):
        click.echo(json.dumps({"dryRun": True, "planned": res["planned"],
                               "withRubric": bool(with_rubric),
                               "pin": eff_pin,
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
@click.option("--kb", default="", help="D110：题库 kind（与 --chap 一起精确识别跨章同号题）")
@click.option("--chap", default="", help="D110：章节名（sheet 名）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_solution_list(obj, qid, kb, chap, workspace, verbose):
    """列出题目答案版本库（JSON）。"""
    from .files import solutions as sol
    ws = _setup(verbose or obj.get("verbose"), workspace)
    data = sol.read_solutions(ws, qid, kb=kb, chap=chap) if qid else {"items": sol.list_solutions(ws)}
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
@click.option("--kb", default="", help="D110：题库 kind（配合 --chap 精确定位跨章同号题）")
@click.option("--chap", default="", help="D110：章节名")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_solution_pin(obj, qid, version_id, kb, chap, workspace, verbose):
    """把某版本置顶（设为生效答案，其余取消置顶）。"""
    from .files import solutions as sol
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = sol.pin_version(ws, qid, version_id, kb=kb, chap=chap)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "置顶失败")


@kb_solution.command("rm")
@click.option("--qid", required=True)
@click.option("--version", "version_id", required=True)
@click.option("--kb", default="", help="D110：题库 kind（配合 --chap 精确定位跨章同号题）")
@click.option("--chap", default="", help="D110：章节名")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_solution_rm(obj, qid, version_id, kb, chap, workspace, verbose):
    """删除某版本。"""
    from .files import solutions as sol
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = sol.remove_version(ws, qid, version_id, kb=kb, chap=chap)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "删除失败")


@cli.group("prompt", help="D151：提示词模板库（作答要求 + 5 类 system prompt；可存/可改/可删）")
def prompt_grp():
    pass


@prompt_grp.command("list")
@click.option("--category", default="ai-solve", show_default=True,
              type=click.Choice(["ai-solve", "transcribe", "evaluate", "solve",
                                "rubric", "termnorm"]),
              help="D151：模板类别（system prompt 或作答要求）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def prompt_list(obj, category, workspace, verbose):
    """列出某类提示词模板（JSON）。"""
    from .files import prompts as P
    ws = _setup(verbose or obj.get("verbose"), workspace)
    click.echo(json.dumps({"ok": True, "category": category,
                           "items": P.list_templates(ws, category),
                           "default": (P.default_template(ws, category) or {}).get("id", "")},
                          ensure_ascii=False, indent=1))


@prompt_grp.command("save")
@click.option("--id", "pid", required=True, help="模板 id（字母数字开头，可含 _ . -）")
@click.option("--name", default="", help="显示名称")
@click.option("--text", default=None, help="模板内容（或 --file）")
@click.option("--file", "file_", default=None, help="从文件读模板内容")
@click.option("--default", "make_default", is_flag=True, help="同时设为默认模板")
@click.option("--category", default="ai-solve", show_default=True,
              type=click.Choice(["ai-solve", "transcribe", "evaluate", "solve",
                                "rubric", "termnorm"]),
              help="D151：模板类别（system prompt 或作答要求）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def prompt_save(obj, pid, name, text, file_, make_default, category, workspace, verbose):
    """新建/更新提示词模板。"""
    from .files import prompts as P
    ws = _setup(verbose or obj.get("verbose"), workspace)
    body = text if text is not None else (
        Path(file_).expanduser().read_text(encoding="utf-8") if file_ else "")
    res = P.save_template(ws, pid=pid, name=name, text=body,
                          make_default=make_default, category=category)
    click.echo(json.dumps(res, ensure_ascii=False, indent=1))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "保存失败")


@prompt_grp.command("delete")
@click.option("--id", "pid", required=True)
@click.option("--category", default="ai-solve", show_default=True,
              type=click.Choice(["ai-solve", "transcribe", "evaluate", "solve",
                                "rubric", "termnorm"]),
              help="D151：模板类别（system prompt 或作答要求）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def prompt_delete(obj, pid, category, workspace, verbose):
    """删除提示词模板（内置模板不可删）。"""
    from .files import prompts as P
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = P.delete_template(ws, pid, category)
    click.echo(json.dumps(res, ensure_ascii=False, indent=1))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "删除失败")


@prompt_grp.command("use")
@click.option("--id", "pid", required=True)
@click.option("--category", default="ai-solve", show_default=True,
              type=click.Choice(["ai-solve", "transcribe", "evaluate", "solve",
                                "rubric", "termnorm"]),
              help="D151：模板类别（system prompt 或作答要求）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def prompt_use(obj, pid, category, workspace, verbose):
    """把某模板设为默认。"""
    from .files import prompts as P
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = P.set_default(ws, pid, category)
    click.echo(json.dumps(res, ensure_ascii=False, indent=1))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "设置默认失败")


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


@sheet.command("answers")
@click.option("--task", "task_path", required=True, help="任务包（作业纸）JSON 路径")
@click.option("--out", "-o", default=None, help="输出 html 路径（缺省 <workspace>/answers-<taskpad id>.html）")
@click.option("--title", default="", help="文档标题（缺省取任务包 id）")
@click.option("--no-content", is_flag=True, help="不显示题干（只出题号 + 答案，更紧凑）")
@click.option("--no-no", is_flag=True, help="不显示题号")
@click.option("--no-page-break", is_flag=True,
              help="连排（默认每题另起一页：一题排完 → 新题另起一页）")
@click.option("--katex", "katex_mode", default="local", type=click.Choice(["cdn", "local"], case_sensitive=False),
              help="公式资源引用：local（缺省，../katex/ 相对引用）或 cdn")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def sheet_answers(obj, task_path, out, title, no_content, no_no, no_page_break,
                  katex_mode, workspace, verbose):
    """D113：生成「参考答案」独立文档（竖版单列 · 一题一页起步）。

    与 PWA「参考答案预览」同构（同一套 CSS/结构/公式语义）：
    - 只有竖版单列；一题答案排完 → 新题另起一页（`--no-page-break` 可改为连排）；
    - 单题超过一整页时自然跨页，但不与其它题答案交错；
    - 题级切分：只在题与题之间分页，绝不切公式/图；
    - 行内公式保持行内，行间公式独立成行并突出显示。

    示例：assist sheet answers --task my.taskpad.json -o answers.html
    """
    from .paper.htmlfile import render_answer_html
    from .paper.task import load_task
    ws = _setup(verbose or obj.get("verbose"), Path(workspace) if workspace else None)
    task_file = Path(task_path).expanduser().resolve()
    if not task_file.is_file():
        raise click.ClickException(f"任务包不存在：{task_file}")
    task = load_task(task_file)
    # 先定输出路径，再据此计算 KaTeX 相对引用
    out_path = (Path(out).expanduser().resolve() if out
                else ws / "sheets" / "html" / f"answers-{str(task.get('id') or 'task')}.html")
    html = render_answer_html(
        task, ws,
        include_content=not no_content,
        include_no=not no_no,
        one_page_per_question=not no_page_break,
        title=title,
        katex_mode=str(katex_mode).lower(),
        out_path=out_path,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    n = html.count('class="answer-card"')
    click.echo(f"参考答案 → {out_path}（{n} 题；"
               + ("一题一页" if not no_page_break else "连排") + "）")


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
@click.option("--no-measure", is_flag=True,
              help="D107：不自动测量排版（缺 layout_result 时回退旧网格；测量需 Playwright）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def sheet_html(obj, task_path, roster_path, out, no_watermark, no_solution, students_mode,
               katex_mode, assets_dir, no_measure, workspace, verbose):
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
        assets_dir=Path(assets_dir).expanduser().resolve() if assets_dir else None,
        no_measure=no_measure)
    click.echo(str(fn))
    click.echo(f"学生 {n_stu} 人 · 页块 {n_pages} 个（浏览器打开后 Ctrl/Cmd+P 打印；"
               "KaTeX 走 CDN，离线时公式按源码降级显示）"
               + ("" if not no_solution else "；本文件不含参考答案（--no-solution）")
               + ("" if students_mode.lower() == "roster" else f"；名单口径 --students {students_mode.lower()}"))


@sheet.command("layout")
@click.option("--task", "task_path", required=True, help="任务包 JSON 路径")
@click.option("--out", "-o", default=None, help="输出 taskpad JSON 路径（缺省原地更新）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def sheet_layout(obj, task_path, out, workspace, verbose):
    """D107：测量参考答案排版并写入 `layout_result`（PWA/CLI 同一算法）。

    使 AI/CLI 全流程可用：kb ai-solve → sheet layout → sheet html / make --teacher。
    需要 Playwright + Chromium（`playwright install chromium`，或设 ASSIST_CHROMIUM_PATH）。
    """
    import json as _json
    from .paper.layout_measure import LayoutMeasureError, measure_layout
    ws = _setup(verbose or obj.get("verbose"), workspace)
    task_file = Path(task_path).expanduser().resolve()
    task = _json.loads(task_file.read_text(encoding="utf-8"))
    lay = task.get("layout") or {}
    orientation = "landscape" if lay.get("orientation") == "landscape" else "portrait"
    # 取题干与生效答案（按题库 id）
    from .files.kb_io import read_kb
    from .files.solutions import effective_solution
    from .paper.task import resolve_items_with_ids
    kb_dir = ws / "kb"
    kb_data = read_kb(kb_dir)
    base = resolve_items_with_ids(kb_data, task.get("items", []), kb_dir,
                                  str(lay.get("numbering") or "auto"),
                                  seed=task.get("random_seed"),
                                  target_tag=str(task.get("target_tag") or ""))
    items = []
    for content, _img, _tag, no, qid in base:
        eff = effective_solution(ws, str(qid), "") if qid else {"text": ""}
        items.append({"qid": str(qid), "no": str(no), "content": str(content),
                      "solution": str(eff.get("text") or "")})
    try:
        result = measure_layout(items, orientation=orientation)
    except LayoutMeasureError as exc:
        raise click.ClickException(str(exc))
    task["layout_result"] = result
    out_path = Path(out).expanduser().resolve() if out else task_file
    out_path.write_text(_json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")
    click.echo(_json.dumps({"ok": True, "pages": len(result.get("pages") or []),
                            "warnings": result.get("warnings") or [],
                            "out": str(out_path)}, ensure_ascii=False, indent=1))


@sheet.command("make")
@click.option("--task", "task_path", required=True, help="任务包 JSON 路径")
@click.option("--roster", "roster_path", default=None, help="点名册 xlsx（缺省找 classes/<class>/roster/）")
@click.option("--out", "-o", default=None, help="输出目录（缺省 classes/<class>/sheets/out）")
@click.option("--no-watermark", is_flag=True)
@click.option("--teacher", "teacher_mode", is_flag=True,
              help="教师版：每题独占一页并附完整参考答案，答案超长自动续页、后续题目顺延（D103）")
@click.option("--assets-dir", "assets_dir", default=None,
              help="显式素材目录（水印图/字体）；缺省 workspace 优先，回落 engine/assets（D87）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def sheet_make(obj, task_path, roster_path, out, no_watermark, teacher_mode, assets_dir, workspace, verbose):
    """按任务包生成每生一份作业纸 PDF（xlsx 名单驱动）；--teacher = 教师版（一题一页+答案）。"""
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
        teacher_mode=teacher_mode,
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


@cli.group("atopia", help="D134：AI 调用本项目工具的安全工作区（工具白名单 + 分级 + 审计）")
def atopia_grp():
    pass


# D134：旧名兼容别名（`assist assistopia ...` 仍可用；子命令由同一组注册，
# 因此在 main 里把旧组挂到新组上即可——见 cli_main 的 alias 处理）。
@cli.group("assistopia", hidden=True,
           help="[已更名] 旧名别名，等价于 `assist atopia`（D134）")
def assistopia_grp():
    pass


@atopia_grp.command("tools")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def atopia_tools(obj, workspace, verbose):
    """列出工具白名单与风险级别（含 extensions/ 覆盖后的生效级别）。"""
    from .atopia import registry as R
    from .atopia import limits as LM
    ws = _setup(verbose or obj.get("verbose"), workspace)
    tools = R.effective_tools(ws)
    click.echo(json.dumps({
        "ok": True,
        "levels": R.LEVEL_LABEL,
        "limits": LM.read_limits(ws),
        "hardCaps": LM.HARD_CAPS,
        "extensions": str(R.extensions_dir(ws)),
        "tools": [t.to_dict() for t in tools],
    }, ensure_ascii=False, indent=2))


@atopia_grp.command("run")
@click.option("--tool", "tool_name", required=True, help="工具 id（见 atopia tools）")
@click.option("--args", "args_json", default="{}", help="参数 JSON，如 '{\"kind\": \"qa\"}'")
@click.option("--confirm", "confirmed_by", default="",
              help="L2 写入工具的教师确认来源（如 teacher:cli）；不填则拒绝")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def atopia_run(obj, tool_name, args_json, confirmed_by, workspace, verbose):
    """执行一个 L0/L1（或已确认的 L2）工具；L3 一律拒绝。"""
    from .atopia import limits as LM
    from .atopia import runner as RN
    from .atopia.registry import ToolDenied
    ws = _setup(verbose or obj.get("verbose"), workspace)
    try:
        args = json.loads(args_json or "{}")
        if not isinstance(args, dict):
            raise click.ClickException("--args 必须是 JSON 对象")
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"--args 不是合法 JSON：{exc}")
    sess = LM.Session(session_id=f"cli-{id(obj)}", limits=LM.read_limits(ws))
    try:
        rep = RN.run_tool(ws, tool_name, args, session=sess,
                          confirmed_by=confirmed_by)
    except ToolDenied as exc:
        raise click.ClickException(str(exc))
    except LM.LimitExceeded as exc:
        raise click.ClickException(str(exc))
    click.echo(json.dumps({**rep, "stdout": rep["stdout"], "stderr": rep["stderr"]},
                          ensure_ascii=False, indent=2))
    if not rep["ok"]:
        raise click.ClickException(f"工具执行失败（{rep['status']}）：{
            (rep['stderr'] or rep['stdout'])[:300]}")


@atopia_grp.command("ask")
@click.argument("task")
@click.option("--model", default="", help="覆盖模型")
@click.option("--yes", "auto_yes", is_flag=True,
              help="对 L2 写入工具自动确认（**仅供教师本人在终端使用**；仍不做 L3）")
@click.option("--max-turns", default=6, type=int, show_default=True)
@click.option("--protocol", type=click.Choice(["native", "json"]), default="native",
              show_default=True,
              help="native=原生 tools 协议（不支持时自动降级）；json=强制 JSON 指令协议")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def atopia_ask(obj, task, model, auto_yes, max_turns, protocol, workspace, verbose):
    """让 AI 在本项目工具上完成一个任务（受分级/护栏/审计约束）。"""
    from .atopia import agent as AG
    from .atopia import limits as LM
    from .grading.llm import LLMClient
    ws = _setup(verbose or obj.get("verbose"), workspace)
    client = _rubric_client(ws)
    sess = LM.Session(session_id=f"ask-{id(obj)}", limits=LM.read_limits(ws))

    def _confirm(tool_name: str, args: dict) -> str:
        # L2 二次确认：终端里逐次问（--yes 才自动同意，仍然逐次记账）
        if auto_yes:
            click.echo(f"[确认] 自动同意 {tool_name} {json.dumps(args, ensure_ascii=False)}",
                       err=True)
            return "teacher:cli:--yes"
        ok = click.confirm(
            f"\nAI 请求执行写操作：{tool_name}\n  参数：{json.dumps(args, ensure_ascii=False)}"
            f"\n确认执行？（会修改工作区数据）", default=False)
        return "teacher:cli:confirm" if ok else ""

    # D135：默认走原生 tools 协议，provider 不支持时自动降级到 JSON 指令协议；
    # 两条路径共用同一个 Gate（run_tool），安全口径完全一致。
    rep = AG.run_session_auto(client, ws, task, model=model or None, session=sess,
                              confirm=_confirm, max_turns=max_turns,
                              prefer=protocol)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=2))
    if not rep.get("ok"):
        raise click.ClickException(rep.get("error") or "会话失败")


@atopia_grp.command("limits")
@click.option("--set", "set_pairs", multiple=True,
              help="设置护栏，如 --set maxCallsPerSession=60（受硬顶约束）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def atopia_limits(obj, set_pairs, workspace, verbose):
    """查看/调整护栏（调用次数、L1 成本、超时、会话时长）。"""
    from .atopia import limits as LM
    ws = _setup(verbose or obj.get("verbose"), workspace)
    if set_pairs:
        patch = {}
        for pair in set_pairs:
            if "=" not in pair:
                raise click.ClickException(f"--set 需要 k=v 形式：{pair}")
            k, v = pair.split("=", 1)
            patch[k.strip()] = v.strip()
        rep = LM.write_limits(ws, patch)
        click.echo(json.dumps(rep, ensure_ascii=False, indent=2))
        if not rep.get("ok"):
            raise click.ClickException(rep.get("error") or "设置失败")
        return
    click.echo(json.dumps({"ok": True, "limits": LM.read_limits(ws),
                           "defaults": LM.DEFAULTS, "hardCaps": LM.HARD_CAPS,
                           "hint": "用 --set key=value 调整；超过硬顶会被拒绝"},
                          ensure_ascii=False, indent=2))


@atopia_grp.command("extensions")
@click.option("--init", is_flag=True, help="创建 extensions/ 骨架（不覆盖已有内容）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def atopia_extensions(obj, init, workspace, verbose):
    """查看/初始化用户扩展目录（升级**永不触碰**）。"""
    from .atopia import extensions as E
    ws = _setup(verbose or obj.get("verbose"), workspace)
    if init:
        E.ensure(ws)
    click.echo(json.dumps({
        "ok": True, "root": str(E.root(ws)),
        "files": sorted(E.snapshot(ws)),
        "toolOverrides": __import__("assist.atopia.registry", fromlist=["x"])
                          .load_overrides(ws),
        "hint": "tools/*.json 只能把级别**调高**；rules/ 与 knowledge-terms.json 可覆盖默认",
    }, ensure_ascii=False, indent=2))


@atopia_grp.command("reset")
@click.option("--keep-extensions/--drop-extensions", "keep_extensions", default=True,
              show_default=True,
              help="默认保留 extensions/（教师资产）；--drop-extensions 才一起清掉")
@click.option("--yes", is_flag=True, help="确认执行（缺省只演练）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def atopia_reset(obj, keep_extensions, yes, workspace, verbose):
    """D134：清空 `<ws>/atopia/` 运行状态（护栏回默认 / 清审计）。

    **属 L3：不注册为 AI 工具**（删除类操作一律不给 AI，docs/81 §2）。
    """
    from .atopia import paths as P
    ws = _setup(verbose or obj.get("verbose"), workspace)
    if not yes:
        click.echo(json.dumps({
            "ok": True, "dryRun": True, "root": str(P.atopia_root(ws)),
            "keepExtensions": keep_extensions,
            "hint": "确认后加 --yes 执行；默认保留 extensions/",
        }, ensure_ascii=False, indent=2))
        return
    rep = P.reset(ws, keep_extensions=keep_extensions)
    rep.update({"root": str(P.atopia_root(ws)), "keepExtensions": keep_extensions})
    click.echo(json.dumps(rep, ensure_ascii=False, indent=2))


@atopia_grp.command("migrate")
@click.option("--force", is_flag=True, help="忽略会话内已迁移缓存，重新执行")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def atopia_migrate(obj, force, workspace, verbose):
    """D134：把旧位置（`<ws>/assistopia/`、`<ws>/extensions/`）迁到 `<ws>/atopia/`。"""
    from .atopia import paths as P
    ws = _setup(verbose or obj.get("verbose"), workspace)
    if force:
        P._migrated.discard(str(Path(ws).resolve()))
    rep = P.ensure_migrated(ws)
    rep["root"] = str(P.atopia_root(ws))
    click.echo(json.dumps(rep, ensure_ascii=False, indent=2))


@atopia_grp.command("journal")
@click.option("--limit", default=30, type=int, show_default=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def atopia_journal(obj, limit, workspace, verbose):
    """查看审计日志（最近 N 条）。"""
    from .atopia import runner as RN
    ws = _setup(verbose or obj.get("verbose"), workspace)
    recs = RN.read_journal(ws, limit=limit)
    click.echo(json.dumps({"ok": True, "count": len(recs), "records": recs},
                          ensure_ascii=False, indent=2))


@cli.group("fs", help="D148：Atopia 的**只读**文件查看（ls/read/search，限 workspace 内）")
def fs_grp():
    pass


@fs_grp.command("ls")
@click.option("--path", "path", default=".", help="workspace 内相对路径（缺省根目录）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def fs_ls(obj, path, workspace, verbose):
    """列目录（只读）。"""
    from .atopia import fsview as F
    ws = _setup(verbose or obj.get("verbose"), workspace)
    try:
        click.echo(json.dumps(F.ls(ws, path), ensure_ascii=False, indent=1))
    except F.FSViewError as exc:
        raise click.ClickException(str(exc))


@fs_grp.command("read")
@click.option("--path", "path", required=True, help="workspace 内文件路径")
@click.option("--lines", default=200, type=int, show_default=True, help="最多读多少行")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def fs_read(obj, path, lines, workspace, verbose):
    """读文本文件（只读；二进制拒读）。"""
    from .atopia import fsview as F
    ws = _setup(verbose or obj.get("verbose"), workspace)
    try:
        click.echo(json.dumps(F.read(ws, path, lines=lines), ensure_ascii=False, indent=1))
    except F.FSViewError as exc:
        raise click.ClickException(str(exc))


@fs_grp.command("search")
@click.argument("query")
@click.option("--glob", "glob", default="", help="文件名过滤（如 *.json）")
@click.option("--max-hits", default=50, type=int, show_default=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def fs_search(obj, query, glob, max_hits, workspace, verbose):
    """按关键词搜索 workspace 内文件内容（只读）。"""
    from .atopia import fsview as F
    ws = _setup(verbose or obj.get("verbose"), workspace)
    try:
        click.echo(json.dumps(F.search(ws, query, glob=glob, max_hits=max_hits),
                              ensure_ascii=False, indent=1))
    except F.FSViewError as exc:
        raise click.ClickException(str(exc))


@cli.group("materials", help="D131：课堂资料库 <ws>/materials/<chap>/（PPT/PDF/讲义 → 知识点清单）")
def materials_grp():
    pass


@materials_grp.command("list")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def materials_list(obj, workspace, verbose):
    """列出已有章节资料 + 与题库章节的对账（题库有但资料缺 / 资料有但题库缺）。"""
    from .files import materials as M
    from .files.kb_io import read_kb
    ws = _setup(verbose or obj.get("verbose"), workspace)
    chaps = M.list_chaps(ws)
    kb = read_kb(ws / "kb")
    kb_chaps: set[str] = set()
    for _kind, chapters in (kb or {}).items():
        if isinstance(chapters, dict):
            kb_chaps.update(str(c) for c in chapters)
    out = []
    for c in chaps:
        d = M.chap_dir(ws, c)
        idx = M.read_index(ws, c)
        out.append({
            "chap": c, "dir": str(d),
            "sources": len(M.list_sources(ws, c)),
            "extracted": len(idx.get("sources") or []),
            "chars": (idx.get("summary") or {}).get("chars", 0),
            "has_ai_suggest": (d / M.KNOW_AI).is_file(),
            "has_confirmed": (d / M.KNOW_MD).is_file(),
        })
    click.echo(json.dumps({
        "ok": True, "root": str(M.materials_root(ws)),
        "chaps": out,
        "kb_chaps_without_materials": sorted(kb_chaps - set(chaps)),
        "materials_chaps_without_kb": sorted(set(chaps) - kb_chaps),
        "hint": f"把资料放进 {M.materials_root(ws)}/<章节>/_source/ 后运行 "
                f"`assist materials extract --chap <章节>`",
    }, ensure_ascii=False, indent=2))


@materials_grp.command("extract")
@click.option("--chap", required=True, help="章节名（与题库 sheet 同名，如 chap04）")
@click.option("--force", is_flag=True, help="忽略 sha256 缓存，强制重新抽取")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def materials_extract(obj, chap, force, workspace, verbose):
    """抽取 `_source/` 里的 PPT/PDF/图片/文本 → `索引.json` + `_extract/`（增量）。"""
    from .files import materials as M
    ws = _setup(verbose or obj.get("verbose"), workspace)
    try:
        rep = M.extract_chap(ws, chap, force=force)
    except M.MaterialsError as exc:
        raise click.ClickException(str(exc))
    click.echo(json.dumps(rep, ensure_ascii=False, indent=2))
    if not rep.get("ok"):
        raise click.ClickException("部分资料抽取失败（见 errors）")


@materials_grp.command("files")
@click.option("--chap", required=True)
@click.option("--trash", is_flag=True, help="同时列出回收站 `_source/_trash/`")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def materials_files(obj, chap, trash, workspace, verbose):
    """D134-T3b：列出某章 `_source/` 的原件（文件名/大小/时间/sha）。"""
    from .files import materials as M
    ws = _setup(verbose or obj.get("verbose"), workspace)
    try:
        rows = M.files_of(ws, chap, include_trash=trash)
    except M.MaterialsError as exc:
        raise click.ClickException(str(exc))
    click.echo(json.dumps({"ok": True, "chap": chap,
                           "source": str(M.chap_dir(ws, chap) / M.SOURCE),
                           "count": len(rows), "files": rows},
                          ensure_ascii=False, indent=2))


@materials_grp.command("remove")
@click.option("--chap", required=True)
@click.option("--file", "file_name", required=True,
              help="相对 `_source/` 的文件名（如 lecture01.pptx）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def materials_remove(obj, chap, file_name, workspace, verbose):
    """D134-T3c：把文件移入 `_source/_trash/`（**不真删**，可人工找回）。"""
    from .files import materials as M
    ws = _setup(verbose or obj.get("verbose"), workspace)
    try:
        rep = M.remove_source(ws, chap, file_name)
    except M.MaterialsError as exc:
        raise click.ClickException(str(exc))
    click.echo(json.dumps(rep, ensure_ascii=False, indent=2))


@materials_grp.command("restore")
@click.option("--chap", required=True)
@click.option("--file", "file_name", required=True,
              help="回收站中的文件名（如 a.pdf 或 _trash/a.pdf）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def materials_restore(obj, chap, file_name, workspace, verbose):
    """D135：把文件从 `_source/_trash/` **移回** `_source/`（同名自动 -2）。"""
    from .files import materials as M
    ws = _setup(verbose or obj.get("verbose"), workspace)
    try:
        rep = M.restore_source(ws, chap, file_name)
    except M.MaterialsError as exc:
        raise click.ClickException(str(exc))
    click.echo(json.dumps(rep, ensure_ascii=False, indent=2))


@materials_grp.command("show")
@click.option("--chap", required=True)
@click.option("--text", "show_text", is_flag=True, help="打印抽取到的文本（前 4000 字）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def materials_show(obj, chap, show_text, workspace, verbose):
    """查看某章节的索引与（可选）抽取文本。"""
    from .files import materials as M
    ws = _setup(verbose or obj.get("verbose"), workspace)
    idx = M.read_index(ws, chap)
    out = {"ok": True, "chap": chap, "index": idx}
    if show_text:
        src = M.read_source_text(ws, chap, max_chars=4000)
        out["text_preview"] = src["text"]
        out["text_chars_total"] = len(src["text"])
    click.echo(json.dumps(out, ensure_ascii=False, indent=2))


@materials_grp.command("suggest")
@click.option("--chap", required=True)
@click.option("--model", default="", help="覆盖模型")
@click.option("--max-chars", default=60000, type=int, show_default=True,
              help="送入模型的文本上限（超出截断并标记）")
@click.option("--max-images", default=20, type=int, show_default=True,
              help="图片/扫描件走多模态时最多送几张页图")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def materials_suggest(obj, chap, model, max_chars, max_images, workspace, verbose):
    """AI 抽取「本章知识点 + 逻辑关系」→ `知识点清单.ai.json`（**不**自动生效）。"""
    from .files import materials as M
    ws = _setup(verbose or obj.get("verbose"), workspace)
    client = _rubric_client(ws)
    try:
        rep = M.suggest_knowledge(client, ws, chap, model=model or None,
                                  max_chars=max_chars, max_images=max_images)
    except M.MaterialsError as exc:
        raise click.ClickException(str(exc))
    click.echo(json.dumps(rep, ensure_ascii=False, indent=2))
    click.echo(f"\n提示：核对后用 `assist materials confirm --chap {chap}` 生成本章知识点清单。",
               err=True)


@materials_grp.command("confirm")
@click.option("--chap", required=True)
@click.option("--force", is_flag=True, help="覆盖已有 `知识点清单.md`（教师已确认版）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def materials_confirm(obj, chap, force, workspace, verbose):
    """把 AI 建议固化为生效的 `知识点清单.md`（AI **不**覆盖已确认清单，除非 --force）。"""
    from .files import materials as M
    ws = _setup(verbose or obj.get("verbose"), workspace)
    try:
        rep = M.confirm_knowledge(ws, chap, force=force)
    except M.MaterialsError as exc:
        raise click.ClickException(str(exc))
    click.echo(json.dumps(rep, ensure_ascii=False, indent=2))
    if not rep.get("ok"):
        raise click.ClickException(rep.get("error") or "确认失败")


@materials_grp.command("knowledge")
@click.option("--chap", required=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def materials_knowledge(obj, chap, workspace, verbose):
    """查看生效的知识点清单（= summary 批阅依据）。"""
    from .files import materials as M
    ws = _setup(verbose or obj.get("verbose"), workspace)
    md = M.read_knowledge_md(ws, chap)
    click.echo(json.dumps({"ok": bool(md), "chap": chap,
                           "terms": M.knowledge_terms(ws, chap),
                           "markdown": md,
                           "hint": "" if md else
                           f"尚无生效清单：先 extract → suggest → confirm（章节 {chap}）"},
                          ensure_ascii=False, indent=2))


@cli.group("rules", help="D130：评阅规则（全局 + 按题目来源分型；改数值后新批阅生效）")
def rules_grp():
    pass


def _rubric_client(ws):
    from .grading.llm import LLMClient
    return LLMClient(ws=ws)


@rules_grp.command("generate")
@click.option("--kind", "kb_kind", default="qa", help="题库 kind（决定评阅范式与规则摘要）")
@click.option("--chap", default="", help="章节 sheet 名；缺省=整库")
@click.option("--ids", default="", help="题号（逗号分隔）；缺省=该章全部")
@click.option("--model", default="", help="覆盖模型")
@click.option("--apply", is_flag=True, help="真正写入答案版本库（缺省 dry-run 只预览）")
@click.option("--force", is_flag=True, help="copy/summary 等默认不生成要点的题型也强制生成")
@click.option("--concurrency", default=2, type=int, show_default=True, help="并发题数")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def rules_generate(obj, kb_kind, chap, ids, model, apply, force, concurrency, workspace, verbose):
    """D130-T5：AI 生成「参考解答 + 评阅要点 + 知识点」，写入答案版本库（**默认不置顶**）。"""
    from concurrent.futures import ThreadPoolExecutor
    from .files.kb_io import read_kb
    from .grading import rubric as RB
    from .grading.rules import normalize_kind, rubric_enabled
    ws = _setup(verbose or obj.get("verbose"), workspace)
    kind = normalize_kind(kb_kind)
    # D134-T5c：summary 的要点**必须基于本章已确认的课堂资料**——
    # 没有资料时让模型"生成本章要点"等于编造依据，应引导教师先去整理资料。
    if kind == "summary" and not rubric_enabled(ws, kind, chap=chap or "") and not force:
        if not chap:
            raise click.ClickException(
                "summary 生成要点必须指定 --chap：要点依据是本章的《知识点清单.md》")
        click.echo(json.dumps({
            "ok": True, "skipped": True,
            "reason": f"本章（{chap}）还没有教师确认的课堂资料知识点清单，"
                      "无法生成本章要点（否则等于让模型编造“本章该讲什么”）。",
            "howTo": [
                f"把授课计划/PPT 放进 <ws>/materials/{chap}/_source/",
                f"assist materials extract --chap {chap}",
                f"assist materials suggest --chap {chap}",
                f"assist materials confirm --chap {chap}   # 教师确认后才生效",
                f"assist rules generate --kind summary --chap {chap} --apply",
            ],
            "fallback": "若无课堂资料，summary 批阅会自动走「保底口径」"
                        "（知识点总结/公式推导/示意图/长度四维，缺项不扣分）",
        }, ensure_ascii=False, indent=2))
        return
    if not rubric_enabled(ws, kind, chap=chap or "") and not force:
        click.echo(json.dumps({"ok": True, "skipped": True,
                               "reason": f"{kind} 按口径不生成 AI 评阅要点"
                                         "（以原文/课堂资料为唯一依据；确需生成加 --force）"},
                              ensure_ascii=False, indent=2))
        return
    kb_data = read_kb(ws / "kb")
    targets = RB.select_questions(kb_data, kinds=[kb_kind],
                                  chaps=[chap] if chap else None,
                                  ids=[x for x in str(ids or "").split(",") if x.strip()])
    if not targets:
        raise click.ClickException("没有匹配的题目（检查 --kind/--chap/--ids）")
    client = _rubric_client(ws)
    model_name = model or getattr(client, "evaluation_model", "") or ""

    def _one(t):
        try:
            r = RB.generate_rubric(client, ws=ws, kind=kind, content=t["content"],
                                   solution=t["solution"], related=t["related"],
                                   model=model or None)
            return {"qid": t["qid"], "chap": t["chap"], "ok": True, "rubric": r,
                    "text": RB.rubric_to_text(r)}
        except Exception as exc:  # noqa: BLE001 —— 单题失败不阻断
            return {"qid": t["qid"], "chap": t["chap"], "ok": False, "error": str(exc)[:300]}

    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as ex:
        results = list(ex.map(_one, targets))

    written = []
    if apply:
        for r in results:
            if not r.get("ok"):
                continue
            res = RB.save_rubric_version(ws, kb=kb_kind, chap=r["chap"],
                                         qid=r["qid"], rubric=r["rubric"],
                                         model=model_name, pin=False)
            written.append({"qid": r["qid"], "chap": r["chap"], "ok": res.get("ok"),
                            "version": (res.get("added") or {}).get("id"),
                            "pinned": (res.get("added") or {}).get("pinned")})
    click.echo(json.dumps({
        "ok": all(r.get("ok") for r in results),
        "kind": kind, "apply": bool(apply), "total": len(results),
        "failed": [r for r in results if not r.get("ok")],
        "written": written,
        "preview": [{"qid": r["qid"], "chap": r["chap"], "text": r.get("text", "")}
                    for r in results if r.get("ok")],
    }, ensure_ascii=False, indent=2))


@kb.command("check-knowledge")
@click.option("--model", default="", help="覆盖模型")
@click.option("--apply", is_flag=True, help="执行归一（必须配合 --mapping 或 --select）")
@click.option("--mapping", "mapping_file", default="", help="等价组 JSON（AI 提议结果；--apply 用）")
@click.option("--select", "select_idx", default="", help="勾选的组号（从 1 起，逗号分隔；缺省=默认勾选）")
@click.option("--dry-run", "dry_run", is_flag=True, help="只展示影响面，不写库")
@click.option("--rollback", is_flag=True, help="按最后一条变更日志回滚")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_check_knowledge(obj, model, apply, mapping_file, select_idx, dry_run, rollback,
                       workspace, verbose):
    """D130-T7：知识点术语归一（AI **只提议**；教师勾选后才执行；可回滚）。"""
    from .files.kb_io import read_kb
    from .grading import termnorm as TN
    ws = _setup(verbose or obj.get("verbose"), workspace)
    if rollback:
        click.echo(json.dumps(TN.rollback(ws, dry_run=dry_run), ensure_ascii=False, indent=2))
        return
    if mapping_file:
        data = json.loads(Path(mapping_file).expanduser().read_text(encoding="utf-8"))
        groups = data.get("groups") if isinstance(data, dict) else data
        groups = groups or []
        if select_idx:
            want = {int(x) for x in str(select_idx).split(",") if x.strip().isdigit()}
            for i, g in enumerate(groups, start=1):
                g["selected"] = i in want
        mapping = TN.build_mapping(groups)
        if not mapping:
            raise click.ClickException("没有勾选任何等价组（用 --select 指定组号）")
        if apply and not dry_run:
            click.echo(json.dumps(TN.apply_mapping(ws, mapping), ensure_ascii=False, indent=2))
        else:
            click.echo(json.dumps(TN.impact(ws, mapping), ensure_ascii=False, indent=2))
        return
    # 无 mapping：让 AI 提议（只读，不改库）
    kb_data = read_kb(ws / "kb")
    terms = TN.collect_terms(kb_data)
    if not terms:
        click.echo(json.dumps({"ok": True, "groups": [],
                               "hint": "题库里还没有任何 related 标注（先跑 kb tag-knowledge）"},
                              ensure_ascii=False, indent=2))
        return
    client = _rubric_client(ws)
    res = TN.propose_groups(client, terms, model=model or None)
    res["ok"] = True
    res["hint"] = ("AI 只提议，默认不全选；语义有风险的组默认不勾。"
                   "确认后用 --mapping 保存的 JSON + --select 勾选组号 + --apply 执行。")
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))


@kb.group("vocab", help="D130-T8：受控知识点词表 <ws>/knowledge-terms.json")
def kb_vocab():
    pass


@kb_vocab.command("harvest")
@click.option("--write", is_flag=True, help="写回词表（缺省 dry-run）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_vocab_harvest(obj, write, workspace, verbose):
    """从题库 related 列自动汇总术语（保留人工维护的别名/来源）。"""
    from .grading import vocab as V
    ws = _setup(verbose or obj.get("verbose"), workspace)
    click.echo(json.dumps(V.harvest(ws, write=write), ensure_ascii=False, indent=2))


@kb_vocab.command("list")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_vocab_list(obj, workspace, verbose):
    """列出受控词表。"""
    from .grading import vocab as V
    ws = _setup(verbose or obj.get("verbose"), workspace)
    click.echo(json.dumps(V.load_vocab(ws), ensure_ascii=False, indent=2))


@kb_vocab.command("set-topic")
@click.option("--term", required=True)
@click.option("--topic", default="", help="章内主题；传空串=清除归类")
@click.option("--chapter", default=None, help="同时设置所属章（可选）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_vocab_set_topic(obj, term, topic, chapter, workspace, verbose):
    """D138：给术语设置**章内主题**（两层分类的最后一段）。"""
    from .grading import vocab as V
    ws = _setup(verbose or obj.get("verbose"), workspace)
    vocab = V.load_vocab(ws)
    if term.strip().lower() not in V.term_index(vocab):
        raise click.ClickException(f"词表里没有该术语：{term}（先 kb vocab add）")
    res = V.add_term(ws, term, source="human", topic=topic, chapter=chapter)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "写入失败")


@kb_vocab.command("add")
@click.option("--term", required=True)
@click.option("--alias", "aliases", multiple=True, help="同义/别名（可多次）")
@click.option("--topic", default=None,
              help="D138：章内主题（如 碰撞问题）；不传=保持原值")
@click.option("--chapter", default=None,
              help="D138：所属章（如 chap04）；不传=保持原值")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_vocab_add(obj, term, aliases, topic, chapter, workspace, verbose):
    """人工新增/更新术语（同义词并入 aliases；可指定 topic/chapter）。"""
    from .grading import vocab as V
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = V.add_term(ws, term, aliases=list(aliases), source="human",
                     topic=topic, chapter=chapter)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "写入失败")


@kb.command("tag-knowledge")
@click.option("--kb", "kb_kind", multiple=True,
              help="题库 kind（可多次；缺省=全部题型）")
@click.option("--chap", "chaps", multiple=True, help="章节 sheet 名（可多次）")
@click.option("--ids", default="", help="具体题号（逗号分隔）")
@click.option("--only-empty/--no-only-empty", default=True, show_default=True,
              help="默认只标**未标注**的题")
@click.option("--force", is_flag=True, help="覆盖已有知识点（默认不覆盖）")
@click.option("--dry-run", "dry_run", is_flag=True, help="只预览，不写题库")
@click.option("--model", default="", help="覆盖模型")
@click.option("--concurrency", default=2, type=int, show_default=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_tag_knowledge(obj, kb_kind, chaps, ids, only_empty, force, dry_run, model,
                     concurrency, workspace, verbose):
    """D130-T6：AI 为题目打**知识点**标签（四种粒度；默认只标未标注）。"""
    from concurrent.futures import ThreadPoolExecutor
    from .files.kb_io import read_kb
    from .grading import rubric as RB
    from .grading.vocab import canonical, join_terms, load_vocab
    from .grading.rules import normalize_kind
    ws = _setup(verbose or obj.get("verbose"), workspace)
    kb_data = read_kb(ws / "kb")
    targets = RB.select_questions(kb_data, kinds=list(kb_kind) or None,
                                  chaps=list(chaps) or None,
                                  ids=[x for x in str(ids or "").split(",") if x.strip()])
    plan = RB.plan_tagging(ws, targets, only_empty=only_empty, force=force)
    todo = plan["todo"]
    if not todo:
        click.echo(json.dumps({"ok": True, "todo": 0, "skipped": len(plan["skipped"]),
                               "skipped_detail": plan["skipped"][:20]},
                              ensure_ascii=False, indent=2))
        return
    client = _rubric_client(ws)
    vocab = load_vocab(ws)

    def _one(t):
        try:
            r = RB.generate_rubric(client, ws=ws, kind=normalize_kind(t["kb"]),
                                   content=t["content"], solution=t["solution"],
                                   related=t["related"], model=model or None)
            terms = [canonical(vocab, x) for x in (r.get("knowledge") or []) if str(x).strip()]
            terms = [x for x in dict.fromkeys(terms) if x]
            return {**t, "ok": True, "terms": terms}
        except Exception as exc:  # noqa: BLE001
            return {**t, "ok": False, "error": str(exc)[:300]}

    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as ex:
        results = list(ex.map(_one, todo))

    updates = []
    for r in results:
        if not r.get("ok") or not r.get("terms"):
            continue
        updates.append({"kb": r["kb"], "chap": r["chap"], "qid": r["qid"],
                        "related": join_terms(r["terms"]),
                        "meta": {"source": "ai", "ai_suggested": join_terms(r["terms"]),
                                 "pinned_by": ""}})
    res = {"ok": all(r.get("ok") for r in results), "dry_run": bool(dry_run),
           "todo": len(todo), "skipped": len(plan["skipped"]),
           "updates": updates,
           "failed": [r for r in results if not r.get("ok")],
           "skipped_detail": plan["skipped"][:20]}
    if not dry_run and updates:
        writer = RB.apply_related(ws, updates)
        res["written"] = writer
        # 词表顺带汇总（新术语入库，来源 ai）
        try:
            from .grading import vocab as V
            V.harvest(ws, write=True)
        except Exception as exc:  # noqa: BLE001
            res["vocab_error"] = str(exc)[:200]
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))


@rules_grp.command("show")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def rules_show(obj, workspace, verbose):
    """显示当前生效规则（JSON，缺失即写默认）。"""
    from .grading import rules as R
    ws = _setup(verbose or obj.get("verbose"), workspace)
    click.echo(json.dumps(R.read_rules(ws), ensure_ascii=False, indent=2))


@rules_grp.command("defaults")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def rules_defaults(obj, workspace, verbose):
    """显示**内置默认**规则（不改文件；供规则卡「恢复默认」对照）。"""
    from .grading import rules as R
    _setup(verbose or obj.get("verbose"), workspace)
    click.echo(json.dumps(R.DEFAULT_RULES, ensure_ascii=False, indent=2))


@rules_grp.command("summary")
@click.option("--kind", default=None, help="题型（problems/qa/copy/…）；缺省全部")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def rules_summary(obj, kind, workspace, verbose):
    """把规则渲染成可读摘要（= 进入评阅 prompt 的那份）。"""
    from .grading import rules as R
    ws = _setup(verbose or obj.get("verbose"), workspace)
    kinds = [R.normalize_kind(kind)] if kind else list(R.SUPPORTED_KINDS)
    for k in kinds:
        click.echo(R.rule_summary(ws, k))
        click.echo("")


@rules_grp.command("set")
@click.option("--path", required=True, help="字段路径，如 global.briefProcessDeduct 或 types.qa.perMissingPointDeduct")
@click.option("--value", required=True, help="新值（自动按 JSON 解析数值/布尔/数组/字符串）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def rules_set(obj, path, value, workspace, verbose):
    """改一个规则数值/扩展项（带范围校验 + journal）。"""
    from .grading import rules as R
    ws = _setup(verbose or obj.get("verbose"), workspace)
    data = R.read_rules(ws)
    try:
        parsed = json.loads(value)
    except Exception:  # noqa: BLE001 —— 非 JSON 就按原字符串
        parsed = value
    cur = data
    segs = [x for x in str(path).split(".") if x]
    for seg in segs[:-1]:
        if not isinstance(cur.get(seg), dict):
            cur[seg] = {}
        cur = cur[seg]
    cur[segs[-1]] = parsed
    res = R.write_rules(ws, data)
    click.echo(json.dumps(res, ensure_ascii=False, indent=2))
    if not res.get("ok"):
        raise click.ClickException(res.get("error") or "写入失败")


@rules_grp.command("reset")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def rules_reset(obj, workspace, verbose):
    """恢复内置默认规则（改动记 journal）。"""
    from .grading import rules as R
    ws = _setup(verbose or obj.get("verbose"), workspace)
    res = R.reset_rules(ws)
    click.echo(json.dumps({"ok": res.get("ok"), "changes": res.get("changes"),
                           "file": res.get("file")}, ensure_ascii=False, indent=2))


@cli.command("teacher-report")
@click.option("--task", "task_path", required=True, help="任务包 JSON（定位 grading 产物）")
@click.option("--top", "top_n", default=15, type=int, show_default=True,
              help="易错知识点/共现各列几条")
@click.option("--out", "out_dir", default="", help="输出目录（缺省 grading/<task>/reports）")
@click.option("--png", "render_png", is_flag=True, help="同时导出 PNG 长图")
@click.option("--pdf", "render_pdf", is_flag=True, help="同时导出 PDF（隐含 --png）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def teacher_report_cmd(obj, task_path, top_n, out_dir, render_png, render_pdf,
                       workspace, verbose):
    """D126-B：生成教师总结报告（易错知识点 + 共现 + 得分率；只给教师）。"""
    from .grading import teacher_report as TR
    from .grading.flow import grading_dir
    ws = _setup(verbose or obj.get("verbose"), workspace)
    task_file = Path(task_path).expanduser().resolve()
    if not task_file.is_file():
        raise click.ClickException(f"任务包不存在：{task_file}")
    task = json.loads(task_file.read_text(encoding="utf-8"))
    base = grading_dir(ws, task)
    ev = base / "evaluations"
    if not any(ev.glob("[!_]*.json")):
        raise click.ClickException(f"没有评阅结果：{ev}（先跑批阅）")
    out = Path(out_dir).expanduser() if out_dir else (base / "reports")
    # D138：从本章生效清单取「主题」映射，报告按主题分组（无清单则退回扁平表格）
    chaps = sorted({str(i.get("chap") or "") for i in (task.get("items") or [])
                    if isinstance(i, dict) and str(i.get("chap") or "")})
    topics = TR.load_topic_map(ws, chaps or None)
    rep = TR.generate(ev, out, title=str(task.get("course") or task.get("id") or ""),
                      subtitle=str(task.get("class_dir") or ""), top_n=top_n,
                      render_png=render_png or render_pdf, render_pdf=render_pdf,
                      topics=topics)
    click.echo(json.dumps({k: v for k, v in rep.items() if k != "stat"},
                          ensure_ascii=False, indent=2))


@cli.command("trend")
@click.option("--class-dir", "class_dir", required=True,
              help="班级目录（如 classes/化工25）；趋势按该目录下的评阅时间串成序列")
@click.option("--min-recur", default=2, type=int, show_default=True,
              help="至少在这么多次作业里出现才算「反复出错」")
@click.option("--out", "out_dir", default="",
              help="输出目录（缺省 <ws>/classes/<班级>/grading/_trend）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def trend_cmd(obj, class_dir, min_recur, out_dir, workspace, verbose):
    """D135：跨多次作业的知识点趋势（同一知识点是否反复出错；只给教师）。"""
    from .grading import trend as TR
    ws = _setup(verbose or obj.get("verbose"), workspace)
    out = Path(out_dir).expanduser() if out_dir else (
        Path(ws).resolve() / class_dir.strip().strip("/") / "grading" / "_trend")
    rep = TR.generate(ws, class_dir, out, min_recur=min_recur,
                      title=f"知识点趋势 · {class_dir}")
    click.echo(json.dumps({k: v for k, v in rep.items() if k not in ("stat", "markdown")}
                          | {"summary": (rep.get("stat") or {}).get("summary")},
                          ensure_ascii=False, indent=2))


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
@click.option("--header", "headers", multiple=True,
              help="D136：自定义请求头，形如 x-opencode-session={session}（只允许 x-* 与 user-agent）")
@click.option("--user-agent", "user_agent", default=None,
              help="D136：自定义 user-agent（缺省 assignment-assistant/<版本>）")
@click.option("--workspace", "-w", default=None)
def llm_provider(action, name, provider_type, cmd, input_mode, output_mode, timeout_s,
                 supports_images, base_url, api_key, clear_key, batch_support, model, stage,
                 headers, user_agent, workspace):
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
        # D136：--header name=value（可多次）；缺 '=' 直接报错，避免静默丢弃
        hmap: "dict | None" = None
        if headers:
            hmap = {}
            for item in headers:
                if "=" not in str(item):
                    raise click.ClickException(
                        f"--header 需要 name=value 形式，收到 {item!r}")
                k, v = str(item).split("=", 1)
                hmap[k.strip()] = v.strip()
        rep = providers.save_provider(
            ws, name, base_url=base_url, api_key=key_arg,
            batch_support=(True if batch_support else None), model=model,
            provider_type=provider_type, cmd=list(cmd) if cmd else None,
            input_mode=input_mode, output_mode=output_mode, timeout_s=timeout_s,
            supports_images=supports_images,
            headers=hmap, user_agent=user_agent)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    raise SystemExit(0 if rep.get("ok") else 2)


@llm.command("test")
@click.option("--stage", "stage", default="both",
              type=click.Choice(["both", "transcription", "evaluation"], case_sensitive=False),
              help="测哪一段：transcription（多模态）/ evaluation（纯文本）/ both")
@click.option("--model", default="", help="临时覆盖模型名（不写配置）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def llm_test(obj, stage, model, workspace, verbose):
    """D125：按段测试 LLM 配置（最小请求；能立刻发现 base_url/key/model 错配）。"""
    import base64 as _b64
    import tempfile as _tmp
    from .grading.llm import LLMAPIError, LLMClient
    ws = _setup(verbose or obj.get("verbose"), workspace)
    stages = (["transcription", "evaluation"] if stage == "both" else [stage.lower()])
    results = []
    for st in stages:
        item = {"stage": st, "ok": False}
        try:
            client = LLMClient(ws=ws)
            ep = client._step_endpoint(st)
            item.update({"provider": ep.get("provider") or "-",
                         "type": ep.get("type") or "api",
                         "base_url": ep.get("base_url") or "",
                         "model": model or ep.get("model") or "",
                         "hasKey": bool(ep.get("api_key"))})
            t0 = time.time()
            if st == "transcription":
                # 多模态：造一张 8x8 的 PNG，问一句话
                from PIL import Image
                fd, png = _tmp.mkstemp(suffix=".png")
                try:
                    Image.new("RGB", (8, 8), (255, 255, 255)).save(png)
                    txt = client.chat_with_images(
                        "你是一个测试助手。", "这张图片是什么颜色？只回答颜色。",
                        [png], model=model or None, max_tokens=16, step="transcription")
                finally:
                    try:
                        import os as _os
                        _os.unlink(png)
                    except OSError:
                        pass
            else:
                txt = client.chat("你是一个测试助手。", "只回复两个字：收到。",
                                  model=model or None, max_tokens=16, step="evaluation")
            item.update({"ok": True, "ms": int((time.time() - t0) * 1000),
                         "reply": str(txt or "")[:60]})
        except LLMAPIError as exc:
            item["error"] = str(exc)[:400]
        except Exception as exc:  # noqa: BLE001
            item["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        results.append(item)
    click.echo(json.dumps({"ok": all(r["ok"] for r in results), "results": results},
                          ensure_ascii=False, indent=1))
    if not all(r["ok"] for r in results):
        raise click.ClickException("至少一段配置测试失败（见上面 detail：provider/base_url/model）")


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
@click.option("--scope-id", "scope_id", default=None,
              help="D127：批阅作用域键（作业包 id；单张作业纸模式=作业纸 id）。"
                   "决定 grading/<scope>/{drafts,transcripts,...} 目录，必须与 PWA 读取端一致。")
@click.option("--images", "images_dir", default=None, help="学生作业图片目录（文件名=学生名或学号-题号）")
@click.option("--rerun", "rerun", default=None,
              type=click.Choice(["download", "transcribe", "evaluate", "report", "upload"]),
              help="单步重跑（指定 step 名，只重跑该步）")
@click.option("--allow-partial", "allow_partial", is_flag=True,
              help="D125：转录有学生失败时仍继续评阅（默认中止，避免用残缺数据出报告）")
@click.option("--steps", "steps", default="",
              help="D125：本次只跑这些步骤（逗号分隔，如 `transcribe` / `transcribe,evaluate`）；"
                   "缺省=用任务包 grade.steps")
@click.option("--xxt-class", "xxt_class", default="",
              help="D86：学习通班级 <courseId>:<classId>（用 class_map 解析 class_dir 并装配 plan）")
@click.option("--work", "work_id", default="", help="D86：学习通 workId（批阅下载目录定位用）")
@click.option("--plan", "plan_path", default="", help="D86：已有批阅任务清单 plan.json（或用 --xxt-class 现装配）")
@click.option("--mode", "mode", default="", type=click.Choice(["", "optimized", "brute"]),
              help="D86：optimized（默认，给题目/答案）| brute（先自己作答再比对）")
@click.option("--tags", "tags", default="", help="D86：只批阅这些 tag（逗号分隔）")
@click.option("--limit", "limit", default=0, type=int,
              help="只处理前 N 名**有作答**的学生（0=全部；D148 修正语义）")
@click.option("--students", "students", default="",
              help="D148：只处理这些学生（逗号分隔的姓名）——逐生补批用")
@click.option("--dry-plan", "dry_plan", is_flag=True, default=False, help="只装配并打印 plan 摘要，不调 LLM")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def grade(obj, task_path, pads_dir, images_dir, rerun, steps, allow_partial, xxt_class, work_id,
          plan_path, mode, tags, limit, students, dry_plan, scope_id, workspace, verbose):
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
    # D127：--scope-id 统一批阅目录键（作业包 id / 作业纸 id），与 PWA 读取端同口径
    if scope_id:
        task["pack_id"] = str(scope_id)
    task_id = str(scope_id or task.get("id") or "task")

    plan = None
    if plan_path:
        plan = _inputs.load_plan(ws, Path(plan_path).stem) or _json.loads(
            Path(plan_path).read_text(encoding="utf-8"))
    elif xxt_class:
        cid, _, kid = str(xxt_class).partition(":")
        from .xxt import classmap
        # D121：解析不到**不回退**（回退会产生 <ws>/classes/grading 假目录），改为可读报错
        try:
            resolved = classmap.resolve_or_raise(ws, cid, kid, str(task.get("class") or ""))
        except classmap.ClassDirResolutionError as exc:
            raise click.ClickException(str(exc)) from None
        class_dir = resolved["classDir"]
        tag_list = [t.strip() for t in str(tags).split(",") if t.strip()]
        plan = _inputs.build_plan(ws, task_id=task_id, class_dir=class_dir,
                                  class_id=kid, work_id=work_id, mode=(mode or "optimized"),
                                  tags=tag_list,
                                  tasks_dir=Path(pads_dir).expanduser().resolve() if pads_dir else None)
        if limit and plan.get("students"):
            # D148：`--limit N` = 前 N 名**有作答**的学生（不是名单前 N 名）。
            # 名单来自 roster，没交作业的人也在里面；按名单切片很可能切到没图的人，
            # 于是报"名单 1 人，0 人有图"（教师实际踩到）。
            _all = plan["students"]
            _with_img = [x for x in _all if x.get("images")]
            plan["students"] = _with_img[:limit]
            logger.info(f"[批阅] --limit {limit}：名单 {len(_all)} 人 → "
                        f"有作答 {len(_with_img)} 人 → 本次 {len(plan['students'])} 人")
        _inputs.save_plan(ws, class_dir, plan)
    if dry_plan or (plan and dry_plan):
        click.echo(_json.dumps(_inputs.plan_summary(plan or {}), ensure_ascii=False, indent=1))
        return

    # D125：--steps 覆盖任务包 grade.steps（分步批阅：仅转录 / 仅评阅 / 转录+评阅）
    step_list = [x.strip() for x in str(steps or "").split(",") if x.strip()]
    if step_list:
        bad = [x for x in step_list if x not in ("transcribe", "evaluate", "report")]
        if bad:
            raise click.UsageError(f"--steps 含未知步骤：{','.join(bad)}"
                                   "（可选 transcribe,evaluate,report）")
        task["grade"] = {**(task.get("grade") or {}), "steps": step_list}
        tp.write_text(json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")

    kwargs = {"images_dir": images_dir} if images_dir else {}
    _stu = [x.strip() for x in str(students or "").split(",") if x.strip()]
    if _stu:
        kwargs["students"] = _stu
    if allow_partial:
        kwargs["allow_partial"] = True
    if plan:
        kwargs["plan"] = plan
        # D124：把解析出的班级目录**显式**传给 run_task（只给 plan 不够：
        # run_task 内 grading_dir() 用的是 task 上的 class_dir，而 taskpad 不含该字段）
        if str(plan.get("classDir") or "").strip():
            kwargs["class_dir"] = str(plan["classDir"])
        if mode:
            kwargs["mode"] = mode
    # D118：输入侧问题（如"没有任何学生作答图"）应给可读错误，而不是 FileNotFoundError 堆栈
    from .grading.flow import GradingInputError
    try:
        rec = run_step(tp, ws, rerun, **kwargs) if rerun else run_task(tp, ws, **kwargs)
    except GradingInputError as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(f"完成 run_id={rec['run_id']} steps={rec['steps_done']}\n产物目录={rec['bucket']}")
    usage = rec.get("usage") or {}
    if usage.get("total"):
        t = usage["total"]
        click.echo(f"token 用量：prompt={t.get('prompt_tokens', 0)} "
                   f"completion={t.get('completion_tokens', 0)} "
                   f"total={t.get('total_tokens', 0)} calls={t.get('calls', 0)}"
                   "（provider 未返回 usage 时可能为 0）")


@cli.group("workspace", help="D120：workspace 目录布局（校验/迁移）+ 名单与作业纸落盘")
def workspace_grp():
    pass


@workspace_grp.command("layout")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def workspace_layout_cmd(obj, workspace, verbose):
    """检查 kb/ 下是否有错位目录（classes/roster/grading/tasks/packs）。"""
    from . import workspace_layout as WL
    ws = _setup(verbose or obj.get("verbose"), workspace)
    click.echo(json.dumps(WL.inspect(ws), ensure_ascii=False, indent=1))


@workspace_grp.command("fix-layout")
@click.option("--apply", "apply_", is_flag=True, help="真正迁移（缺省只演练）")
@click.option("--move", is_flag=True,
              help="迁移后删除源文件（默认只复制不删源；复制并校验大小后才删）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def workspace_fix_layout(obj, apply_, move, workspace, verbose):
    """D120/D122：把 kb/classes/** 等错位数据迁移到 <ws>/classes/**。

    默认**只复制不删源**；加 `--move` 则复制成功并校验后删源。
    迁移后残留的空源目录可用 `assist workspace clean-migrated` 回收。
    """
    from . import workspace_layout as WL
    ws = _setup(verbose or obj.get("verbose"), workspace)
    rep = WL.fix_layout(ws, apply=apply_, move=move)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    if not apply_ and rep["summary"]["moved"]:
        mode = "移动（删源）" if move else "复制（保留源）"
        click.echo(f"\n（演练：将{mode} {rep['summary']['moved']} 个文件。确认后加 --apply）")


@workspace_grp.command("clean-migrated")
@click.option("--apply", "apply_", is_flag=True, help="真正删除（缺省只演练）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def workspace_clean_migrated(obj, apply_, workspace, verbose):
    """D122：清理「已迁移完成」的源（kb/classes/** 等）。

    安全判定：目标文件存在**且 sha256 与源一致**，才允许删；否则保留并告警。
    """
    from . import workspace_layout as WL
    ws = _setup(verbose or obj.get("verbose"), workspace)
    rep = WL.clean_migrated(ws, apply=apply_)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    if rep["summary"]["blocked"]:
        click.echo(f"\n⚠ {rep['summary']['blocked']} 个源目录未通过一致性校验，已保留（请人工核对）")
    if not apply_ and rep["summary"]["removable"]:
        click.echo(f"\n（演练：可安全删除 {rep['summary']['removable']} 项 / "
                   f"{rep['summary']['bytes'] / 1024 / 1024:.1f} MB。确认后加 --apply）")


@workspace_grp.command("backup")
@click.option("--out", "out_zip", default=None, help="输出 zip 路径（缺省 <ws>/backups/…zip）")
@click.option("--browser-json", default=None, type=click.Path(exists=True, dir_okay=False),
              help="PWA 导出的 localStorage JSON（可选）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def workspace_backup(obj, out_zip, browser_json, workspace, verbose):
    """D121：一键备份（kb/classes/tasks/packs/sheets + 浏览器数据；**不含 .runtime/**，密钥脱敏）。"""
    from . import backup as B
    ws = _setup(verbose or obj.get("verbose"), workspace)
    bd = None
    if browser_json:
        try:
            bd = json.loads(Path(browser_json).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise click.ClickException(f"浏览器数据 JSON 读取失败：{exc}") from None
    rep = B.create_backup(ws, Path(out_zip) if out_zip else None, browser_data=bd)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    if not rep.get("ok"):
        raise click.ClickException(rep.get("error") or "备份失败")
    chk = B.verify_no_secrets(rep["path"])
    click.echo(json.dumps({"secretCheck": chk}, ensure_ascii=False, indent=1))
    if not chk.get("ok"):
        raise click.ClickException("备份包自检失败：疑似含未脱敏密钥")


@workspace_grp.command("audit-class-dirs")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def workspace_audit_class_dirs(obj, workspace, verbose):
    """D124：检查班级目录名是否等于班级真名（RosterClass.name）。"""
    from . import class_dir_audit as CDA
    ws = _setup(verbose or obj.get("verbose"), workspace)
    click.echo(json.dumps(CDA.audit(ws), ensure_ascii=False, indent=1))


@workspace_grp.command("fix-class-dirs")
@click.option("--apply", "apply_", is_flag=True, help="真正重命名（缺省只演练）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def workspace_fix_class_dirs(obj, apply_, workspace, verbose):
    """D124：把错名班级目录改成班级名（同步更新 class_map）。"""
    from . import class_dir_audit as CDA
    ws = _setup(verbose or obj.get("verbose"), workspace)
    rep = CDA.fix(ws, apply=apply_)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    if rep["summary"]["conflict"]:
        click.echo(f"\n⚠ {rep['summary']['conflict']} 个目标目录已存在，未自动合并（请人工确认）")
    if not apply_ and rep["summary"]["renamed"]:
        click.echo(f"\n（演练：将重命名 {rep['summary']['renamed']} 个目录。确认后加 --apply）")


@workspace_grp.command("clean-junk")
@click.option("--apply", "apply_", is_flag=True, help="真正删除（缺省只演练）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def workspace_clean_junk(obj, apply_, workspace, verbose):
    """D121：清理假目录（<ws>/grading、<ws>/classes/grading 等）。

    **含真实批阅产物（evaluations/transcripts/reports）的目录一律拒绝删除。**
    """
    from . import workspace_junk as J
    ws = _setup(verbose or obj.get("verbose"), workspace)
    rep = J.clean_junk(ws, apply=apply_)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    if rep["summary"]["protected"]:
        click.echo(f"\n⚠ {rep['summary']['protected']} 个目录含真实批阅产物，已拒绝删除（请人工处理）")
    if not apply_ and rep["summary"]["deletable"]:
        click.echo(f"\n（演练：可删 {rep['summary']['deletable']} 项 / "
                   f"{rep['summary']['bytes'] / 1024 / 1024:.1f} MB。确认后加 --apply）")


@workspace_grp.command("roster-save")
@click.option("--class-dir", required=True, help="如 classes/化工25")
@click.option("--from-json", "json_path", required=True, type=click.Path(exists=True, dir_okay=False),
              help="名单 JSON：[{name,number,class,tag}]")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def workspace_roster_save(obj, class_dir, json_path, workspace, verbose):
    """D120：把名单写入 <ws>/<class_dir>/roster/roster.xlsx（路径由引擎决定）。"""
    from .files import roster_io
    ws = _setup(verbose or obj.get("verbose"), workspace)
    students = json.loads(Path(json_path).read_text(encoding="utf-8"))
    rep = roster_io.write_roster(ws, class_dir, students)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    if not rep.get("ok"):
        raise click.ClickException(rep.get("error") or "写名单失败")


@workspace_grp.command("roster-show")
@click.option("--class-dir", required=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def workspace_roster_show(obj, class_dir, workspace, verbose):
    """D120：读回名单（PWA localStorage 丢失时可从这里恢复）。"""
    from .files import roster_io
    ws = _setup(verbose or obj.get("verbose"), workspace)
    rep = roster_io.read_roster_file(ws, class_dir)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    if not rep.get("ok"):
        raise click.ClickException(rep.get("error") or "读取失败")


@workspace_grp.command("taskpad-list")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def workspace_taskpad_list(obj, workspace, verbose):
    """D120：列出磁盘上的作业纸（<ws>/tasks/）。"""
    from .files import taskpads
    ws = _setup(verbose or obj.get("verbose"), workspace)
    items = taskpads.list_taskpads(ws)
    click.echo(json.dumps({"ok": True, "count": len(items),
                           "ids": [x.get("id") for x in items]},
                          ensure_ascii=False, indent=1))


@cli.group("grading", help="D119：批阅成果管理（清理可重跑产物 / 临时文件 / 旧目录残留）")
def grading_grp():
    pass


@grading_grp.command("clean")
@click.option("--task", "task_id", default="", help="只清某张作业纸（grading/<taskId>/）")
@click.option("--reports", is_flag=True, help="清 reports/（报告可重跑）")
@click.option("--journal", is_flag=True, help="清 journal.jsonl / batch-report.json / diagnostics.jsonl")
@click.option("--drafts", is_flag=True, help="清 drafts/（**人工批改成果，谨慎**）")
@click.option("--tmp", is_flag=True, help="清 <ws>/tmp/ai-grade/（作业包临时快照）")
@click.option("--stale-images", "stale_images", is_flag=True,
              help="清已废弃的 grading/<task>/images/（D119 起不再使用）")
@click.option("--all", "all_", is_flag=True, help="清整个 grading/<task>/（不含作答原件）")
@click.option("--apply", "apply_", is_flag=True, help="真正删除（缺省只演练）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def grading_clean(obj, task_id, reports, journal, drafts, tmp, stale_images, all_, apply_, workspace, verbose):
    """D119：清理批阅成果（默认演练；**绝不触碰** kb/ 与作答原件 pages/review/）。"""
    from .grading import cleanup as C
    ws = _setup(verbose or obj.get("verbose"), workspace)
    rep = C.clean(ws, task_id=task_id, reports=reports, journal=journal, drafts=drafts,
                  tmp=tmp, all_=all_, stale_images=stale_images, apply=apply_)
    click.echo(json.dumps(rep, ensure_ascii=False, indent=1))
    if not rep.get("ok"):
        raise click.ClickException(rep.get("error") or "清理失败")
    if not apply_ and rep.get("count"):
        click.echo(f"\n（以上为演练，共 {rep['count']} 项 / {rep['human']}。确认后加 --apply 执行）")


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
    try:
        resolved = classmap.resolve_or_raise(ws, cid, kid, str(task.get("class") or ""))
    except classmap.ClassDirResolutionError as exc:
        raise click.ClickException(str(exc)) from None
    class_dir = resolved["classDir"]
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


def _alias_assistopia_argv(argv: list[str]) -> list[str]:
    """D134：`assist assistopia ...` → `assist atopia ...`（旧名永久兼容）。

    只认**第一个**子命令位置；`-w/--workspace` 等全局选项若出现在前面则原样保留。
    """
    out = list(argv)
    for i, tok in enumerate(out):
        if tok.startswith("-"):
            continue
        if tok == "assistopia":
            out[i] = "atopia"
        break
    return out


def main():
    """CLI entry：包一层异常处理，支持 ASSIST_JSON_ERRORS 机读错误（便于 AI agent 调）。"""
    import sys
    json_mode = _json_errors_enabled()
    if sys.argv and len(sys.argv) > 1:
        sys.argv = [sys.argv[0], *_alias_assistopia_argv(sys.argv[1:])]
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


@cli.command("migrate-grading-dir")
@click.option("--workspace", "-w", default=None)
@click.option("--class-dir", default=None, help="只处理某个班级目录（如 classes/化工25）")
@click.option("--dry-run/--apply", "dry_run", default=True,
              help="默认只演练（--apply 才真正移动）")
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def migrate_grading_dir(obj, workspace, class_dir, dry_run, verbose):
    """D127：把旧的 `grading/<作业纸id>/` 迁移到 `grading/<作业包id>/`。

    作业包在 D127 起是唯一批次载体；老数据目录名是单张作业纸 id。
    迁移是**复制 + 校验**，不删源（安全优先）；已迁移过的会跳过（幂等）。
    """
    import shutil

    from .grading.flow import grading_key
    from .packs import list_packs

    ws = _setup(verbose or obj.get("verbose"), workspace)
    packs = list_packs(ws) or []
    # padId -> packId
    pad_to_pack: dict[str, str] = {}
    for pk in packs:
        pid = str(pk.get("id") or "")
        for ref in (pk.get("pads") or []):
            if isinstance(ref, dict) and ref.get("padId"):
                pad_to_pack[str(ref["padId"])] = pid

    root = Path(ws) / (class_dir or "classes")
    if not root.is_dir():
        click.echo(json.dumps({"ok": False, "error": f"目录不存在：{root}"},
                              ensure_ascii=False, indent=1))
        raise SystemExit(2)
    moved, skipped, unknown = [], [], []
    for gdir in sorted(root.glob("*/grading/*")):
        if not gdir.is_dir():
            continue
        name = gdir.name
        target_id = pad_to_pack.get(name)
        if not target_id:
            unknown.append(str(gdir))
            continue
        if target_id == name:
            skipped.append({"from": str(gdir), "reason": "已是包 id"})
            continue
        dst = gdir.parent / target_id
        if dst.exists() and any(dst.iterdir()):
            skipped.append({"from": str(gdir), "to": str(dst), "reason": "目标已存在（不覆盖）"})
            continue
        if dry_run:
            moved.append({"from": str(gdir), "to": str(dst), "dryRun": True})
            continue
        shutil.copytree(gdir, dst, dirs_exist_ok=True)
        moved.append({"from": str(gdir), "to": str(dst), "dryRun": False})
    out = {"ok": True, "dryRun": dry_run, "moved": moved, "skipped": skipped,
           "unknown": unknown,
           "hint": "默认只演练；确认无误后加 --apply。迁移为复制，不删源目录。"}
    click.echo(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
