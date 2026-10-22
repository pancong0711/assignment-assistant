"""D77 通知发布纯函数回归（不触网、不开浏览器）。"""
import json
from pathlib import Path

from assist.xxt.notice import (body_to_html, list_notice_attachments, normalize_targets,
                               safe_attachment_path, save_notice_uploads, validate_targets)


def test_normalize_and_validate_allowlist(tmp_path):
    from assist.xxt.allowlist import write_allowlist
    write_allowlist(tmp_path, [{"courseId": "217801417", "classId": "40009084", "name": "默认班级"}])
    targets = normalize_targets([{
        "courseId": "217801417",
        "courseName": "大学物理知识点拾遗（by pc）",
        "classes": [{"classId": "40009084", "name": "默认班级"}],
    }])
    assert validate_targets(targets, tmp_path) is None
    bad = normalize_targets([{"courseId": "1", "classes": ["2"]}])
    err = validate_targets(bad, tmp_path)
    assert err and "白名单拒绝" in err


def test_no_hardcoded_allowlist_constant():
    """P0：历史上硬编码的 NOTICE_TEST_ALLOWLIST 已删除；白名单只认 settings 配置。"""
    import assist.xxt.notice as notice
    assert not hasattr(notice, "NOTICE_TEST_ALLOWLIST")
    # 未配置白名单时，即使过去硬编码过的班级也必须被拒。
    from assist.xxt.notice import validate_targets
    targets = normalize_targets([{"courseId": "217801417",
                                  "classes": [{"classId": "40009084"}]}])
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as d:
        err = validate_targets(targets, _P(d))
    assert err and "白名单拒绝" in err


def test_body_to_html_escapes_plain_text():
    html = body_to_html("第一行\n第二行 <script>")
    assert "<p>第一行</p>" in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_safe_attachment_and_list(tmp_path):
    pdf = tmp_path / "classes" / "c" / "sheets" / "out" / "a.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 fake")
    outside = tmp_path.parent / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4 fake")
    ok = safe_attachment_path(str(pdf), tmp_path)
    assert ok == pdf.resolve()
    assert safe_attachment_path(str(outside), tmp_path) is None
    items = list_notice_attachments(tmp_path)
    assert items and items[0]["name"] == "a.pdf"
    # JSON serializable
    json.dumps(items)


def test_save_notice_uploads_roundtrip(tmp_path):
    import base64
    data = base64.b64encode(b"hello pdf").decode()
    items = save_notice_uploads(tmp_path, [{"name": "a.pdf", "data_b64": data}])
    assert len(items) == 1 and items[0]["name"] == "a.pdf"
    assert Path(items[0]["path"]).read_bytes() == b"hello pdf"
    assert Path(items[0]["path"]).is_relative_to(tmp_path)


def test_work_target_allowlist(tmp_path):
    from assist.xxt.allowlist import write_allowlist
    from assist.xxt.work import validate_work_target
    write_allowlist(tmp_path, [{"courseId": "217801417", "classId": "40009084"}])
    assert validate_work_target("217801417", "40009084", tmp_path) is None
    err = validate_work_target("1", "2", tmp_path)
    assert err and "白名单拒绝" in err


def test_targets_from_pairs_keeps_class_name():
    """P0：`--target c:k:className` 的第三段是班级名，必须透传到 sendMap 的 name。"""
    from assist.xxt.cli import targets_from_pairs
    t = targets_from_pairs(["c1:k1:班级甲", "c1:k2", "c2:k3:班级乙"])
    assert t[0]["courseId"] == "c1"
    assert [c["classId"] for c in t[0]["classes"]] == ["k1", "k2"]
    assert t[0]["classes"][0]["name"] == "班级甲"   # 显式班级名保留
    assert t[0]["classes"][1]["name"] == "k2"        # 未给名 → 回落 classId
    assert t[0]["courseName"] == "c1"                # CLI 直调无课程名 → 回落 courseId
    assert t[1]["classes"][0]["name"] == "班级乙"


def test_targets_from_pairs_rejects_bad():
    import click
    from assist.xxt.cli import targets_from_pairs
    for bad in ["c1", "c1:", ":k1"]:
        try:
            targets_from_pairs([bad])
        except click.UsageError:
            pass
        else:
            raise AssertionError(f"应拒绝：{bad!r}")

# ---------------- D99：附件类型矩阵 + 上传就绪判定 ----------------


def test_default_exts_include_xlsx():
    """D99：xlsx 在默认白名单内（真机矩阵验证与 pdf/docx 同为 editor-iframe 云附件）。"""
    from assist.xxt.allowlist import DEFAULT_NOTICE_ATTACHMENT_EXTS, read_notice_attachment_exts
    for ext in ("xls", "xlsx"):
        assert ext in DEFAULT_NOTICE_ATTACHMENT_EXTS
    assert "xlsx" in read_notice_attachment_exts()


def test_safe_attachment_accepts_xlsx(tmp_path):
    xlsx = tmp_path / "tmp" / "分组安排.xlsx"
    xlsx.parent.mkdir(parents=True)
    xlsx.write_bytes(b"PK\x03\x04 fake xlsx")
    assert safe_attachment_path(str(xlsx), tmp_path) == xlsx.resolve()


def test_safe_attachment_still_rejects_unlisted_ext(tmp_path):
    """未在配置中的后缀（如 exe）即使默认扩到 xlsx 也必须拒绝。"""
    exe = tmp_path / "tmp" / "evil.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    assert safe_attachment_path(str(exe), tmp_path) is None


class _StubEditorPage:
    """按脚本依次返回**一次快照**的假页面（模拟 _editor_snapshot 的单次 evaluate）。

    快照字段：len/count/pending/errors；与真机 `_editor_snapshot` JS 返回值同构，
    这样测试能验证「块数 / pending / error 必须在同一次采样里判定」。
    """

    def __init__(self, contents, pending=False, errors=0):
        self.contents = list(contents)
        self.pending = pending
        self.errors = errors
        self.waits = 0

    def evaluate(self, *_a, **_k):
        if len(self.contents) > 1:
            return self.contents.pop(0)
        return self.contents[0]

    def wait_for_timeout(self, _ms):
        self.waits += 1


def _snap(html: str, pending: bool = False, errors: int = 0, settled: bool = True) -> dict:
    """按真机快照口径构造 {len,count,pending,errors,settled}（用于 stub 返回值）。"""
    count = sum(html.count(m) for m in ('class="editor-iframe"', 'class="attach-iframe"',
                                        'class="drag-image-wrap"', 'ans-ued-img'))
    return {"len": len(html), "count": count, "pending": pending,
            "errors": errors, "settled": settled}


_UPLOADING_IFRAME = ('<div class="editor-iframe"><div class="attachprogress">'
                     '<p class="uploadinfotext">正在上传...</p></div></div>')
_READY_IFRAME = ('<div class="editor-iframe" id="WU_FILE_0"><iframe '
                 'src="https://noteyd.chaoxing.com/attachment/insertCloud.html"></iframe></div>')


def test_upload_progress_requires_block_and_no_pending_in_one_snapshot():
    from assist.xxt.notice import _upload_progress
    # 块已出现但仍在「正在上传」→ 不算就绪（D99 假阳性根因）
    st = _upload_progress(_StubEditorPage([_snap(_UPLOADING_IFRAME, pending=True)]), before=0)
    assert st["count"] == 1 and st["pending"] and not st["ok"]
    # 无 pending + 块数增加 → 就绪
    st = _upload_progress(_StubEditorPage([_snap(_READY_IFRAME)]), before=0)
    assert st["count"] == 1 and not st["pending"] and st["ok"]
    # 块数没增加 → 不算就绪（防止把上一个文件算成这个）
    st = _upload_progress(_StubEditorPage([_snap(_READY_IFRAME)]), before=1)
    assert not st["ok"]


def test_upload_progress_carries_error_count_in_same_snapshot():
    """D99 关键：errors 必须与 count/pending 来自同一次采样（图片进度层是瞬态的）。"""
    from assist.xxt.notice import _upload_progress
    st = _upload_progress(_StubEditorPage([_snap(_READY_IFRAME, errors=1)]), before=0)
    assert st["errors"] == 1


def test_wait_upload_waits_until_ready_not_first_block():
    """回归 D99：先出现「正在上传」占位块，必须继续等到它变成就绪块。"""
    from assist.xxt.notice import _wait_upload
    page = _StubEditorPage([_snap(_UPLOADING_IFRAME, pending=True),
                            _snap(_UPLOADING_IFRAME, pending=True),
                            _snap(_READY_IFRAME)])
    ok, count = _wait_upload(page, before=0, timeout_s=30, poll_s=0.0, stable_hits=1)
    assert ok and count == 1
    assert page.waits >= 1


def test_wait_upload_fails_after_error_grace_with_no_success_evidence():
    """失败占位持续存在且没有成功证据 → 宽限期耗尽后判失败。"""
    from assist.xxt.notice import _wait_upload
    page = _StubEditorPage([_snap('<div class="drag-image-wrap"></div>', errors=1, settled=False)])
    ok, _count = _wait_upload(page, before=0, timeout_s=30, poll_s=0.0,
                              before_failed=0, error_grace_s=0.0)
    assert ok is False


def test_wait_upload_survives_transient_error_marker():
    """真机 png 序列：先出现 imguploaderror，随后换成真实 <img> → 必须判成功，不能误杀。"""
    from assist.xxt.notice import _wait_upload
    page = _StubEditorPage([
        _snap('<div class="drag-image-wrap"></div>', errors=1, settled=False),
        _snap('<div class="drag-image-wrap"></div>', errors=1, settled=False),
        _snap('<div class="drag-image-wrap"><img src="data:image/png;base64,AAA"></div>',
              errors=0, settled=True),
    ])
    ok, count = _wait_upload(page, before=0, timeout_s=30, poll_s=0.0,
                             stable_hits=1, before_failed=0, error_grace_s=5.0)
    assert ok and count == 1


def test_wait_upload_ignores_stale_error_marker():
    """常驻的旧 imguploaderror（上传前已存在）不能把本次成功判成失败。"""
    from assist.xxt.notice import _wait_upload
    page = _StubEditorPage([_snap(_READY_IFRAME, errors=1)])
    ok, count = _wait_upload(page, before=0, timeout_s=30, poll_s=0.0,
                             stable_hits=1, before_failed=1)
    assert ok and count == 1


def test_wait_upload_reports_fail_reason():
    from assist.xxt.notice import _upload_fail_reason
    assert "UEditor" in _upload_fail_reason({"count": -1})
    assert "失败占位" in _upload_fail_reason({"count": 1}, new_failed=True)
    assert "正在上传" in _upload_fail_reason({"count": 1, "pending": True})

def test_wait_upload_requires_stable_snapshot_twice():
    """默认 stable_hits=2：就绪后要连续两次采样一致才算完成（避免页面还在插入）。"""
    from assist.xxt.notice import _wait_upload
    page = _StubEditorPage([_snap(_READY_IFRAME)])
    ok, count = _wait_upload(page, before=0, timeout_s=30, poll_s=0.0)
    assert ok and count == 1
    assert page.waits >= 1


def test_wait_upload_times_out_when_never_ready():
    from assist.xxt.notice import _wait_upload
    page = _StubEditorPage([_snap(_UPLOADING_IFRAME, pending=True)])
    ok, count = _wait_upload(page, before=0, timeout_s=0.01, poll_s=0.0)
    assert ok is False

