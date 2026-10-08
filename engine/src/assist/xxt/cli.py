"""d63 T1：`assist xxt` 命令组（check/login）。由 assist/cli.py 注册进主 cli。"""
from __future__ import annotations

import json
from pathlib import Path

import click


def default_storage(ctx) -> Path:
    import os
    v = os.environ.get("XXT_STORAGE")
    if v:
        return Path(v).expanduser()
    from ..workspace import DEFAULT_WORKSPACE
    return DEFAULT_WORKSPACE / ".runtime" / "xxt-storage.json"


def register(group: click.Group) -> None:
    @group.command("check")
    @click.option("--storage", "storage", default=None,
                  type=click.Path(dir_okay=False), help="storage_state JSON（默认 env XXT_STORAGE 或 workspace/.runtime）")
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
        if rep.get("verdict") == "logged_in":
            rep2 = check_session(storage_path)
            click.echo(json.dumps({"post_login_check": rep2}, ensure_ascii=False, indent=1))
        raise SystemExit(0 if rep.get("verdict") == "logged_in" else 2)
