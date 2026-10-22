"""D90-P1/P2：Playground 单次调用 + 批量。

- 无多轮对话上下文：每次独立 system+user；
- 附件：图片走多模态 data-url；文档先抽文本拼进 user；
- 复用 D86 provider/两段式（stage_endpoint("evaluation")）构造 LLMClient；
- 结果落 store（<ws>/playground/records/）。
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from . import extract, store

DEFAULT_SYSTEM = "你是一位严谨的助手。请直接、准确地回答用户问题；数学公式用 LaTeX（行内 $...$、行间 $$...$$）。"


def _client(ws: Path, provider: str = "", model: str = ""):
    """按 provider/model 构造 LLMClient。

    - 指定 provider：取其 base_url/key（providers.py），模型用传入或该 provider 默认；
    - 未指定：沿用 D86 「评阅段」endpoint（缺省 provider/模型）。
    """
    from ..grading.llm import LLMClient
    from ..grading import providers as prov
    if provider:
        p = prov.get_provider(ws, provider)
        if not p:
            raise RuntimeError(f"provider 不存在：{provider}")
        ptype = str(p.get("type") or "api")
        if ptype != "command":
            key = p.get("api_key") or ""
            if not key:
                raise RuntimeError(f"provider「{provider}」未配置 api_key")
        settings = {**p, "model": model or (p.get("models") or [""])[0] or ""}
        return LLMClient(settings=settings), (model or (p.get("models") or [""])[0] or "")
    ep = prov.stage_endpoint(ws, "evaluation")
    settings = {**ep, "model": model or ep.get("model") or ""}
    return LLMClient(settings=settings), (model or ep.get("model") or "")


def _build_user_text(question: str, attach_paths: "list[str] | None") -> "tuple[str, list[str], list[str]]":
    images, texts, notes = extract.build_attachment_block(attach_paths or [])
    blocks = [str(question or "").strip()]
    if texts:
        blocks.append("\n\n" + "\n\n".join(texts))
    if notes:
        blocks.append("\n\n（附件提示：" + "；".join(notes) + "）")
    return "".join(blocks), images, notes


def ask(ws: Path, *, question: str, provider: str = "", model: str = "",
        system: str = "", attachments: "list[str] | None" = None,
        temperature: float | None = None, max_tokens: int = 8192,
        folder: str = store.DEFAULT_FOLDER, save: bool = True,
        record_id: str = "", mode: str = "single", batch_group: str = "") -> dict:
    """单次调用：返回 {ok, answer, model, provider, recordId, error, notes}。"""
    q = str(question or "").strip()
    if not q and not attachments:
        return {"ok": False, "error": "请输入问题或添加附件"}
    user_text, images, notes = _build_user_text(q, attachments)
    try:
        client, used_model = _client(Path(ws), provider, model)
        if images:
            answer = client.chat_with_images(system or DEFAULT_SYSTEM, user_text, images,
                                             model=used_model or None,
                                             temperature=temperature, max_tokens=max_tokens,
                                             step="evaluation")
        else:
            answer = client.chat(system or DEFAULT_SYSTEM, user_text,
                                 model=used_model or None, temperature=temperature,
                                 max_tokens=max_tokens, step="evaluation")
        rec = {
            "id": record_id or store.new_id(),
            "folder": folder or store.DEFAULT_FOLDER,
            "provider": provider or "(评阅段)", "model": used_model,
            "temperature": temperature, "mode": mode, "batchGroup": batch_group,
            "question": q, "attachments": [Path(a).name for a in (attachments or [])],
            "answer": answer, "notes": notes, "error": "",
        }
        rid = ""
        if save:
            rid = store.save_record(ws, rec)["record"]["id"]
        else:
            rid = rec["id"]
        return {"ok": True, "answer": answer, "model": used_model, "provider": provider,
                "recordId": rid, "notes": notes}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"playground ask 失败: {type(exc).__name__}")
        msg = str(exc)[:300]
        if save:
            store.save_record(ws, {
                "id": record_id or store.new_id(), "folder": folder or store.DEFAULT_FOLDER,
                "provider": provider or "(评阅段)", "model": model, "mode": mode,
                "batchGroup": batch_group, "question": q,
                "attachments": [Path(a).name for a in (attachments or [])],
                "answer": "", "notes": notes, "error": msg})
        return {"ok": False, "error": msg, "notes": notes}


def batch(ws: Path, *, questions: "list[str]", provider: str = "", model: str = "",
          system: str = "", attachments: "list[str] | None" = None,
          temperature: float | None = None, max_tokens: int = 8192,
          folder: str = store.DEFAULT_FOLDER, workers: int = 3,
          save: bool = True, combine: bool = False) -> dict:
    """批量：默认逐条独立调用（受控并发）；`combine=True` 合并为**一次**请求。

    - 逐条模式：同一组附件会对**每条**问题重复发送（图片 token 最贵）；
    - 合并模式（省 token）：把问题编号后拼进一次请求，附件只发一遍，要求模型按
      `[Q1]/[Q2]` 分段回答，再按编号拆回；附件多、问题多时显著省 token。
      代价：单次上下文更长、单点失败会整批失败（不适合超多问题）。
    返回 {ok, groupId, results:[{question,answer,recordId,ok,error}], mode}。
    """
    qs = [str(q).strip() for q in (questions or []) if str(q).strip()]
    if not qs:
        return {"ok": False, "error": "没有问题可发送"}
    group = store.new_id()
    if combine:
        return _batch_combined(ws, qs, group=group, provider=provider, model=model,
                               system=system, attachments=attachments,
                               temperature=temperature, max_tokens=max_tokens,
                               folder=folder, save=save)
    # 预先抽取附件（文本 + 图片），避免每条重复解析
    images, texts, notes = extract.build_attachment_block(attachments or [])
    try:
        client, used_model = _client(Path(ws), provider, model)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}

    from concurrent.futures import ThreadPoolExecutor

    def one(i: int, q: str) -> dict:
        user_text = q
        if texts:
            user_text += "\n\n" + "\n\n".join(texts)
        if notes:
            user_text += "\n\n（附件提示：" + "；".join(notes) + "）"
        rid = store.new_id()
        try:
            if images:
                ans = client.chat_with_images(system or DEFAULT_SYSTEM, user_text, images,
                                              model=used_model or None, temperature=temperature,
                                              max_tokens=max_tokens, step="evaluation")
            else:
                ans = client.chat(system or DEFAULT_SYSTEM, user_text, model=used_model or None,
                                  temperature=temperature, max_tokens=max_tokens, step="evaluation")
            if save:
                store.save_record(ws, {"id": rid, "folder": folder or store.DEFAULT_FOLDER,
                                       "provider": provider or "(评阅段)", "model": used_model,
                                       "mode": "batch", "batchGroup": group, "question": q,
                                       "attachments": [Path(a).name for a in (attachments or [])],
                                       "answer": ans, "error": ""})
            return {"ok": True, "question": q, "answer": ans, "recordId": rid}
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)[:200]
            if save:
                store.save_record(ws, {"id": rid, "folder": folder or store.DEFAULT_FOLDER,
                                       "provider": provider or "(评阅段)", "model": used_model,
                                       "mode": "batch", "batchGroup": group, "question": q,
                                       "attachments": [Path(a).name for a in (attachments or [])],
                                       "answer": "", "error": msg})
            return {"ok": False, "question": q, "error": msg, "recordId": rid}

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, min(8, int(workers or 3)))) as ex:
        for r in ex.map(lambda p: one(*p), list(enumerate(qs))):
            results.append(r)
    ok_n = sum(1 for r in results if r.get("ok"))
    return {"ok": True, "groupId": group, "model": used_model, "total": len(qs),
            "succeeded": ok_n, "results": results}


def _split_combined(answer: str, n: int) -> list[str]:
    """按 `[Q1]/[Q2]…` 标记把合并回答拆回 n 段；缺标记时退化为整段给第 1 题。"""
    import re
    if not answer:
        return [""] * n
    parts: list[str] = [""] * n
    # 匹配 [Q1] / 【Q1】 / Q1. 等常见写法
    marks = list(re.finditer(r"(?:\[|【)?\s*Q\s*(\d+)\s*(?:\]|】)?\s*[:：.]?", answer))
    found = {int(m.group(1)) for m in marks}
    if not marks or not all(1 <= i <= n for i in found):
        parts[0] = answer.strip()
        return parts
    for idx, m in enumerate(marks):
        qno = int(m.group(1))
        if not (1 <= qno <= n):
            continue
        start = m.end()
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(answer)
        parts[qno - 1] = answer[start:end].strip()
    return parts


def _batch_combined(ws: Path, qs: list[str], *, group: str, provider: str, model: str,
                    system: str, attachments: "list[str] | None",
                    temperature, max_tokens: int, folder: str, save: bool) -> dict:
    """合并模式：一次请求回答全部问题，附件只发一遍（省 token）。"""
    images, texts, notes = extract.build_attachment_block(attachments or [])
    try:
        client, used_model = _client(Path(ws), provider, model)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}

    lines = [f"[Q{i + 1}] {q}" for i, q in enumerate(qs)]
    user_text = ("请依次回答下面的每一个问题，并在每条回答开头用对应的 [Q编号] 标记，"
                 "不要省略任何一题：\n\n" + "\n\n".join(lines))
    if texts:
        user_text += "\n\n" + "\n\n".join(texts)
    if notes:
        user_text += "\n\n（附件提示：" + "；".join(notes) + "）"

    try:
        if images:
            answer = client.chat_with_images(system or DEFAULT_SYSTEM, user_text, images,
                                             model=used_model or None, temperature=temperature,
                                             max_tokens=max_tokens, step="evaluation")
        else:
            answer = client.chat(system or DEFAULT_SYSTEM, user_text,
                                 model=used_model or None, temperature=temperature,
                                 max_tokens=max_tokens, step="evaluation")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:300]
        if save:
            store.save_record(ws, {"id": store.new_id(), "folder": folder or store.DEFAULT_FOLDER,
                                   "provider": provider or "(评阅段)", "model": used_model,
                                   "mode": "batch", "batchGroup": group,
                                   "question": " / ".join(qs),
                                   "attachments": [Path(a).name for a in (attachments or [])],
                                   "answer": "", "error": msg})
        return {"ok": False, "error": msg, "mode": "combine"}

    parts = _split_combined(answer, len(qs))
    results: list[dict] = []
    for i, q in enumerate(qs):
        rid = store.new_id()
        ans = parts[i]
        if save:
            store.save_record(ws, {"id": rid, "folder": folder or store.DEFAULT_FOLDER,
                                   "provider": provider or "(评阅段)", "model": used_model,
                                   "mode": "batch", "batchGroup": group, "question": q,
                                   "attachments": [Path(a).name for a in (attachments or [])],
                                   "answer": ans, "error": ""})
        results.append({"ok": bool(ans), "question": q, "answer": ans, "recordId": rid})
    return {"ok": True, "groupId": group, "model": used_model, "mode": "combine",
            "total": len(qs), "succeeded": sum(1 for r in results if r["ok"]),
            "results": results}


# ---------------- D98：items 模式（每条自带文字 + 图片，互不重复） ----------------

def batch_items(ws: Path, *, items: list[dict], provider: str = "", model: str = "",
                system: str = "", temperature: float | None = None, max_tokens: int = 8192,
                folder: str = store.DEFAULT_FOLDER, workers: int = 3,
                save: bool = True) -> dict:
    """批量：**每条 item 自带 `question` 与 `images`**，逐条独立请求、互不共享。

    与 `batch(combine=...)` 的区别：
    - `batch` = 同一组附件 + 多个问题（附件会重复或合并）；
    - `batch_items` = 每条各附各的图/文，**不会把 A 条的图/题干带到 B 条**（结构性隔离）。

    item 结构见 `grading/items.py`（`normalize_items`）。返回
    {ok, groupId, mode:"items", total, succeeded, results:[{id,question,answer,recordId,ok,error}]}。
    """
    from ..grading.batchrun import run_items
    from ..grading.items import ItemsError, image_files, normalize_items

    try:
        norm = normalize_items(items)
    except ItemsError as exc:
        return {"ok": False, "error": str(exc)}
    if not norm:
        return {"ok": False, "error": "没有可发送的 item"}

    try:
        client, used_model = _client(Path(ws), provider, model)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}

    group = store.new_id()

    def worker(it: dict) -> dict:
        q = str(it.get("question") or "").strip()
        imgs = [str(p) for p in image_files(it)]
        # 本条只读本条内容；不引用其它 item
        user_text = q
        notes = []
        missing = len(it.get("images") or []) - len(imgs)
        if missing:
            notes.append(f"{missing} 张图片不存在已跳过")
        if notes:
            user_text += "\n\n（附件提示：" + "；".join(notes) + "）"
        rid = store.new_id()
        item_system = it.get("system") or system or DEFAULT_SYSTEM
        item_model = it.get("model") or used_model or None
        try:
            if imgs:
                ans = client.chat_with_images(item_system, user_text, imgs, model=item_model,
                                              temperature=temperature, max_tokens=max_tokens,
                                              step="evaluation")
            else:
                ans = client.chat(item_system, user_text, model=item_model,
                                  temperature=temperature, max_tokens=max_tokens,
                                  step="evaluation")
        except Exception as exc:  # noqa: BLE001 —— 单条失败标记，继续其余
            msg = str(exc)[:300]
            if save:
                store.save_record(ws, {"id": rid, "folder": folder or store.DEFAULT_FOLDER,
                                       "provider": provider or "(评阅段)", "model": used_model,
                                       "mode": "batch-items", "batchGroup": group,
                                       "question": q,
                                       "attachments": [Path(p).name for p in it.get("images") or []],
                                       "answer": "", "error": msg})
            return {"ok": False, "id": it["id"], "question": q, "error": msg, "recordId": rid}
        if save:
            store.save_record(ws, {"id": rid, "folder": folder or store.DEFAULT_FOLDER,
                                   "provider": provider or "(评阅段)", "model": used_model,
                                   "mode": "batch-items", "batchGroup": group, "question": q,
                                   "attachments": [Path(p).name for p in it.get("images") or []],
                                   "answer": ans, "notes": notes, "error": ""})
        return {"ok": True, "id": it["id"], "question": q, "answer": ans, "recordId": rid,
                "notes": notes, "images": len(imgs)}

    report = run_items(norm, worker, kind="playground-items",
                       concurrency=max(1, min(8, int(workers or 3))))
    results = []
    for it in report.get("items") or []:
        r = {k: v for k, v in it.items() if k not in ("status",)}
        r["ok"] = it.get("status") == "ok"
        results.append(r)
    return {"ok": True, "groupId": group, "mode": "items", "model": used_model,
            "total": report["total"], "succeeded": report["ok"], "results": results}
