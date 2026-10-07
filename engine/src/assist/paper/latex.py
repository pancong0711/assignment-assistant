"""样题 LaTeX 渲染（可选依赖 xelatex）。

迁移自 _legacy/2603paperDesign/src/paperdesign/latextools.py（latexSample2603 及其
latexHead/latexOneProblem 系列）；xelatex 缺失时给出可操作的提示，不硬崩。
"""

import os
import subprocess
from pathlib import Path

from loguru import logger

from .. import ASSETS_DIR
from .tinytex import find_xelatex

_COPYRIGHT_NOTE = "迁移自 2603paperDesign latextools.py：LaTeX 样题页（可选依赖 xelatex）"

_EXPORT_HEADER = r"""\documentclass[12pt]{article}
\usepackage[UTF8]{ctex}
\usepackage{amsmath,amssymb,bm}
\usepackage{graphicx}
\usepackage[margin=2.2cm]{geometry}
\pagestyle{empty}
\begin{document}
"""

_EXPORT_FOOTER = "\n\\end{document}\n"


def check_xelatex(workspace: Path | str | None = None) -> str | None:
    """返回 xelatex 路径；优先系统 PATH，其次 workspace/.runtime/tex。

    TinyTeX 可选、不入仓库：设置中心/`assist tex install` 安装后，这里即可
    被 doctor / render_sample 复用（无需教师配置系统 PATH）。
    """
    return find_xelatex(workspace)


def render_sample(items: list[dict], out_dir: Path, fn_base: str = "paperProblems",
                  workspace: Path | str | None = None) -> Path | None:
    """items: [{content, img_path}] → LaTeX → PDF → PNG（1页样题图）。

    返回 PNG 路径；xelatex 缺失或编译失败返回 None 并给出提示。
    """
    exe = check_xelatex(workspace)
    if exe is None:
        logger.warning("未检测到 xelatex，跳过 LaTeX 样题渲染。"
                       "安装 TeX 后重试（体检页页脚有指引）。")
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    tex = [_EXPORT_HEADER]
    for i, item in enumerate(items, 1):
        content = str(item.get("content", "")).replace("\n", " ")
        img = item.get("img_path")
        tex.append(f"\\noindent {i}. {content}\n\\vspace{{1.2em}}\n")
        if img and Path(img).exists():
            tex.append("\\begin{center}\\includegraphics[width=0.8\\linewidth]{"
                       + Path(img).name + "}\\end{center}\n")
            # 图片需复制到工作目录以便相对引用
            import shutil as _sh
            _sh.copy2(img, out_dir / Path(img).name)
    tex.append(_EXPORT_FOOTER)
    tex_fn = out_dir / f"{fn_base}.tex"
    tex_fn.write_text("".join(tex), encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{Path(exe).parent}{os.pathsep}{env.get('PATH', '')}"
    rc = subprocess.call([exe, "-interaction=nonstopmode", tex_fn.name],
                         cwd=out_dir, env=env, stdout=subprocess.DEVNULL,
                         stderr=subprocess.STDOUT)
    pdf_fn = out_dir / f"{fn_base}.pdf"
    if rc != 0 or not pdf_fn.exists():
        logger.warning(f"LaTeX 编译失败（exit {rc}），见 {out_dir / (fn_base + '.log')}")
        return None
    logger.info(f"样题 PDF: {pdf_fn}")
    return pdf_fn
