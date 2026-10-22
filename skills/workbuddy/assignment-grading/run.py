#!/usr/bin/env python3
"""WorkBuddy skill 入口：调用本机 assist CLI 完成两段式批阅。

只做编排，不做 LLM 调用；正文与报告均由 assist 落盘。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys


def _write_receipt(payload: dict) -> str:
    """写执行回执（含自检报告路径），便于用户/开发者定位问题。"""
    import datetime
    import os
    root = os.environ.get("ASSIST_WORKSPACE") or "."
    d = os.path.join(root, "skill-receipts")
    os.makedirs(d, exist_ok=True)
    fn = os.path.join(d, datetime.datetime.now().strftime("receipt-%Y%m%d-%H%M%S.json"))
    try:
        with open(fn, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
    except OSError:
        return ""
    return fn


def _selfcheck() -> dict:
    """生成自检报告（失败现场的第一手证据）。"""
    exe = shutil.which("assist")
    if not exe:
        return {"ok": False, "error": "未找到 assist"}
    try:
        cp = subprocess.run([exe, "doctor", "--report", "--json"],
                            capture_output=True, text=True, timeout=90)
        return {"ok": cp.returncode == 0, "data": json.loads(cp.stdout or "{}")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def _run(args: list[str]) -> dict:
    exe = shutil.which("assist")
    if not exe:
        return {"ok": False, "error": "未找到 assist 命令，请先安装 assignment-assistant"}
    cp = subprocess.run([exe, *args], capture_output=True, text=True, timeout=3600)
    out = (cp.stdout or "").strip()
    if cp.returncode != 0:
        err = (cp.stderr or out or "").strip()
        # 不要把整段 traceback 甩给用户：提取最后一行 + 引导看自检报告
        last = next((ln for ln in reversed(err.splitlines())
                     if ln.strip() and not ln.strip().startswith(("File ", "~", "^"))), "")
        if not last or "Traceback" in last:
            last = "assist 执行失败（详细根因见自检报告）"
        return {"ok": False, "exitCode": cp.returncode,
                "error": last.strip()[:300],
                "hint": "运行 `assist doctor --report` 查看分层根因与修复建议",
                "raw": err[-800:]}
    return {"ok": True, "stdout": out[:2000]}


def main() -> int:
    ap = argparse.ArgumentParser(description="两段式 AI 批阅（转录→评阅）")
    ap.add_argument("--task", required=True, help="任务包 JSON")
    ap.add_argument("--xxt-class", required=True, help="<courseId>:<classId>")
    ap.add_argument("--work", default="", help="学习通 workId")
    ap.add_argument("--rerun", default="", choices=["", "evaluate", "report"],
                    help="只重跑某一步")
    a = ap.parse_args()

    # 1) 先体检（能力 + 风险提示）
    doc = _run(["doctor", "--json"])
    if not doc.get("ok"):
        print(json.dumps(doc, ensure_ascii=False))
        return 2
    try:
        caps = json.loads(doc["stdout"]).get("capabilities", {})
    except Exception:
        caps = {}
    if caps.get("recommendedPath") == "subagent-or-manual":
        print(json.dumps({
            "ok": False,
            "error": "本机没有可用的 LLM 后端（无 API key、无 command provider、无 agent CLI）",
            "hint": ("请先配置：assist llm provider --action set --name local "
                     "--type command --cmd <你的CLI>，或配置 API provider"),
        }, ensure_ascii=False))
        return 2
    warns = [w for w in caps.get("warnings") or []
             if w.get("code") == "transcription_command_no_images"]
    if warns:
        print(json.dumps({"ok": False, "error": warns[0]["message"]}, ensure_ascii=False))
        return 2

    # 2) 执行（转录 + 评阅 + 报告）
    args = ["grade", "--task", a.task, "--xxt-class", a.xxt_class]
    if a.work:
        args += ["--work", a.work]
    if a.rerun:
        args += ["--rerun", a.rerun]
    rep = _run(args)
    # D98：失败时附带自检回执（根因分层 + 修复建议），成功也记录一份便于回溯
    receipt = {"at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
               "action": "assignment-grading", "args": vars(a),
               "result": {"ok": rep.get("ok"), "error": rep.get("error")}}
    sc = _selfcheck()
    if sc.get("data"):
        rep["selfcheck"] = {
            "summary": sc["data"].get("summary"),
            "issues": sc["data"].get("issues"),
        }
    receipt["selfcheckSummary"] = (sc.get("data") or {}).get("summary")
    fn = _write_receipt(receipt)
    if fn:
        rep["receipt"] = fn
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
