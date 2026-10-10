"""D74-7：工作区云同步/网盘占用检测（只读提示，不杀进程、不移动文件）。

现场：工作区在 D:\\BaiduSyncdisk 下，更新引擎时复制不完整（D73-12）。
本模块只回答「是否疑似被同步盘/客户端影响」，由 start.bat / doctor / PWA 展示提示。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 路径关键字（小写匹配；同时覆盖中文目录名）
PATH_MARKERS = (
    "baidusyncdisk", "onedrive", "dropbox", "google drive", "googledrive",
    "iclouddrive", "nutstore", "坚果云", "weiyun", "微云",
)

# 进程名关键字 -> 展示名
PROCESS_NAMES = {
    "baidunetdisk": "百度网盘",
    "yundetectservice": "百度网盘",
    "onedrive": "OneDrive",
    "dropbox": "Dropbox",
    "nutstore": "坚果云",
    "weiyun": "微云",
}


def path_markers(ws: "Path | str") -> list[str]:
    """工作区路径命中的同步目录关键字（纯函数，可测）。"""
    text = str(ws).replace("\\", "/").lower()
    return [m for m in PATH_MARKERS if m in text]


def stale_markers(ws: "Path | str", limit: int = 20) -> list[str]:
    """同步未完成的临时文件（百度网盘的 *.baiduyun.p.downloading）。"""
    out: list[str] = []
    try:
        for p in Path(ws).rglob("*.baiduyun.p.downloading"):
            out.append(str(p))
            if len(out) >= limit:
                break
    except Exception:  # noqa: BLE001
        pass
    return out


def running_processes() -> list[str]:
    """检测正在运行的同步客户端（返回展示名，去重）。"""
    try:
        if sys.platform.startswith("win"):
            cp = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                                capture_output=True, text=True, timeout=15)
        else:
            cp = subprocess.run(["ps", "-eo", "comm="],
                                capture_output=True, text=True, timeout=10)
        text = (cp.stdout or "").lower()
    except Exception:  # noqa: BLE001
        return []
    found = {name for key, name in PROCESS_NAMES.items() if key in text}
    return sorted(found)


def detect(ws: "Path | str") -> dict:
    """综合检测；detected=True 表示建议提示用户暂停同步/退出客户端。"""
    pm = path_markers(ws)
    procs = running_processes()
    stale = stale_markers(ws)
    reasons: list[str] = []
    if pm:
        reasons.append("工作区位于同步目录：" + "、".join(pm))
    if procs:
        reasons.append("同步客户端运行中：" + "、".join(procs))
    if stale:
        reasons.append(f"存在未同步完成的文件 {len(stale)} 个")
    return {"detected": bool(pm or procs or stale), "reasons": reasons,
            "path_markers": pm, "processes": procs, "stale_markers": stale}
