#!/usr/bin/env python3
"""skill 安装/校验器：把仓库的 skills/ 装到各 AI 宿主，并做前置检查。

支持宿主（2026-10-18 官方文档实测）：
- qwenwork  : skill = <skills_root>/<name>/SKILL.md
- workbuddy : skill = <skills_root>/<name>/skill.yml + 实现文件 + README
- generic   : 仓库内 skills/*.md 规程（给人/agent 阅读，不安装）

用法：
  python tools/skill_installer.py list                     # 列出可装 skill 与宿主
  python tools/skill_installer.py check                    # 仅校验前置（assist/目录/文档规范）
  python tools/skill_installer.py install --host qwenwork  # 复制到 ~/.qwenwork/skills/
  python tools/skill_installer.py install --host workbuddy --dest <dir>
  python tools/skill_installer.py verify --host qwenwork   # 校验已安装目录是否完整

所有命令支持 --json（便于 agent 调用）。退出码：0 成功 / 1 校验失败 / 2 用法错误。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"

# 宿主配置：源目录 / 默认安装根 / 必需文件
HOSTS = {
    "qwenwork": {
        "src": SKILLS / "qwenwork",
        "default_root": Path.home() / ".qwenwork" / "skills",
        "required": ["SKILL.md"],
        "doc": "https://docs.qwenwork.ai/desktop/skills.md",
    },
    "workbuddy": {
        "src": SKILLS / "workbuddy",
        "default_root": None,   # 官方未公开固定目录，需 --dest
        "required": ["skill.yml", "run.py", "README.md"],
        "doc": "https://www.workbuddy.ai/docs/workbuddy/From-Beginner-to-Expert-Guide/Practice-Cases/Create-Skills",
    },
}


def _skills_of(host: str) -> list[Path]:
    src = HOSTS[host]["src"]
    if not src.is_dir():
        return []
    return sorted([d for d in src.iterdir() if d.is_dir()])


def cmd_list(as_json: bool) -> int:
    out = []
    for host, cfg in HOSTS.items():
        for d in _skills_of(host):
            out.append({"host": host, "name": d.name, "src": str(d),
                        "required": cfg["required"],
                        "defaultRoot": str(cfg["default_root"]) if cfg["default_root"] else None})
    if as_json:
        print(json.dumps({"ok": True, "skills": out}, ensure_ascii=False, indent=1))
    else:
        for r in out:
            print(f"[{r['host']}] {r['name']}  →  {r['defaultRoot'] or '(需 --dest)'}")
    return 0


def _assist_doctor() -> dict:
    """跑 assist doctor --json；失败返回 {ok:False, error}。"""
    exe = shutil.which("assist")
    if not exe:
        return {"ok": False, "error": "未找到 assist 命令（先安装 assignment-assistant）"}
    try:
        cp = subprocess.run([exe, "doctor", "--json"], capture_output=True, text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"执行 assist doctor 失败：{exc}"}
    if cp.returncode != 0:
        return {"ok": False, "error": (cp.stderr or cp.stdout or "")[:300]}
    try:
        return {"ok": True, "data": json.loads(cp.stdout or "{}")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"doctor 输出非 JSON：{exc}"}


def _assist_selfcheck() -> dict:
    """跑 `assist doctor --report --json`，返回 {ok, issues, raw}。"""
    exe = shutil.which("assist")
    if not exe:
        return {"ok": False}
    try:
        cp = subprocess.run([exe, "doctor", "--report", "--json"],
                            capture_output=True, text=True, timeout=90)
        data = json.loads(cp.stdout or "{}")
        return {"ok": True, "issues": data.get("issues") or [],
                "summary": data.get("summary") or {}}
    except Exception:  # noqa: BLE001
        return {"ok": False}


def cmd_check(as_json: bool) -> int:
    """前置校验：仓库 skill 完整 + assist 可用 + LLM 能力 + 转录图片风险。"""
    problems: list[str] = []
    warns: list[str] = []
    details: dict = {"hosts": {}}

    for host, cfg in HOSTS.items():
        ds = _skills_of(host)
        if not ds:
            problems.append(f"{host}: 源目录无 skill（{cfg['src']}）")
            continue
        for d in ds:
            missing = [f for f in cfg["required"] if not (d / f).is_file()]
            if missing:
                problems.append(f"{host}/{d.name}: 缺少必需文件 {missing}")
            details["hosts"].setdefault(host, []).append({"name": d.name, "ok": not missing})

    doc = _assist_doctor()
    details["assist"] = doc
    if not doc.get("ok"):
        problems.append(f"assist 不可用：{doc.get('error')}")
    else:
        caps = (doc.get("data") or {}).get("capabilities") or {}
        details["capabilities"] = caps
        # 复用 selfcheck 的分层诊断（与 `assist doctor --report` 同口径）
        selfcheck = _assist_selfcheck()
        details["selfcheck"] = selfcheck
        if selfcheck.get("ok"):
            for i in selfcheck.get("issues") or []:
                msg = f"[{i.get('layer')}/{i.get('code')}] {i.get('message')}"
                if i.get("level") == "error":
                    problems.append(msg + (f" → {i['fix']}" if i.get("fix") else ""))
                elif i.get("level") in ("warn", "warning"):
                    warns.append(msg)
        else:
            # 自检命令不可用时退回能力探测
            if caps.get("recommendedPath") == "subagent-or-manual":
                problems.append("没有可用 LLM 后端（无 API key / 无 command provider / 无 CLI）")

    ok = not problems
    if as_json:
        print(json.dumps({"ok": ok, "problems": problems, "warnings": warns,
                          "details": details}, ensure_ascii=False, indent=1))
    else:
        print("前置校验：" + ("通过" if ok else "未通过"))
        for p in problems:
            print(f"  ✗ {p}")
        for w in warns:
            print(f"  ⚠ {w}")
        if doc.get("ok"):
            caps = details.get("capabilities") or {}
            print(f"  推荐路径：{caps.get('recommendedPath')}")
    return 0 if ok else 1


def cmd_install(host: str, dest: str | None, as_json: bool) -> int:
    if host not in HOSTS:
        print(json.dumps({"ok": False, "error": f"未知宿主：{host}"}, ensure_ascii=False)
              if as_json else f"未知宿主：{host}")
        return 2
    cfg = HOSTS[host]
    root = Path(dest).expanduser() if dest else cfg["default_root"]
    if root is None:
        msg = f"{host} 需要 --dest <skills 目录>（官方未公开默认目录）"
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False) if as_json else msg)
        return 2
    root.mkdir(parents=True, exist_ok=True)

    installed = []
    for d in _skills_of(host):
        target = root / d.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(d, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        installed.append({"name": d.name, "to": str(target)})

    result = {"ok": bool(installed), "host": host, "root": str(root),
              "installed": installed, "doc": cfg["doc"]}
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for it in installed:
            print(f"✓ 已安装 {host}/{it['name']} → {it['to']}")
        print(f"  官方文档：{cfg['doc']}")
    return 0 if installed else 1


def cmd_verify(host: str, dest: str | None, as_json: bool) -> int:
    if host not in HOSTS:
        return 2
    cfg = HOSTS[host]
    root = Path(dest).expanduser() if dest else cfg["default_root"]
    if root is None:
        print(json.dumps({"ok": False, "error": "需要 --dest"}, ensure_ascii=False)
              if as_json else "需要 --dest")
        return 2
    rows = []
    for d in _skills_of(host):
        target = root / d.name
        exists = target.is_dir()
        missing = [f for f in cfg["required"] if not (target / f).is_file()] if exists else []
        rows.append({"name": d.name, "installed": exists, "missing": missing,
                     "ok": exists and not missing})
    ok = bool(rows) and all(r["ok"] for r in rows)
    if as_json:
        print(json.dumps({"ok": ok, "host": host, "root": str(root), "items": rows},
                         ensure_ascii=False, indent=1))
    else:
        print(f"{host} 安装校验：" + ("通过" if ok else "未通过"))
        for r in rows:
            if r["ok"]:
                print(f"  ✓ {r['name']}")
            elif not r["installed"]:
                print(f"  ✗ {r['name']}：未安装（{root / r['name']} 不存在）")
            else:
                print(f"  ✗ {r['name']}：缺少 {r['missing']}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 宿主 skill 安装/校验")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("list", "check"):
        sp = sub.add_parser(name)
        sp.add_argument("--json", action="store_true")

    for name in ("install", "verify"):
        sp = sub.add_parser(name)
        sp.add_argument("--host", required=True, choices=sorted(HOSTS))
        sp.add_argument("--dest", default=None, help="目标 skills 目录")
        sp.add_argument("--json", action="store_true")

    a = ap.parse_args()
    if a.cmd == "list":
        return cmd_list(a.json)
    if a.cmd == "check":
        return cmd_check(a.json)
    if a.cmd == "install":
        return cmd_install(a.host, a.dest, a.json)
    if a.cmd == "verify":
        return cmd_verify(a.host, a.dest, a.json)
    return 2


if __name__ == "__main__":
    sys.exit(main())
