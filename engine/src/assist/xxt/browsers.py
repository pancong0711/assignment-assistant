"""本机浏览器盘点与启动档位（D65-P0.1 / D65-P0.2）。

链序：① XXT_CHROME 显式路径 → ② 本机 msedge → ③ 本机 chrome
→ ④ 本机 chromium → ⑤ Playwright 自带完整版 chromium（新无头语义，不找
chromium-headless-shell）。

设计边界：
- 本机浏览器任一档可用时，Playwright 零内核下载；
- 启动必须显式给 channel / executable_path，避免 Playwright 在
  headless=True 且无 channel 时默认挑选 chromium-headless-shell；
- `inventory(probe=True)` 会真正启动一次做验证，doctor 不用“文件存在”冒充绿。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]


def _candidates() -> list[tuple[str, list[str]]]:
    """按优先级返回 (channel 名, 可执行文件候选路径/命令)。"""
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        lf = os.environ.get("LOCALAPPDATA", "")
        return [
            ("msedge", [rf"{pf86}\Microsoft\Edge\Application\msedge.exe",
                        rf"{pf}\Microsoft\Edge\Application\msedge.exe"]),
            ("chrome", [rf"{pf}\Google\Chrome\Application\chrome.exe",
                        rf"{pf86}\Google\Chrome\Application\chrome.exe",
                        (rf"{lf}\Google\Chrome\Application\chrome.exe" if lf else "")]),
        ]
    if sys.platform == "darwin":
        return [
            ("msedge", ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]),
            ("chrome", ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]),
        ]
    return [
        ("msedge", ["microsoft-edge", "microsoft-edge-stable"]),
        ("chrome", ["google-chrome", "google-chrome-stable"]),
        ("chromium", ["chromium", "chromium-browser"]),
    ]


def _find(cands: list[str]) -> "str | None":
    for c in cands:
        if not c:
            continue
        if c.startswith(("/", "\\")) or (len(c) > 1 and c[1] == ":"):
            if Path(c).exists():
                return c
        else:
            w = shutil.which(c)
            if w:
                return w
    return None


def _local_attempts() -> list[dict]:
    """有序本机档位；每项含内部 `_kwargs`，不直接暴露给 PWA。"""
    out: list[dict] = []
    v = os.environ.get("XXT_CHROME", "").strip()
    if v:
        p = _find([v])
        if p:
            out.append({
                "tier": 1, "kind": "env", "name": f"XXT_CHROME 指定：{Path(p).name}",
                "path": p, "_kwargs": {"executable_path": p},
            })
    for name, cands in _candidates():
        p = _find(cands)
        if not p:
            continue
        label = {
            "msedge": "本机 Microsoft Edge",
            "chrome": "本机 Google Chrome",
            "chromium": "本机 Chromium",
        }[name]
        out.append({
            "tier": 2 if name == "msedge" else 3,
            "kind": "channel", "name": label, "path": p,
            "_kwargs": {"channel": name, "executable_path": p},
        })
    return out


def launch_attempts() -> list[dict]:
    """有序 kwargs 列表：本机档位优先，最后回落到 Playwright 完整版。"""
    out = [it["_kwargs"] for it in _local_attempts()]
    out.append({"channel": "chromium"})  # D65-P0.2：完整版新无头，不用 headless shell
    return out


def _probe(kwargs: dict, timeout_ms: int = 20000) -> None:
    """真正启动一次并立刻关闭；失败抛出，供 doctor 的 probe=True 使用。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, timeout=timeout_ms, args=ARGS, **kwargs)
        browser.close()


def _public(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_")}


def inventory(probe: bool = False) -> dict:
    """盘点本机浏览器；probe=True 时逐档真启动，遇到首个可用档即停。"""
    attempts = _local_attempts()
    if not probe:
        tiers = [_public(it) for it in attempts]
        return {"tiers": tiers, "pick": tiers[0] if tiers else None}

    tiers: list[dict] = []
    pick: dict | None = None
    for item in attempts:
        pub = _public(item)
        try:
            _probe(item["_kwargs"])
            pub["verified"] = True
            tiers.append(pub)
            pick = pub
            break
        except Exception as e:  # noqa: BLE001
            pub["verified"] = False
            pub["error"] = str(e).replace("\n", " ")[:180]
            tiers.append(pub)
    return {"tiers": tiers, "pick": pick}
