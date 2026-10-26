"""prompts.py — D108：AI 作答要求「提示词模板」库。

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
SUBDIR = "ai-solve"
MAX_TEXT_LEN = 2000
MAX_NAME_LEN = 60
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

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
            "1. 需要图示时，直接内联 <svg viewBox=\"0 0 200 150\" xmlns=\"http://www.w3.org/2000/svg\">；\n"
            "2. 只用 line/rect/circle/ellipse/polyline/polygon/path/text 基本图元；\n"
            "3. 黑白线稿（stroke=\"black\" fill=\"none\"），最多 20 个图元；\n"
            "4. 不要引用任何外部资源（禁止 <image>、href、外链 URL）；\n"
            "5. 公式仍用 LaTeX：行内 $...$、行间 $$...$$。"
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


def prompts_dir(ws) -> Path:
    d = Path(ws).resolve() / PROMPTS_DIR / SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(ws, pid: str) -> "Path | None":
    s = str(pid or "").strip()
    return prompts_dir(ws) / f"{s}.json" if _ID_RE.match(s) else None


def _seed_builtins(ws) -> None:
    """首次访问时把内置模板落盘（已存在的不覆盖，保留用户修改）。"""
    d = prompts_dir(ws)
    for tpl in BUILTIN:
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


def list_templates(ws) -> list[dict]:
    """列出全部模板（内置在前，按 default/name 排序）。"""
    _seed_builtins(ws)
    out: list[dict] = []
    for f in sorted(prompts_dir(ws).glob("*.json")):
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


def _clear_other_defaults(ws, keep_id: str) -> None:
    for f in prompts_dir(ws).glob("*.json"):
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


def default_template(ws) -> "dict | None":
    """返回默认模板；无 default 时返回内置 standard（或第一条）。"""
    items = list_templates(ws)
    for t in items:
        if t.get("default"):
            return t
    for t in items:
        if t.get("id") == "standard":
            return t
    return items[0] if items else None


def get_template(ws, pid: str) -> "dict | None":
    _seed_builtins(ws)          # 保证内置模板存在（首次访问即落盘）
    p = _path(ws, pid)
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
                  make_default: bool = False, overwrite_builtin_text: bool = True) -> dict:
    """新建或更新模板（含校验）。"""
    sid = str(pid or "").strip()
    if not _ID_RE.match(sid):
        return {"ok": False, "error": "模板 id 非法（1..64 位，字母数字开头，可含 _ . -）"}
    nm = str(name or "").strip()[:MAX_NAME_LEN]
    body = str(text or "").strip()
    if not body:
        return {"ok": False, "error": "模板内容为空"}
    if len(body) > MAX_TEXT_LEN:
        return {"ok": False, "error": f"模板内容过长（{len(body)} > {MAX_TEXT_LEN} 字）"}
    _seed_builtins(ws)
    p = _path(ws, sid)
    assert p is not None
    existing = get_template(ws, sid) or {}
    # 内置模板：允许改内容/名称、允许设默认，但不允许把 builtin 标记抹掉
    payload = {
        "id": sid,
        "name": nm or existing.get("name") or sid,
        "text": body,
        "default": bool(make_default or existing.get("default")),
        "builtin": bool(existing.get("builtin")),
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    from ..filelock import atomic_write_text
    atomic_write_text(p, json.dumps(payload, ensure_ascii=False, indent=1))
    if payload["default"]:
        _clear_other_defaults(ws, sid)
    return {"ok": True, "template": payload}


def delete_template(ws, pid: str) -> dict:
    """删除模板；内置模板不可删。"""
    tpl = get_template(ws, pid)
    if not tpl:
        return {"ok": False, "error": f"模板不存在：{pid}"}
    if tpl.get("builtin"):
        return {"ok": False, "error": f"内置模板不可删除（可复制为新模板后编辑）：{pid}"}
    p = _path(ws, pid)
    if not p:
        return {"ok": False, "error": "模板 id 非法"}
    was_default = bool(tpl.get("default"))
    p.unlink(missing_ok=True)
    if was_default:
        # 默认被删 → 回落到内置 standard
        std = get_template(ws, "standard")
        if std:
            save_template(ws, pid="standard", name=std.get("name") or "standard",
                          text=std.get("text") or "", make_default=True)
    return {"ok": True, "deleted": pid}


def set_default(ws, pid: str) -> dict:
    tpl = get_template(ws, pid)
    if not tpl:
        return {"ok": False, "error": f"模板不存在：{pid}"}
    p = _path(ws, pid)
    assert p is not None
    d = dict(tpl)
    d["default"] = True
    d["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    from ..filelock import atomic_write_text
    atomic_write_text(p, json.dumps(d, ensure_ascii=False, indent=1))
    _clear_other_defaults(ws, pid)
    return {"ok": True, "default": pid}


def requirement_text(ws, template_id: str = "", fallback: str = "") -> str:
    """取「实际用于 prompt 的要求文本」：模板 id 优先，其次 fallback（单次输入）。"""
    tid = str(template_id or "").strip()
    if tid:
        tpl = get_template(ws, tid)
        if tpl and str(tpl.get("text") or "").strip():
            return str(tpl["text"]).strip()
        logger.warning(f"提示词模板不存在或为空：{tid}（回退到单次输入）")
    return str(fallback or "").strip()
