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


# D148：模型经常把 LaTeX 直接写进 JSON 字符串（`"\frac{1}{2}"`）。
# 问题在于 `\f` `\t` `\b` `\n` `\r` 恰好都是**合法 JSON 转义**，
# 于是 json.loads 会"成功"但把 `\frac` 变成「换页符 + rac」——
# 这就是预览里出现特殊字符的根因。
_FP = "\x0c"     # 换页符：\frac / \forall / \flat 被吃掉后的残留
_BS = "\x08"     # 退格符：\beta / \bar 被吃掉后的残留


def _repair_latex_escapes(body: str) -> str:
    """把"看起来被吃掉的 LaTeX 命令"补回反转义形式。

    只修**正常文本里几乎不可能出现**的控制字符（换页符/退格符）——
    它们恰恰是 `\frac` `\beta` 被 JSON 转义后的产物，因此判定很可靠。
    """
    return body.replace(_FP, r"\\f").replace(_BS, r"\\b")


def _escape_bare_backslashes(text: str) -> str:
    r"""把**未被转义**的反斜杠补成双反斜杠，使 JSON 合法。

    合法转义（`\"` `\\` `\/` `\b` `\f` `\n` `\r` `\t` `\uXXXX`）原样保留；
    其余（如裸的 `\frac`）补成 `\\`。
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = text[i + 1] if i + 1 < n else ""
        if nxt in ('"', "\\", "/") or nxt in ("b", "f", "n", "r", "t"):
            out.append(ch + nxt)
            i += 2
        elif nxt == "u" and i + 5 < n:
            out.append(text[i:i + 6])
            i += 6
        else:
            out.append("\\\\")
            i += 1
    return "".join(out)


def parse_llm_json(raw: str) -> dict:
    """清洗 ```json 围栏并解析（迁移自 transcriber._cleaned 逻辑）。

    D148：模型常把 LaTeX 直接写进 JSON，导致两种坏情况：
    1. **能解析但内容被改坏**：`\frac` → 换页符 + `rac`；
    2. **不能解析**：出现裸反斜杠。
    这里先正常解析；失败时做一次"转义修复"重试；成功但含控制字符时也用修复版。
    """
    cleaned = raw.strip()
    for p in ("```json", "```"):
        if cleaned.startswith(p):
            cleaned = cleaned[len(p):]
        if cleaned.endswith(p):
            cleaned = cleaned[:-len(p)]
    body = cleaned.strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        repaired = _repair_latex_escapes(body)
        for cand in (repaired, _escape_bare_backslashes(repaired)):
            try:
                return json.loads(cand)
            except json.JSONDecodeError:
                continue
        raise
    # 关键：`\f` 是**合法** JSON 转义，所以 json.loads 会"成功"，
    # 但内容已被改成换页符。必须**在原始文本里**查这种"可疑的 LaTeX 前导"，
    # 例如 `\frac` `\beta` `\times` `\rho`（都紧跟在一个被吃掉的首字母上）。
    if _looks_like_eaten_latex(body):
        try:
            return json.loads(_fix_latex_in_json(body))
        except json.JSONDecodeError:
            return data
    return data


def _fix_latex_in_json(body: str) -> str:
    r"""把 JSON 文本里"会被误当转义"的 LaTeX 命令改写成 `\命令`。

    例：`"rac{1}{2}"` → `"\frac{1}{2}"`（JSON 解析后得到字面 `rac`）。
    只有 `  	 
 
` 后面**紧跟已知 LaTeX 结尾**时才改，
    避免把真正的换行/制表符改坏。
    """
    import re as _re
    tails = "rac|orall|lat|eta|ar|heta|an|imes|ho|ightarrow|abla|ot|im|elta|u|psilon"
    pat = _re.compile(r'\\([fbtrn])((?:' + tails + r')[A-Za-z]*)')
    return pat.sub(lambda m: "\\\\" + m.group(1) + m.group(2), body)


_LATEX_TAILS = ("rac", "orall", "lat", "eta", "ar", "heta", "an", "imes",
                "ho", "ightarrow", "abla", "u", "ot", "im", "psilon", "elta")


def _looks_like_eaten_latex(body: str) -> bool:
    """检测"LaTeX 命令被 JSON 转义吃掉首字母"的痕迹。

    例：模型写 `\frac`（JSON 文本里是反斜杠+f+r+a+c），json.loads 后
    变成 `\x0c` + `rac`。所以原始文本里会出现 `\frac` 这种
    "反斜杠 + 单个字母 + 已知 LaTeX 结尾"的组合。
    """
    import re as _re
    return bool(_re.search(r"\\[fbtrn](rac|eta|heta|imes|ho|abla|ot|elta|orall|lat)", body))


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
        base = transcription_prompt(svg_redraw=on)
        # D151：转录 system prompt 可被模板覆盖（不选模板 = 内置）
        from ..files.prompts import system_prompt_env
        return system_prompt_env("transcribe", base)
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
    # D160：先用 json_schema 强制结构化；不支持则逐级回退。
    # 顺序：json_schema → json_object → 纯提示词。每级失败都换下一级重试。
    from .prompts import TRANSCRIPTION_SCHEMA, validate_transcription
    _formats: "list[dict | None]" = [TRANSCRIPTION_SCHEMA,
                                     {"type": "json_object"},
                                     None]
    _fi = 0
    for attempt in range(_TRANSCRIBE_ATTEMPTS):
        try:
            raw = client.chat_with_images(
                system_prompt=_system_prompt(),
                user_text=TRANSCRIBE_USER_TEXT,
                image_paths=[str(p) for p in images],
                model=model, temperature=0.1, step="transcription",
                response_format=_formats[min(_fi, len(_formats) - 1)],
            )
            data = parse_llm_json(raw)
            # D160：结构校验——不合格就当失败，换下一档重试（不写半成品）
            errs = validate_transcription(data)
            if errs:
                raise RuntimeError("转写结构不合格：" + "；".join(errs[:4]))
            break
        except Exception as e:  # noqa: BLE001 —— 沿用旧版"转录失败重试再判断"语义
            last_err = e
            msg = str(e).lower()
            # provider 不支持该 response_format → 降一档（不要在同一档反复重试）
            if _fi < len(_formats) - 1 and ("schema" in msg or "response_format" in msg
                                            or "unsupported" in msg or "400" in msg):
                _fi += 1
                logger.warning(f"转录[{student}] 不支持当前输出格式，降级到第 {_fi + 1} 档：{e}")
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
