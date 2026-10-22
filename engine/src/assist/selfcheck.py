"""D98：自检/回执（doctor --report）——把"出了什么问题、该改哪里"变成一份可交付报告。

为什么需要：用户/开发者拿到"失败"时，常见困境是不知道**根因在哪一层**：
  环境（Python/依赖）→ 配置（provider/stage）→ 能力（api/command/图片）→
  数据（workspace/kb/roster）→ 运行产物（batch-report/diagnostics）。

本模块把这些按统一结构汇总，并对每个问题给出 `code`（稳定标识）、`layer`（层）、
`fix`（可执行建议），既给人看也便于 agent/脚本按 code 分支处理。

不调用模型、不联网（除 --online 显式探测远端版本）。
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path

SCHEMA = 1


def _check(ok: bool, level: str = "error") -> dict:
    return {"ok": bool(ok), "level": "ok" if ok else level}


def _issue(code: str, layer: str, message: str, fix: str = "", *, level: str = "error") -> dict:
    return {"code": code, "layer": layer, "level": level, "message": message, "fix": fix}


def collect_environment() -> dict:
    """环境层：Python、包、可选依赖。"""
    import importlib
    issues: list[dict] = []
    deps = {}
    for mod in ("openpyxl", "reportlab", "loguru", "httpx", "PIL", "pypdf"):
        try:
            importlib.import_module(mod)
            deps[mod] = True
        except ImportError:
            deps[mod] = False
            issues.append(_issue(f"dep_missing.{mod}", "environment",
                                 f"缺少依赖 {mod}", "运行 `assist bootstrap` 或 pip install 补齐"))
    uv = bool(shutil.which("uv"))
    if not uv:
        issues.append(_issue("uv_missing", "environment", "未找到 uv",
                             "安装 uv 可加速依赖解析（非必需，pip 可回退）", level="info"))
    try:
        from . import __version__ as ver
    except Exception:  # noqa: BLE001
        ver = "?"
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "engineVersion": ver,
        "deps": deps,
        "uv": uv,
        "issues": issues,
    }


def collect_config(ws: Path) -> dict:
    """配置层：workspace、provider、两段式、密钥是否就位（不回显 key）。"""
    issues: list[dict] = []
    ws = Path(ws)
    out: dict = {"workspace": str(ws), "workspaceExists": ws.is_dir()}
    if not ws.is_dir():
        issues.append(_issue("workspace_missing", "config", f"workspace 不存在：{ws}",
                             "运行 `assist bootstrap --workspace <路径>`"))
        out["issues"] = issues
        return out

    settings = ws / "settings.local.json"
    out["settingsExists"] = settings.is_file()
    try:
        from .grading import providers as P
        provs = P.list_providers(ws, mask=True)
        stages_cfg = P.stages(ws)
        out["providers"] = [{"name": p["name"], "type": p.get("type") or "api",
                             "baseUrl": bool(p.get("base_url")),
                             "hasKey": bool(p.get("has_key")),
                             "cmd": bool(p.get("cmd")),
                             "supportsImages": p.get("supports_images"),
                             "batchSupport": bool(p.get("batch_support"))}
                            for p in provs]
        out["stages"] = {k: {"provider": v.get("provider"), "model": v.get("model")}
                         for k, v in stages_cfg.items()}
        by_name = {p["name"]: p for p in provs}
        for stage in ("transcription", "evaluation"):
            st = stages_cfg.get(stage) or {}
            name = str(st.get("provider") or "")
            if not name:
                issues.append(_issue(f"stage_unset.{stage}", "config",
                                     f"未配置 {stage} 段 provider",
                                     f"`assist llm provider --action stage --stage {stage} --name <provider>`",
                                     level="info"))
                continue
            p = by_name.get(name)
            if p is None:
                issues.append(_issue(f"stage_provider_missing.{stage}", "config",
                                     f"{stage} 段引用的 provider「{name}」不存在",
                                     "重新执行 --action stage 指向已存在的 provider"))
                continue
            if (p.get("type") or "api") == "api" and not p.get("has_key"):
                issues.append(_issue(f"stage_provider_no_key.{stage}", "config",
                                     f"{stage} 段 provider「{name}」未配置 api_key",
                                     "`assist llm provider --action set --name <p> --api-key ...`"))
    except Exception as exc:  # noqa: BLE001
        issues.append(_issue("config_read_failed", "config", f"读取 provider 配置失败：{exc}",
                             "检查 settings.local.json 是否为合法 JSON"))
    out["issues"] = issues
    return out


def collect_capabilities(ws: Path) -> dict:
    """能力层：可走哪条路径 + 转录图片风险。"""
    try:
        from .grading import providers as P
        caps = P.capabilities(ws)
    except Exception as exc:  # noqa: BLE001
        return {"issues": [_issue("capability_probe_failed", "capability",
                                  f"能力探测失败：{exc}", "检查 workspace 配置")]}
    issues = []
    for w in caps.get("warnings") or []:
        issues.append(_issue(w.get("code") or "warning", "capability",
                             w.get("message") or "", "", level=w.get("level") or "warn"))
    # 注意：仅"检测到 agent CLI"不等于已配置可用后端——必须真的配了 provider/stage。
    if not (caps.get("api") or {}).get("available") and \
            not (caps.get("command") or {}).get("available"):
        cfgs = caps.get("agentCli") or []
        hint = ("配置 API provider 或 `assist llm provider --action set --name local "
                "--type command --cmd <agent-cli>`")
        if cfgs:
            hint += f"（检测到本机 CLI：{', '.join(c['name'] for c in cfgs)}，但尚未配成 provider）"
        issues.append(_issue("no_llm_backend", "capability",
                             "没有已配置的 LLM 后端（有 CLI 也需先配成 provider）", hint))
    caps["issues"] = issues
    return caps


def collect_data(ws: Path) -> dict:
    """数据层：题库、班级名单、任务包。"""
    issues: list[dict] = []
    ws = Path(ws)
    kb = ws / "kb"
    xlsx = sorted(p.name for p in kb.glob("*.xlsx")) if kb.is_dir() else []
    if not xlsx:
        issues.append(_issue("kb_missing", "data", "题库为空（kb/ 下无 xlsx）",
                             "PWA 体检页「创建题库」或放入题库 xlsx", level="warn"))
    classes = ws / "classes"
    class_dirs = sorted(p.name for p in classes.iterdir()
                        if p.is_dir()) if classes.is_dir() else []
    if not class_dirs:
        issues.append(_issue("no_classes", "data", "workspace 下没有班级目录（classes/）",
                             "先在学习通页提取/建班，或手动创建 classes/<班级>", level="warn"))
    tasks = sorted(p.name for p in (ws / "tasks").glob("*.taskpad.json")) \
        if (ws / "tasks").is_dir() else []
    return {"kbFiles": xlsx, "classDirs": class_dirs, "taskpads": tasks, "issues": issues}


def collect_artifacts(ws: Path, limit: int = 5) -> dict:
    """运行产物：最近的 batch-report / diagnostics（帮助定位"上次为什么失败"）。"""
    ws = Path(ws)
    out: dict = {"reports": [], "diagnostics": []}
    if not (ws / "classes").is_dir():
        return out
    reports = sorted((ws / "classes").glob("**/grading/**/batch-report.json"),
                     key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    for p in reports:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            fails = [{"id": it.get("id"), "error": it.get("error")}
                     for it in (d.get("items") or []) if it.get("status") != "ok"]
            out["reports"].append({
                "path": str(p), "kind": d.get("kind"),
                "total": d.get("total"), "ok": d.get("ok"), "failed": d.get("failed"),
                "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
                "sampleFailures": fails[:5],
            })
        except Exception:  # noqa: BLE001
            continue
    diags = sorted((ws / "classes").glob("**/grading/**/diagnostics.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    for p in diags:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        tail = []
        for ln in lines[-3:]:
            try:
                tail.append(json.loads(ln))
            except Exception:  # noqa: BLE001
                pass
        out["diagnostics"].append({"path": str(p), "lines": len(lines), "tail": tail})
    return out


def build_report(ws: Path) -> dict:
    """汇总自检报告（人类可读 + 机器可读）。"""
    env = collect_environment()
    cfg = collect_config(ws)
    cap = collect_capabilities(ws)
    data = collect_data(ws)
    arts = collect_artifacts(ws)

    issues: list[dict] = []
    for part in (env, cfg, cap, data):
        issues.extend(part.get("issues") or [])
    errors = [i for i in issues if i.get("level") == "error"]
    warns = [i for i in issues if i.get("level") in ("warn", "warning")]

    # 最近的失败产物可作为附加线索
    recent_fail = None
    for r in arts.get("reports") or []:
        if (r.get("failed") or 0) > 0:
            recent_fail = r
            break
    if recent_fail:
        issues.append(_issue(
            "recent_batch_failures", "artifact",
            f"最近一次 {recent_fail['kind']} 有 {recent_fail['failed']} 条失败",
            f"查看 {recent_fail['path']}；失败项可单独重跑", level="warn"))

    return {
        "schema": SCHEMA,
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "ok": not errors,
            "errors": len(errors),
            "warnings": len(warns),
            "recommendedPath": cap.get("recommendedPath"),
        },
        "issues": issues,
        "environment": env,
        "config": cfg,
        "capabilities": cap,
        "data": data,
        "artifacts": arts,
    }


def format_human(report: dict) -> str:
    """人类可读渲染（按层分组，问题优先）。"""
    lines: list[str] = []
    s = report.get("summary") or {}
    lines.append(f"自检：{'通过' if s.get('ok') else '发现问题'}"
                 f"（error={s.get('errors', 0)}, warn={s.get('warnings', 0)}）")
    if s.get("recommendedPath"):
        lines.append(f"推荐路径：{s['recommendedPath']}")
    issues = report.get("issues") or []
    if issues:
        lines.append("")
        lines.append("问题：")
        for i in issues:
            mark = {"error": "✗", "warn": "⚠", "warning": "⚠", "info": "·"}.get(i.get("level"), "·")
            lines.append(f"  {mark} [{i.get('layer')}/{i.get('code')}] {i.get('message')}")
            if i.get("fix"):
                lines.append(f"      → {i['fix']}")
    env = report.get("environment") or {}
    lines.append("")
    lines.append(f"环境：python {env.get('python')} / engine {env.get('engineVersion')} / uv={env.get('uv')}")
    cfg = report.get("config") or {}
    if cfg.get("providers") is not None:
        lines.append(f"workspace：{cfg.get('workspace')}（存在={cfg.get('workspaceExists')}）")
        for p in cfg.get("providers") or []:
            lines.append(f"  provider {p['name']}: type={p['type']} key={p['hasKey']} "
                         f"cmd={p['cmd']} images={p['supportsImages']}")
        for stage, st in (cfg.get("stages") or {}).items():
            lines.append(f"  stage {stage}: provider={st.get('provider')} model={st.get('model')}")
    arts = report.get("artifacts") or {}
    if arts.get("reports"):
        lines.append("")
        lines.append("最近运行：")
        for r in arts["reports"]:
            lines.append(f"  {r['kind']}: {r['ok']}/{r['total']} 成功，{r['failed']} 失败 "
                         f"（{r['mtime']}）")
            for f in r.get("sampleFailures") or []:
                lines.append(f"    - {f.get('id')}: {str(f.get('error'))[:120]}")
    return "\n".join(lines)


def write_report(report: dict, path: "Path | str") -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    from .filelock import atomic_write_text
    atomic_write_text(p, json.dumps(report, ensure_ascii=False, indent=1))
    return p
