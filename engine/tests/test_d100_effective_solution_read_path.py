"""D100：参考答案「生效版」读取链路收口（AI 作答 → 题库 → 作业纸）。

覆盖：
- T1 `effective_map` 批量索引语义与 `effective_solution` 逐条一致；
- T2 `GET /kb/solutions`（无 qid）返回 {effective, digest}；
- T3 AI 作答**默认置顶**（pin=True 默认）；`--no-pin` / pin=false 保持旧行为；
- T4 `assist sheet html` 题帧走 `effective_solution`（pin 后的 AI 答案进入 HTML）；
- 回归：未置顶（latest）也应出现在 HTML（"有版本即生效"）。
"""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from click.testing import CliRunner
from openpyxl import Workbook

from assist.cli import cli
from assist.files import solutions as sol
from assist.grading import solve


def _mk_kb(ws: Path) -> None:
    kb = ws / "kb"
    kb.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    sh = wb.active
    sh.title = "chap04"
    sh.append(["id", "content", "img_path", "page", "related", "type", "solution", "note"])
    sh.append(["c1", "求质点速度 $v$。", "", 1, "牛顿力学", "计算", "旧列答案", ""])
    sh.append(["c2", "解释熵增。", "", 1, "热力学", "简答", "", ""])
    wb.save(kb / "problems.xlsx")


def _mk_task(ws: Path) -> Path:
    task = {
        "id": "d100-html", "class_dir": "classes/classA", "course": "大学物理",
        "class": "classA", "layout": {"orientation": "portrait", "per_page": 2,
                                      "header": {"title": "D100"}},
        "items": [{"kb": "problems", "chap": "chap04", "ids": ["c1"], "tag": "t"}],
        "watermark": {"enabled": False}, "grade": {},
    }
    fn = ws / "task.json"
    fn.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    return fn


# ---------------- T1：批量索引 ----------------

def test_effective_map_matches_single(tmp_path):
    ws = tmp_path / "ws"
    sol.add_version(ws, "q1", "人写答案", source="human")
    sol.add_version(ws, "q2", "AI 答案", source="ai", model="m")
    sol.add_version(ws, "q3", "   ")          # 空文本不落库
    sol.pin_version(ws, "q2", "v1")
    batch = sol.effective_map(ws)
    assert set(batch) == {"q1", "q2"}
    for qid in batch:
        single = sol.effective_solution(ws, qid)
        assert batch[qid]["text"] == single["text"]
        assert batch[qid]["from"] == single["from"]
    assert batch["q2"]["from"] == "pinned" and batch["q2"]["version"] == "v1"
    assert batch["q1"]["from"] == "latest" and batch["q1"]["ai_versions"] == 0
    assert batch["q2"]["ai_versions"] == 1
    assert batch["q2"]["id"] == "v1"          # 供 PWA 版本徽标


def test_effective_map_empty_ws(tmp_path):
    assert sol.effective_map(tmp_path / "ws") == {}
    assert sol.solutions_digest(tmp_path / "ws") == 0.0


def test_effective_map_digest_changes(tmp_path):
    ws = tmp_path / "ws"
    assert sol.solutions_digest(ws) == 0.0
    sol.add_version(ws, "q1", "A")
    first = sol.solutions_digest(ws)
    assert first > 0
    import time
    time.sleep(0.01)
    sol.add_version(ws, "q1", "B")
    assert sol.solutions_digest(ws) >= first


# ---------------- T3：AI 作答默认置顶 ----------------

def test_solve_apply_default_pins(tmp_path, monkeypatch):
    """D100-T3：`solve_targets` 默认 pin=True —— AI 作答即成为生效答案。"""
    ws = tmp_path / "ws"; _mk_kb(ws)
    sol.add_version(ws, "chap04-c1", "原答案", source="human", kb="problems", chap="chap04")
    sol.pin_version(ws, "chap04-c1", "v1", kb="problems", chap="chap04")

    class _Stub:
        def chat(self, **kw): return "AI 新解"

    monkeypatch.setattr(solve, "_client", lambda ws_, model="": (_Stub(), "m"))
    targets = solve.list_targets(ws, "problems", "chap04", ["c1"])
    solve.solve_targets(ws, targets, model="m", apply=True, dry_run=False)   # 不传 pin
    d = sol.read_solutions(ws, "chap04-c1", kb="problems", chap="chap04")
    assert d["versions"][-1]["pinned"] is True, "AI 作答默认应置顶"
    assert d["versions"][0]["pinned"] is False, "旧版取消置顶但仍在库"
    assert sol.effective_solution(ws, "chap04-c1", kb="problems", chap="chap04")["text"] == "AI 新解"


def test_solve_apply_no_pin_keeps_original(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; _mk_kb(ws)
    sol.add_version(ws, "chap04-c1", "原答案", source="human", kb="problems", chap="chap04")
    sol.pin_version(ws, "chap04-c1", "v1", kb="problems", chap="chap04")

    class _Stub:
        def chat(self, **kw): return "AI 新解"

    monkeypatch.setattr(solve, "_client", lambda ws_, model="": (_Stub(), "m"))
    targets = solve.list_targets(ws, "problems", "chap04", ["c1"])
    solve.solve_targets(ws, targets, model="m", apply=True, pin=False, dry_run=False)
    assert sol.effective_solution(ws, "chap04-c1", kb="problems", chap="chap04")["text"] == "原答案"


def test_add_version_pin_if_unpinned(tmp_path):
    ws = tmp_path / "ws"
    # 无 pinned → 保守置顶
    sol.add_version(ws, "q", "A", pin_if_unpinned=True)
    assert sol.effective_solution(ws, "q")["from"] == "pinned"
    # 已有 pinned → 不再抢
    sol.add_version(ws, "q", "B", pin_if_unpinned=True)
    assert sol.effective_solution(ws, "q")["text"] == "A"


def test_cli_ai_solve_pin_flags(tmp_path):
    """`--no-pin` 必须能被解析（默认 --pin=True）。"""
    ws = tmp_path / "ws"; _mk_kb(ws)
    r = CliRunner().invoke(cli, ["kb", "ai-solve", "--kb-kind", "problems",
                                 "--chap", "chap04", "--no-pin", "-w", str(ws)])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output.split("\n（dry-run")[0])["dryRun"] is True


# ---------------- T4：sheet html 走 effective_solution ----------------

def test_sheet_html_uses_effective_solution(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    task = _mk_task(ws)
    sol.add_version(ws, "chap04-c1", "AI 生成的参考答案", source="ai", model="m",
                    kb="problems", chap="chap04")
    sol.pin_version(ws, "chap04-c1", "v1", kb="problems", chap="chap04")
    out = ws / "o.html"
    r = CliRunner().invoke(cli, ["sheet", "html", "--task", str(task),
                                 "--workspace", str(ws), "-o", str(out),
                                 "--students", "blank", "--no-measure"])
    assert r.exit_code == 0, r.output
    html = out.read_text(encoding="utf-8")
    assert "AI 生成的参考答案" in html, "作业纸 HTML 必须用生效版（置顶 AI 答案）"
    assert "旧列答案" not in html, "xlsx 旧列不应压过版本库"


def test_sheet_html_uses_latest_when_unpinned(tmp_path):
    """回归：未置顶（latest）也生效——AI 作答后即使忘点置顶也要能看到。"""
    ws = tmp_path / "ws"; _mk_kb(ws)
    task = _mk_task(ws)
    sol.add_version(ws, "chap04-c1", "未置顶的 AI 答案", source="ai",
                    kb="problems", chap="chap04")
    out = ws / "o.html"
    r = CliRunner().invoke(cli, ["sheet", "html", "--task", str(task),
                                 "--workspace", str(ws), "-o", str(out),
                                 "--students", "blank", "--no-measure"])
    assert r.exit_code == 0, r.output
    assert "未置顶的 AI 答案" in out.read_text(encoding="utf-8")


def test_sheet_html_falls_back_to_xlsx_without_versions(tmp_path):
    ws = tmp_path / "ws"; _mk_kb(ws)
    task = _mk_task(ws)
    out = ws / "o.html"
    r = CliRunner().invoke(cli, ["sheet", "html", "--task", str(task),
                                 "--workspace", str(ws), "-o", str(out),
                                 "--students", "blank", "--no-measure"])
    assert r.exit_code == 0, r.output
    assert "旧列答案" in out.read_text(encoding="utf-8")


# ---------------- T2：GET /kb/solutions 批量端点 ----------------

@pytest.fixture()
def server(tmp_path):
    import assist.serve as S
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    S._set_serve_ws(ws)
    S.Handler.ws = ws.resolve()
    S.Handler.token = ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", ws
    finally:
        httpd.shutdown()
        S._SERVE_WS = None


def _get(base, path):
    with urllib.request.urlopen(base + path) as r:
        return json.loads(r.read())


def test_serve_kb_solutions_batch(server):
    base, ws = server
    sol.add_version(ws, "q1", "答案一", source="human")
    sol.add_version(ws, "q2", "AI 答案二", source="ai", model="m")
    sol.pin_version(ws, "q2", "v1")
    d = _get(base, "/kb/solutions")
    assert d["ok"] is True
    assert d["effective"]["q1"]["text"] == "答案一"
    assert d["effective"]["q2"]["text"] == "AI 答案二"
    assert d["effective"]["q2"]["from"] == "pinned"
    assert d["digest"] > 0
    # raw=1 仍可用（旧调用兼容）
    raw = _get(base, "/kb/solutions?raw=1")
    assert [x["qid"] for x in raw["items"]] == ["q1", "q2"]


def test_serve_kb_solutions_batch_empty(server):
    base, _ws = server
    d = _get(base, "/kb/solutions")
    assert d["ok"] is True and d["effective"] == {} and d["digest"] == 0.0
