"""D77 通知发布纯函数回归（不触网、不开浏览器）。"""
import json
from pathlib import Path

from assist.xxt.notice import (NOTICE_TEST_ALLOWLIST, body_to_html, list_notice_attachments,
                               normalize_targets, safe_attachment_path, validate_targets)


def test_normalize_and_validate_allowlist():
    targets = normalize_targets([{
        "courseId": "217801417",
        "courseName": "大学物理知识点拾遗（by pc）",
        "classes": [{"classId": "40009084", "name": "默认班级"}],
    }])
    assert validate_targets(targets) is None
    bad = normalize_targets([{"courseId": "1", "classes": ["2"]}])
    err = validate_targets(bad)
    assert err and "白名单拒绝" in err
    assert ("217801417", "40009084") in NOTICE_TEST_ALLOWLIST


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
