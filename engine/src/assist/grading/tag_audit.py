"""tag_audit.py — D172：tag 审计（纯 Python，**不调用任何模型**）。

## 教师需求（docs/117-D172）

> 将每个学生的作答内容转写后的**题目提取出来**，和**作业包里的题目**进行对比，找出**实际 tag**。
> ……tag 审核列于 tag 列值不同的行需突出，方便教师检查。
> 转写部分已完成，已经有题目内容了，**应该不需要 AI**，可通过编程完成，是不是？  → 是。

## 为什么纯编程够用

1. 转写结果已是结构化 JSON：`items[].printed_question` 就是**印在学生纸上的题干**，
   转写阶段已经把它和 `answer` 分开（`prompts.TRANSCRIPTION_PROMPT`「题目与作答必须分开」）；
2. 候选集只有**当前作业包内**的 2–6 张作业纸（教师 D2：不做跨包）→ 这是**选择题**，不是开放检索；
3. 同一包内不同层的题目，真正的差别落在**数值常量与条件**上（同章不同参数），
   字面 n-gram + 数值重合比语义向量更准（向量容易把「动量守恒」和「能量守恒」判近）。

因此本模块**无模型依赖、离线可用、同输入必得同输出**（验收红线，docs/117-D172 §9）。

## 算法（三个阶段）

阶段 A 抽题块
    对每份转写：
      - 优先用 `items[]` 的 `printed_question`；
      - 空 → 退回旧版 `markdown` 按题号锚点切块，再按「解：/由…得/=」切成题干段/作答段；
      - 仍空 → 该题块记 `linkMissing`（标 `?`），**不参与分母**。

阶段 B 打分（字符 n-gram + 数值常量）
    两侧同口径去噪 → `bigram = 2/3-gram Dice`，`number = 数值常量重合率`；
    `S = bigramWeight * bigram + numberWeight * number`（权重见规则卡 `tagAudit`）。

阶段 C 判定（**无 LLM 兜底**）
    题块 × 候选题做**背靠背最优分配**（DFS 分支定界，题数很少）：
      作业纸得分 = 已分配题目的 S 均值 / 覆盖率；
    三档：
      high    —— S >= minScore 且 margin >= marginMin
      medium  —— 有明确 Top1 但差距不够
      low     —— 有候选但分数低
      unknown —— 全部题块都 `linkMissing`，或没有候选题
    `match` = auditTag == rosterTag（rosterTag 为 None → `unknown`，不硬说 match/mismatch）。

## 口径约定（与 docs/112-D168 同精神）

- **`unknown` 绝不写 0 分、绝不写 match**；必须给出可读 `reason`；
- **未转写 ≠ unknown**：未转写单独记 `skippedNotTranscribed`（教师 N2：未转写不可审核）；
- 审计**只比对题干**，不看作答对错，不读 `errors`；
- 产物是**证据**（`audit/tags-audit.json`），**不是权威**；改 tag 必须教师确认后由
  `snapshots` 打补丁（`source=audit-apply`），见 `apply_audit_tags()`。

## 产物

    classes/<班>/grading/<packId>/audit/tags-audit.json     唯一真源（前端只读这个）
    classes/<班>/roster-tags/_history/<packId>__<ts>.json   应用前自动存的历史副本（撤销用）
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

from loguru import logger

ENGINE_VER = "ngram-v1"

# ---------------- 默认参数（规则卡 `tagAudit` 可覆盖，见 rules.tag_audit_cfg） ----------------
DEFAULTS = {
    "minScore": 0.75,        # 高置信下限
    "marginMin": 0.15,       # Top1 与 Top2 的最小差（高置信要求）
    "mediumScore": 0.45,     # 低于此 → low
    "bigramWeight": 0.65,    # 字面 n-gram 权重
    "numberWeight": 0.35,    # 数值常量权重
    "minChars": 12,          # 题干太短（去噪后）视为「没抄题」
}

# 正则：LaTeX 命令（保留其内容）、上下标、圈画/涂改符、常见题干停用词
_RE_LATEX_CMD = re.compile(r"\\[a-zA-Z]+")
_RE_DOLLAR = re.compile(r"\$+")
_RE_BRACES = re.compile(r"[{}^_~]")
# OCR 常把圈画/下划线/方框识别成这些符号 → 学生侧额外忽略
_RE_MARKUP = re.compile(r"[□■▢◻◼△▲▽▼•·⁃‣◦*※↓↑←→⤴⤵]|[_=]{2,}")
_RE_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_STEM_STOP = ("如图", "已知", "试求", "求：", "（本小题满分", "(本小题满分", "如图所示")


def _cfg(overrides: "dict | None" = None) -> dict:
    out = dict(DEFAULTS)
    for k, v in (overrides or {}).items():
        if k in out and v is not None:
            try:
                out[k] = type(out[k])(v)
            except (TypeError, ValueError):
                logger.debug(f"[tag-audit] 忽略非法规则值 {k}={v!r}")
    return out


# ---------------- 阶段 A：抽题块 ----------------

def _items_of(transcript: dict) -> list[dict]:
    """转写 → [{no, stem}]（只取题干；无题干记空串）。"""
    out: list[dict] = []
    items = (transcript or {}).get("items")
    if isinstance(items, list) and items:
        for i, it in enumerate(items, start=1):
            if not isinstance(it, dict):
                continue
            stem = str(it.get("printed_question") or "").strip()
            if not stem:
                # 学生把题干抄进了作答区（self-made sheet）→ 没法可靠分离，记空
                stem = ""
            out.append({"no": str(it.get("no") or i), "stem": stem,
                        "used_items": True})
        return out
    # 旧版 v1：只有 markdown → 按题号锚点切块
    md = str((transcript or {}).get("markdown") or "")
    return _split_markdown(md)


_RE_QNUM = re.compile(r"(?m)^\s*(?:#{1,6}\s*)?(?:第\s*)?(\d{1,2})\s*(?:题|[.．、)])\s*")


def _split_markdown(md: str) -> list[dict]:
    """旧版 markdown → 题块（题干段取题号后到第一处「解/答/由/=」之前）。"""
    if not md.strip():
        return []
    hits = list(_RE_QNUM.finditer(md))
    out: list[dict] = []
    for k, m in enumerate(hits):
        end = hits[k + 1].start() if k + 1 < len(hits) else len(md)
        block = md[m.end():end]
        # 题干段：截到第一个「作答特征」之前
        cut = len(block)
        for pat in (r"(?m)^\s*\*\*解", r"(?m)^\s*解[:：]", r"(?m)^\s*答[:：]",
                    r"(?m)^\s*\*\*作答", r"(?m)^\s*由.{0,20}得", r"(?m)^\s*\\\["):
            mm = re.search(pat, block)
            if mm:
                cut = min(cut, mm.start())
        stem = block[:cut].strip()
        out.append({"no": str(m.group(1)), "stem": stem, "used_items": False})
    return out


# ---------------- 阶段 B：归一 + 打分 ----------------

def normalize_text(text: str, *, student: bool = False) -> str:
    """两侧同口径归一：去 LaTeX 命令但留内容、去 $ 与上下标、统一标点空白。

    `student=True` 时额外去掉圈画/下划线/涂改符（OCR 噪声的主要来源）。
    """
    t = str(text or "")
    t = _RE_LATEX_CMD.sub(" ", t)      # \frac、\times 等命令名去掉，保留 a b 内容
    t = _RE_DOLLAR.sub(" ", t)
    t = _RE_BRACES.sub(" ", t)
    if student:
        t = _RE_MARKUP.sub(" ", t)
    for w in _STEM_STOP:
        t = t.replace(w, " ")
    # 统一全角标点/空白
    t = t.replace("，", ",").replace("。", ".").replace("；", ";").replace("：", ":")
    t = re.sub(r"[^\w\u4e00-\u9fff.%+]", " ", t)   # 去标点（数字/单位保留）
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def grams(text: str, n: int) -> dict[str, int]:
    """字符 n-gram 多重集（中文不需要分词）。"""
    s = text.replace(" ", "")
    if len(s) < n:
        return {s: 1} if s else {}
    out: dict[str, int] = {}
    for i in range(len(s) - n + 1):
        g = s[i:i + n]
        out[g] = out.get(g, 0) + 1
    return out


def dice(a: dict[str, int], b: dict[str, int]) -> float:
    """多重集 Dice 系数 = 2|A∩B| / (|A|+|B|)。"""
    if not a or not b:
        return 0.0
    inter = 0
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    for g, c in small.items():
        c2 = big.get(g)
        if c2:
            inter += min(c, c2)
    return 2.0 * inter / (sum(a.values()) + sum(b.values()))


def numbers_of(text: str) -> set[str]:
    """题干里的数值常量（含小数；忽略纯 1 位数题号噪声）。"""
    out = set()
    for m in _RE_NUMBER.finditer(text or ""):
        v = m.group(0)
        if len(v.replace(".", "")) >= 1:
            out.add(v)
    return out


def number_overlap(a: set[str], b: set[str]) -> float:
    """数值重合率；两侧都没数字 → 视为「无信息」返回 1.0（不惩罚纯文字题）。"""
    if not a and not b:
        return 1.0
    if not a or not b:
        # 一侧有数字一侧没有：多半是 OCR 把数字弄丢了 → 给中性偏低分
        return 0.3
    return len(a & b) / len(a | b)


def score_pair(student_stem: str, paper_stem: str, cfg: "dict | None" = None) -> float:
    """单个题块 vs 单张作业纸某题的相似度 S ∈ [0,1]。"""
    c = cfg or DEFAULTS
    a = normalize_text(student_stem, student=True)
    b = normalize_text(paper_stem, student=False)
    if not a or not b:
        return 0.0
    g2 = max(dice(grams(a, 2), grams(b, 2)), dice(grams(a, 3), grams(b, 3)))
    nov = number_overlap(numbers_of(a), numbers_of(b))
    w1, w2 = float(c["bigramWeight"]), float(c["numberWeight"])
    tot = (w1 + w2) or 1.0
    return max(0.0, min(1.0, (w1 * g2 + w2 * nov) / tot))


# ---------------- 阶段 C：背靠背最优分配 ----------------

def best_assignment(student_stems: list[str], paper_stems: list[str],
                    cfg: "dict | None" = None) -> tuple[float, list[tuple[int, int, float]]]:
    """题块 → 候选题的**背靠背**最优分配（DFS 分支定界；题数很小）。

    返回 (平均分, [(题块i, 候选题j, S)])。题块多于候选题时，多出的记 0（计入均值，
    表示「这张卷子做不完这些题」——这也是区分层级的信号）。
    题块可多于也可少于候选题；**不允许**两个题块抢同一候选题。
    """
    c = cfg or DEFAULTS
    n, m = len(student_stems), len(paper_stems)
    if n == 0 or m == 0:
        return 0.0, []
    S = [[score_pair(student_stems[i], paper_stems[j], c) for j in range(m)] for i in range(n)]
    best = {"val": -1.0, "pairs": []}

    # 上界：每题块取该行最大值（忽略冲突）→ 剪枝用
    row_max = [max(r) for r in S]
    order = sorted(range(n), key=lambda i: -row_max[i])

    def dfs(k: int, used: set[int], acc: float, pairs: list[tuple[int, int, float]]) -> None:
        if acc + sum(row_max[i] for i in order[k:]) <= best["val"] + 1e-9:
            return
        if k == n:
            val = acc / n
            if val > best["val"]:
                best["val"] = val
                best["pairs"] = list(pairs)
            return
        i = order[k]
        # 允许该题块「不配对」（S=0），保证总能完成搜索
        dfs(k + 1, used, acc, pairs)
        for j in range(m):
            if j in used:
                continue
            used.add(j)
            pairs.append((i, j, S[i][j]))
            dfs(k + 1, used, acc + S[i][j], pairs)
            pairs.pop()
            used.remove(j)

    dfs(0, set(), 0.0, [])
    return max(best["val"], 0.0), sorted(best["pairs"])


# ---------------- 面向流程的入口 ----------------

def papers_from_taskpads(ws, taskpads: list[dict]) -> list[dict]:
    """**taskpad 原样 → 作业纸题目**（从题库 `kb/` 解析题干）。

    为什么必须这么做（D172 实测 bug）：`taskpad.items[]` 只存
    `{kb, chap, ids, tag, labels}`，**不含题干**！此前 PWA/CLI 把 taskpad 直接当
    「questions」传进来，读 `content` 永远拿不到 → 每张纸都是空题 → 审计全班
    `unknown`。题干只在题库里，必须经 `paper.task.resolve_items_with_ids` 展开。

    返回 [{padId, tag, questions:[{no, qid, stem}]}]
    """
    from ..files.kb_io import read_kb
    from ..paper.task import resolve_items_with_ids
    kb_dir = Path(ws) / "kb"
    try:
        kb_data = read_kb(kb_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[tag-audit] 读题库失败：{str(exc)[:120]}")
        return []
    out: list[dict] = []
    for pad in taskpads or []:
        if not isinstance(pad, dict):
            continue
        items = pad.get("items")
        if not isinstance(items, list):
            continue
        tag = str(pad.get("target_tag") or "")
        try:
            rows = resolve_items_with_ids(kb_data, items, kb_dir,
                                          numbering=str(pad.get("numbering") or "auto"),
                                          seed=pad.get("seed"),
                                          target_tag=tag)
        except Exception as exc:  # noqa: BLE001 —— 单张失败不影响其余
            logger.warning(f"[tag-audit] 解析作业纸 {pad.get('id')!r} 失败：{str(exc)[:120]}")
            rows = []
        qs = []
        for (content, _img, _tag, no, qid) in rows:
            qs.append({"no": str(no or ""), "qid": str(qid or ""),
                       "stem": str(content or "")})
        out.append({"padId": str(pad.get("id") or ""), "tag": tag, "questions": qs})
    return out


def papers_of(pads: list[dict]) -> list[dict]:
    """作业纸 → [{padId, tag, questions:[{no, stem}]}]（保持包内顺序）。

    **幂等**：接受两种形状——`questions[].content`（引擎/CLI 归一后）与
    `questions[].stem`（已归一）——重复归一不能把题干弄丢。

    ⚠️ **不要**把 taskpad 原样传进来（它没有题干）：taskpad 请先过
    `papers_from_taskpads(ws, taskpads)`。
    """
    out: list[dict] = []
    for p in pads or []:
        if not isinstance(p, dict):
            continue
        qs = []
        for i, q in enumerate(p.get("questions") or [], start=1):
            if not isinstance(q, dict):
                continue
            qs.append({"no": str(q.get("no") or i),
                       "qid": str(q.get("qid") or ""),
                       "stem": str(q.get("stem") or q.get("content") or "")})
        out.append({"padId": str(p.get("padId") or p.get("id") or ""),
                    "tag": str(p.get("tag") or ""),
                    "questions": qs})
    return out


def _verdict(score: float, margin: float, cfg: dict) -> str:
    """置信度三档 + low。

    关键（2026-11-06 修复）：`margin` 不足时**不能**算 high——哪怕 score=1.0。
    原因：同包三层题干往往只差一两位参数，Top1 与 Top2 分数可能只差 0.04；
    此时“判成另一层”与“判对”一样容易，必须让教师看一眼，不能当结论。
    """
    if score >= cfg["minScore"] and margin >= cfg["marginMin"]:
        return "high"
    if score >= cfg["mediumScore"]:
        return "medium"      # 有明确候选，但区分度不够 → 需人工确认
    return "low"


def audit_student(transcript: dict, papers: list[dict], *, roster_tag: "str | None",
                  current_roster_tag: "str | None" = None,
                  cfg: "dict | None" = None) -> dict:
    """审计单个学生。

    `roster_tag`：来自 `roster-tags/<packId>.json` 快照（**冻结值**，批阅依据）；
    为 None 表示没有快照 → 用 `current_roster_tag` 兜底，并在 `rosterTagSource` 标明。
    """
    c = _cfg(cfg)
    blocks = _items_of(transcript or {})
    stems = [b["stem"] for b in blocks]
    link_missing = [i + 1 for i, s in enumerate(stems)
                    if len(normalize_text(s, student=True)) < int(c["minChars"])]
    usable = [s for i, s in enumerate(stems) if (i + 1) not in link_missing]

    rt = roster_tag if roster_tag is not None else current_roster_tag
    src = "snapshot" if roster_tag is not None else (
        "current-roster" if current_roster_tag is not None else "none")
    base = {"name": "", "rosterTag": rt, "currentRosterTag": current_roster_tag,
            "rosterTagSource": src, "linkMissing": link_missing,
            "auditTag": None, "auditPadId": None, "confidence": "unknown",
            "score": 0.0, "margin": 0.0, "verdict": "unknown",
            "pairs": [], "alternatives": [],
            "reason": "", "resolution": None}

    if not blocks:
        base["reason"] = "转写里没有可用的题目块（未转写或转写无 items）"
        return base
    if not usable:
        base["reason"] = "所有题的题干都没找到（未抄题/OCR 丢失题干），无法比对"
        return base
    if not papers:
        base["reason"] = "当前作业包内没有可用作业纸题目（包为空或未注入 pads）"
        return base

    ranked = []
    for p in papers:
        sc, pairs = best_assignment(usable, [q["stem"] for q in p["questions"]], c)
        # **双向**覆盖率：两个方向都要罚，否则「只抄了第 1 题」会错判成「只印了第 1 题」的短卷
        #   forward：学生题数 > 纸题数 → 这张纸装不下（必不是它）
        #   backward：纸题数 > 学生题数 → 学生只做了卷面一小部分（不太可能是这张）
        n_u = max(1, len(usable))
        n_p = max(1, len(p["questions"]))
        cover = (min(1.0, n_u / n_p) + min(1.0, n_p / n_u)) / 2.0
        ranked.append({"paper": p, "score": sc, "pairs": pairs, "coverage": cover,
                       "final": sc * (0.6 + 0.4 * cover)})
    ranked.sort(key=lambda x: -x["final"])
    top = ranked[0]
    margin = top["final"] - (ranked[1]["final"] if len(ranked) > 1 else 0.0)
    conf = _verdict(top["final"], margin, c)
    base.update({
        "auditTag": top["paper"]["tag"], "auditPadId": top["paper"]["padId"],
        "confidence": conf, "score": round(top["final"], 4), "margin": round(margin, 4),
        "pairs": [{"block": b + 1, "no": _no_of(blocks, link_missing, b),
                   "paperNo": (top["paper"]["questions"][j]["no"]
                               if j < len(top["paper"]["questions"]) else ""),
                   "score": round(s, 4)}
                  for (b, j, s) in top["pairs"]],
        "alternatives": [{"padId": r["paper"]["padId"], "tag": r["paper"]["tag"],
                          "score": round(r["final"], 4)} for r in ranked[1:3]],
    })

    # verdict：match / mismatch / unknown
    if rt is None or str(rt).strip() == "":
        base["verdict"] = "unknown"
        base["reason"] = (f"匹配到「{top['paper']['tag']}」层作业纸（{conf}），"
                          f"但该生没有 roster tag，无法判断是否一致")
    elif _same_tag(top["paper"]["tag"], rt):
        if conf == "low":
            # 分数太低时“一致”也说明不了什么 → unknown（不能因为碰巧对上就报绿）
            base["verdict"] = "unknown"
            base["reason"] = (f"匹配分数过低（{top['final']:.2f}），无法确认；"
                              f"碰巧对上 roster tag「{rt}」")
        else:
            base["verdict"] = "match"
            base["reason"] = (f"{len(usable)} 题对上「{top['paper']['tag']}」层作业纸，"
                              f"与 roster tag 一致")
    elif conf == "high":
        # **只有 high 才允许报 mismatch**：报错会把一行标红，误报代价远高于漏报
        base["verdict"] = "mismatch"
        base["reason"] = (f"匹配到「{top['paper']['tag']}」层作业纸（得分 {top['final']:.2f}，"
                          f"领先次优 {margin:.2f}），与 roster tag「{rt}」不一致")
    elif conf == "medium":
        base["verdict"] = "unknown"
        base["reason"] = (f"最可能是「{top['paper']['tag']}」层（得分 {top['final']:.2f}，"
                          f"但领先次优仅 {margin:.2f}，不足 {c['marginMin']:.2f}）——"
                          f"与 roster tag「{rt}」是否一致需人工判断")
    else:
        base["verdict"] = "unknown"
        base["reason"] = (f"匹配分数过低（{top['final']:.2f}），无法判定；"
                          f"最可能是「{top['paper']['tag']}」")
    return base


def _no_of(blocks: list[dict], link_missing: list[int], usable_index: int) -> str:
    """usable 列表下标 → 原题号。"""
    k = -1
    for i, b in enumerate(blocks):
        if (i + 1) in link_missing:
            continue
        k += 1
        if k == usable_index:
            return str(b["no"])
    return "?"


def _same_tag(a: str, b: str) -> bool:
    from ..paper.pack import _norm_tag
    return _norm_tag(a) == _norm_tag(b)


# ---------------- 全班审计 + 落盘 ----------------

class AuditError(RuntimeError):
    """审计失败（可读业务错误）。"""


def audit_path(ws, class_dir: str, pack_id: str) -> Path:
    from .snapshots import _class_root, _safe_pack_id
    return (_class_root(ws, class_dir) / "grading" / _safe_pack_id(pack_id)
            / "audit" / "tags-audit.json")


def _read_json(p: Path) -> "dict | None":
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def run_audit(ws, *, class_dir: str, pack_id: str, pads: "list[dict] | None" = None,
              taskpads: "list[dict] | None" = None,
              students: "list[str] | None" = None,
              cfg: "dict | None" = None, write: bool = True) -> dict:
    """跑一次全班审计。

    `pads`：作业包内作业纸 [{padId, tag, questions:[{no, content}]}]（**候选集**，教师 D2 不跨包）。
    `students`：只审计这些人（None = 全部）。
    转写从 `classes/<班>/grading/<packId>/transcripts/*.json` 读；**不调用模型**。
    """
    from . import snapshots as S
    from ..files.roster_io import read_roster_file

    # D172-T9：参数从**规则卡**读（阈值不许写死在代码里），显式 cfg 优先
    if cfg is None:
        try:
            from .rules import tag_audit_cfg
            cfg = tag_audit_cfg(ws)
        except Exception:  # noqa: BLE001 —— 规则坏了不影响审计
            cfg = None

    class_root = S._class_root(ws, class_dir)
    pack_id = S._safe_pack_id(pack_id)
    # 优先：taskpad 原样 → 从题库解析题干（唯一正确路径）
    papers = papers_from_taskpads(ws, taskpads) if taskpads else papers_of(pads or [])
    empty_papers = [p["padId"] for p in papers if not p["questions"]]
    # roster tag：快照（冻结）优先，其次今天的 roster
    snap = S.read_tags_snapshot(ws, class_dir, pack_id)
    snap_by_name = {str(s.get("name")): str(s.get("tag") or "")
                    for s in (snap.get("students") or [])} if snap.get("ok") else {}
    cur = read_roster_file(Path(ws).resolve(), class_dir)
    cur_by_name = {str(s.get("name")): str(s.get("tag") or "")
                   for s in (cur.get("students") or [])} if cur.get("ok") else {}

    tdir = class_root / "grading" / pack_id / "transcripts"
    files = sorted(tdir.glob("[!_]*.json")) if tdir.is_dir() else []
    want = {str(x).strip() for x in (students or []) if str(x).strip()}
    rows, skipped = [], []
    for f in files:
        name = f.stem
        if want and name not in want:
            continue
        tr = _read_json(f)
        if not isinstance(tr, dict):
            skipped.append({"name": name, "reason": "转写文件损坏"})
            continue
        row = audit_student(tr, papers,
                            roster_tag=snap_by_name.get(name),
                            current_roster_tag=cur_by_name.get(name),
                            cfg=cfg)
        row["name"] = name
        rows.append(row)

    # 教师 N2：未转写 → 不可审核，单列（**不混入 unknown**）
    seen = {r["name"] for r in rows}
    for nm in sorted(set(cur_by_name) | set(snap_by_name)):
        if nm in seen:
            continue
        if want and nm not in want:
            continue
        skipped.append({"name": nm, "reason": "未转写，无法审核"})

    summary = {"match": 0, "mismatch": 0, "unknown": 0}
    by_roster: dict[str, dict] = {}
    for r in rows:
        summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
        rt = str(r.get("rosterTag") or "(无tag)")
        b = by_roster.setdefault(rt, {"ok": 0, "bad": 0, "unknown": 0})
        if r["verdict"] == "match":
            b["ok"] += 1
        elif r["verdict"] == "mismatch":
            b["bad"] += 1
        else:
            b["unknown"] += 1
    # 全班都无法判定时，把**最可能的原因**直接说出来（否则教师只看到一片灰）
    if rows and summary.get("unknown") == len(rows) and all(
            not (r.get("pairs") or []) for r in rows):
        if not papers:
            rep_hint = "当前作业包没有解析出任何作业纸（pads 未传入或题目为空）"
        elif len(empty_papers) == len(papers):
            rep_hint = ("作业纸都没有题目：taskpad 只存题号、题干在题库里，"
                        "引擎未能从 kb/ 解析出题干（多为 kb/chap/ids 与题库不一致，"
                        "题库 id 形如 `<章>-<号>`）")
        else:
            rep_hint = "转写里有题干、作业纸也有题目，但相似度全部偏低（可调低 minScore 查看）"
    else:
        rep_hint = ""
    rep = {
        "ok": True, "packId": pack_id, "hint": rep_hint, "classDir": str(class_dir).strip().strip("/"),
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "engine": ENGINE_VER,
        "submittedSource": "students.json",
        "rosterTagSource": "snapshot" if snap_by_name else "current-roster",
        "snapshotMissing": bool(snap.get("missing")),
        "papers": [{"padId": p["padId"], "tag": p["tag"],
                    "questionCount": len(p["questions"])} for p in papers],
        # 诊断：这些作业纸解析不出题目（题库缺 manifest / items 为空 / 合成题未生成）
        "papersWithoutQuestions": empty_papers,
        "students": rows,
        "skippedNotTranscribed": skipped,
        "summary": summary, "byRosterTag": by_roster,
    }
    if write:
        p = audit_path(ws, class_dir, pack_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        # history：保留最近 20 次（只追加摘要）
        old = _read_json(p) or {}
        hist = list(old.get("history") or [])
        hist.append({"at": rep["generatedAt"], **summary})
        rep["history"] = hist[-20:]
        from ..filelock import atomic_write_text
        atomic_write_text(p, json.dumps(rep, ensure_ascii=False, indent=1))
        rep["path"] = str(p)
        logger.info(f"[tag-audit] {pack_id}: papers={len(papers)}"
                    + (f"（{len(empty_papers)} 张无题目！）" if empty_papers else "")
                    + f" match={summary['match']} "
                    f"mismatch={summary['mismatch']} unknown={summary['unknown']} "
                    f"skipped={len(skipped)}")
    return rep


def read_audit(ws, *, class_dir: str, pack_id: str) -> dict:
    p = audit_path(ws, class_dir, pack_id)
    if not p.is_file():
        return {"ok": False, "missing": True, "path": str(p)}
    d = _read_json(p)
    if not isinstance(d, dict):
        return {"ok": False, "error": "审计文件损坏", "path": str(p)}
    d["ok"] = True
    d["path"] = str(p)
    return d


def apply_audit_tags(ws, *, class_dir: str, pack_id: str, changes: list[dict],
                     reason: str = "audit-apply") -> dict:
    """把教师确认的 tag 变更**补丁式**写进 `roster-tags/<packId>.json`。

    `changes`：[{name, tag}]（tag 为空串表示清空）。

    安全设计（教师 N1）：
      - 写前**必存** `_history/<packId>__<ts>.json`（`reason` 标明来源），供「撤销」；
      - 只改被点名的学生，其余学生原样保留；每行留 `previousTag`；
      - 幂等：值与现值相同则不写（返回 `unchanged`）。
    """
    from . import snapshots as S
    from ..filelock import atomic_write_text

    class_root = S._class_root(ws, class_dir)
    pack_id = S._safe_pack_id(pack_id)
    snap = S.read_tags_snapshot(ws, class_dir, pack_id)
    if not snap.get("ok"):
        return {"ok": False, "error": "该作业包没有 roster-tags 快照，无法应用（请先批阅一次生成快照）"}
    rows = [dict(s) for s in (snap.get("students") or [])]
    by_name = {str(r.get("name")): r for r in rows}
    applied, missing, unchanged = [], [], []
    for ch in changes or []:
        nm = str(ch.get("name") or "").strip()
        if not nm:
            continue
        r = by_name.get(nm)
        if r is None:
            missing.append(nm)
            continue
        new = str(ch.get("tag") or "").strip()
        if str(r.get("tag") or "") == new:
            unchanged.append(nm)
            continue
        applied.append({"name": nm, "from": str(r.get("tag") or ""), "to": new})
        r["previousTag"] = str(r.get("tag") or "")
        r["tag"] = new
        r["tagUpdatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        r["tagUpdateReason"] = reason
    if not applied:
        return {"ok": True, "applied": [], "unchanged": unchanged, "missing": missing,
                "historyPath": None, "written": False,
                "note": "没有实际变化（幂等，不写盘）"}

    # 1) 历史副本（撤销用）
    hist_dir = class_root / S.TAGS_DIR / "_history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    hp = hist_dir / f"{pack_id}__{ts}.json"
    n = 1
    while hp.exists():
        hp = hist_dir / f"{pack_id}__{ts}-{n}.json"
        n += 1
    # 这份副本是**改动前**的状态；但为了「撤销」时能反查，也在副本里记下**本次动作**。
    # 语义：historyReason = 触发这次备份的动作；source 保持快照原值（谁是它当时的来源）。
    atomic_write_text(hp, json.dumps(
        {**{k: v for k, v in snap.items() if k not in ("ok", "path")},
         "source": str(snap.get("source") or ""),
         # historyReason = **这次要做的事**（为什么备份）；snapshotSource = 这份副本**本身**的来源
         "historyReason": reason,
         "snapshotSource": str(snap.get("source") or ""),
         "historyAt": time.strftime("%Y-%m-%d %H:%M:%S")},
        ensure_ascii=False, indent=1))
    # 2) 写权威快照
    payload = {k: v for k, v in snap.items() if k not in ("ok", "path")}
    payload.update({"students": rows, "source": reason,
                    "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S")})
    atomic_write_text(S.tags_snapshot_path(ws, class_dir, pack_id),
                      json.dumps(payload, ensure_ascii=False, indent=1))
    # 3) 回写 audit 的 resolution（证据侧留痕）
    ap = audit_path(ws, class_dir, pack_id)
    aud = _read_json(ap)
    if isinstance(aud, dict):
        at = time.strftime("%Y-%m-%d %H:%M:%S")
        for st in (aud.get("students") or []):
            for a in applied:
                if str(st.get("name")) == a["name"]:
                    st["resolution"] = {"at": at, "action": reason,
                                        "from": a["from"], "to": a["to"], "by": "teacher"}
                    st["rosterTag"] = a["to"]
                    st["verdict"] = "match"
        atomic_write_text(ap, json.dumps(aud, ensure_ascii=False, indent=1))
    logger.info(f"[tag-audit] 已应用 {len(applied)} 人 tag 变更（{pack_id}），历史副本 {hp.name}")
    return {"ok": True, "applied": applied, "unchanged": unchanged, "missing": missing,
            "historyPath": str(hp), "written": True}


def list_history(ws, *, class_dir: str, pack_id: str) -> list[dict]:
    """列出该包的快照历史副本（供「撤销」选择）。"""
    from .snapshots import _class_root, _safe_pack_id
    d = _class_root(ws, class_dir) / "roster-tags" / "_history"
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob(f"{_safe_pack_id(pack_id)}__*.json"), reverse=True):
        d0 = _read_json(f) or {}
        out.append({"file": f.name, "path": str(f),
                    "at": d0.get("historyAt") or "",
                    "reason": d0.get("historyReason") or d0.get("source") or "",
                    # 这份副本**本身**代表的快照来源（撤销时按它显示“恢复到哪个状态”）
                    "snapshotSource": d0.get("snapshotSource") or d0.get("source") or "",
                    "count": len(d0.get("students") or [])})
    return out


def undo_last(ws, *, class_dir: str, pack_id: str, file: str = "") -> dict:
    """撤销：用历史副本回写快照（回写前**再存**一份当前状态，防"撤销了又不满意"）。"""
    from . import snapshots as S
    from ..filelock import atomic_write_text
    from .snapshots import _class_root, _safe_pack_id

    hist = list_history(ws, class_dir=class_dir, pack_id=pack_id)
    if not hist:
        return {"ok": False, "error": "没有可撤销的历史副本"}
    pick = next((h for h in hist if h["file"] == file), None) if file else \
        next((h for h in hist if h["reason"] == "audit-apply"), hist[0])
    if pick is None:
        return {"ok": False, "error": f"找不到历史副本 {file!r}"}
    data = _read_json(Path(pick["path"]))
    if not isinstance(data, dict) or not data.get("students"):
        return {"ok": False, "error": "历史副本损坏"}
    # 先保存当前状态。**reason 必须保留原来源**（如 audit-apply），
    # 只在 historyReason 前加 `before-undo:` 便于人读——若直接改成 before-undo，
    # UI 就分不清「哪一份是被审计改过的状态」。
    cur = S.read_tags_snapshot(ws, class_dir, pack_id)
    if cur.get("ok"):
        cur_reason = str(cur.get("source") or "unknown")
        d0 = _class_root(ws, class_dir) / S.TAGS_DIR / "_history"
        d0.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        atomic_write_text(d0 / f"{_safe_pack_id(pack_id)}__{ts}.json",
                          json.dumps({**{k: v for k, v in cur.items()
                                         if k not in ("ok", "path")},
                                      "historyReason": "before-undo",
                                      "snapshotSource": cur_reason,
                                      "historyAt": time.strftime("%Y-%m-%d %H:%M:%S")},
                                     ensure_ascii=False, indent=1))
    # 剔除“历史副本专用”元字段，否则会把 snapshotSource 等写回正式快照
    _META = ("ok", "path", "historyReason", "historyAt", "snapshotSource")
    payload = {k: v for k, v in data.items() if k not in _META}
    payload["source"] = "undo"
    payload["restoredFrom"] = pick["file"]
    payload["generatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    atomic_write_text(S.tags_snapshot_path(ws, class_dir, pack_id),
                      json.dumps(payload, ensure_ascii=False, indent=1))
    logger.info(f"[tag-audit] 已撤销：从 {pick['file']} 恢复快照")
    return {"ok": True, "restoredFrom": pick["file"],
            "count": len(payload.get("students") or [])}
