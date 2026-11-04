"""fsview.py — D148：Atopia 的**通用只读文件能力**（`fs.ls` / `fs.read` / `fs.search`）。

为什么需要：D132 的工具白名单全是"特定任务命令"（kb.stats / materials.show / …），
**没有任何通用文件操作**。于是教师让 AI"找某题的参考答案"时，AI 只能绕着用
`materials.files`（它只列 `materials/<chap>/_source/`），根本翻不到别处。

教师诉求：AI 应该能"先找到文档、再打开查看"。

安全设计（**不削弱 D132**）：
- 仍然只登记这三个能力（白名单），不是"任意命令"；
- 路径**必须在 workspace 内**（复用 `path_in_ws` 语义，这里再独立校验一次）；
- **硬屏蔽**敏感路径：secrets / `.runtime` / `.git` / `atopia/limits.json`；
- **全为只读**：这三个函数不写任何文件；
- 行数/条数/字节上限，防把模型上下文撑爆；
- 二进制文件拒读（含 NUL 字节）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from loguru import logger

MAX_LIST = 300
MAX_READ_LINES = 200
MAX_READ_BYTES = 64 * 1024
MAX_SEARCH_HITS = 50
MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024

# 硬屏蔽：即使路径在 workspace 内也不许读
_BLOCKED_PARTS = {".runtime", ".git", "node_modules", ".venv", "__pycache__"}
_BLOCKED_NAMES = {"settings.local.secrets.json", "limits.json"}


class FSViewError(RuntimeError):
    """文件查看失败（可读的业务错误）。"""


def _resolve_in_ws(ws, path: str) -> Path:
    """把 `path` 解析到 workspace 内的绝对路径；越界/命中屏蔽一律拒绝。"""
    ws_p = Path(ws).resolve()
    raw = str(path or "").strip().lstrip("/\\") or "."
    p = (ws_p / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    try:
        rel = p.relative_to(ws_p)
    except ValueError:
        raise FSViewError(f"路径必须在 workspace 内：{path!r}") from None
    parts = set(rel.parts)
    if parts & _BLOCKED_PARTS:
        raise FSViewError(
            f"该路径属于受保护目录（{', '.join(sorted(parts & _BLOCKED_PARTS))}），不允许读取")
    if p.name in _BLOCKED_NAMES or p.name.endswith(".secrets.json"):
        raise FSViewError(f"{p.name} 属于敏感文件（可能含密钥），不允许读取")
    return p


def _is_binary(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            return b"\x00" in f.read(4096)
    except OSError:
        return False


def ls(ws, path: str = ".") -> dict:
    """列出目录内容（名称/类型/大小/修改时间）。"""
    p = _resolve_in_ws(ws, path)
    if not p.exists():
        raise FSViewError(f"路径不存在：{path}")
    if p.is_file():
        st = p.stat()
        return {"ok": True, "path": path, "type": "file", "bytes": st.st_size,
                "entries": []}
    entries: list[dict] = []
    try:
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except OSError as exc:
        raise FSViewError(f"无法读取目录：{exc}") from None
    for it in items[:MAX_LIST]:
        name = it.name
        if name in _BLOCKED_NAMES or name.endswith(".secrets.json"):
            continue
        if name in _BLOCKED_PARTS:
            continue
        try:
            st = it.stat()
            entries.append({
                "name": name,
                "type": "dir" if it.is_dir() else "file",
                "bytes": 0 if it.is_dir() else st.st_size,
            })
        except OSError:
            continue
    return {"ok": True, "path": path, "type": "dir", "count": len(entries),
            "truncated": len(list(p.iterdir())) > MAX_LIST, "entries": entries}


def read(ws, path: str, *, lines: int = MAX_READ_LINES) -> dict:
    """读文本文件（前 N 行 / 最多 64KB）。二进制拒读。"""
    p = _resolve_in_ws(ws, path)
    if not p.is_file():
        raise FSViewError(f"文件不存在：{path}")
    if _is_binary(p):
        raise FSViewError(f"{p.name} 像是二进制文件（含 NUL 字节），不读取")
    n = max(1, min(int(lines or MAX_READ_LINES), MAX_READ_LINES))
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            out: list[str] = []
            total = 0
            truncated = False
            for i, line in enumerate(f):
                if i >= n or total >= MAX_READ_BYTES:
                    truncated = True
                    break
                out.append(line)
                total += len(line.encode("utf-8", "replace"))
    except OSError as exc:
        raise FSViewError(f"读取失败：{exc}") from None
    return {"ok": True, "path": path, "lines": len(out), "bytes": total,
            "truncated": truncated, "text": "".join(out)}


def search(ws, query: str, *, glob: str = "", max_hits: int = MAX_SEARCH_HITS) -> dict:
    """在 workspace 内按关键词搜文件内容（返回 `文件:行:摘要`）。"""
    q = str(query or "").strip()
    if not q:
        raise FSViewError("搜索关键词不能为空")
    ws_p = Path(ws).resolve()
    pattern = str(glob or "").strip() or "*"
    hits: list[dict] = []
    scanned = 0
    for p in ws_p.rglob(pattern):
        if len(hits) >= max_hits:
            break
        try:
            rel = p.relative_to(ws_p)
        except ValueError:
            continue
        if set(rel.parts) & _BLOCKED_PARTS:
            continue
        if p.name in _BLOCKED_NAMES or p.name.endswith(".secrets.json"):
            continue
        if not p.is_file():
            continue
        try:
            if p.stat().st_size > MAX_SEARCH_FILE_BYTES:
                continue
        except OSError:
            continue
        if _is_binary(p):
            continue
        scanned += 1
        try:
            with p.open("r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if q in line:
                        hits.append({"file": str(rel).replace(os.sep, "/"),
                                     "line": i, "text": line.strip()[:200]})
                        if len(hits) >= max_hits:
                            break
        except OSError:
            continue
    return {"ok": True, "query": q, "scanned": scanned, "count": len(hits),
            "truncated": len(hits) >= max_hits, "hits": hits}
