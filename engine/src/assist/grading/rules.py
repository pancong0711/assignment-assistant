"""rules.py — D130：**按题目来源分型**的评阅规则（三层规则的"规则"两层）。

设计（docs/78 §3.2）：
    第 1 层 全局规则   `<ws>/grading-rules.json : global`
    第 2 层 题型规则   `<ws>/grading-rules.json : types.<kind>`
    第 3 层 单题要点   随答案版本库走（本模块**不**管，见 §3.2 / T5）

**规则与要点解耦**：要点描述"该答什么"，规则描述"缺了怎么扣"。
本模块只负责：
1. `DEFAULT_RULES` —— 默认值（用户 2026-10-30 拍板的评分细则，逐条可追溯）；
2. 读写 `<ws>/grading-rules.json`（缺失即写默认；json 损坏回落默认且不覆盖用户文件）；
3. 数值校验（带范围，供评阅规则卡 T9 与 CLI 共用）；
4. `rule_summary(kind)` —— 生成 prompt 用的**规则摘要**（要点生成与评阅共用同一份）。

为什么单独成文件：此前 `ANALYSIS_PROMPT` / `TAG_INSTRUCTIONS` / `score_from_analysis`
三处硬编码，教师看不到也改不了（docs/78 §2 P2–P4）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from loguru import logger

RULES_FILE = "grading-rules.json"

# ---- 题目来源 kind 归一（docs/78 §3.1） ----
# copys / copyonly / copysp 都是"抄写"的别名；punish（期末补作业）历史上沿用抄写规则。
_KIND_ALIASES = {
    "copys": "copy",
    "copyonly": "copy",
    "copysp": "copy",
    "punish": "copy",
}
SUPPORTED_KINDS = ("problems", "qa", "copy", "distinguish",
                   "innovation", "translation", "summary")


def normalize_kind(kind: str | None) -> str:
    """题库表名 / tag → 评阅范式 kind（未知一律回落 `problems`）。

    未知回落 `problems` 的理由：它是历史默认（计算/推导逐处找错），
    且扣分最严格——宁可多扣可人工上调，也不要静默放宽。
    """
    k = str(kind or "").strip().lower()
    k = _KIND_ALIASES.get(k, k)
    return k if k in SUPPORTED_KINDS else "problems"


# ---- 默认规则（用户 2026-10-30 拍板，docs/78 §3.3） ----
DEFAULT_RULES: dict = {
    "version": 1,
    "global": {
        # 解题过程过于简略、缺关键步骤 → 每次 −5（即便答案正确）
        "briefProcessDeduct": 5,
        # ≥80% 的题都被判"过程简略" → **总分额外 −5**（一次性，非逐题）
        "allBriefRatio": 0.8,
        "allBriefDeduct": 5,
        # 缺签名（迁移自 2601 规则，保留）
        "noSignatureDeduct": 5,
        # 书写规范（潦草/模糊/杂乱）合并扣分上限
        "writingDeduct": 5,
        # 单题扣分上限 & 总分底线（迁移自 2601 规则，保留）
        "perQuestionCap": 20,
        "floor": 40,
        # 低置信度错误是否计分（D98-B5：默认不计，防幻觉误伤）
        "countLowConfidence": False,
    },
    "types": {
        "problems": {
            "mode": "errorCount",           # 逐处找错
            "perErrorDeduct": 5,
            "perQuestionCap": 20,
            "requireDiagram": False,        # 由图决定，不强制
            "generateRubric": True,
        },
        "qa": {
            "mode": "missingPoints",        # 要点完整性 + 示意图
            "perMissingPointDeduct": 5,
            "missingDiagramDeduct": 5,
            "requireDiagram": True,
            "generateRubric": True,
        },
        "copy": {
            "mode": "checklist",            # 抄写完整性三缺一
            "perMissingItemDeduct": 5,
            "checklist": ["题目", "解题过程", "示意图"],
            "requireDiagram": "if_question_has",   # 题本身有图才要求抄图
            "generateRubric": False,        # 以原文为唯一依据
        },
        "distinguish": {
            "mode": "lengthBased",          # 辨析角度与依据（较宽）
            "lengthFactor": 3,              # 基准 = 题目字数 × 3
            "lengthFloorChars": 60,         # 下限保护 max(3×题长, 60)
            "shortRatioDeduct": {"0.8": 5, "0.5": 10},   # <80% → −5；<50% → −10
            "irrelevantDeduct": 20,         # 与题目完全无关 → −20
            "logicErrorExempt": True,       # 逻辑错误豁免扣分，但必须生成启发式提问
            "requireDiagram": False,
            "generateRubric": True,
        },
        "innovation": {
            "mode": "lengthBased",
            "lengthFactor": 3,
            "lengthFloorChars": 60,
            "shortRatioDeduct": {"0.8": 5, "0.5": 10},
            "irrelevantDeduct": 20,
            "logicErrorExempt": True,
            "requireDiagram": False,
            "generateRubric": True,
        },
        "translation": {
            "mode": "lengthBased",
            "lengthFactor": 3,
            "lengthFloorChars": 60,
            "shortRatioDeduct": {"0.8": 5, "0.5": 10},
            "irrelevantDeduct": 20,
            "logicErrorExempt": True,
            "requireDiagram": False,
            "generateRubric": True,
        },
        "summary": {
            "mode": "checklist",            # 知识点与概念 / 重要公式及推导 / 示意图
            "perMissingItemDeduct": 5,
            "checklist": ["知识点与概念", "重要公式及推导", "示意图"],
            "requireDiagram": "if_question_has",
            "generateRubric": False,        # 未来接课堂资料（P2）
        },
    },
}

# 数值字段的合法范围（T9 规则卡校验 + CLI 共用）；"gt"/"ge"/"le" 语义同字面
_NUM_RANGES: dict[str, tuple[float, float]] = {
    "briefProcessDeduct": (0, 50),
    "allBriefRatio": (0, 1),
    "allBriefDeduct": (0, 50),
    "noSignatureDeduct": (0, 50),
    "writingDeduct": (0, 50),
    "perQuestionCap": (0, 100),
    "floor": (0, 100),
    "perErrorDeduct": (0, 50),
    "perMissingPointDeduct": (0, 50),
    "missingDiagramDeduct": (0, 50),
    "perMissingItemDeduct": (0, 50),
    "lengthFactor": (1, 10),
    "lengthFloorChars": (0, 1000),
    "irrelevantDeduct": (0, 100),
}


def rules_path(ws) -> Path:
    return Path(ws).resolve() / RULES_FILE


def read_rules(ws) -> dict:
    """读规则；**缺失即写默认**；损坏则回落默认（不覆盖用户文件，便于人工救回）。"""
    p = rules_path(ws)
    if not p.is_file():
        data = json.loads(json.dumps(DEFAULT_RULES))  # deep copy
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 —— 落盘失败也要能用
            logger.warning(f"[规则] 写入默认规则失败（仅内存生效）：{str(exc)[:120]}")
        return data
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("顶层不是对象")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[规则] {p.name} 解析失败（{str(exc)[:80]}），本次使用默认规则")
        return json.loads(json.dumps(DEFAULT_RULES))
    return _fill_defaults(raw)


def _fill_defaults(raw: dict) -> dict:
    """用户文件缺字段/缺题型时补默认（升级后新增规则不会因旧文件而丢失）。"""
    out = json.loads(json.dumps(DEFAULT_RULES))
    for section in ("global", "types"):
        user_sec = raw.get(section)
        if isinstance(user_sec, dict):
            for k, v in user_sec.items():
                if isinstance(v, dict) and isinstance(out[section].get(k), dict):
                    out[section][k].update(v)
                elif k in out[section]:
                    out[section][k] = v
    for k in ("version",):
        if k in raw:
            out[k] = raw[k]
    return out


def write_rules(ws, rules: dict, *, journal: bool = True) -> dict:
    """校验并写回；`journal=True` 时把改动追加到 `<ws>/grading-rules.journal.jsonl`。"""
    new = _fill_defaults(rules)
    errs = validate_rules(new)
    if errs:
        return {"ok": False, "error": "；".join(errs), "errors": errs}
    p = rules_path(ws)
    old = read_rules(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    diffs = diff_rules(old, new)
    if journal and diffs:
        _journal_append(ws, {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "changes": diffs, "file": str(p)})
    return {"ok": True, "file": str(p), "changes": diffs, "rules": new}


def reset_rules(ws, *, journal: bool = True) -> dict:
    """恢复默认（改动同样记 journal，便于"我又改回去了"可追溯）。"""
    return write_rules(ws, json.loads(json.dumps(DEFAULT_RULES)), journal=journal)


def _journal_append(ws, rec: dict) -> None:
    p = Path(ws).resolve() / "grading-rules.journal.jsonl"
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[规则] journal 写入失败：{str(exc)[:120]}")


def validate_rules(rules: dict) -> list[str]:
    """范围校验（T9 规则卡与 CLI 共用）。返回错误列表（空 = 通过）。"""
    errs: list[str] = []
    g = rules.get("global") or {}
    for key, (lo, hi) in _NUM_RANGES.items():
        if key in g:
            v = g.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errs.append(f"global.{key} 必须是数值")
            elif not (lo <= float(v) <= hi):
                errs.append(f"global.{key}={v} 超出范围 [{lo}, {hi}]")
    types = rules.get("types") or {}
    for kind, cfg in types.items():
        if kind not in SUPPORTED_KINDS:
            errs.append(f"未知题型：{kind}（可选 {', '.join(SUPPORTED_KINDS)}）")
            continue
        if not isinstance(cfg, dict):
            errs.append(f"types.{kind} 必须是对象")
            continue
        for key, (lo, hi) in _NUM_RANGES.items():
            if key in cfg:
                v = cfg[key]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errs.append(f"types.{kind}.{key} 必须是数值")
                elif not (lo <= float(v) <= hi):
                    errs.append(f"types.{kind}.{key}={v} 超出范围 [{lo}, {hi}]")
        mode = cfg.get("mode")
        if mode and mode not in ("errorCount", "missingPoints", "checklist", "lengthBased"):
            errs.append(f"types.{kind}.mode={mode} 非法"
                        "（errorCount/missingPoints/checklist/lengthBased）")
        ratio = cfg.get("shortRatioDeduct")
        if ratio is not None:
            if not isinstance(ratio, dict) or not ratio:
                errs.append(f"types.{kind}.shortRatioDeduct 必须是非空对象，如 {{\"0.8\": 5}}")
            else:
                for rk, rv in ratio.items():
                    try:
                        rf = float(rk)
                    except Exception:  # noqa: BLE001
                        errs.append(f"types.{kind}.shortRatioDeduct 的键 {rk!r} 必须是 0~1 的小数")
                        continue
                    if not (0 < rf <= 1):
                        errs.append(f"types.{kind}.shortRatioDeduct 的键 {rk} 必须在 (0, 1]")
                    if not isinstance(rv, (int, float)) or isinstance(rv, bool) or rv < 0:
                        errs.append(f"types.{kind}.shortRatioDeduct[{rk}] 必须是非负数值")
        cl = cfg.get("checklist")
        if cl is not None and (not isinstance(cl, list) or not cl
                               or not all(isinstance(x, str) and x.strip() for x in cl)):
            errs.append(f"types.{kind}.checklist 必须是非空字符串数组")
    return errs


def diff_rules(old: dict, new: dict) -> list[dict]:
    """逐字段差异（journal/规则卡"本次改动"展示用）。"""
    out: list[dict] = []

    def walk(a, b, prefix=""):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                walk(a.get(k), b.get(k), f"{prefix}.{k}" if prefix else str(k))
            return
        if a != b:
            out.append({"path": prefix, "old": a, "new": b})

    walk(old or {}, new or {})
    return out


def type_rules(ws, kind: str) -> dict:
    """取某 kind 的题型规则（kind 已归一；缺失回落默认）。"""
    k = normalize_kind(kind)
    rules = read_rules(ws) if ws is not None else DEFAULT_RULES
    cfg = dict(((rules.get("types") or {}).get(k) or {}))
    base = dict(DEFAULT_RULES["types"][k])
    base.update(cfg)
    return base


def global_rules(ws) -> dict:
    g = dict(DEFAULT_RULES["global"])
    if ws is not None:
        g.update((read_rules(ws).get("global") or {}))
    return g


# ---- 规则摘要（T2）：生成要点与评阅共用同一份"该缺什么怎么扣" ----
_KIND_FOCUS = {
    "problems": "计算/推导题：逐处找错（物理原理、公式、代入、单位、有效数字），"
                "指出具体哪一步错。",
    "qa": "问答题：检查**评阅要点是否答全**，以及是否画了题目要求的示意图。",
    "copy": "抄写题：只检查**抄写完整性**（题干要求抄什么就查什么），"
            "不评价推导/计算/逻辑；不要因为抄的是课本原文而非例题就判不完整。",
    "distinguish": "辨析题：看概念区分是否清晰、依据是否成立；允许表述简略，"
                   "但要有明确判断与理由。",
    "innovation": "创新题：看思考过程与独立见解；超纲设想只要自洽即可，不因超纲扣分。",
    "translation": "翻译题：看译文准确性与术语规范；不苛求文采。",
    "summary": "总结题：看知识点与概念是否准确、重要模型/公式（含推导）是否讲到、"
               "示意图（题干要求时）是否给出。",
}


def rule_summary(ws, kind: str) -> str:
    """把某 kind 的规则**渲染成一句句可读的摘要**（进 prompt，也供规则卡只读展示）。

    注意：只描述"缺了怎么扣"，不描述"该答什么"（后者属评阅要点，T5）。
    """
    k = normalize_kind(kind)
    t = type_rules(ws, k)
    g = global_rules(ws)
    lines = [f"【评阅范式：{k}】{_KIND_FOCUS.get(k, '')}"]
    mode = t.get("mode")
    if mode == "errorCount":
        lines.append(f"- 每处明确错误扣 {t.get('perErrorDeduct', 5)} 分，"
                     f"单题最多扣 {t.get('perQuestionCap', 20)} 分。")
    elif mode == "missingPoints":
        lines.append(f"- 每个未答到的评阅要点扣 {t.get('perMissingPointDeduct', 5)} 分；"
                     f"题目要求画图而未画扣 {t.get('missingDiagramDeduct', 5)} 分。")
    elif mode == "checklist":
        items = "、".join(t.get("checklist") or [])
        lines.append(f"- 逐项核对：{items}；每缺一项扣 {t.get('perMissingItemDeduct', 5)} 分"
                     "（题目本身没有图时，不要求抄示意图）。")
    elif mode == "lengthBased":
        ratio = t.get("shortRatioDeduct") or {}
        tiers = "；".join(f"不足 {float(r) * 100:.0f}% → −{v}"
                         for r, v in sorted(ratio.items(), key=lambda x: -float(x[0])))
        lines.append(f"- 以题目字数的 {t.get('lengthFactor', 3)} 倍为作答长度基准"
                     f"（下限 {t.get('lengthFloorChars', 60)} 字）：{tiers}；"
                     f"与题目完全无关 → −{t.get('irrelevantDeduct', 20)}。")
        if t.get("logicErrorExempt", True):
            lines.append("- **逻辑错误本身不额外扣分**（按长度档判定即可），"
                         "但必须针对该逻辑问题给出启发式提问。")
    lines.append(f"- 全局：过程过于简略缺关键步骤，每处 −{g.get('briefProcessDeduct', 5)}；"
                 f"若 ≥{float(g.get('allBriefRatio', 0.8)) * 100:.0f}% 的题目都被判为过简，"
                 f"总分再一次性 −{g.get('allBriefDeduct', 5)}（不逐题累计）。")
    return "\n".join(lines)


def rubric_enabled(ws, kind: str) -> bool:
    """该 kind 是否生成 AI 评阅要点（copy/summary 默认不生成）。"""
    return bool(type_rules(ws, normalize_kind(kind)).get("generateRubric", False))
