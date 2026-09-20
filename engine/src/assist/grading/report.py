"""report.py — 批阅报告生成（Markdown + HTML MathJax）＋全局报告/汇总 xlsx。

迁移自 _legacy/2601playwright/src/report_generator.py：
- A4_CSS / MATHJAX_CDN / _build_report_md 结构照搬；
- HTML 公式用 MathJax CDN 渲染；
- PNG 截图（Playwright）属阶段4 —— 留 TODO 不实现；
- 汇总 xlsx 改用 openpyxl（去 pandas 依赖，不新增轮子）；
- MD→HTML 用内置轻量转换器（免新增 markdown 依赖；阶段4 如需更完整
  语法再按需引入库）。
"""

from __future__ import annotations

import html as _html
import json
import time
from pathlib import Path

from loguru import logger
from openpyxl import Workbook

# ---- 迁移自 report_generator.A4_CSS ----
A4_CSS = """
@page { size: A4; margin: 2cm; }
body {
    font-family: 'SimSun', 'Noto Sans SC', 'Microsoft YaHei', serif;
    font-size: 12pt; line-height: 1.8;
    width: 210mm; padding: 25mm; margin: 0 auto; color: #222;
}
h1 { font-size: 18pt; text-align: center; border-bottom: 2px solid #333; padding-bottom: 8px; }
h2 { font-size: 15pt; margin-top: 22px; border-bottom: 1px solid #aaa; padding-bottom: 4px; }
h3 { font-size: 13pt; margin-top: 16px; }
table { width: 100%; border-collapse: collapse; margin: 10px 0; }
td, th { border: 1px solid #ccc; padding: 5px 8px; text-align: left; font-size: 11pt; }
th { background: #f0f0f0; }
blockquote{ border-left:3px solid #d80; margin:8px 0; padding:4px 10px; background:#fff7ee; color:#8a4a00;}
.footer { text-align: center; color: #999; font-size: 10pt; margin-top: 30px; }
"""

# ---- 迁移自 report_generator.MATHJAX_CDN ----
MATHJAX_CDN = ('<script>MathJax={tex:{inlineMath:[["$","$"],["\\\\(","\\\\)"]]},chtml:{scale:1.2}};</script>'
               '<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>')


# ---- 迁移自 report_generator._build_report_md（2601 结构保留）----
def build_report_md(transcript_path: Path, eval_path: Path) -> str:
    t_data = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    e_data = json.loads(Path(eval_path).read_text(encoding="utf-8"))

    student = t_data.get("student") or e_data.get("student") or Path(transcript_path).stem
    homework = t_data.get("homework") or e_data.get("homework") or ""
    t_model = t_data.get("model", "?")
    e_model = e_data.get("model", "?")
    ts = e_data.get("timestamp") or t_data.get("timestamp") or time.strftime("%Y-%m-%d %H:%M")
    t_ver = t_data.get("_trans_version", 1)
    e_ver = e_data.get("_eval_version", 1)
    ver_str = f"转录 v{t_ver} / 评阅 v{e_ver}" if (t_ver > 1 or e_ver > 1) else ""

    score = e_data.get("total_score", 0)
    deductions = e_data.get("deductions", [])
    feedback_md = e_data.get("feedback_md", "")
    markdown_text = t_data.get("markdown", "")
    name_match = e_data.get("_name_match", t_data.get("_name_match", True))

    lines = ["# 作业批阅报告", ""]
    lines.append(f"**学生：** {student}")
    if e_data.get("_manual_review"):
        lines += ["> ⚠️ **需人工评阅**：AI 无法完成该作业评阅，请教师手动检查", ""]
    if not name_match:
        lines += [f"> ⚠️ **姓名预警**：转录内容中未检测到学生姓名 \"{student}\"，"
                  "可能图片与姓名不匹配，请人工检查", ""]
    # 阶段3 新增：顶替嫌疑就地告警（任务包绑定题目的合并收益点）
    if e_data.get("verdict") == "suspected-substitution":
        lines += ["> 🚨 **顶替嫌疑**：学生作答与作业纸题目不匹配，请教师人工核查", ""]
    if homework:
        lines.append(f"**作业：** {homework}")
    lines.append(f"**转录模型：** {t_model}  |  **评阅模型：** {e_model}")
    lines.append(f"**批阅时间：** {ts}")
    if ver_str:
        lines.append(f"**批阅版本：** {ver_str}")
    lines += ["", "---", "", "## 一、评分", "", f"**总分：{score} / 100**"]
    if deductions:
        lines += ["", "**扣分明细：**", *[f"- {d}" for d in deductions]]
    lines += ["", "---", "", "## 二、学生作答-转录", "", markdown_text,
              "", "---", ""]
    if feedback_md:
        lines += ["## 三、AI 评阅反馈", "", feedback_md, ""]
    lines += ["---", "*assist-engine 0.1.0 - AI 辅助批阅*", ""]
    return "\n".join(lines)


# ---- MD → HTML：轻量转换器（免新增 markdown 依赖）----
def _inline(text: str) -> str:
    """行内粗体/代码转义（保留 $...$ 原样给 MathJax）。"""
    text = _html.escape(text, quote=False)
    text = text.replace("**", "⟦B⟧")
    segs = text.split("⟦B⟧")
    for i in range(1, len(segs), 2):
        segs[i] = f"<strong>{segs[i]}</strong>"
    text = "".join(segs).replace("⟦B⟧", "")
    text = text.replace("`", "⟦C⟧")
    segs = text.split("⟦C⟧")
    for i in range(1, len(segs), 2):
        segs[i] = f"<code>{segs[i]}</code>"
    return "".join(segs).replace("⟦C⟧", "")


def md_to_html(md_text: str) -> str:
    """极简 Markdown → HTML（标题/列表/表格/引用/段落），公式交给 MathJax。"""
    out: list[str] = []
    in_table = False
    for block in md_text.split("\n\n"):
        block = block.strip("\n")
        if not block.strip():
            continue
        lines = block.split("\n")
        # 表格
        if len(lines) > 1 and "|" in lines[0] and lines[0].strip().startswith("|"):
            if in_table:
                out.append("</table>")
                in_table = False
            rows = []
            for ln in lines:
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                rows.append(cells)
            if rows and all(set(":-") >= set(c.replace("|", "")) for c in rows[1]) and rows[1]:
                rows.pop(1)
            out.append("<table>")
            head, *body = rows
            out.append("<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr>")
            for r in body:
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
            out.append("</table>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            if s.startswith("### "):
                out.append(f"<h3>{_inline(s[3:])}</h3>")
            elif s.startswith("## "):
                out.append(f"<h2>{_inline(s[3:])}</h2>")
            elif s.startswith("# "):
                out.append(f"<h1>{_inline(s[2:])}</h1>")
            elif s.startswith("> "):
                out.append(f"<blockquote>{_inline(s[2:])}</blockquote>")
            elif s in ("---", "***"):
                out.append("<hr>")
            elif s.startswith("- "):
                out.append(f"<li>{_inline(s[2:])}</li>")
            else:
                out.append(f"<p>{_inline(s)}</p>")
    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>批阅报告</title><style>{A4_CSS}</style>{MATHJAX_CDN}</head><body>
{''.join(out)}
</body></html>"""


# TODO(阶段4)：_html_to_png —— Playwright 截图（迁移自 report_generator._html_to_png），
# 依赖 Playwright 内核安装（D14 PLAYWRIGHT_BROWSERS_PATH），阶段4 一并实现 A4 PNG。

def generate_report(transcript_path: Path, eval_path: Path, out_dir: Path) -> list[Path]:
    """一份学生报告：Markdown + HTML（MathJax）。迁移自 report_generator.generate_report。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = Path(eval_path).stem
    md = build_report_md(transcript_path, eval_path)
    md_file = out / f"{base}.md"
    md_file.write_text(md, encoding="utf-8")
    html_file = out / f"{base}.html"
    html_file.write_text(md_to_html(md), encoding="utf-8")
    return [md_file, html_file]


def generate_summary_xlsx(eval_dir: Path, output_path: Path) -> Path:
    """全班汇总 xlsx（列结构沿用 report_generator.generate_summary_xlsx）。"""
    rows = []
    for f in sorted(Path(eval_dir).glob("[!_]*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if "_manual_review" in d and d.get("_manual_review") and not d.get("analysis"):
            rows.append((d.get("student", f.stem), d.get("total_score", 0),
                         "", "需人工评阅", ""))
            continue
        quality = d.get("quality", {}) or {}
        analysis = d.get("analysis", {}) or {}
        qs = analysis.get("questions", [])
        rows.append((
            d.get("student", f.stem),
            d.get("total_score", 0),
            f"{quality.get('handwriting', '?')}/{quality.get('clarity', '?')}/{quality.get('organization', '?')}",
            sum(len(q.get("errors", [])) for q in qs),
            d.get("verdict", "normal"),
        ))
    wb = Workbook()
    ws = wb.active
    ws.title = "批阅汇总"
    ws.append(["学生", "得分", "书写规范", "错误总数", "verdict"])
    for r in rows:
        ws.append(list(r))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


def generate_global_report(eval_dir: Path, out_dir: Path) -> Path:
    """全局报告 _global_report.md（迁移自 report_generator.generate_global_report 精简版）。"""
    records = []
    for f in sorted(Path(eval_dir).glob("[!_]*.json")):
        try:
            records.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"读取评阅文件失败，跳过 {f.name}: {e}")
    if not records:
        return None
    scores = [d.get("total_score", 0) or 0 for d in records]
    total = len(records)
    manual = sum(1 for d in records if d.get("_manual_review"))
    subst = sum(1 for d in records if d.get("verdict") == "suspected-substitution")
    segments = {"90-100": 0, "80-89": 0, "70-79": 0, "60-69": 0, "<60": 0}
    for s in scores:
        k = "90-100" if s >= 90 else "80-89" if s >= 80 else "70-79" if s >= 70 else "60-69" if s >= 60 else "<60"
        segments[k] += 1
    lines = [
        "# 批阅全局报告", "",
        f"**生成时间：** {time.strftime('%Y-%m-%d %H:%M')}",
        f"**已评阅学生：** {total} 人", "", "---", "",
        "## 一、统计概览", "",
        "| 指标 | 数值 |", "|------|------|",
        f"| 已评阅 | {total} 人 |",
        f"| 平均分 | {sum(scores)/total:.1f} |",
        f"| 最高分 | {max(scores)} |",
        f"| 最低分 | {min(scores)} |",
        f"| 需人工评阅 | {manual} 人 |",
        f"| 顶替嫌疑 | {subst} 人 |", "",
        "## 二、分数段分布", "",
        "| 分数段 | 人数 |", "|--------|------|",
    ]
    for seg in ("90-100", "80-89", "70-79", "60-69", "<60"):
        lines.append(f"| {seg} | {segments[seg]}人 |")
    lines += ["", "## 三、学生明细", "",
              "| 学生 | 分数 | 状态 |", "|------|------|------|"]
    for d in sorted(records, key=lambda x: x.get("student", "")):
        verdict = "顶替嫌疑" if d.get("verdict") == "suspected-substitution" else \
                  ("需人工" if d.get("_manual_review") else "OK")
        lines.append(f"| {d.get('student', '?')} | {d.get('total_score', 0)} | {verdict} |")
    lines += ["", "---", "*assist-engine 0.1.0 - 全局报告*", ""]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fn = out_dir / "_global_report.md"
    fn.write_text("\n".join(lines), encoding="utf-8")
    return fn
