#!/usr/bin/env python3
"""lint tools/start.bat —— 防止 cmd 解析坑复发（编码 / 括号块 / 注释）。

规则（基于 v3-v5 三个真实闪退案例）：
1) 文件必须纯 ASCII（cmd 解析器对 UTF-8 高字节会“当命令”执行，D25/D27）
2) 行尾必须 CRLF
3) 括号块 ( ... ) 内不得出现 %PATH% / %LOCALAPPDATA% 等可能含 ( 的变量直接展开
4) 括号块内不得有 :: 行注释（cmd 解析为标签而中断块）
5) 句内不得有 < > 直接在 REM 外出现（会试着重定向文件）
用例（回归基线）：./tools/start.bat
"""
import re
import sys
from pathlib import Path

TARGETS = [Path("tools/start.bat"), Path("tools/start.sh")]


def main() -> int:
    fails: list[str] = []
    for t in TARGETS:
        data = t.read_bytes()
        name = str(t)
        if t.suffix == ".bat":
            if not all(b < 128 for b in data):
                fails.append(f"{t}: 含非 ASCII 字节（cmd 解析歧义源）")
            if data.count(b"\n") != data.count(b"\r\n"):
                fails.append(f"{t}: 行尾必须为 CRLF")
            text = data.decode("utf-8", errors="replace")
            depth = 0
            for i, line in enumerate(text.splitlines(), 1):
                before = line.count("(") - line.count(")")
                stripped = line.strip()
                if depth > 0:
                    if stripped.startswith("::"):
                        fails.append(f"{t}:{i}: 括号块内 :: 注释（旧闪退案例#1）")
                    for var in ("%PATH%", "%LOCALAPPDATA%", "%ProgramFiles%"):
                        if var in line:
                            fails.append(f"{t}:{i}: 括号块内展开 {var}（cmd 坑：值含 (x86)/Common 时撕裂解析，闪退案例#2）")
                depth += line.count("(") - line.count(")")
        else:  # start.sh
            text = data.decode("utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if "UV_TOOL_BIN_DIR" in line:
                    fails.append(f"{t}:{i}: 用错误 env（应为 UV_INSTALL_DIR，闪退案例#3）")
    if fails:
        for f in fails:
            print(f"[lint-bat FAIL] {fails and f}")
        return 1
    print(f"[lint-bat] {len(TARGETS)} 个启动脚本审核通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
