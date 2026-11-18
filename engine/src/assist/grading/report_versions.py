"""D193 §3：批阅报告的**内容哈希版本**（不是文件名时间戳）。

设计目标（教师诉求：报告要与上传/分数对得上、新版覆盖旧版、历史可回溯）：

- 稳定路径：`reports/<学生>.md|.html|.png` **始终是最新**（覆盖写）——
  前端、上传、预览、历史引用都不用改路径；
- 版本号 = `sha256(markdown)[:6]`（内容哈希）→ **幂等**：内容没变不产生新版本，
  不会每点一次生成就多一份；
- 历史：`reports/.versions/<学生>/<YYYYmmdd-HHMMSS>-<ver>.{md,html,png}`；
- 索引：`reports/.versions/index.json`，记录
  `{student, version, ts, kind, score, sha256, reason, files}`；
- 草稿回写 `human.report = {version, sha256, generatedAt, file}`，
  上传清单与报告页脚用同一个版本号，教师能直接对照。

纯函数 + 文件操作，不依赖 playwright（PNG 由调用方渲染后交给 `record()`）。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

INDEX_NAME = "index.json"
VERSIONS_DIR = ".versions"
_MAX_KEEP = 30          # 每生最多保留的历史版本数（超出删最旧）
_SAFE = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+")


def safe_stem(name: str) -> str:
    """学生名 → 可用作文件名/目录名的稳定串（保留中文）。"""
    s = _SAFE.sub("_", str(name or "").strip()).strip(" ._")
    return s or "student"


def content_digest(md: str) -> str:
    """报告版本号：markdown 内容的 sha256 前 6 位（稳定、幂等、可校验）。"""
    return hashlib.sha256(str(md or "").encode("utf-8")).hexdigest()[:6]


def version_tag(ts: float | None = None, version: str = "") -> str:
    """人类可读版本标签：`20261118-140302-ab12cd`（报告页脚/清单展示用）。"""
    t = time.localtime(ts if ts is not None else time.time())
    return f"{time.strftime('%Y%m%d-%H%M%S', t)}-{str(version or '')[:6]}"


def read_index(reports_dir) -> dict:
    p = Path(reports_dir) / VERSIONS_DIR / INDEX_NAME
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 缺省/损坏都当作空索引
        return {"items": []}
    if not isinstance(data, dict):
        return {"items": []}
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    return data


def _write_index(reports_dir, data: dict) -> None:
    from ..filelock import atomic_write_text
    p = Path(reports_dir) / VERSIONS_DIR / INDEX_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps(data, ensure_ascii=False, indent=1))


def latest_entry(reports_dir, student: str) -> "dict | None":
    """某学生最新一条版本记录（没有则 None）。"""
    name = str(student or "")
    hits = [x for x in read_index(reports_dir).get("items") or []
            if isinstance(x, dict) and str(x.get("student") or "") == name]
    if not hits:
        return None
    return max(hits, key=lambda x: (float(x.get("ts") or 0), str(x.get("version") or "")))


def record(reports_dir, student: str, md: str, *, kind: str = "", score=None,
           reason: str = "", files: "list[Path] | None" = None,
           copy_files: "list[Path] | None" = None) -> dict:
    """登记一次报告生成；内容未变时**不产生新版本**（但仍刷新 mtime 与 latest）。

    参数：
      md         报告 markdown（版本号来源）
      files      本次写出的“最新”文件（md/html/png，会被复制进 .versions）
      copy_files 显式指定要归档的文件（缺省=files）
    返回：{version, sha256, tag, ts, changed, entry, latestFiles}
    """
    reports_dir = Path(reports_dir)
    version = content_digest(md)
    digest = hashlib.sha256(str(md or "").encode("utf-8")).hexdigest()
    ts = time.time()
    prev = latest_entry(reports_dir, student)
    changed = not (prev and str(prev.get("sha256") or "") == digest)
    tag = version_tag(ts, version)

    entry = {
        "student": str(student or ""),
        "version": version,
        "sha256": digest,
        "tag": tag,
        "ts": ts,
        "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
        "kind": str(kind or ""),
        "score": score if isinstance(score, (int, float)) else None,
        "reason": str(reason or ""),
        "files": [],
    }
    srcs = [Path(f) for f in (copy_files if copy_files is not None else (files or []))]
    if changed and srcs:
        stem = safe_stem(student)
        vdir = reports_dir / VERSIONS_DIR / stem
        vdir.mkdir(parents=True, exist_ok=True)
        for src in srcs:
            if not src.is_file():
                continue
            dst = vdir / f"{tag}{src.suffix}"
            try:
                dst.write_bytes(src.read_bytes())
                entry["files"].append(dst.name)
            except OSError:
                continue
        # 历史上限：超出删最旧
        olds = sorted([p for p in vdir.iterdir() if p.is_file()],
                      key=lambda p: p.stat().st_mtime)
        for p in olds[:max(0, len(olds) - _MAX_KEEP * 3)]:
            try:
                p.unlink()
            except OSError:
                pass

    data = read_index(reports_dir)
    items = [x for x in data.get("items") or []
             if isinstance(x, dict) and not (
                 str(x.get("student") or "") == str(student or "")
                 and str(x.get("sha256") or "") == digest)]
    items.append(entry)
    # 每生最多保留 _MAX_KEEP 条索引
    per: dict[str, list] = {}
    for x in items:
        per.setdefault(str(x.get("student") or ""), []).append(x)
    trimmed: list = []
    for _stu, rows in per.items():
        rows.sort(key=lambda x: float(x.get("ts") or 0), reverse=True)
        trimmed.extend(rows[:_MAX_KEEP])
    data["items"] = sorted(trimmed, key=lambda x: float(x.get("ts") or 0))
    try:
        _write_index(reports_dir, data)
    except Exception:  # noqa: BLE001 —— 索引落盘失败不影响报告本身
        pass
    return {"version": version, "sha256": digest, "tag": tag,
            "ts": int(ts), "changed": changed, "entry": entry,
            "latestFiles": [str(Path(f)) for f in (files or [])]}


def history(reports_dir, student: str) -> "list[dict]":
    """某生的版本历史（新→旧）。"""
    rows = [x for x in read_index(reports_dir).get("items") or []
            if isinstance(x, dict) and str(x.get("student") or "") == str(student or "")]
    return sorted(rows, key=lambda x: float(x.get("ts") or 0), reverse=True)
