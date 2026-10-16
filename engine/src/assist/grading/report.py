"""D86 §5：批阅报告（固定版式）+ 轻量批语图（A4 宽 / 小四 / 长图）。

版式（用户 2026-10-15 拍板）：两档 PNG 均为 **A4 纸宽（210mm）**；
轻量批语图字号 **小四（12pt）**；输出**长图**（`full_page`）。
渲染方法迁移自 `_legacy/2601playwright/src/report_generator.py`：
Markdown → HTML → Playwright 截图；公式改用**自托管 KaTeX**（离线可用，CDN 兜底）。

两档：
- 正式报告（AI/人工同版式，仅标注不同）→ `generate_report(..., kind="ai"|"human")`
- 轻量批语图（预览-学习通里的人工批阅）→ `render_comment_png(text, out, kind="human")`
"""
from __future__ import annotations

import html as _html
import json
import time
from pathlib import Path

from loguru import logger
from openpyxl import Workbook

A4_WIDTH_MM = 210
BODY_FONT_PT = 12          # 小四

REPORT_CSS = """
@page { size: A4; margin: 2cm; }
html, body { margin: 0; padding: 0; background: #fff; }
body { font-family: 'SimSun', 'Noto Sans SC', 'Microsoft YaHei', serif;
       font-size: 12pt; line-height: 1.8; box-sizing: border-box;
       width: 100%; padding: 18mm 15mm; color: #222; }
h1 { font-size: 18pt; text-align: center; border-bottom: 2px solid #333; padding-bottom: 8px; }
h2 { font-size: 15pt; margin-top: 20px; border-bottom: 1px solid #aaa; padding-bottom: 4px; }
h3 { font-size: 13pt; margin-top: 14px; }
table { width: 100%; border-collapse: collapse; margin: 10px 0; }
td, th { border: 1px solid #ccc; padding: 5px 8px; text-align: left; font-size: 11pt; }
th { background: #f0f0f0; }
.report-tag { text-align: center; font-size: 10pt; color: #666; margin: 4px 0 18px; }
.report-tag.human { color: #7a4b00; font-weight: 600; }
.report-tag.ai { color: #14532d; font-weight: 600; }
.revised { color: #c00000; font-weight: 600; }
.attach-head { text-align: center; font-size: 12pt; color: #333; margin: 18px 0 4px; }
.quality { color: #444; font-size: 10pt; }
"""

KIND_LABEL = {"ai": "AI 批阅报告", "human": "人工批阅报告",
              "ai-revised": "AI 批阅报告（人工修订）"}


def _md_to_html(md_text: str) -> str:
    try:                                   # 有 markdown 库则正规转换
        import markdown as _md
        return _md.markdown(md_text, extensions=["tables", "fenced_code"])
    except Exception:                      # noqa: BLE001 —— 无依赖时最小降级
        out = []
        for line in str(md_text or "").splitlines():
            t = line.rstrip()
            if t.startswith("### "):
                out.append(f"<h3>{_html.escape(t[4:])}</h3>")
            elif t.startswith("## "):
                out.append(f"<h2>{_html.escape(t[3:])}</h2>")
            elif t.startswith("# "):
                out.append(f"<h1>{_html.escape(t[2:])}</h1>")
            elif t.strip():
                out.append(f"<p>{_html.escape(t)}</p>")
        return "\n".join(out)


def find_katex_dir(explicit=None) -> "Path | None":
    """找自托管 KaTeX（离线渲染）：显式 > 仓库 app/public/katex > <ws>/assets/katex。"""
    cands = []
    if explicit:
        cands.append(Path(explicit))
    repo = Path(__file__).resolve().parents[4]
    cands.append(repo / "app" / "public" / "katex")
    try:
        from ..workspace import find_workspace
        cands.append(Path(find_workspace(None)) / "assets" / "katex")
    except Exception:  # noqa: BLE001
        pass
    for c in cands:
        if c and (c / "katex.min.css").is_file() and (c / "contrib" / "auto-render.min.js").is_file():
            return c
    return None


def _katex_head(katex_dir: "Path | None") -> str:
    if katex_dir:
        base = katex_dir.resolve().as_uri()
        return (f'<link rel="stylesheet" href="{base}/katex.min.css">'
                f'<script src="{base}/katex.min.js"></script>'
                f'<script src="{base}/contrib/auto-render.min.js"></script>')
    return ('<link rel="stylesheet" '
            'href="https://cdn.jsdelivr.net/npm/katex@0.16.4/dist/katex.min.css">'
            '<script src="https://cdn.jsdelivr.net/npm/katex@0.16.4/dist/katex.min.js"></script>'
            '<script src="https://cdn.jsdelivr.net/npm/katex@0.16.4/dist/contrib/auto-render.min.js"></script>')


def report_html(md_text: str, *, kind: str = "ai", title: str = "",
                subtitle: str = "", katex_dir: "Path | None" = None) -> str:
    """Markdown → 报告 HTML（A4 版式 + KaTeX + 来源标注）。"""
    body = _md_to_html(md_text)
    label = KIND_LABEL.get(str(kind or "ai").lower(), KIND_LABEL["ai"])
    h1 = f"<h1>{_html.escape(title)}</h1>" if title else ""
    sub = f'<div class="report-tag">{_html.escape(subtitle)}</div>' if subtitle else ""
    tag = f'<div class="report-tag {kind}">{label}</div>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{REPORT_CSS}</style>{_katex_head(katex_dir or find_katex_dir())}
</head><body>{h1}{tag}{sub}{body}
<script>
(function() {{
  function done() {{ window.__ASSIST_KATEX_DONE__ = true; }}
  if (window.renderMathInElement) {{
    try {{ renderMathInElement(document.body, {{delimiters: [
      {{left: '$$', right: '$$', display: true}},
      {{left: '$', right: '$', display: false}},
      {{left: '\\(', right: '\\)', display: false}},
      {{left: '\\[', right: '\\]', display: true}}]}}); }} catch (e) {{}}
    done();
  }} else {{ done(); }}
}})();
</script></body></html>"""


def html_to_png(html_text: str, out_path, *, width: int = 794, wait_ms: int = 5000) -> "Path | None":
    """HTML → 长图（Playwright Chromium，`full_page=True`）；缺 playwright 返回 None。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"未安装 playwright，跳过 PNG 渲染（{exc}）")
        return None
    with sync_playwright() as pw:
        from ..xxt.browsers import ARGS, launch_attempts
        browser = None
        last = None
        for kwargs in launch_attempts():
            try:
                browser = pw.chromium.launch(headless=True, args=ARGS, **kwargs)
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
        if browser is None:
            logger.warning(f"浏览器不可用，跳过 PNG：{last}")
            return None
        try:
            page = browser.new_page(viewport={"width": int(width), "height": 1123})
            page.set_content(html_text, wait_until="load")
            try:
                page.wait_for_function("() => window.__ASSIST_KATEX_DONE__ === true",
                                       timeout=wait_ms)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(600)
            page.screenshot(path=str(out), full_page=True)
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
    return out


def render_report_png(md_text: str, out_path, *, kind: str = "ai", title: str = "",
                      subtitle: str = "", katex_dir=None, width: int = 794):
    """Markdown → 报告 PNG（A4 宽 / 长图）。"""
    return html_to_png(report_html(md_text, kind=kind, title=title, subtitle=subtitle,
                                   katex_dir=katex_dir), out_path, width=width)


def render_comment_png(text: str, out_path, *, kind: str = "human", title: str = "",
                       subtitle: str = "", katex_dir=None, width: int = 794):
    """轻量批语图：纯文本/含 LaTeX 的批语 → PNG（A4 宽 / 小四 / 长图）。

    不追求正式报告的标题/分段落结构（仅可选 title/subtitle）。
    """
    lines = [f"<p>{_html.escape(x)}</p>" if x.strip() else "" for x in str(text or "").splitlines()]
    body = "\n".join(lines) or "<p>（空批语）</p>"
    label = KIND_LABEL.get(str(kind or "human").lower(), KIND_LABEL["human"])
    h1 = f"<h1>{_html.escape(title)}</h1>" if title else ""
    sub = f'<div class="report-tag">{_html.escape(subtitle)}</div>' if subtitle else ""
    html_text = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{REPORT_CSS}</style>{_katex_head(katex_dir or find_katex_dir())}
</head><body>{h1}<div class="report-tag {kind}">{label}</div>{sub}{body}
<script>
(function() {{
  if (window.renderMathInElement) {{
    try {{ renderMathInElement(document.body, {{delimiters: [
      {{left: '$$', right: '$$', display: true}},
      {{left: '$', right: '$', display: false}},
      {{left: '\\(', right: '\\)', display: false}}]}}); }} catch (e) {{}}
  }}
  window.__ASSIST_KATEX_DONE__ = true;
}})();
</script></body></html>"""
    return html_to_png(html_text, out_path, width=width)


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

def diff_mark(ai_text: str, revised_text: str) -> str:
    """D92-R2：把 revised_text 相对 ai_text 的**新增/改动行**包成 `[[R]]…[[/R]]` 标记。

    按行 diff（difflib）；公式块（含 $$ 或 $ 的行）整行为原子，不拆内部。
    返回带标记的纯文本（后续 _inline/md 渲染时把 [[R]]… 转 <span class="revised">）。
    """
    import difflib
    a = str(ai_text or "").splitlines()
    b = str(revised_text or "").splitlines()
    sm = difflib.SequenceMatcher(a=a, b=b)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.extend(b[j1:j2])
        else:  # replace / insert / delete → 标记为修订片段
            for ln in b[j1:j2]:
                out.append(f"[[R]]{ln}[[/R]]")
    return "\n".join(out)


def _mode_report_md(*, student: str, ai: dict, human: dict, human_mode: str,
                    revision: dict, revised: bool) -> "tuple[str, str]":
    """按 {构成 × 修订} 生成报告 markdown 与 kind（用于标注）。

    返回 (md, kind)；kind ∈ ai | ai-revised | human（human+ai 用分段自带标注）。
    """
    hm = str(human_mode or "none")
    ai_comment = str((ai or {}).get("comment") or "")
    rev_text = str((revision or {}).get("text") or "")
    # 只要存在"人工修订版"且与 AI 原文不同 → 用修订版并按行标红（适用于 ai / human+ai 构成）
    has_rev = bool(rev_text) and bool(revised)
    ai_body = rev_text if has_rev else ai_comment
    if has_rev:
        ai_body = diff_mark(ai_comment, rev_text)     # 标红标记
    ai_kind = "ai-revised" if has_rev else "ai"
    ai_score = (ai or {}).get("score")

    def _ai_section() -> "list[str]":
        head = ["# AI 批阅报告" + ("（人工修订）" if ai_kind == "ai-revised" else ""), ""]
        if ai_score is not None:
            head.append(f"**AI 评分：** {ai_score} / 100")
        head += ["", ai_body]
        return head

    def _human_section() -> "list[str]":
        head = ["# 人工批阅报告", ""]
        if (human or {}).get("score") is not None:
            head.append(f"**人工评分：** {human.get('score')} / 100")
        head += ["", str((human or {}).get("comment") or "")]
        return head

    lines: list[str] = []
    if hm == "human":
        lines += _human_section()
        return "\n".join(lines), "human"
    if hm in ("append", "replace") and (human or {}).get("used"):
        # 人工在前 + 【附件】AI 在后
        lines += _human_section()
        lines += ["", "---", "", "## 【附件】", ""]
        lines += _ai_section()
        return "\n".join(lines), "human"
    # 仅 AI（none / revise）
    lines += _ai_section()
    return "\n".join(lines), ai_kind


def report_html_from_md(md_text: str, *, kind: str = "ai", title: str = "",
                        subtitle: str = "", katex_dir=None) -> str:
    """同 report_html，但支持 [[R]]…[[/R]] 修订标红标记（D92）。"""
    body = _md_to_html(md_text)
    body = (body.replace("[[R]]", '<span class="revised">')
                .replace("[[/R]]", "</span>"))
    label = KIND_LABEL.get(str(kind or "ai").lower(), KIND_LABEL["ai"])
    h1 = f"<h1>{_html.escape(title)}</h1>" if title else ""
    sub = f'<div class="report-tag">{_html.escape(subtitle)}</div>' if subtitle else ""
    tag = f'<div class="report-tag {kind}">{label}</div>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{REPORT_CSS}</style>{_katex_head(katex_dir or find_katex_dir())}
</head><body>{h1}{tag}{sub}{body}
<script>
(function() {{
  function done() {{ window.__ASSIST_KATEX_DONE__ = true; }}
  if (window.renderMathInElement) {{
    try {{ renderMathInElement(document.body, {{delimiters: [
      {{left: '$$', right: '$$', display: true}},
      {{left: '$', right: '$', display: false}}]}}); }} catch (e) {{}}
    done();
  }} else {{ done(); }}
}})();
</script></body></html>"""


def generate_report(transcript_path: Path, eval_path: Path, out_dir: Path,
                    *, kind: str = "ai", subtitle: str = "", render_png: bool = True,
                    katex_dir=None) -> list[Path]:
    """一份学生报告：Markdown + HTML(**报告版式**) + PNG（A4 宽/长图；缺 playwright 时跳过）。

    `kind="ai"|"human"` → 报告标题下标注「AI 批阅报告 / 人工批阅报告」（同版式，仅标注不同）。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = Path(eval_path).stem
    md = build_report_md(transcript_path, eval_path)
    md_file = out / f"{base}.md"
    md_file.write_text(md, encoding="utf-8")
    html_file = out / f"{base}.html"
    title = f"{base} 批阅报告"
    html_file.write_text(report_html(md, kind=kind, title=title, subtitle=subtitle,
                                     katex_dir=katex_dir), encoding="utf-8")
    outs = [md_file, html_file]
    if render_png:
        png = render_report_png(md, out / f"{base}.png", kind=kind, title=title,
                                subtitle=subtitle, katex_dir=katex_dir)
        if png:
            outs.append(png)
    return outs


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
