"""transcribe.py — 多模态转录：学生作业图片 → Markdown/LaTeX。

迁移自 _legacy/2601playwright/src/llm/transcriber.py：
- TRANSCRIPTION_PROMPT 逐段原样迁移（含 Markdown/LaTeX 精度与 JSON 转义要求）；
- 保留"JSON 清洗 ```json 围栏"+"解析重试"逻辑；
- 分组规则升级：文件名 <学生名|学号>[-_题号].png（ assort CLI 从本地目录读）。
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path

from loguru import logger

from .llm import LLMClient

# ---- prompt：原样迁移自 _legacy/2601playwright/src/llm/transcriber.py ----
# D127：转写提示词的**唯一真源**在 prompts.TRANSCRIPTION_PROMPT（结构化 items[]）；
# 此处保留同名符号仅为向后兼容（旧代码 `from .transcribe import TRANSCRIPTION_PROMPT`）。
from .prompts import TRANSCRIPTION_PROMPT  # noqa: E402

TRANSCRIBE_USER_TEXT = ("请把这份物理作业图片转录为结构化 JSON："
                        "逐题分开「题目 / 作答」，示意图只做语义描述，不要画图。")

# 转录解析重试（迁移旧 transcriber 的 5 次尝试逻辑，收敛为 3 次即可）
_TRANSCRIBE_ATTEMPTS = 3


def parse_llm_json(raw: str) -> dict:
    """清洗 ```json 围栏并解析（迁移自 transcriber._cleaned 逻辑）。"""
    cleaned = raw.strip()
    for p in ("```json", "```"):
        if cleaned.startswith(p):
            cleaned = cleaned[len(p):]
        if cleaned.endswith(p):
            cleaned = cleaned[:-len(p)]
    return json.loads(cleaned.strip())


def student_from_filename(fn: Path) -> str:
    """文件名 → 学生名：`姓名.png` / `学号-题号.png` / `姓名-1.png`。"""
    stem = fn.stem
    return re.split(r"[-_]", stem, maxsplit=1)[0] or "unknown"


def group_images(images_dir: Path) -> dict[str, list[Path]]:
    """把目录里的图片按学生名分组（文件名前缀相同即同一学生）。

    D118：目录不存在时返回空字典（此前直接 iterdir() 会抛 FileNotFoundError；
    Windows 上教师没放图片就会看到 WinError 3「系统找不到指定的路径 ...images」）。
    是否"该报错"由调用方决定（缺图片应是可读提示，而非异常堆栈）。
    """
    exts = (".png", ".jpg", ".jpeg", ".webp")
    groups: dict[str, list[Path]] = defaultdict(list)
    d = Path(images_dir)
    if not d.is_dir():
        logger.warning(f"图片目录不存在，按空处理：{d}")
        return {}
    for f in sorted(d.iterdir()):
        if f.is_file() and f.suffix.lower() in exts:
            groups[student_from_filename(f)].append(f)
    return dict(groups)


def _system_prompt() -> str:
    """D106：按开关返回转录 prompt（SVG 重绘默认关）。

    开关来源（优先级）：环境变量 ASSIST_SVG_REDRAW=1 > 默认关。
    PWA 端的设置项最终写为环境变量/请求参数由 serve 层注入。
    """
    import os
    try:
        from .prompts import transcription_prompt
        on = str(os.environ.get("ASSIST_SVG_REDRAW") or "0") not in ("0", "", "false", "False")
        return transcription_prompt(svg_redraw=on)
    except Exception:  # noqa: BLE001
        return TRANSCRIPTION_PROMPT


# D127：转写产物结构版本。2 = items[]（题目/作答分开）；1 = 旧版一坨 markdown。
TRANS_VERSION = 2


def _engine_version() -> str:
    try:
        from .. import __version__ as _v
        return f"assist-engine {_v}"
    except Exception:  # noqa: BLE001
        return "assist-engine"


def is_structured(data: "dict | None") -> bool:
    """D127：是否为结构化转写（items[] 非空）。旧版只有 markdown。"""
    if not isinstance(data, dict):
        return False
    items = data.get("items")
    return isinstance(items, list) and any(isinstance(x, dict) for x in items)


def transcript_to_markdown(data: "dict | None") -> str:
    """把结构化转写渲染成 markdown（题目/作答/示意图分开）。

    D127 兼容：若无 items[] 但已有旧版 markdown，则原样返回（供报告复用；
    评阅/报告入口会另行提示"请重新转写"，此处不做静默降级判断）。
    """
    if not isinstance(data, dict):
        return ""
    items = data.get("items")
    if not (isinstance(items, list) and items):
        return str(data.get("markdown") or "")
    out: list[str] = []
    for i, it in enumerate(items, start=1):
        if not isinstance(it, dict):
            continue
        no = str(it.get("no") or i).strip() or str(i)
        q = str(it.get("printed_question") or "").strip()
        a = str(it.get("answer") or "").strip()
        out.append(f"### 第 {no} 题")
        out.append("")
        out.append(f"**题目：** {q if q else '（作业纸上未识别到印刷题干）'}")
        out.append("")
        out.append("**作答：**")
        out.append(a if a else "（未识别到作答内容）")
        for dg in (it.get("diagrams") or []):
            if not isinstance(dg, dict):
                continue
            kind = str(dg.get("kind") or "示意图").strip()
            desc = str(dg.get("description") or "").strip()
            if desc:
                out.append("")
                out.append(f"**{kind}：** {desc}")
        out.append("")
    tail = str(data.get("unmatched_notes") or "").strip()
    if tail:
        out += ["---", "", "**其他页面内容：**", tail, ""]
    return "\n".join(out).strip()


def transcribe_student(client: LLMClient, images: list[Path], student: str,
                       out_dir: Path, model: str | None = None) -> Path:
    """转录单个学生的一组图片 → transcripts/<student>.json（含 v1 版本号）。"""
    last_err: Exception | None = None
    for attempt in range(_TRANSCRIBE_ATTEMPTS):
        try:
            raw = client.chat_with_images(
                system_prompt=_system_prompt(),
                user_text=TRANSCRIBE_USER_TEXT,
                image_paths=[str(p) for p in images],
                model=model, temperature=0.1, step="transcription",
            )
            data = parse_llm_json(raw)
            break
        except Exception as e:  # noqa: BLE001 —— 沿用旧版"转录失败重试再判断"语义
            last_err = e
            if attempt < _TRANSCRIBE_ATTEMPTS - 1:
                logger.warning(f"转录[{student}] 第{attempt+1}次尝试失败: {e}")
                time.sleep(1)
    else:
        raise RuntimeError(f"转录失败[{student}]（重试{_TRANSCRIBE_ATTEMPTS}次）：{last_err}")

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{student}.json"
    # D106：记录每张图的压缩元数据（原图未修改；便于对比转录效果/排查）
    image_info = list(getattr(client, "last_image_meta", []) or [])
    data.update({
        "student": student,
        "model": model or client.transcription_model,
        "images": [p.name for p in images],
        "image_info": image_info,
        "version": _engine_version(),
        "_trans_version": TRANS_VERSION,
        "timestamp": time.strftime("%Y-%m-%d %H:%M"),
    })
    # 姓名一致性预警（迁移自 transcriber._name_match）
    markdown_text = data.get("markdown", "") or ""
    data["_name_match"] = student in markdown_text
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if not data["_name_match"]:
        logger.warning(f"转录内容中未检测到学生姓名 '{student}'，请人工复核")
    return out


# ---------------- D98-B4：转录 batch（items 模式） ----------------

def transcribe_item(client: LLMClient, item: dict, out_dir: Path,
                    model: str | None = None) -> dict:
    """转录**单个 item**（一名学生，多页在 item.images 内）→ 写 transcripts/<id>.json。

    返回 {ok, out, student, nameMatch, error?}；单条失败不抛（由 batchrun 收集）。
    """
    from .items import image_files
    student = str(item.get("id"))
    try:
        imgs = image_files(item)
        if not imgs:
            return {"ok": False, "student": student, "error": "无可用图片",
                    "images": list(item.get("images") or [])}
        path = transcribe_student(client, imgs, student, Path(out_dir), model=model)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {"ok": True, "out": str(path), "student": student,
                "nameMatch": bool(data.get("_name_match")),
                "pages": len(imgs)}
    except Exception as exc:  # noqa: BLE001 —— 单条失败标记，继续其余
        return {"ok": False, "student": student,
                "error": f"{exc.__class__.__name__}: {str(exc)[:300]}",
                "images": [str(p) for p in (item.get("images") or [])]}


def transcribe_batch(client: LLMClient, items: list[dict], out_dir: Path, *,
                     model: str | None = None, concurrency: int = 3,
                     emit=None) -> dict:
    """转录 batch：items 逐条独立请求（结构性隔离）+ 并发 + 执行报告。"""
    from .batchrun import run_items
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return run_items(
        items,
        lambda it: transcribe_item(client, it, out_dir, model=model),
        kind="transcribe", concurrency=concurrency, out_dir=out_dir.parent,
        emit=emit)
