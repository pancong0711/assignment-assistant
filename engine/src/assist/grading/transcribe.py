"""transcribe.py — 多模态转录：学生作业图片 → Markdown/LaTeX。

迁移自 _legacy/2601playwright/src/llm/transcriber.py：
- TRANSCRIPTION_PROMPT 逐段原样迁移（含 Markdown/LaTeX 精度与 JSON 转义要求）；
- 保留"JSON 清洗 ```json 围栏"+"解析重试"逻辑；
- 分组规则升级：文件名 <学生名|学号>[-_题号].png（ assort CLI 从本地目录读）。
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path

from loguru import logger

from .llm import LLMClient

# ---- prompt：原样迁移自 _legacy/2601playwright/src/llm/transcriber.py ----
TRANSCRIPTION_PROMPT = """你是一位物理作业转录助手。你的任务是将学生提交的手写作业图片精确转录为结构化 JSON。

要求：
1. 严格保留原始内容——不要修改、纠正或补充学生的答案
2. 数学公式用 LaTeX 行内公式 $...$ 和行间公式 $$...$$ 表示
3. 保持原有的题目编号和结构
4. 如果学生有手绘图表，用 ASCII 或文字描述标注 "[此处有手绘图表：...]"
5. 保留学生写下的所有文字，包括错误的内容（可以在批阅阶段处理）
6. 如果图片模糊或无法辨认，在对应位置标注 "[无法辨认]"
7. 输出严格 JSON 格式，包含 markdown 和 quality 两个字段：
{
  "markdown": "转录的 Markdown 内容",
  "quality": {
    "handwriting": "工整",
    "clarity": "清晰",
    "organization": "整洁"
  }
}
quality 字段说明：
  - handwriting: 字迹工整程度（工整/一般/潦草）
  - clarity: 图片清晰度（清晰/模糊）
  - organization: 排版整洁度（整洁/一般/杂乱）
8. 特别注意精度：
    - 仔细核对所有数字的小数点和位数
    - **幂指数（$10^n$、$e^n$ 等）的底数和指数必须逐字核对**
    - 区分大小写英文字母和希腊字母（V/v, ν, ρ 等）
    - 保留所有物理单位（m/s², J, Pa, K 等）和上下标
    - 公式中的每一处数字、符号、指数必须与原图逐字核对
9. 特别注意转义：JSON 字符串中的反斜杠必须写成 \\\\，例如 \\times 应写为 \\\\times，\\frac 应写为 \\\\frac。请检查输出 JSON 中所有反斜杠是否已正确转义"""

TRANSCRIBE_USER_TEXT = "请将这份物理作业图片转录为 Markdown 格式。"

# 转录解析重试（迁移旧 transcriber 的 5 次尝试逻辑，收敛为 3 次即可）
_TRANSCRIBE_ATTEMPTS = 3


def parse_llm_json(raw: str) -> dict:
    """清洗 ```json 围栏并解析（迁移自 transcriber._cleaned 逻辑）。"""
    cleaned = raw.strip()
    for p in ("```json", "```"):
        if cleaned.startswith(p):
            cleaned = cleaned[len(p):]
        if cleaned.endswith(p):
            cleaned = cleaned[:-len(p)]
    return json.loads(cleaned.strip())


def student_from_filename(fn: Path) -> str:
    """文件名 → 学生名：`姓名.png` / `学号-题号.png` / `姓名-1.png`。"""
    stem = fn.stem
    return re.split(r"[-_]", stem, maxsplit=1)[0] or "unknown"


def group_images(images_dir: Path) -> dict[str, list[Path]]:
    """把目录里的图片按学生名分组（文件名前缀相同即同一学生）。"""
    exts = (".png", ".jpg", ".jpeg", ".webp")
    groups: dict[str, list[Path]] = defaultdict(list)
    for f in sorted(Path(images_dir).iterdir()):
        if f.is_file() and f.suffix.lower() in exts:
            groups[student_from_filename(f)].append(f)
    return dict(groups)


def transcribe_student(client: LLMClient, images: list[Path], student: str,
                       out_dir: Path, model: str | None = None) -> Path:
    """转录单个学生的一组图片 → transcripts/<student>.json（含 v1 版本号）。"""
    last_err: Exception | None = None
    for attempt in range(_TRANSCRIBE_ATTEMPTS):
        try:
            raw = client.chat_with_images(
                system_prompt=TRANSCRIPTION_PROMPT,
                user_text=TRANSCRIBE_USER_TEXT,
                image_paths=[str(p) for p in images],
                model=model, temperature=0.1,
            )
            data = parse_llm_json(raw)
            break
        except Exception as e:  # noqa: BLE001 —— 沿用旧版"转录失败重试再判断"语义
            last_err = e
            if attempt < _TRANSCRIBE_ATTEMPTS - 1:
                logger.warning(f"转录[{student}] 第{attempt+1}次尝试失败: {e}")
                time.sleep(1)
    else:
        raise RuntimeError(f"转录失败[{student}]（重试{_TRANSCRIBE_ATTEMPTS}次）：{last_err}")

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{student}.json"
    data.update({
        "student": student,
        "model": model or client.transcription_model,
        "images": [p.name for p in images],
        "version": "assist-engine 0.1.0 (migrated from 2601playwright v0.3.0)",
        "_trans_version": 1,
        "timestamp": time.strftime("%Y-%m-%d %H:%M"),
    })
    # 姓名一致性预警（迁移自 transcriber._name_match）
    markdown_text = data.get("markdown", "") or ""
    data["_name_match"] = student in markdown_text
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if not data["_name_match"]:
        logger.warning(f"转录内容中未检测到学生姓名 '{student}'，请人工复核")
    return out
