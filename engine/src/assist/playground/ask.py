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
        key = p.get("api_key") or ""
        if not key:
            raise RuntimeError(f"provider「{provider}」未配置 api_key")
        settings = {"base_url": p.get("base_url"), "api_key": key,
                    "model": model or p.get("model") or ""}
        return LLMClient(settings=settings), (model or p.get("model") or "")
    ep = prov.stage_endpoint(ws, "evaluation")
    settings = {"base_url": ep.get("base_url"), "api_key": ep.get("api_key"),
                "model": model or ep.get("model") or ""}
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
          save: bool = True) -> dict:
    """批量：逐条独立调用（受控并发；无对话上下文）。

    同一组附件的文本块会拼进**每条**问题；图片附件也随每条发送。
    返回 {ok, groupId, results:[{question,answer,recordId,ok,error}]}。
    """
    qs = [str(q).strip() for q in (questions or []) if str(q).strip()]
    if not qs:
        return {"ok": False, "error": "没有问题可发送"}
    group = store.new_id()
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
