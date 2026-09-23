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


def _setup(verbose: bool, ws: Path | None = None):
    from .log import setup_logging
    from .workspace import apply_runtime_env, find_workspace
    setup_logging(verbose)
    ws_path = find_workspace() if ws is None else ws
    apply_runtime_env(ws_path)
    return ws_path


@click.group()
@click.help_option("-h", "--help")
@click.version_option(None, "--version")
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
@click.pass_obj
def doctor(obj, workspace, verbose):
    """环境体检：Python/uv/依赖/字体/引擎可导入性（对齐 PWA 体检页格式）。"""
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
        checks.append(("xelatex(可选)", "green" if check_xelatex() else "yellow"))
    except ImportError:
        checks.append(("xelatex(可选)", "red"))
    cfg = load_workspace_settings(ws_path)
    checks.append(("settings.local.json", "green" if (ws_path / "settings.local.json").exists() else "yellow"))
    checks.append(("kb/problems.xlsx", "green" if (ws_path / "kb" / "problems.xlsx").exists() else "yellow"))
    rows = ["项        状态", "-" * 24] + [f"{n:<10}{'✓' if s == 'green' else ('!' if s == 'yellow' else '✗')} ({s})" for n, s in checks]
    click.echo("\n".join(rows))
    bad = [n for n, s in checks if s == "red"]
    if bad:
        click.echo(f"缺失：{bad}。安装：assist bootstrap")


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
    kb_dir = _kb_dir(_setup(verbose or obj.get("verbose")))
    kb_data = read_kb(kb_dir)
    rows = []
    for kind, chapters in kb_data.items():
        for chap, entries in chapters.items():
            rows.append((kind, chap, len(entries)))
    if not rows:
        click.echo("题库为空（kb/ 下无 xlsx）。可用 `assist kb init` 生成示例。")
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
    """导出 JSON 副本到 kb/export/（AI 阅读/diff 基准，不入库）。"""
    from .files import read_kb, write_json
    ws = _setup(verbose or obj.get("verbose"))
    out = write_json(ws / "kb", read_kb(ws / "kb"))
    click.echo(f"已导出 → {out}")


@kb.command("snapshot")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def kb_snapshot(obj, workspace, verbose):
    """手动把 kb/*.xlsx 快照到 kb/.history/。"""
    from .files import snapshot as snap
    ws = _setup(verbose or obj.get("verbose"))
    made = snap(ws / "kb")
    click.echo(f"快照 {len(made)} 个文件")


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
    ws = _setup(verbose or obj.get("verbose"))
    out_dir = (ws / out).resolve()
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
    items_of = lambda i: [(f"题干占位（stage1 demo）：请写出第{i+1}题的过程。", figs[i % 2], "distinguish"),
                          ("第二题（无图占位）：练习书写规范。", None, "copy")]
    files = make_pdf(
        students, items_of, ws / out_dir, orientation,
        assets_dir=ASSIST_ROOT / "assets",
        title="大学物理-作业纸(demo)", watermark=not no_watermark,
    )
    for f in files:
        click.echo(str(f))


@sheet.command("make")
@click.option("--task", "task_path", required=True, help="任务包 JSON 路径")
@click.option("--roster", "roster_path", default=None, help="点名册 xlsx（缺省找 classes/<class>/roster/）")
@click.option("--out", "-o", default=None, help="输出目录（缺省 classes/<class>/sheets/out）")
@click.option("--no-watermark", is_flag=True)
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def sheet_make(obj, task_path, roster_path, out, no_watermark, workspace, verbose):
    """按任务包生成每生一份作业纸 PDF（xlsx 名单驱动）。"""
    from .paper import sheets_from_task
    from .workspace import load_workspace_settings
    ws = _setup(verbose or obj.get("verbose"))
    files = sheets_from_task(
        Path(task_path).expanduser().resolve(), ws,
        out_dir=Path(out).expanduser().resolve() if out else None,
        no_watermark=no_watermark,
        roster_path=str(roster_path) if roster_path else None,
        user_cfg=load_workspace_settings(ws),
    )
    for f in files:
        click.echo(str(f))


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
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def sheet_batch(obj, roster_fn, task_files, map_specs, default_pad, class_dir, out, workspace, verbose):
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
        mapping=mapping, default_pad=default_pad)
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


@cli.command()
@click.option("--task", "task_path", required=True, help="任务包 JSON 路径（grade 节驱动）")
@click.option("--images", "images_dir", default=None, help="学生作业图片目录（文件名=学生名或学号-题号）")
@click.option("--rerun", "rerun", default=None,
              type=click.Choice(["download", "transcribe", "evaluate", "report", "upload"]),
              help="单步重跑（指定 step 名，只重跑该步）")
@click.option("--workspace", "-w", default=None)
@click.option("--verbose", "-v", is_flag=True)
@click.pass_obj
def grade(obj, task_path, images_dir, rerun, workspace, verbose):
    """AI 批阅：transcribe → evaluate → report（阶段3；download/upload 属阶段4）。

    任务包 grade.steps 驱动；journal 运行记录写入
    classes/<class>/grading/<task>/journal.jsonl（05-D8）；
    apikey 从 workspace settings.local.json 的 llm 段读（绝不入代码/日志）。
    """
    from .grading.flow import run_task, run_step
    ws = _setup(verbose or obj.get("verbose"), workspace)
    tp = Path(task_path).expanduser().resolve()
    kwargs = {"images_dir": images_dir} if images_dir else {}
    rec = run_step(tp, ws, rerun, **kwargs) if rerun else run_task(tp, ws, **kwargs)
    click.echo(f"完成 run_id={rec['run_id']} steps={rec['steps_done']}\n产物目录={rec['bucket']}")


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
