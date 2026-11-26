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
# D170-T9：合法评阅模式**集中定义**。
# 此前校验里硬编码了一个四元组，新增 mode 时必然漏改 →
# write_rules 会静默失败（教师改了规则却存不进去）。新增模式只改这里一处。
VALID_MODES = ("errorCount", "missingPoints", "checklist", "lengthBased", "topicMatch",
               "translation")
# D168-B5：`example`（例题库）**刻意不在** SUPPORTED_KINDS 里——
# 它只做分析、不批阅。normalize_kind 会把未知回落 problems，
# 所以这里单独声明"分析专用"，供调用方判断（避免例题被当成待批阅题）。
ANALYSIS_ONLY_KINDS = ("example",)


def resolve_item_kind(item: "dict | None", q: "dict | None" = None) -> "tuple[str, str]":
    """D213：**唯一**的“某道题属于哪个题库”的解析口径（提示词与算分共用）。

    现场：plan.json 为旧版时题目只有 `tag`（作业纸 tag）而没有 `kind/kb`；
    提示词按 `kind > kb > tag` 注入 innovation 规则（模型据此把逻辑问题写成
    启发式提问），但算分只认 `kind > kb > q.kind > problems` → 回落到 problems
    “每错 −5” → innovation 题被按逻辑错误重扣。

    优先级（与 prompts.normalize_prompt_items 完全一致）：
      题目级 kind > 题目级 kb（题库表名）> 作业纸 tag > 模型自报 q.kind > problems

    返回 `(kind, source)`；`source` ∈ item.kind / item.kb / item.tag / model / fallback，
    便于把“这题到底按哪套规则评的”写进结果供教师核对。
    """
    it = item or {}
    q = q or {}
    # D216：程序对齐给出的题库（逐题）优先级最高，来源标 align
    if str(it.get("_kindSource") or "") == "align" and str(it.get("kb") or "").strip():
        return normalize_kind(it["kb"]), "align"
    for key, src in (("kind", "item.kind"), ("kb", "item.kb"), ("tag", "item.tag")):
        v = str(it.get(key) or "").strip()
        if v:
            return normalize_kind(v), src
    v = str(q.get("kind") or "").strip()
    if v:
        return normalize_kind(v), "model"
    return "problems", "fallback"


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
        # D234：补交/迟交扣分（程序按提交状态自动执行，不交给 AI 判断）
        "lateSubmissionDeduct": 5,
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
        },
        "qa": {
            "mode": "missingPoints",        # 要点完整性 + 示意图
            "perMissingPointDeduct": 5,
            "missingDiagramDeduct": 5,
            "requireDiagram": True,
        },
        # D170-T9：抄写题改为「主题一致 + 字数下限」。
        # 教师原话：
        #   「转写过程很可能多模态模型没有准确转写全部内容，造成理解歧义，
        #     抄写题不必要判断抄写内容的逻辑，只要内容跟题目末尾括号中文字主题
        #     一致就好，关键是要抄写一些内容，字数不宜太少。」
        # 理由：转录来自照片识别，细节必然失真；据此判"没抄全/抄错"会**冤枉学生**。
        # 而"主题是否跑偏""字数明显不足"是**鲁棒**的判据。
        "copy": {
            "mode": "topicMatch",
            "minChars": 80,                  # 抄写内容下限（字数太少 = 没真抄）
            "topicMismatchDeduct": 20,       # 与题目主题不符
            "shortRatioDeduct": {"0.5": 10, "1.0": 5},   # 不足 50% → −10；不足 100% → −5
            "requireDiagram": False,         # 不再要求抄图（转写不可靠）
            "ignoredChecks": ["逻辑", "推导", "公式正确性", "是否抄全题目/过程/图"],
        },
        "distinguish": {
            "mode": "lengthBased",          # 辨析角度与依据（较宽）
            "lengthFactor": 3,              # 基准 = 题目字数 × 3
            "lengthFloorChars": 60,         # 下限保护 max(3×题长, 60)
            "shortRatioDeduct": {"0.8": 5, "0.5": 10},   # <80% → −5；<50% → −10
            "irrelevantDeduct": 20,         # 与题目完全无关 → −20
            "logicErrorExempt": True,       # 逻辑错误豁免扣分，但必须生成启发式提问
            "requireDiagram": False,
        },
        "innovation": {
            "mode": "lengthBased",
            "lengthFactor": 3,
            "lengthFloorChars": 60,
            "shortRatioDeduct": {"0.8": 5, "0.5": 10},
            "irrelevantDeduct": 20,
            "logicErrorExempt": True,
            "requireDiagram": False,
        },
        # D174：翻译题放宽为「基本完成度」判据（教师原话）：
        #   「主要看学生有没有翻译和回答基本问题：翻译完全不对 → −5；
        #     没有回答问题 → −5；字数少于题目描述 → −10。」
        # 与抄写题同一思路：转录来自照片识别，译文细节不可靠；
        # 文学作品翻译也**没有唯一标准答案**，逐词比对准确性会误伤学生。
        # 因此 translation 不再走通用 lengthBased（8 折/5 折 + 无关 −20），
        # 改走 mode="translation"（不读 errors，只判三件事）。
        "translation": {
            "mode": "translation",
            "questionAnsweredDeduct": 5,      # 没有回答/完成题目所问
            "translationWrongDeduct": 5,      # 翻译完全不对（答非所问/通篇乱译）
            "shortAnswerDeduct": 10,          # 字数少于题目描述的要求
            "logicErrorExempt": True,         # 译文准确性/术语不扣分，只给启发式提问
            "requireDiagram": False,
        },
        "summary": {
            "mode": "checklist",            # 知识点与概念 / 重要公式及推导 / 示意图
            "perMissingItemDeduct": 5,
            "checklist": ["知识点与概念", "重要公式及推导", "示意图"],
            "requireDiagram": "if_question_has",
            # D134-T4：**保底口径**（无课堂资料时用；四维判定，缺项不扣分，只扣"过简"）
            "fallback": {
                "enabled": True,
                "minChars": 150,            # 低于此字数视为"总结过于简略"
                "minCharsDeduct": 5,
                "requireKnowledgeSummary": True,     # 必须看到知识点/概念的归纳
                "requireFormulaOrDerivation": True,  # 必须有公式或推导
                "requireDiagram": "if_question_has",
                "missingItemDeduct": 0,     # 保底模式**缺项不扣分**（防误伤）
            },
        },
    },
    # D172：tag 审计（纯 Python 匹配器）的可调参数——**阈值不许写死在代码里**。
    # 说明：审计只比对题干；minScore/marginMin 越高 → 越保守（更多 unknown，更少误报）。
    "tagAudit": {
        "minScore": 0.75,       # 高置信下限（作业纸得分 ≥ 此值）
        "marginMin": 0.15,      # Top1 与 Top2 的最小差（高置信要求）
        "mediumScore": 0.45,    # 低于此 → low（一律 unknown）
        "bigramWeight": 0.65,   # 字面 n-gram（2/3-gram Dice）权重
        "numberWeight": 0.35,   # 数值常量重合权重（同章不同参数主要靠它区分）
        "minChars": 12,         # 题干去噪后短于此 → 视为「没抄题」（标 ?）
        # D216：批阅前置「程序对齐」阈值（与审计同一段，避免两套口径打架）
        "coverageMin": 0.6,          # 判定“做的是这份卷”的最低覆盖率
        "worksheetMarginMin": 0.15,  # 与次佳作业纸的最小差值
        "matchScore": 0.45,          # 单题算“匹配上”的最低相似度
        "alignMinChars": 6,          # 对齐时题干最小长度（比审计宽松）
    },
}

# 数值字段的合法范围（T9 规则卡校验 + CLI 共用）；"gt"/"ge"/"le" 语义同字面
_NUM_RANGES: dict[str, tuple[float, float]] = {
    "briefProcessDeduct": (0, 50),
    "allBriefRatio": (0, 1),
    "allBriefDeduct": (0, 50),
    "noSignatureDeduct": (0, 50),
    "writingDeduct": (0, 50),
    "lateSubmissionDeduct": (0, 50),
    "perQuestionCap": (0, 100),
    "floor": (0, 100),
    "perErrorDeduct": (0, 50),
    "perMissingPointDeduct": (0, 50),
    "missingDiagramDeduct": (0, 50),
    "perMissingItemDeduct": (0, 50),
    "lengthFactor": (1, 10),
    "lengthFloorChars": (0, 1000),
    "irrelevantDeduct": (0, 100),
    # D170-T9：抄写题（topicMatch）—— 字数下限与主题不符扣分
    "minChars": (0, 5000),
    "topicMismatchDeduct": (0, 100),
    # D172：tag 审计
    "minScore": (0, 1),
    "marginMin": (0, 1),
    "mediumScore": (0, 1),
    "bigramWeight": (0, 1),
    "numberWeight": (0, 1),
    # D216：批阅前置「程序对齐」阈值
    "coverageMin": (0, 1),
    "worksheetMarginMin": (0, 1),
    "matchScore": (0, 1),
    "alignMinChars": (1, 500),
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
        # D134 修复：**首次读取**（规则文件不存在、刚落盘默认）也必须叠加
        # `atopia/extensions/rules/` 覆盖，否则新建 workspace 上扩展静默失效。
        return _apply_extensions(p, data)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("顶层不是对象")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[规则] {p.name} 解析失败（{str(exc)[:80]}），本次使用默认规则")
        return json.loads(json.dumps(DEFAULT_RULES))
    return _apply_extensions(p, _fill_defaults(raw))


def tag_audit_cfg(ws) -> dict:
    """D172：读 tag 审计参数（规则卡 `tagAudit` 段）；异常时回落默认。"""
    try:
        got = read_rules(ws).get("tagAudit")
        return dict(got) if isinstance(got, dict) else dict(DEFAULT_RULES["tagAudit"])
    except Exception:  # noqa: BLE001 —— 规则坏了也不能让审计崩
        return dict(DEFAULT_RULES["tagAudit"])


def _apply_extensions(path: Path, data: dict) -> dict:
    """D132-T18：叠加 `<ws>/extensions/rules/grading-rules.json` 覆盖。

    放在这里而不是 `read_rules` 开头，是为了保证"规则文件本身仍缺失即写默认"
    的既有语义不变（扩展只**叠加**，不影响默认文件生成）。
    """
    try:
        from ..atopia import extensions as E
        ws = path.parent
        merged = E.effective_rules_from(ws, data)
        return merged
    except Exception:  # noqa: BLE001 —— 扩展异常绝不能影响评阅
        return data


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
    # D172：顶层独立段（不属于 global/types 的题型结构）
    if isinstance(raw.get("tagAudit"), dict):
        for k, v in raw["tagAudit"].items():
            if k in out.get("tagAudit", {}):
                out["tagAudit"][k] = v
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
    # D172：tag 审计参数（顶层独立段）
    ta = rules.get("tagAudit")
    if ta is not None:
        if not isinstance(ta, dict):
            errs.append("tagAudit 必须是对象")
        else:
            for key in ("minScore", "marginMin", "mediumScore", "bigramWeight",
                        "numberWeight", "minChars",
                        "coverageMin", "worksheetMarginMin", "matchScore",
                        "alignMinChars"):
                if key not in ta:
                    continue
                v = ta[key]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errs.append(f"tagAudit.{key} 必须是数值")
                    continue
                lo, hi = _NUM_RANGES[key]
                if not (lo <= float(v) <= hi):
                    errs.append(f"tagAudit.{key}={v} 超出范围 [{lo}, {hi}]")
            if isinstance(ta.get("bigramWeight"), (int, float)) \
                    and isinstance(ta.get("numberWeight"), (int, float)) \
                    and float(ta["bigramWeight"]) + float(ta["numberWeight"]) <= 0:
                errs.append("tagAudit.bigramWeight + numberWeight 必须 > 0")
            for key in ta:
                if key not in ("minScore", "marginMin", "mediumScore", "bigramWeight",
                               "numberWeight", "minChars",
                               "coverageMin", "worksheetMarginMin", "matchScore",
                               "alignMinChars"):
                    errs.append(f"tagAudit.{key} 未知字段")
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
        if mode and mode not in VALID_MODES:
            errs.append(f"types.{kind}.mode={mode} 非法（合法值：{'/'.join(VALID_MODES)}）")
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
        fb = cfg.get("fallback")
        if fb is not None:
            if not isinstance(fb, dict):
                errs.append(f"types.{kind}.fallback 必须是对象")
            else:
                if "enabled" in fb and not isinstance(fb["enabled"], bool):
                    errs.append(f"types.{kind}.fallback.enabled 必须是布尔值")
                for k2, (lo2, hi2) in (("minChars", (0, 5000)),
                                       ("minCharsDeduct", (0, 100)),
                                       ("missingItemDeduct", (0, 100))):
                    if k2 in fb:
                        v2 = fb[k2]
                        if not isinstance(v2, (int, float)) or isinstance(v2, bool):
                            errs.append(f"types.{kind}.fallback.{k2} 必须是数值")
                        elif not (lo2 <= float(v2) <= hi2):
                            errs.append(f"types.{kind}.fallback.{k2}={v2} 超出范围 [{lo2}, {hi2}]")
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
    "copy": "抄写题：只判断 ① 内容是否与**题目末尾括号里的主题**相符；"
            "② 字数是否太少。**不评价**逻辑/推导/公式正误/是否抄全三项——"
            "转录来自照片识别，据此判错会冤枉学生。",
    "distinguish": "辨析题：看概念区分是否清晰、依据是否成立；允许表述简略，"
                   "但要有明确判断与理由。",
    "innovation": "创新题：看思考过程与独立见解；超纲设想只要自洽即可，不因超纲扣分。",
    "translation": "翻译题：**只看基本完成度**——是否真的翻译了、是否回答了题目所问、"
                   "字数是否达到题目要求；不逐词比对准确性，不苛求文采与术语。",
    "summary": "总结题：看主要概念/定理/定律（覆盖主要内容即可，不要求列全）、"
               "定义或公式（“/”表示或，二者其一即可）、概念关系与示意图；"
               "不因课程本身没有定理/定律而苛求。",
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
    elif mode == "topicMatch":
        ratio = t.get("shortRatioDeduct") or {}
        tiers = "；".join(f"不足 {float(r) * 100:.0f}% → −{v}"
                         for r, v in sorted(ratio.items(), key=lambda x: float(x[0])))
        lines.append(f"- **只做两件事**：① 抄写内容是否与**题目末尾括号里的主题**相符"
                     f"（不逐字对照 → 不符 −{t.get('topicMismatchDeduct', 20)}）；"
                     f"② 字数是否达到 {t.get('minChars', 80)} 字（{tiers}）。")
        ignored = "、".join(t.get("ignoredChecks") or [])
        if ignored:
            lines.append(f"- **不要评价**：{ignored}——转录来自照片识别，细节会失真，"
                         "据此判错会冤枉学生。")
    elif mode == "translation":
        lines.append(f"- **只判基本完成度**（D174 放宽）："
                     f"翻译完全不对 → −{t.get('translationWrongDeduct', 5)}；"
                     f"没有回答题目所问 → −{t.get('questionAnsweredDeduct', 5)}；"
                     f"字数少于题目要求 → −{t.get('shortAnswerDeduct', 10)}。")
        lines.append("- **不逐词比对译文准确性、不评价术语与文采**"
                     "——文学作品翻译无唯一标准答案，转录也有失真；"
                     "译文问题只在 `guidance` 里给出启发式提问。")
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


def rubric_enabled(ws, kind: str, chap: str = "") -> bool:
    """该 kind 是否允许生成 AI 评阅要点（**代码口径**，不再是规则卡开关）。

    D144：移除规则卡里的 `generateRubric` 开关——它挂在"评阅规则卡"里，
    但**批阅根本不读它**（批阅读 mode/扣分数值），只影响 `rules generate`
    要不要跳过某个题型，与「AI 作答时同时生成要点」又是另一套规则，极易误解。
    现在改为固定的代码规则，教师无需配置：

    - `copy`：**永不自动生成**（以原文为唯一依据，D130 口径）；
      确需生成用显式 `--force`；
    - `summary`（D134-T5a）：**仅当**本章有教师确认的 `知识点清单.md` 时才生成
      —— 没有资料时生成本章要点等于让模型编造"本章应该讲什么"，
      应改用保底口径（`summary_fallback`），而不是产出假依据；
    - 其它 kind：允许。
    """
    k = normalize_kind(kind)
    if k == "copy":
        return False
    if k == "summary":
        if ws is None:
            return False
        c = str(chap or "").strip()
        if not c:
            return False
        try:
            from ..files import materials as _mat
            return bool(_mat.read_knowledge_md(ws, c).strip())
        except Exception:  # noqa: BLE001 —— 资料缺失 = 不生成（不报错）
            return False
    return True


def summary_fallback(ws, kind: str = "summary") -> dict:
    """D134-T4：`summary` 的**保底口径**配置（无课堂资料时使用）。

    返回 `{}` 表示保底关闭（此时行为与 D130 完全一致）。
    """
    fb = type_rules(ws, normalize_kind(kind)).get("fallback") or {}
    if not isinstance(fb, dict) or not fb.get("enabled", True):
        return {}
    return {
        "enabled": True,
        "minChars": int(fb.get("minChars", 150) or 0),
        "minCharsDeduct": float(fb.get("minCharsDeduct", 0) or 0),
        "requireKnowledgeSummary": bool(fb.get("requireKnowledgeSummary", True)),
        "requireFormulaOrDerivation": bool(fb.get("requireFormulaOrDerivation", True)),
        "requireDiagram": fb.get("requireDiagram", "if_question_has"),
        "missingItemDeduct": float(fb.get("missingItemDeduct", 0) or 0),
    }
