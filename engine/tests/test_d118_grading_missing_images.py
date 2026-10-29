"""D118：AI 批阅「没有任何学生作答图」时应给可读错误，而不是 FileNotFoundError 堆栈。

复现的原始报错（Windows）：
    ❌ AI 批阅失败：FileNotFoundError: [WinError 3] 系统找不到指定的路径。:
    'D:\\...\\2609assignment\\grading\\202610-chap05-811\\images'
"""
import json
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from assist.cli import cli
from assist.grading.flow import GradingInputError, _run_transcribe
from assist.grading.transcribe import group_images


class _StubClient:
    def chat(self, **kw):  # noqa: ANN003
        raise AssertionError("不应调用 LLM：该用例只验证前置检查")


def test_group_images_missing_dir_returns_empty(tmp_path):
    """目录不存在 → 返回 {}（此前直接 iterdir() 抛 FileNotFoundError）。"""
    missing = tmp_path / "grading" / "202610-chap05-811" / "images"
    assert not missing.exists()
    assert group_images(missing) == {}


def test_group_images_existing_dir_still_works(tmp_path):
    d = tmp_path / "images"; d.mkdir()
    (d / "张三-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (d / "张三-2.jpg").write_bytes(b"\xff\xd8\xff")
    (d / "李四-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    groups = group_images(d)
    assert set(groups.keys()) == {"张三", "李四"}
    assert len(groups["张三"]) == 2


def test_plan_without_any_images_raises_readable_error(tmp_path):
    """plan 模式下一名学生的图都没有 → 可读的 GradingInputError（不是 FileNotFoundError）。"""
    ctx = {
        "task": {},
        "plan": {"students": [{"name": "张三", "images": []},
                              {"name": "李四", "images": []}]},
        "images_dir": tmp_path / "grading" / "c" / "w" / "images",
    }
    with pytest.raises(GradingInputError) as ei:
        _run_transcribe(ctx, _StubClient(), tmp_path / "transcripts")
    msg = str(ei.value)
    assert "没有任何学生图片" in msg
    assert "下载" in msg, "错误信息应给出下一步操作"
    # D119：错误信息应指出**真实**的作答原件目录（pages/review/...），
    # 而不是曾经那个从不存在的 <ws>/grading/<task>/images
    assert "pages/review" in msg, f"错误信息应指出真实下载目录：{msg}"
    assert "grading" not in msg, f"不应再提已废弃的 grading/<task>/images：{msg}"


def test_cli_grade_missing_images_is_click_exception_not_traceback(tmp_path):
    """CLI：该场景应输出可读错误（ClickException），而不是 Python 堆栈。"""
    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    # 造一个可用的 LLM 配置（真实场景教师已配好；否则会在更早的步骤失败，
    # 就测不到"缺图片"这条路径）
    (ws / "settings.local.json").write_text(json.dumps({
        "llm": {"base_url": "http://127.0.0.1:1/v1", "api_key": "sk-test", "model": "m"}
    }, ensure_ascii=False), encoding="utf-8")
    pad = {
        "id": "202610-chap05-811",
        "class": "classA",
        "layout": {"orientation": "portrait", "per_page": 2,
                   "header": {"title": "t"}, "footer": {"text": ""}},
        "items": [{"kb": "problems", "chap": "chap04", "ids": ["c1"], "tag": "distinguish"}],
        "watermark": {"enabled": False},
        "grade": {"steps": ["transcribe"]},
    }
    task = ws / "task.json"
    task.write_text(json.dumps(pad, ensure_ascii=False), encoding="utf-8")
    # 造 plan（学生有名字但无图）
    from assist.grading import inputs as _inputs
    plan = {"taskId": pad["id"], "classDir": "classes/classA", "mode": "optimized",
            "tags": ["distinguish"],
            "students": [{"name": "张三", "number": "01", "tag": "distinguish",
                          "workAnswerId": "", "images": [], "questions": [],
                          "padId": ""}]}
    _inputs.save_plan(ws, "classes/classA", plan)
    plan_path = _inputs.plan_path(ws, "classes/classA", pad["id"])
    r = CliRunner().invoke(cli, ["grade", "--task", str(task), "--plan", str(plan_path),
                                 "-w", str(ws)])
    out = r.output + (str(r.exception) if r.exception else "")
    assert "FileNotFoundError" not in out, f"不应再出现 FileNotFoundError：{out}"
    assert "没有任何学生图片" in out, f"应给可读错误：{out}"


# ---------------- serve 前置体检 ----------------

def test_serve_ai_run_preflight_rejects_when_no_images(tmp_path):
    """POST /xxt/grade/ai-run：没有任何学生作答图 → 400 + 可读错误（不启动 job）。"""
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from openpyxl import Workbook

    import assist.serve as S
    from assist.xxt import allowlist

    ws = tmp_path / "ws"
    (ws / "kb").mkdir(parents=True)
    (ws / "classes" / "classA" / "roster").mkdir(parents=True)
    wb = Workbook(); sh = wb.active
    sh.append(["姓名", "学号", "班级", "tag"])
    sh.append(["张三", "01", "classA", ""])
    wb.save(ws / "classes" / "classA" / "roster" / "roster.xlsx")
    allowlist.write_allowlist(ws, [{"courseId": "co1", "classId": "c1"}])

    S._set_serve_ws(ws); S.Handler.ws = ws.resolve(); S.Handler.token = ""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        body = json.dumps({
            "courseId": "co1", "classId": "c1", "workId": "w1",
            "taskpad": {"id": "202610-chap05-811", "class": "classA",
                        "layout": {"orientation": "portrait", "per_page": 2,
                                   "header": {"title": "t"}, "footer": {"text": ""}},
                        "items": [{"kb": "problems", "chap": "chap04",
                                   "ids": ["c1"], "tag": "t"}],
                        "watermark": {"enabled": False},
                        "grade": {"steps": ["transcribe"]}},
        }).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/xxt/grade/ai-run",
                                     data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
            raised = False
        except urllib.error.HTTPError as e:
            raised = e.code == 400
            payload = json.loads(e.read())
        assert raised, "应返回 400"
        assert "没有任何学生有作答图" in payload["error"]
        assert "下载" in payload["error"]
    finally:
        httpd.shutdown(); S._SERVE_WS = None
