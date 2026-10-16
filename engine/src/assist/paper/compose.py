"""D93：按 tag 合成题目（summary / copy-page / translation）——引擎三端同源算法。

- summary：固定模板，每题纸自动 1 道（id=summary）；
- copy：题库行有 `page` 列 → 题干拼"请抄写：{page}页 {content}，并画出示意图。（{id}）"；
- translation：从 translation 题库**用 seed 确定性随机**抽 1 道（同一作业纸稳定；一次作业多纸同题靠共享 seed）。

与 PWA `app/src/lib/taskpad.ts` 的展开逻辑必须同算法（parity 哨兵护航）：
- `seed_index(seed, n)` 用**可移植**的确定性公式（不依赖语言 RNG），两端一致。
"""
from __future__ import annotations

SUMMARY_ID = "summary"
SUMMARY_CONTENT = ("请总结课堂内容。（提示：列出主要概念、定律，包括定义、公式、示意图，"
                   "指出概念之间的关系，如xx是xxx的前提条件、xx经求导积分可得到xxx等。）")
TRANSLATION_ID = "translation"
COPY_TEMPLATE = "请抄写：{page}页 {content}，并画出示意图。（{qid}）"

MAX_SEED = 2_147_483_647


def seed_index(seed: int, n: int) -> int:
    """可移植的确定性索引：seed ∈ [0, n)。与 PWA 同口径（纯整数运算）。

    用简单的 32 位 LCG 再取模，避免各语言 RNG 差异。
    """
    if n <= 0:
        return 0
    s = int(seed or 0) & 0xFFFFFFFF
    s = (1103515245 * s + 12345) & 0x7FFFFFFF
    return s % n


def copy_content(page, content, qid: str) -> str:
    """copy 题库条目有 page 时的题干改写（无 page 由调用方原样返回）。"""
    return COPY_TEMPLATE.format(page=page, content=str(content or ""), qid=str(qid or ""))


def pick_translation(entries: list[dict], seed: int) -> "dict | None":
    """从 translation 条目里用 seed 确定性地取一条（条目 content 已由 kb_io 合成）。"""
    if not entries:
        return None
    return entries[seed_index(seed, len(entries))]
