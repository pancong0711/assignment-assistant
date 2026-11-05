"""D98-B1：batch 统一输入契约（items）。

动机：Playground 批量、转录 batch、评阅 batch 各自构造请求，形态不一；  
本模块定义**唯一**的 item 结构并做校验，保证：

1. **每条自带** `question` 与 `images`，互不共享；
2. 构造该条请求时**只读本条字段**——绝不把其它条的题干/图片拼进来
   （`build_messages` 只接受单个 item，结构上杜绝跨条污染）；
3. 同一学生多页 → 一个 item 的 `images[]` 多张（同一次请求，裁决 1）。

item schema：
    {
      "id": "stu001",            # 必填、唯一、安全字符
      "question": "请转录…",      # 文字任务（可为空，若仅有图片）
      "images": ["a1.jpg", …],   # 可选；相对路径按 base_dir 解析
      "system": "可选覆盖默认 system",
      "model": "可选覆盖模型",
      "meta": {...}              # 可选，原样透传（如 student/tag），不进入 prompt
    }
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# D170-T1：id 白名单。
# 除了字母/数字/下划线/点，还允许**姓名里常见的分隔符**：
#   · (U+00B7 间隔号) —— 维吾尔族等民族姓名（阿丽古丽·玉苏甫）、俄式姓名（阿·谢·普希金）
#   • (U+2022 项目符号) / ・(U+30FB 片假名中点) —— 录入时可能被输入法替换
#   （）与全角括号 —— 少数名单会写成「张三（组长）」
# 这些字符**不含路径分隔符**，做文件名/报告键都安全。
_ID_RE = re.compile(r"^[0-9A-Za-z_\-\u4e00-\u9fff.\u00b7\u2022\u30fb\uff08\uff09()（）]{1,80}$")

# 常见但**仍不允许**的字符（用于给出可操作报错）
_BAD_CHARS_RE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


class ItemsError(ValueError):
    """items 输入非法（带可读错误，便于 CLI 直接提示）。"""


def _clean_id(raw, idx: int) -> str:
    """校验 id；报错必须**可操作**（教师要知道该改什么）。

    D170-T1 背景：`阿丽古丽·玉苏甫` 因间隔号被拒 → 整份名单批阅失败。
    现在间隔号已允许；其它非法字符会指出**具体是哪个字符、为什么不行**。
    """
    s = str(raw or "").strip()
    if not s:
        raise ItemsError(f"第 {idx + 1} 条缺少 id（该条没有题号或学生名）")
    if _ID_RE.match(s):
        return s
    bad = _BAD_CHARS_RE.findall(s)
    if bad:
        chars = "、".join(sorted({repr(c) for c in bad}))
        raise ItemsError(
            f"第 {idx + 1} 条 id 含**路径分隔符或控制字符**：{chars}（id={s!r}）。"
            f"这类字符会破坏文件名，请去掉后重试。")
    if len(s) > 80:
        raise ItemsError(
            f"第 {idx + 1} 条 id 过长（{len(s)} > 80 字符）：{s[:30]}…")
    raise ItemsError(
        f"第 {idx + 1} 条 id 含不支持的字符（id={s!r}）。"
        f"允许：中英文/数字/下划线/连字符/点/间隔号·，其余请替换。")


def normalize_items(raw, *, base_dir: "str | Path | None" = None) -> list[dict]:
    """校验并把路径解析为绝对路径；返回规范化 items。

    - 每条的 `images` 只解析本条，互不影响；
    - id 必须唯一（重复直接报错，避免报告错配）。
    """
    if isinstance(raw, dict) and "items" in raw:
        raw = raw.get("items")
    if not isinstance(raw, list) or not raw:
        raise ItemsError("items 必须是非空数组")
    base = Path(base_dir) if base_dir else None
    out: list[dict] = []
    seen: set[str] = set()
    for i, it in enumerate(raw):
        if not isinstance(it, dict):
            raise ItemsError(f"第 {i + 1} 条不是对象")
        iid = _clean_id(it.get("id"), i)
        if iid in seen:
            raise ItemsError(f"id 重复：{iid}")
        seen.add(iid)
        images: list[str] = []
        for p in (it.get("images") or []):
            pp = Path(str(p)).expanduser()
            if base is not None and not pp.is_absolute():
                pp = base / pp
            images.append(str(pp))
        out.append({
            "id": iid,
            "question": str(it.get("question") or ""),
            "images": images,
            "system": str(it.get("system") or ""),
            "model": str(it.get("model") or ""),
            "meta": it.get("meta") if isinstance(it.get("meta"), dict) else {},
        })
    return out


def build_messages(item: dict, *, default_system: str, user_text: str,
                   image_data_urls: "list[str] | None" = None) -> list[dict]:
    """**只基于单条 item** 构造 messages（结构性隔离：函数签名拿不到其它条）。

    - `user_text` 由调用方按任务类型生成（如转录固定指令 / 评阅题目+答案+转录）；
    - `image_data_urls` 是该条图片的 data-url（多模态）；纯文本任务传 None。
    """
    if not isinstance(item, dict) or "id" not in item:
        raise ItemsError("build_messages 需要单个已规范化 item")
    system = str(item.get("system") or default_system or "")
    if image_data_urls:
        content: list[dict] = [{"type": "text", "text": user_text}]
        for u in image_data_urls:
            content.append({"type": "image_url", "image_url": {"url": u}})
        user = content
    else:
        user = user_text
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": user})
    return msgs


def load_items_file(path: "str | Path", *, base_dir: "str | Path | None" = None) -> list[dict]:
    """读 JSON 文件（数组或 {items:[...]}）。图片相对路径按**文件所在目录**解析。"""
    p = Path(path).expanduser().resolve()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ItemsError(f"items 文件解析失败：{exc}") from exc
    return normalize_items(raw, base_dir=base_dir or p.parent)


def image_files(item: dict) -> list[Path]:
    """该条 item 的图片路径（过滤不存在的，供调用方告警）。"""
    return [Path(p) for p in (item.get("images") or []) if Path(p).is_file()]
