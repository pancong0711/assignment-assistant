"""作业纸任务包 → PDF（阶段1）。

任务包即 CLI 的固化参数（05-D2：CLI 参数/Web 实体/执行历史三合一）。
schema 见 docs/04 §1：layout.orientation / per_page / items[{kb,chap,ids,tag}]。
"""

import json
from pathlib import Path

from loguru import logger

from ..files import read_kb
from ..files.roster import read_roster
from .layout import make_pdf


def load_task(task_path: Path) -> dict:
    return json.loads(Path(task_path).read_text(encoding="utf-8"))


def item_id_matches(chap: str, want, entry_id: str) -> bool:
    """D111：任务包 `ids` 可能存裸题号（历史）或全局 id（`chap04-01`）。

    判定：`want == entry_id` 或 `scope_question_id(chap, want) == entry_id`。
    这样历史作业纸（裸 id）与新数据（带前缀）都能命中，无需用户先迁移。
    """
    from ..files.kb_io import scope_question_id
    e = str(entry_id or "").strip()
    if not e:
        return False
    for w in want:
        ws = str(w or "").strip()
        if not ws:
            continue
        if ws == e or scope_question_id(chap, ws) == e:
            return True
    return False


def resolve_items(kb_data: dict, task_items: list[dict], kb_dir: Path,
                  numbering: str = "auto", seed: int | None = None,
                  target_tag: str = "") -> list[tuple]:
    """按任务包 items 展开 → [(content, img_abspath, tag, no)]。

    迁移自 _legacy/2603paperDesign/src/paperdesign/kbtools.py 的按 id 抽题逻辑
    （_oneChap：遍历题库 sheet，匹配 ids）；ids 为空则整章全收。
    no：题号，auto=整份连续编号，id=题库 id，labels=题包内的覆盖值。

    D93：按 tag 合成题（派生，不写入 task items）——
    - tag=summary：追加 1 道固定模板总结题（id=summary）；
    - kb=copy 且行有 page：题干改写"请抄写：{page}页 …，并画出示意图"；
    - tag/kb=translation：从 translation 题库用 seed **确定性随机**抽 1 道。
    切换 tag 时（items 里不再有该 tag）自然不再追加 → 合成题不残留。
    """
    from .compose import (SUMMARY_ID, SUMMARY_CONTENT, TRANSLATION_ID,
                          copy_content, pick_translation, seed_index)
    out: list[tuple] = []
    seq = 0
    seen_ids: set[str] = set()      # 去重：避免手工 + 自动重复
    translation_entries = [e for chs in (kb_data.get("translation") or {}).values() for e in chs]

    def _append(content, img, tag, no, qid):
        out.append((content, img, tag, no))
        if qid:
            seen_ids.add(str(qid))

    for spec in task_items:
        kind = spec.get("kb", "problems")
        chap = spec.get("chap")
        ids = spec.get("ids")
        tag = str(spec.get("tag", kind) or "")
        labels = spec.get("labels") if isinstance(spec.get("labels"), dict) else {}
        chapters = kb_data.get(kind, {})
        if chap:
            entries = list(chapters.get(chap, []))
        else:
            entries = [e for chs in chapters.values() for e in chs]
        if ids:
            # D111：兼容裸题号与带前缀 id
            entries = [e for e in entries if item_id_matches(chap or "", ids, e.get("id"))]
        for e in entries:
            seq += 1
            raw_id = e.get("id")
            qid = str(raw_id) if raw_id not in (None, "") else str(seq)
            # labels 可能以裸 id 或全局 id 为键，两种都查
            label_key = qid
            if not labels.get(label_key) and chap:
                bare = qid[len(str(chap)) + 1:] if str(qid).startswith(f"{chap}-") else qid
                if labels.get(bare):
                    label_key = bare
            no = str(labels.get(label_key) or "")
            if not no:
                no = qid if numbering == "id" else f"{seq}."
            img = e.get("img_path")
            if img and not str(img).startswith("/"):
                img = str(kb_dir / str(img))
            content = e.get("content")
            # D93-copy：抄写题有 page → 改写题干
            if kind == "copy" and e.get("page") not in (None, ""):
                content = copy_content(e.get("page"), content, qid)
            _append(content, img, tag, no, qid)

        # D93-summary：该 tag 命中 → 追加 1 道总结题（除非已手工加过 id=summary）
        if tag == "summary" and SUMMARY_ID not in seen_ids:
            seq += 1
            no = SUMMARY_ID if numbering == "id" else f"{seq}."
            _append(SUMMARY_CONTENT, None, tag or "summary", no, SUMMARY_ID)

        # D93-translation：tag/kb=translation → 用 seed 抽 1 道
        if (tag == "translation" or kind == "translation") and TRANSLATION_ID not in seen_ids:
            picked = pick_translation(translation_entries, int(seed or 0))
            if picked is not None:
                seq += 1
                no = TRANSLATION_ID if numbering == "id" else f"{seq}."
                _append(picked.get("content"), None, tag or "translation", no, TRANSLATION_ID)

    # D93：合成题统一收口（覆盖"仅设 target_tag、items 为空/无对应 tag 分组"的情况）——
    # 触发 tag = target_tag 优先，否则 items 里出现过的 tag。
    tags_present = {str(s.get("tag", s.get("kb", "")) or "") for s in task_items}
    tgt = str(target_tag or "")
    eff = tgt if tgt in ("summary", "translation") else ""
    want_summary = eff == "summary" or "summary" in tags_present
    want_translation = eff == "translation" or "translation" in tags_present
    if want_summary and SUMMARY_ID not in seen_ids:
        seq += 1
        no = SUMMARY_ID if numbering == "id" else f"{seq}."
        _append(SUMMARY_CONTENT, None, "summary", no, SUMMARY_ID)
    if want_translation and TRANSLATION_ID not in seen_ids:
        picked = pick_translation(translation_entries, int(seed or 0))
        if picked is not None:
            seq += 1
            no = TRANSLATION_ID if numbering == "id" else f"{seq}."
            _append(picked.get("content"), None, "translation", no, TRANSLATION_ID)

    if not out:
        logger.warning("任务包未选中任何题目")
    return out


def resolve_items_with_ids(kb_data: dict, task_items: list[dict], kb_dir: Path,
                           numbering: str = "auto", seed: int | None = None,
                           target_tag: str = "") -> list[tuple]:
    """D103-T8：与 `resolve_items` 同逻辑，但返回带**题库 id** 的 5 元组。

    教师版 PDF 需要按 qid 读 `effective_solution`（题号 no 不是 id）。
    返回 [(content, img_abspath, tag, no, qid)]。
    """
    from .compose import (SUMMARY_ID, SUMMARY_CONTENT, TRANSLATION_ID,
                          copy_content, pick_translation, seed_index)
    out: list[tuple] = []
    seq = 0
    seen_ids: set[str] = set()
    translation_entries = [e for chs in (kb_data.get("translation") or {}).values() for e in chs]

    for spec in task_items:
        kind = spec.get("kb", "problems")
        chap = spec.get("chap")
        ids = spec.get("ids")
        tag = str(spec.get("tag", kind) or "")
        labels = spec.get("labels") if isinstance(spec.get("labels"), dict) else {}
        chapters = kb_data.get(kind, {})
        entries = (list(chapters.get(chap, [])) if chap
                   else [e for chs in chapters.values() for e in chs])
        if ids:
            # D111：兼容裸题号与带前缀 id
            entries = [e for e in entries if item_id_matches(chap or "", ids, e.get("id"))]
        for e in entries:
            seq += 1
            raw_id = e.get("id")
            qid = str(raw_id) if raw_id not in (None, "") else str(seq)
            # labels 可能以裸 id 或全局 id 为键，两种都查
            label_key = qid
            if not labels.get(label_key) and chap:
                bare = qid[len(str(chap)) + 1:] if str(qid).startswith(f"{chap}-") else qid
                if labels.get(bare):
                    label_key = bare
            no = str(labels.get(label_key) or "")
            if not no:
                no = qid if numbering == "id" else f"{seq}."
            content = str(e.get("content") or "")
            if kind == "copy" and str(e.get("page") or "").strip():
                content = copy_content(str(e.get("page")), content, qid)
            img = str(e.get("img_path") or "")
            img_abs = str((kb_dir / img).resolve()) if img and not img.startswith("/") else img
            out.append((content, img_abs, tag, no, qid))
            seen_ids.add(qid)
        # 合成题（与 resolve_items 同口径）
        if tag == "summary" and SUMMARY_ID not in seen_ids:
            seq += 1
            out.append((SUMMARY_CONTENT, "", tag, f"{seq}." if numbering != "id" else SUMMARY_ID,
                        SUMMARY_ID))
            seen_ids.add(SUMMARY_ID)
    if str(target_tag or "") == "translation" or any(
            str(i.get("tag") or "") == "translation" for i in task_items):
        if TRANSLATION_ID not in seen_ids and translation_entries:
            chosen = pick_translation(translation_entries, seed_index(seed or 0, len(translation_entries)))
            seq += 1
            out.append((str(chosen.get("content") or ""), str(chosen.get("img_path") or ""),
                        "translation", f"{seq}." if numbering != "id" else TRANSLATION_ID,
                        str(chosen.get("id") or TRANSLATION_ID)))
            seen_ids.add(TRANSLATION_ID)
    return out


def sheets_from_task(task_path: Path, ws: Path, out_dir: Path | None = None,
                     title_default: str = "大学物理-作业纸", assets_dir=None,
                     no_watermark: bool = False,
                     roster_path: str | None = None,
                     user_cfg: dict | None = None,
                     teacher_mode: bool = False) -> list[Path]:
    """根据任务包生成每个学生一份 pdf。"""
    task = load_task(task_path)
    kb_dir = ws / "kb"
    kb_data = read_kb(kb_dir)
    lay = task.get("layout", {})
    if teacher_mode:
        # D103-T8：教师版需要参考答案（按**题库 id** 走 effective_solution：置顶版 > 最新版 > xlsx 列）
        from ..files.solutions import effective_solution
        base = resolve_items_with_ids(kb_data, task.get("items", []), kb_dir,
                                      str(lay.get("numbering") or "auto"),
                                      seed=task.get("random_seed"),
                                      target_tag=str(task.get("target_tag") or ""))
        items = []
        # D110：按 (kb, chap, qid) 作用域取答案（跨章同号不再串答案）
        refs = _resolved_refs(kb_data, task.get("items", []))
        for i, (content, img, tag, no, qid) in enumerate(base):
            kind, cname = refs[i] if i < len(refs) else ("", "")
            eff = (effective_solution(ws, str(qid), "", kb=kind, chap=cname)
                   if qid else {"text": ""})
            items.append((content, img, tag, no, str(eff.get("text") or "")))
    else:
        items = resolve_items(kb_data, task.get("items", []), kb_dir,
                              str(lay.get("numbering") or "auto"), seed=task.get("random_seed"),
                              target_tag=str(task.get("target_tag") or ""))
    orientation = lay.get("orientation", "portrait")
    title = lay.get("header", {}).get("title", title_default)
    fig = lay.get("figure") or {}
    figure_scale = float(fig.get("scale") or 1.0)
    figure_pos = str(fig.get("pos") or "rt")
    figure_max_w = float(fig.get("max_w_mm") or 45.0)
    figure_max_h = float(fig.get("max_h_mm") or 60.0)
    figure_indent = str(lay.get("indent") or "none")

    roster_fn = ws / task.get("class_dir", "classes") / "roster" / f"{task['id']}-roster.xlsx"
    if not roster_fn.parent.exists():
        roster_fn.parent.mkdir(parents=True, exist_ok=True)
    r_path = None
    if roster_path:
        r_path = Path(roster_path).expanduser().resolve()
    elif task.get("roster"):
        r_path = (ws / task["roster"]).resolve()
    if r_path is None or not r_path.exists():
        r_path = roster_fn if roster_fn.exists() else None
    if r_path is None:
        raise FileNotFoundError("缺少点名册：--roster 或 classes/<class>/roster/<id>-roster.xlsx")

    students = read_roster(r_path)
    if not students:
        raise ValueError(f"点名册为空: {r_path}")

    # D87：素材目录（explicit > <ws>/assets > engine/assets）+ 作业纸水印解析
    # 优先级：pad.watermark.items > pad.watermark.style_ref > 默认样式 > 内置三槽
    from .assets import resolve_assets_dir
    from .watermark_styles import resolve_pad_watermark
    resolved_assets, _src = resolve_assets_dir(ws=ws, explicit=assets_dir)
    task_wm = task.get("watermark") if isinstance(task.get("watermark"), dict) else {}
    wm_spec = resolve_pad_watermark(resolved_assets, task_wm)

    out = out_dir or (ws / task.get("class_dir", "classes") / "sheets" / "out")
    return make_pdf(
        students,
        lambda i: items, out,
        orientation=orientation,
        assets_dir=resolved_assets,
        title=title,
        notes_prefix=f"{task['id']}",
        watermark=not no_watermark,
        user_cfg=user_cfg,
        watermark_spec=wm_spec,
        workspace=ws,
        per_page=lay.get("per_page"),
        grid_rows=lay.get("grid_rows"),
        grid_cols=lay.get("grid_cols"),
        teacher_mode=teacher_mode,
        include_solution=teacher_mode,
        figure_scale=figure_scale,
        figure_pos=figure_pos,
        figure_max_w_mm=figure_max_w,
        figure_max_h_mm=figure_max_h,
        figure_indent=figure_indent,
    )


def roster_fn_exists(fn: Path) -> bool:
    return fn.exists()


def out_dir_mkdir(out: Path):
    Path(out).mkdir(parents=True, exist_ok=True)

def _resolved_refs(kb_data: dict, item_specs) -> list[tuple]:
    """与 resolve_items 同序的 `(kb, chap)` 列表（D110：供按作用域取答案）。"""
    out: list[tuple] = []
    for spec in item_specs or []:
        if not isinstance(spec, dict):
            continue
        kind = spec.get("kb", "problems")
        chap = spec.get("chap")
        want = [str(i) for i in (spec.get("ids") or [])]
        chapters = kb_data.get(kind, {})
        pairs = [(chap, chapters.get(chap, []))] if chap else list(chapters.items())
        for cname, entries in pairs:
            for e in entries:
                qid = str(e.get("id") or "")
                # D111：兼容裸题号（历史任务包）与全局 id
                if want and not item_id_matches(str(cname), want, qid):
                    continue
                out.append((kind, str(cname)))
    return out
