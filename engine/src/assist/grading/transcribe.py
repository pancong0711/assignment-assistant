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


def _escape_control_chars(text: str) -> str:
    """D162：把 JSON **字符串字面量内部**的裸控制字符（换行/制表/回车）转义。

    模型常直接把换行写进 JSON 字符串（`"第一行\\n第二行"` 写成真实换行），
    这会让 json.loads 报 `Invalid control character`。
    这里按"是否在字符串内"判断，逐字符转义；字符串外的结构字符不动。
    """
    out: list[str] = []
    in_str = False
    esc = False
    for ch in text:
        if esc:
            out.append(ch)
            esc = False
            continue
        if ch == "\\":
            out.append(ch)
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            continue
        if in_str and ch in ("\n", "\r", "\t"):
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
            continue
        if in_str and ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
            continue
        out.append(ch)
    return "".join(out)


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

    D166：**解析之后**统一过一遍 `_sanitize_latex`（把吃坏的命令还原）。
    这是最可靠的位置——此时双反斜杠已变单反斜杠，边界清晰，
    不会像在原始文本上猜那样误伤合法 `\\`（此前会让"守规矩的输出"更坏）。
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
        # D162：常见失败原因有两种，都要救：
        # ① LaTeX 反斜杠未转义（`\frac`）；
        # ② 字符串里出现**裸换行/制表符**（模型直接换行写进 JSON 字符串，非法）。
        # 顺序：**先救 LaTeX 反斜杠**（`\frac` 是"反斜杠+已知命令名"，判定可靠），
        # 再救**裸换行**（字符串里的真实换行）。
        # 反过来会把 `\frac` 当成"换页符"处理，再也救不回来。
        repaired = _fix_latex_in_json(body) if _looks_like_eaten_latex(body) else body
        cands = [repaired,
                 _escape_control_chars(repaired),
                 _escape_bare_backslashes(repaired),
                 _escape_control_chars(_escape_bare_backslashes(repaired))]
        for cand in cands:
            try:
                return _sanitize_latex(json.loads(cand))
            except json.JSONDecodeError:
                continue
        raise
    # 关键：`\f` 是**合法** JSON 转义，所以 json.loads 会"成功"，
    # 但内容已被改成换页符。原始文本里能看出来的，先修文本再解析；
    # 无论哪条路，最后都过 `_sanitize_latex`（D166：它是兜底，也是主力）。
    if _looks_like_eaten_latex(body):
        try:
            return _sanitize_latex(json.loads(_fix_latex_in_json(body)))
        except json.JSONDecodeError:
            pass
    return _sanitize_latex(data)


def _odd_backslash_positions(body: str) -> "set[int]":
    r"""返回 body 中**属于"单个未配对反斜杠"**的位置索引。

    判定：从左往右扫描，连续 k 个反斜杠时，第 1、3、5… 个（奇数位）是"未配对"的，
    第 2、4、6… 个是配对成 `\\`（JSON 的合法转义）。
    例：`\\frac`（2 个）→ 都不算未配对（模型守规矩）；
        `\,\t`（1 个 + 1 个）→ 两个都是未配对（模型偷懒）。
    """
    pos: set[int] = set()
    i = 0
    n = len(body)
    while i < n:
        if body[i] != "\\":
            i += 1
            continue
        j = i
        while j < n and body[j] == "\\":
            j += 1
        run = j - i
        for k in range(0, run, 2):      # 每对反斜杠的第一个 → 未配对的那个
            pos.add(i + k)
        i = j
    return pos


def _fix_latex_in_json(body: str) -> str:
    r"""把 JSON 文本里"会被误当转义"的 LaTeX 命令改写成 `\\命令`。

    例：`"\frac{1}{2}"` → `"\\frac{1}{2}"`（JSON 解析后得到字面 `\frac`）。
    只改**单个反斜杠**后被吃掉首字母的图案；`\\frac`（模型已按规范写双反斜杠）
    **绝对不动**——见 D166 修复（此前会把合法的 `\\` 也补成 `\\\`）。
    """
    odd = _odd_backslash_positions(body)

    def sub(m: "re.Match[str]") -> str:
        if m.start() not in odd:
            return m.group(0)           # 成对反斜杠：模型守规矩，不动
        return "\\\\" + m.group(1) + m.group(2)

    pat = re.compile(r"\\([fbtrn])(\s*(?:" + _LATEX_TAIL_PATTERN + r")[A-Za-z]*)")
    return pat.sub(sub, body)


# 已知 LaTeX 命令的"尾巴"（首字母被 JSON 转义吃掉后剩下的部分）。
# 顺序无关（已按长度倒序排：长尾巴在前，避免 ra 抢先匹配 rac）。
_LATEX_TAILS = ("rac", "orall", "lat", "eta", "ar", "heta", "an", "imes",
                "ho", "ightarrow", "abla", "ot", "im", "psilon", "elta",
                "ec", "ox", "ullet", "egin", "ecause")
_LATEX_TAIL_PATTERN = "|".join(sorted(_LATEX_TAILS, key=len, reverse=True))


# 首字母 → 该字母开头的已知 LaTeX 命令尾巴（用于把**已解析出**的字符串还原）。
# 例：控制符 \t 后面接 "imes" → 还原成 \times。
_LATEX_CMDS = {
    "f": ("rac", "orall", "lat", "lushleft", "lushright"),
    "b": ("eta", "ar", "ot", "ullet", "egin", "ecause", "oldsymbol", "inom", "oxed"),
    "t": ("imes", "heta", "au", "anh", "ext", "frac", "herefore", "op", "riangle",
          "ilde"),
    "n": ("abla", "ewline", "eq", "ot", "u"),
    "r": ("ho", "ightarrow", "ight", "angle", "ank", "m"),
    "v": ("arepsilon", "ec", "arphi", "artheta", "dots"),
}


def _eaten_patterns() -> "list[tuple[re.Pattern[str], str]]":
    """构造「坏形态 → 还原」正则表（D166 L3 后置净化用）。

    覆盖三种坏形态（都出现在**已解析出**的字符串里）：
      1. 双反斜杠 + 空白* + 尾巴    —— `_fix_latex_in_json` 过度修复的产物
      2. 控制符（\\f \\b \\t \\n \\r \\v）+ 空白* + 尾巴 —— 原样残留
      3. 反斜杠 + 控制符 + 空白* + 尾巴 —— 混合形态（反斜杠后紧跟被吃掉的字符）
      4. 反斜杠 + 字母（t/f/b/n/r/v 字面量）+ 空白* + 尾巴 —— L2 修复后残留的
         "已在 JSON 声明的转义"，解析成 Python 字符串后仍是 `\t` 两字符形态
    """
    out: "list[tuple[re.Pattern[str], str]]" = []
    for head, tails in _LATEX_CMDS.items():
        tail_alt = "|".join(sorted(tails, key=len, reverse=True))
        # 替换串必须写 `\\\\`（re.sub 里 `\\` 才是字面反斜杠）；
        # 直接写 `"\\" + head` 会被 re.sub 当成转义（`\f` → 换页符）——D166 踩过。
        repl_src = "\\\\" + head + r"\1"
        # 形态 1：双反斜杠 + 可选空白 + 尾巴 → 单反斜杠 + 首字母 + 尾巴
        out.append((re.compile(r"\\\\\s*(" + tail_alt + r")[A-Za-z]*"), repl_src))
        ctrl = {"f": "\x0c", "b": "\x08", "t": "\t", "n": "\n", "r": "\r",
                "v": "\x0b"}[head]
        # 形态 2：控制符 + 可选空白 + 尾巴
        out.append((re.compile(re.escape(ctrl) + r"\s*(" + tail_alt + r")[A-Za-z]*"),
                    repl_src))
        # 形态 3：反斜杠 + 控制符 + 空白* + 尾巴
        out.append((re.compile(r"\\" + re.escape(ctrl) + r"\s*(" + tail_alt + r")[A-Za-z]*"),
                    repl_src))
        # 形态 4：反斜杠 + 字面量字母 + **至少一个空白** + 尾巴。
        # 只修「字母与尾巴之间隔着空白」的形态（`\t        imes`）——
        # 紧贴着尾巴的（`\frac`）是**正确 LaTeX**，绝对不能动
        # （D166 调试踩过：加了 `\s*` 会把好的 `\frac` 改成 `\f rac`）。
        out.append((re.compile(r"\\" + head + r"\s+(" + tail_alt + r")[A-Za-z]*"),
                    repl_src))
    return out


_EATEN_PATTERNS: "list[tuple[re.Pattern[str], str]] | None" = None


def _sanitize_latex_text(text: str) -> str:
    """D166：对**已解析出的字符串**还原被吃坏的 LaTeX（最可靠的位置）。

    为什么放在解析之后：此时 JSON 的双反斜杠已变成单反斜杠，边界清晰，
    不需要猜原始 JSON 文本，也就不会像 `_fix_latex_in_json` 那样误伤合法 `\\`。

    **只还原「能对上已知 LaTeX 命令尾巴」的图案**，其余控制符/换行一律保留——
    因此真换行（`第一行\\n第二行`）、真缩进、普通英文都不会被改。
    """
    global _EATEN_PATTERNS
    if not isinstance(text, str) or not text:
        return text
    # 快速跳：明显干净的文本直接返回（避免无谓正则扫描）。
    # 注意：必须包含"反斜杠"本身——L2 修复后的形态是 `\t`+空白+`imes`（反斜杠+字母），
    # 既不含 TAB 也不含双反斜杠，只看控制符会漏掉（D166 调试踩过）。
    if "\\" not in text and not any(
            c in text for c in ("\x0c", "\x08", "\t", "\x0b", "\n", "\r")):
        return text
    if _EATEN_PATTERNS is None:
        _EATEN_PATTERNS = _eaten_patterns()
    out = text
    for pat, repl in _EATEN_PATTERNS:
        out = pat.sub(repl, out)
    return out


def _sanitize_latex(data):
    """递归净化解析结果里的所有字符串（dict/list/str 都处理）。"""
    if isinstance(data, str):
        return _sanitize_latex_text(data)
    if isinstance(data, list):
        return [_sanitize_latex(x) for x in data]
    if isinstance(data, dict):
        return {k: _sanitize_latex(v) for k, v in data.items()}
    return data


def _looks_like_eaten_latex(body: str) -> bool:
    """检测"LaTeX 命令被 JSON 转义吃掉首字母"的痕迹。

    例：模型写 `\frac`（JSON 文本里是反斜杠+f+r+a+c），json.loads 后
    变成 `\x0c` + `rac`。所以原始文本里会出现 `\frac` 这种
    "反斜杠 + 单个字母 + 已知 LaTeX 结尾"的组合。

    D166：**必须排除 `\\frac`（双反斜杠）**——那是模型按规范写出的正确形式，
    此前会把合法 `\\` 当成"被吃掉"再补一个，反而弄坏（见 docs/109 §1.2）。
    """
    _re = re
    return bool(_re.search(
        r"(?<!\\)\\[fbtrn](?:" + _LATEX_TAIL_PATTERN + r")", body))


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
