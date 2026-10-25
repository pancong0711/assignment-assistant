"""imageprep.py — D106：转录图片的分段压缩（压给模型，不动原图）。

背景：原实现把原图 base64 直发模型（`llm.py`），手机照片 3~8MB，
base64 后 +33% → 单张 4~10MB，导致请求体超限、视觉 token 浪费、批量慢。

分段策略（用户拍板）：
| 原始 | 处理 |
|---|---|
| 长边 ≤ MAX_SIDE_FREE(2000) 且 ≤ FREE_BYTES(2MB) | 原样发送 |
| ≤ 8MB | 长边 2000px，JPEG q88 |
| > 8MB | 长边 1600px，JPEG q85 |
| 原图本身就是小体积 PNG（线稿） | 保持 PNG（线条更清晰） |

**识图底线**：长边 ≥1280px、短边 ≥900px、体积 ≥300KB；
低于 ~120 DPI 等价时手写小字不可辨。

重要：**原文件永不修改**；压缩只作用于「送去模型的副本」，
并在返回元数据里记录 `{orig_bytes, sent_bytes, sent_side, strategy}`。
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Literal

from loguru import logger

MAX_SIDE_FREE = 2000          # 免压缩的长边上限
FREE_BYTES = 2 * 1024 * 1024  # 免压缩的体积上限（2MB）
BIG_BYTES = 8 * 1024 * 1024   # 超过则用更激进档
SIDE_MID = 2000
SIDE_SMALL = 1600

ImageMode = Literal["auto", "original"]


def _open_image(path: Path):
    from PIL import Image
    im = Image.open(path)
    im.load()
    return im


def compress_for_model(path: Path, mode: ImageMode = "auto") -> tuple[bytes, str, dict]:
    """返回 (bytes, mime, meta)。

    mode='original' → 原样返回（用于对比转录效果的老行为）。
    mode='auto'     → 按分段策略压缩（默认）。
    """
    p = Path(path)
    raw = p.read_bytes()
    orig_bytes = len(raw)
    mime_guess = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".webp": "image/webp", ".gif": "image/gif"}.get(p.suffix.lower(), "image/jpeg")

    if mode == "original":
        return raw, mime_guess, {"strategy": "original", "orig_bytes": orig_bytes,
                                 "sent_bytes": orig_bytes, "sent_side": None}

    try:
        im = _open_image(p)
    except Exception as exc:  # noqa: BLE001 —— 无法解码则原样发送（由模型侧报错）
        logger.warning(f"图片解码失败，按原图发送：{p}（{exc}）")
        return raw, mime_guess, {"strategy": "decode-failed", "orig_bytes": orig_bytes,
                                 "sent_bytes": orig_bytes, "sent_side": None}

    w, h = im.size
    long_side = max(w, h)
    is_png = mime_guess == "image/png"

    # 档位 1：原样（尺寸与体积都合格）
    if long_side <= MAX_SIDE_FREE and orig_bytes <= FREE_BYTES:
        meta = {"strategy": "passthrough", "orig_bytes": orig_bytes,
                "sent_bytes": orig_bytes, "sent_side": long_side}
        return raw, mime_guess, meta

    # 档位 2/3：按体积选目标长边
    target = SIDE_MID if orig_bytes <= BIG_BYTES else SIDE_SMALL
    scale = min(1.0, target / float(long_side or 1))
    new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    if new_size != (w, h):
        im = im.convert("RGB") if im.mode not in ("RGB", "L") else im
        im = im.resize(new_size, getattr(__import__("PIL.Image", fromlist=["Image"]), "LANCZOS"))

    buf = io.BytesIO()
    # 线稿（PNG 原图且体积尚可）保留 PNG；照片类走 JPEG 压体积
    use_png = is_png and orig_bytes <= BIG_BYTES
    if use_png:
        im.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    else:
        quality = 88 if orig_bytes <= BIG_BYTES else 85
        im.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
        mime = "image/jpeg"
    data = buf.getvalue()

    # 若压缩后反而更大（小图/已高度压缩），退回原图
    if len(data) >= orig_bytes:
        meta = {"strategy": "passthrough-after-resize", "orig_bytes": orig_bytes,
                "sent_bytes": orig_bytes, "sent_side": long_side}
        return raw, mime_guess, meta

    meta = {
        "strategy": "png-resize" if use_png else f"jpeg-q{quality if not use_png else 0}",
        "orig_bytes": orig_bytes,
        "sent_bytes": len(data),
        "orig_side": long_side,
        "sent_side": max(new_size),
        "ratio": round(len(data) / max(1, orig_bytes), 3),
    }
    logger.debug(f"图片压缩 {p.name}: {orig_bytes}→{len(data)} bytes, 长边 {long_side}→{max(new_size)}")
    return data, mime, meta
