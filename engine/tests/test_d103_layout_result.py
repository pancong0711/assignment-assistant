"""D103：CLI 复用 PWA 预排版结果（`layout_result`）渲染 MxN 网格 + 答案续格。"""
import json
from pathlib import Path

from click.testing import CliRunner
from openpyxl import Workbook

from assist.cli import cli


def _mk_ws(ws: Path) -> None:
    kb = ws / "kb"; kb.mkdir(parents=True, exist_ok=True)
    wb = Workbook(); sh = wb.active; sh.title = "chap04"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["q1", "题干一", "", 1, "", "计算", "答案一", ""])
    sh.append(["q2", "题干二", "", 1, "", "计算", "答案二", ""])
    wb.save(kb / "problems.xlsx")


def _task(ws: Path, layout_result=None) -> Path:
    task = {
        "id": "d103", "class_dir": "classes/classA", "course": "大学物理", "class": "classA",
        "layout": {"orientation": "landscape", "per_page": 2, "grid_rows": 1, "grid_cols": 2,
                   "header": {"title": "D103"}},
        "items": [{"kb": "problems", "chap": "chap04", "ids": ["q1", "q2"], "tag": "t"}],
        "watermark": {"enabled": False}, "grade": {},
    }
    if layout_result is not None:
        task["layout_result"] = layout_result
    fn = ws / "task.json"
    fn.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    return fn


def _layout(*pages) -> dict:
    """构造 layout_result（pages = 每页的 cells 列表）。"""
    return {
        "v": 1, "measuredAt": "2026-10-24T00:00:00Z", "contentHash": "fnv1a:abc:1",
        "geometry": {"cellW": 478, "cellH": 290, "rows": 1, "cols": 2},
        "pages": [{"page": i + 1, "cells": cells} for i, cells in enumerate(pages)],
    }


def _render(ws: Path, task: Path) -> str:
    out = ws / "o.html"
    r = CliRunner().invoke(cli, ["sheet", "html", "--task", str(task),
                                 "--workspace", str(ws), "-o", str(out), "--students", "blank", "--no-measure"])
    assert r.exit_code == 0, r.output
    return out.read_text(encoding="utf-8")


def test_no_layout_result_falls_back_to_grid(tmp_path):
    """无 layout_result → 旧行为（MxN 网格 + 整题渲染）。"""
    ws = tmp_path / "ws"; _mk_ws(ws)
    html = _render(ws, _task(ws))
    assert 'data-layout' not in html
    assert 'data-cell=' not in html
    assert ".sheet-body { flex: 1; display: grid;" in html


def test_layout_result_renders_cells_and_continuation(tmp_path):
    """有 layout_result → 按格渲染；续格出现「（题 N 续）」标注。"""
    ws = tmp_path / "ws"; _mk_ws(ws)
    layout = _layout(
        [  # 第 1 页：左格 q1 题干+答案首段；右格 q2
            {"row": 0, "col": 0, "blocks": [
                {"qid": "q1", "no": "1.", "kind": "content", "text": "题干一", "cont": False},
                {"qid": "q1", "no": "1.", "kind": "solution", "text": "答案一（前半）", "cont": False},
            ]},
            {"row": 0, "col": 1, "blocks": [
                {"qid": "q2", "no": "2.", "kind": "content", "text": "题干二", "cont": False},
                {"qid": "q2", "no": "2.", "kind": "solution", "text": "答案二", "cont": False},
            ]},
        ],
        [  # 第 2 页：q1 答案续段
            {"row": 0, "col": 0, "blocks": [
                {"qid": "q1", "no": "1.", "kind": "solution", "text": "答案一（后半）", "cont": True},
            ]},
        ],
    )
    html = _render(ws, _task(ws, layout))
    # 按格渲染
    assert 'data-cell="0,0"' in html and 'data-cell="0,1"' in html
    assert 'data-qid="q1"' in html and 'data-qid="q2"' in html
    # 内容完整（前后两段都在）
    assert "答案一（前半）" in html and "答案一（后半）" in html
    # 续格标注
    assert "（题 1 续）" in html
    # MxN 网格与虚线仍在
    assert "display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));" in html
    assert 'class="sf-line v"' in html
    # 页数按排版结果（2 页），而不是按 per_page 切片（2 题 = 1 页）
    assert html.count('<section class="sheet-page') == 2


def test_layout_result_scaled_formula(tmp_path):
    """超高行间公式的 scale 透传到 HTML。"""
    ws = tmp_path / "ws"; _mk_ws(ws)
    layout = _layout([
        {"row": 0, "col": 0, "blocks": [
            {"qid": "q1", "no": "1.", "kind": "content", "text": "题干一", "cont": False},
            {"qid": "q1", "no": "1.", "kind": "solution", "text": "$$x=1$$", "cont": False, "scale": 0.6},
        ]},
    ])
    html = _render(ws, _task(ws, layout))
    assert "transform:scale(0.6)" in html


def test_layout_result_empty_pages_falls_back(tmp_path):
    """layout_result 存在但 pages 为空 → 回退旧网格（防止空白作业纸）。"""
    ws = tmp_path / "ws"; _mk_ws(ws)
    html = _render(ws, _task(ws, {"v": 1, "pages": []}))
    assert 'data-cell=' not in html
    assert "题干一" in html


def test_layout_result_respects_no_solution(tmp_path):
    """--no-solution 时格内不渲染答案（即使 layout_result 含答案块）。"""
    ws = tmp_path / "ws"; _mk_ws(ws)
    layout = _layout([{"row": 0, "col": 0, "blocks": [
        {"qid": "q1", "no": "1.", "kind": "content", "text": "题干一", "cont": False},
        {"qid": "q1", "no": "1.", "kind": "solution", "text": "答案一", "cont": False},
    ]}])
    out = ws / "o.html"
    r = CliRunner().invoke(cli, ["sheet", "html", "--task", str(_task(ws, layout)),
                                 "--workspace", str(ws), "-o", str(out),
                                 "--students", "blank", "--no-measure", "--no-solution"])
    assert r.exit_code == 0, r.output
    html = out.read_text(encoding="utf-8")
    assert "题干一" in html
    assert "参考答案" not in html


# ---------------- T8：PDF 教师版（一题一页 + 完整答案 + 续页） ----------------

def test_teacher_pdf_one_question_per_page_with_solution(tmp_path):
    """教师版：每页一题、含参考答案（走 effective_solution 置顶版）、页码正确。"""
    from openpyxl import Workbook as Wb
    from pypdf import PdfReader
    from assist.files import solutions as sol
    from assist.paper.task import sheets_from_task

    ws = tmp_path / "ws"; _mk_ws(ws)
    sol.add_version(ws, "q1", "AI 置顶答案正文", source="ai")
    sol.pin_version(ws, "q1", "v1")
    task = json.loads(_task(ws).read_text(encoding="utf-8"))
    task["layout"] = {"orientation": "portrait", "per_page": 2}
    task.pop("layout_result", None)
    (ws / "task.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    rw = Wb(); r = rw.active; r.append(["姓名", "学号", "班级"]); r.append(["学生A", "1", "cA"])
    rw.save(ws / "roster.xlsx")

    files = sheets_from_task(ws / "task.json", ws, out_dir=ws / "out",
                             roster_path=str(ws / "roster.xlsx"), teacher_mode=True)
    assert files, "应生成 PDF"
    rd = PdfReader(str(files[0]))
    assert len(rd.pages) == 2, f"2 题应 = 2 页（一题一页），实际 {len(rd.pages)}"
    all_text = "\n".join((p.extract_text() or "") for p in rd.pages)
    assert "AI 置顶答案正文" in all_text, "教师版必须含参考答案（且用置顶版）"
    # 页码正确（第 N/2 页）
    assert "第1/2页" in all_text and "第2/2页" in all_text


def test_teacher_pdf_long_solution_continues_pages(tmp_path):
    """超长答案 → 自动续页；后续题目顺延（不丢内容）。"""
    from pypdf import PdfReader
    from assist.paper.task import sheets_from_task
    ws = tmp_path / "ws"; _mk_ws(ws)
    long_sol = "很长的解答。" * 2000   # 足够长以触发续页
    from assist.files import solutions as sol
    sol.add_version(ws, "q1", long_sol, source="ai"); sol.pin_version(ws, "q1", "v1")
    task = json.loads(_task(ws).read_text(encoding="utf-8"))
    task["layout"] = {"orientation": "portrait", "per_page": 2}
    task["items"][0]["ids"] = ["q1"]
    (ws / "task.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    from openpyxl import Workbook as Wb
    rw = Wb(); r = rw.active; r.append(["姓名", "学号", "班级"]); r.append(["学生A", "1", "cA"])
    rw.save(ws / "roster.xlsx")
    files = sheets_from_task(ws / "task.json", ws, out_dir=ws / "out",
                             roster_path=str(ws / "roster.xlsx"), teacher_mode=True)
    rd = PdfReader(str(files[0]))
    assert len(rd.pages) >= 2, "超长答案应续页"
    all_text = "".join((p.extract_text() or "") for p in rd.pages).replace("\n", "")
    # 内容完整（不丢字）：应包含足够多的"很长的解答"
    assert all_text.count("很长的解答") >= 1500, "参考答案内容必须完整（不丢字）"


def test_non_teacher_pdf_unchanged(tmp_path):
    """非教师版 PDF 行为不变（不含答案，按 per_page 分页）。"""
    from pypdf import PdfReader
    from assist.paper.task import sheets_from_task
    from openpyxl import Workbook as Wb
    ws = tmp_path / "ws"; _mk_ws(ws)
    task = json.loads(_task(ws).read_text(encoding="utf-8"))
    task["layout"] = {"orientation": "portrait", "per_page": 2}
    (ws / "task.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    rw = Wb(); r = rw.active; r.append(["姓名", "学号", "班级"]); r.append(["学生A", "1", "cA"])
    rw.save(ws / "roster.xlsx")
    files = sheets_from_task(ws / "task.json", ws, out_dir=ws / "out",
                             roster_path=str(ws / "roster.xlsx"))
    rd = PdfReader(str(files[0]))
    assert len(rd.pages) == 1, "2 题/页 → 1 页"
