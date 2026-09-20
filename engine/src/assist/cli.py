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
    ws = _setup(verbose or obj.get("verbose"))
    files = sheets_from_task(
        Path(task_path).expanduser().resolve(), ws,
        out_dir=Path(out).expanduser().resolve() if out else None,
        no_watermark=no_watermark,
        roster_path=str(roster_path) if roster_path else None,
    )
    for f in files:
        click.echo(str(f))


@cli.command()
@click.pass_obj
def serve(obj):  # 阶段4 占位
    """本地引擎 HTTP 服务（Companion 模式，阶段4 实现）。"""
    click.echo("serve：阶段4 实现（占位）。")


@cli.command()
@click.pass_obj
def grade(obj):  # 阶段3 占位
    """AI 批阅（阶段3 实现）。"""
    click.echo("grade：阶段3 实现（占位）。")


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
