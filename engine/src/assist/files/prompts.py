"""prompts.py — 提示词模板库（D151：扩展到 5 类 system prompt）。

存储：`<ws>/prompts/ai-solve/<id>.json`

设计要点：
- **CLI/AI 可复用**（放 workspace 而非浏览器 localStorage）；
- `default` 至多一个（写入时互斥，保证"默认模板"语义唯一）；
- 内置模板 `builtin: true`：**不可删除、不可改 id**，但可复制为新模板后编辑；
- 单模板长度上限 2000 字（提示词最终进 LLM，防误粘贴大段无关内容）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from loguru import logger

PROMPTS_DIR = "prompts"
DEFAULT_SUBDIR = "ai-solve"
# D151：5 类 system prompt + 原有的"作答要求"片段
# D168-B4：新增 `atopia-task`（Atopia 文档解析"任务模板"，docs/113-D169 §3.3）。
# 与其它 6 类的区别：它不是 system prompt，而是**一次完整的文档处理任务**，
# 额外带 `outputSchema`（期望的 JSON 结构）与 `inputKinds`（适用文档类型）。
CATEGORIES = ("ai-solve", "transcribe", "evaluate", "solve", "rubric", "termnorm",
              "atopia-task")
SUBDIR = DEFAULT_SUBDIR          # 兼容旧引用（= ai-solve）
MAX_TEXT_LEN = 2000
MAX_NAME_LEN = 60
# id 同时是 `<id>.json` 文件名：允许中文（与 grading/items.py 的 id 规则一致），
# 但禁止路径分隔符/空白/控制字符，且不得以 "." 开头（避免隐藏文件与 ".."）。
_ID_RE = re.compile(r"^[0-9A-Za-z_\u4e00-\u9fff][0-9A-Za-z_\-\u4e00-\u9fff.]{0,63}$")
ID_HINT = "模板 id 需为 1..64 位，以字母/数字/中文/下划线开头，可含 _ . -（不能含空格或路径分隔符）"

# 内置模板（首次访问时落盘；用户可复制但不可删）
BUILTIN: list[dict] = [
    {
        "id": "standard",
        "name": "标准完整解答（默认）",
        "text": (
            "请给出规范、完整的参考解答：\n"
            "1. 先简述物理过程与所用原理，再逐步推导，最后给出结论；\n"
            "2. 数学公式用 LaTeX：行内 $...$、行间 $$...$$；\n"
            "3. 计算题给出最终数值时注明单位与有效数字；\n"
            "4. 只输出解答正文，不要寒暄、不要重复题干。"
        ),
        "default": True,
    },
    {
        "id": "with-svg",
        "name": "含示意图（几何/受力题）",
        "text": (
            "在标准完整解答的基础上，**必须给出示意图**：\n"
            "1. 位置：**紧跟「受力分析 / 过程分析 / 几何关系」那一段之后**，"
            "让图与文字指代一致；**不要**统一堆到答案末尾；确有多个过程时可在各自段落就近配置；\n"
            "2. 写法：单行内联 <svg viewBox=\"0 0 200 150\" width=\"60mm\" height=\"45mm\" "
            "xmlns=\"http://www.w3.org/2000/svg\">…</svg>，并**另起一段**、前后各留一个空行；\n"
            "3. 只用 line/rect/circle/ellipse/polyline/polygon/path/text 基本图元；\n"
            "4. 黑白线稿（stroke=\"black\" fill=\"none\"），最多 20 个图元，"
            "文字标注用 <text x=… y=… font-size=\"10\">F</text>；\n"
            "5. 不要引用任何外部资源（禁止 <image>、href、外链 URL）；\n"
            "6. 公式仍用 LaTeX：行内 $...$、行间 $$...$$；图内不要写 LaTeX。"
        ),
        "default": False,
    },
    {
        "id": "html-doc",
        "name": "输出 HTML 文档",
        "text": (
            "请用 Markdown + 受支持的 HTML 片段输出解答：\n"
            "1. 可用：标题、表格、有序/无序列表、加粗、代码块、内联 <svg>、base64 内嵌图片；\n"
            "2. 公式用 LaTeX（行内 $...$、行间 $$...$$）；\n"
            "3. **禁止**输出 <script>、<style>、<iframe>、外链资源与任何事件属性；\n"
            "4. 结构建议：题意分析 → 解题步骤（可用表格）→ 最终结论。"
        ),
        "default": False,
    },
    {
        "id": "step-by-step",
        "name": "分步解析（教学向）",
        "text": (
            "请按教学需要分步解析，使用固定四段式：\n"
            "**已知**：列出已知量与隐含条件；\n"
            "**求**：明确所求物理量；\n"
            "**解**：逐步推导，每一步说明所用物理定律与其物理意义；\n"
            "**答**：给出最终结果（含单位与有效数字）。\n"
            "公式用 LaTeX：行内 $...$、行间 $$...$$。"
        ),
        "default": False,
    },
    {
        "id": "concise",
        "name": "精简答案（答案格空间有限）",
        "text": (
            "请给出精简答案：只保留关键步骤与最终结果，总长度控制在 300 字以内；\n"
            "不要展开讲解、不要重复题干；公式用 LaTeX：行内 $...$、行间 $$...$$。"
        ),
        "default": False,
    },
]


# ---------------- D151：5 类 system prompt 的内置默认 ----------------
# 这些文本**必须与代码里的原硬编码一致**（首次落盘后教师可改）。
BUILTIN_BY_CATEGORY: dict[str, list[dict]] = {
    "transcribe": [{
        "id": "standard",
        "name": "标准转录（内置）",
        "text": "",      # 空 = 用代码内置（见 prompts.TRANSCRIPTION_PROMPT）
        "default": True,
    }],
    "evaluate": [{
        "id": "standard",
        "name": "标准批阅（内置）",
        "text": "",
        "default": True,
    }],
    "solve": [{
        "id": "standard",
        "name": "标准作答（内置）",
        "text": "",
        "default": True,
    }],
    "rubric": [{
        "id": "standard",
        "name": "标准要点（内置）",
        "text": "",
        "default": True,
    }],
    "termnorm": [{
        "id": "standard",
        "name": "标准术语归一（内置）",
        "text": "",
        "default": True,
    }],
    # D168-B4：Atopia 文档解析任务（Three built-in tasks，见 docs/113-D169 §3.3）
    "atopia-task": [
        {
            "id": "knowledge-outline",
            "name": "知识点清单（授课计划/大纲/教材，默认）",
            "default": True,
            "inputKinds": ["plan", "ppt", "textbook", "note"],
            "outputSchema": {
                "knowledge": [
                    {"term": "知识点术语", "aliases": ["别名"],
                     "importance": "core|supporting",
                     "chapter": "章节/单元标签（可选）",
                     "topic": "章内主题（可选）",
                     "evidence": "文档中的依据（原文片段）"}
                ],
                "chapters": [{"name": "章节名", "summary": "一句话"}],
            },
            "text": (
                "你在整理**大学物理课程资料**（授课计划 / 教学大纲 / 教材）。\n"
                "请从给定文本中抽取**知识点清单**，供教师核对后写入课堂资料（会成为学科批阅依据）。\n\n"
                "【抽取原则】\n"
                "1. 只抽**物理概念/定律/方法**（如 库仑定律、电场强度、高斯定理）；\n"
                "   不要把「第3章」「课时安排」「教学目标」这类**课程管理信息**当知识点；\n"
                "2. 术语用**规范物理名词**，同义的写进 `aliases`（如 动量守恒 / 动量守恒定律）；\n"
                "3. `importance`：教材/大纲明确要求的核心内容 = core，其余 = supporting；\n"
                "4. `chapter` **可选**：文档里有明确章节/单元归属时才填（教师可能不需要章节层级）；\n"
                "5. `evidence` 必须**逐字引用**原文片段（不超过 40 字），不要自己编；\n"
                "6. 宁可少抽也不要编造：文本里没有的知识点**不要**写入。\n\n"
                "【输出格式（严格 JSON）】\n"
                '{"knowledge": [{"term": "...", "aliases": [], "importance": "core",\n'
                '               "chapter": "", "topic": "", "evidence": "..."}],\n'
                ' "chapters": [{"name": "...", "summary": "..."}]}\n\n'
                "只输出这个 JSON，不要任何解释文字。"
            ),
        },
        {
            "id": "chapter-tag",
            "name": "给已有知识点打章节标签",
            "inputKinds": ["plan", "ppt", "textbook", "note"],
            "outputSchema": {
                "tags": [{"term": "已有知识点", "chapter": "章节/单元",
                          "topic": "章内主题（可选）", "evidence": "依据"}],
            },
            "text": (
                "下面是**课程资料文本** 与 **一批已有关联知识点**。\n"
                "请判断每个知识点在资料中属于哪个**章节/单元**，输出**标签**。\n\n"
                "【原则】\n"
                "1. **不改写知识点名称**，原样返回 `term`；\n"
                "2. `chapter` 用资料里的原词（如「静电场」「恒定磁场」），不要自己造；\n"
                "3. 资料里找不到依据的知识点 → **不要输出**（不要猜）；\n"
                "4. `evidence` 逐字引用原文（≤40 字）。\n\n"
                "【输出格式（严格 JSON）】\n"
                '{"tags": [{"term": "...", "chapter": "...", "topic": "", "evidence": "..."}]}\n\n'
                "只输出这个 JSON。"
            ),
        },
        {
            "id": "example-extract",
            "name": "抽取例题（供标准共现图）",
            "inputKinds": ["textbook", "ppt", "note"],
            "outputSchema": {
                "examples": [{"content": "题干", "solution": "解答",
                              "knowledge": ["涉及知识点"], "source": "出处/页"}],
            },
            "text": (
                "请从**教材/课件文本**中抽取**例题**（含题解的那种）。\n\n"
                "【为什么抽例题】只有例题能反映「哪些知识点会一起出现」，\n"
                "这是画**标准知识点共现图**（反映授课结构）的唯一数据来源——\n"
                "大纲/授课计划只列清单，不产生共现。\n\n"
                "【原则】\n"
                "1. **只抽真正的例题**（有题干 + 有解答），不抽习题、不抽正文叙述；\n"
                "2. `content` 保留题干原意（可精简表达，但不要改数据/条件）；\n"
                "3. `solution` 可以整理成规范步骤，公式用 LaTeX（行内 $...$）；\n"
                "4. `knowledge` 列出该例题涉及的物理概念（2–6 个，规范名词）；\n"
                "5. `source` 标注出处（章节/页码/幻灯片号），便于教师核对。\n\n"
                "【输出格式（严格 JSON）】\n"
                '{"examples": [{"content": "...", "solution": "...",\n'
                '               "knowledge": ["..."], "source": "..."}]}\n\n'
                "只输出这个 JSON。"
            ),
        },
    ],
}


def builtins_for(category: str) -> list[dict]:
    """某类的内置模板（ai-solve 用原有 BUILTIN）。"""
    cat = str(category or DEFAULT_SUBDIR).strip()
    if cat == DEFAULT_SUBDIR:
        return BUILTIN
    return BUILTIN_BY_CATEGORY.get(cat, [{
        "id": "standard", "name": "标准（内置）", "text": "", "default": True,
    }])


def system_prompt(ws, category: str, fallback: str) -> str:
    """D151：取某类"生效的 system prompt"。

    - 有默认模板且其 `text` 非空 → 用模板文本；
    - 否则 → 用代码内置 `fallback`（**不选模板 = 现状**，向后兼容）。
    """
    cat = str(category or "").strip()
    if cat not in CATEGORIES:
        return fallback
    try:
        d = default_template(ws, cat)
    except Exception:  # noqa: BLE001
        return fallback
    text = str((d or {}).get("text") or "").strip()
    return text or fallback


def system_prompt_env(category: str, fallback: str) -> str:
    """D151：不知道 ws 时的取模板入口（用 `ASSIST_WORKSPACE` 环境变量）。

    供 transcribe / termnorm 这类没有 ws 参数的旧函数使用；取不到就用内置。
    """
    import os
    ws = os.environ.get("ASSIST_WORKSPACE")
    if not ws:
        return fallback
    try:
        return system_prompt(ws, category, fallback)
    except Exception:  # noqa: BLE001
        return fallback


def prompts_dir(ws, category: str = DEFAULT_SUBDIR) -> Path:
    """某类模板目录（D151：category ∈ CATEGORIES）。"""
    cat = str(category or DEFAULT_SUBDIR).strip()
    if cat not in CATEGORIES:
        cat = DEFAULT_SUBDIR
    d = Path(ws).resolve() / PROMPTS_DIR / cat
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(ws, pid: str, category: str = DEFAULT_SUBDIR) -> "Path | None":
    s = str(pid or "").strip()
    return prompts_dir(ws, category) / f"{s}.json" if _ID_RE.match(s) else None


def _seed_builtins(ws, category: str = DEFAULT_SUBDIR) -> None:
    """首次访问时把内置模板落盘（已存在的不覆盖，保留用户修改）。"""
    d = prompts_dir(ws, category)
    for tpl in builtins_for(category):
        p = d / f"{tpl['id']}.json"
        if p.exists():
            continue
        payload = {**tpl, "builtin": True,
                   "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            from ..filelock import atomic_write_text
            atomic_write_text(p, json.dumps(payload, ensure_ascii=False, indent=1))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"写入内置提示词模板失败 {tpl['id']}: {exc}")


def list_templates(ws, category: str = DEFAULT_SUBDIR) -> list[dict]:
    """列出某类模板（内置在前，按 default/name 排序）。"""
    _seed_builtins(ws, category)
    out: list[dict] = []
    for f in sorted(prompts_dir(ws, category).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(d, dict):
            continue
        d.setdefault("id", f.stem)
        d.setdefault("name", f.stem)
        d.setdefault("text", "")
        d["builtin"] = bool(d.get("builtin"))
        d["default"] = bool(d.get("default"))
        out.append(d)
    out.sort(key=lambda x: (not x.get("default"), not x.get("builtin"), str(x.get("name") or "")))
    return out


def _clear_other_defaults(ws, keep_id: str, category: str = DEFAULT_SUBDIR) -> None:
    for f in prompts_dir(ws, category).glob("*.json"):
        if f.stem == keep_id:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and d.get("default"):
            d["default"] = False
            from ..filelock import atomic_write_text
            atomic_write_text(f, json.dumps(d, ensure_ascii=False, indent=1))


def default_template(ws, category: str = DEFAULT_SUBDIR) -> "dict | None":
    """返回**该类**的默认模板；无 default 时返回内置 standard（或第一条）。"""
    items = list_templates(ws, category)
    for t in items:
        if t.get("default"):
            return t
    for t in items:
        if t.get("id") == "standard":
            return t
    return items[0] if items else None


def get_template(ws, pid: str, category: str = DEFAULT_SUBDIR) -> "dict | None":
    _seed_builtins(ws, category)     # 保证该类内置模板存在（首次访问即落盘）
    p = _path(ws, pid, category)
    if not p or not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if isinstance(d, dict):
        d.setdefault("id", p.stem)
        d["builtin"] = bool(d.get("builtin"))
        return d
    return None


def save_template(ws, *, pid: str, name: str, text: str,
                  make_default: bool = False, overwrite_builtin_text: bool = True,
                  category: str = DEFAULT_SUBDIR,
                  output_schema=None, input_kinds=None) -> dict:
    """新建或更新模板（含校验）。

    D168-B4：`output_schema` / `input_kinds` 仅 `atopia-task` 类使用
    （任务模板要声明"输出什么结构、适用哪些文档"）；其它类传了也忽略。
    """
    sid = str(pid or "").strip()
    if not sid:
        return {"ok": False, "error": f"缺少模板 id：{ID_HINT}"}
    if not _ID_RE.match(sid):
        return {"ok": False, "error": f"{ID_HINT}：{sid!r}"}
    nm = str(name or "").strip()[:MAX_NAME_LEN]
    body = str(text or "").strip()
    if not body:
        return {"ok": False, "error": "模板内容为空"}
    if len(body) > MAX_TEXT_LEN:
        return {"ok": False, "error": f"模板内容过长（{len(body)} > {MAX_TEXT_LEN} 字）"}
    _seed_builtins(ws, category)
    p = _path(ws, sid, category)
    assert p is not None
    existing = get_template(ws, sid, category) or {}
    # 内置模板：允许改内容/名称、允许设默认，但不允许把 builtin 标记抹掉
    payload = {
        "id": sid,
        "name": nm or existing.get("name") or sid,
        "text": body,
        "default": bool(make_default or existing.get("default")),
        "builtin": bool(existing.get("builtin")),
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    # D168-B4：`atopia-task` 类模板额外带 outputSchema / inputKinds，
    # 保存时必须**原样保留**（否则改一次提示词就把任务契约弄丢了）
    for k in ("outputSchema", "inputKinds"):
        if k in existing:
            payload[k] = existing[k]
    if category == "atopia-task":
        if output_schema is not None:
            payload["outputSchema"] = output_schema
        if input_kinds is not None:
            payload["inputKinds"] = [str(x) for x in input_kinds if str(x).strip()]
    from ..filelock import atomic_write_text
    atomic_write_text(p, json.dumps(payload, ensure_ascii=False, indent=1))
    if payload["default"]:
        _clear_other_defaults(ws, sid, category)
    return {"ok": True, "template": payload}


def delete_template(ws, pid: str, category: str = DEFAULT_SUBDIR) -> dict:
    """删除模板；内置模板不可删。"""
    sid = str(pid or "").strip()
    if not sid:
        return {"ok": False, "error": "缺少模板 id（未选中要删除的模板）"}
    if not _ID_RE.match(sid):
        return {"ok": False, "error": f"{ID_HINT}：{sid!r}"}
    tpl = get_template(ws, sid, category)
    if not tpl:
        return {"ok": False, "error": f"模板不存在：{sid}"}
    if tpl.get("builtin"):
        return {"ok": False, "error": f"内置模板不可删除（可「另存为新模板」后编辑）：{sid}"}
    p = _path(ws, sid, category)
    if not p:
        return {"ok": False, "error": f"{ID_HINT}：{sid!r}"}
    was_default = bool(tpl.get("default"))
    p.unlink(missing_ok=True)
    if was_default:
        # 默认被删 → 回落到内置 standard
        std = get_template(ws, "standard", category)
        if std:
            save_template(ws, pid="standard", name=std.get("name") or "standard",
                          text=std.get("text") or "", make_default=True,
                          category=category)
    return {"ok": True, "deleted": pid}


def set_default(ws, pid: str, category: str = DEFAULT_SUBDIR) -> dict:
    sid = str(pid or "").strip()
    if not sid:
        return {"ok": False, "error": "缺少模板 id（未选中要设为默认的模板）"}
    if not _ID_RE.match(sid):
        return {"ok": False, "error": f"{ID_HINT}：{sid!r}"}
    tpl = get_template(ws, sid, category)
    if not tpl:
        return {"ok": False, "error": f"模板不存在：{sid}"}
    p = _path(ws, sid, category)
    assert p is not None
    d = dict(tpl)
    d["default"] = True
    d["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    from ..filelock import atomic_write_text
    atomic_write_text(p, json.dumps(d, ensure_ascii=False, indent=1))
    _clear_other_defaults(ws, sid, category)
    return {"ok": True, "default": sid}


def requirement_text(ws, template_id: str = "", fallback: str = "") -> str:
    """取「实际用于 prompt 的要求文本」：模板 id 优先，其次 fallback（单次输入）。"""
    tid = str(template_id or "").strip()
    if tid:
        tpl = get_template(ws, tid)
        if tpl and str(tpl.get("text") or "").strip():
            return str(tpl["text"]).strip()
        logger.warning(f"提示词模板不存在或为空：{tid}（回退到单次输入）")
    return str(fallback or "").strip()
