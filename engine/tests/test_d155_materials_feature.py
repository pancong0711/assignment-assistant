"""D155：课堂资料按「特征名」管理 + 上传按类型归档 + summary 关联。

教师拍板：materials 目录按特征名（26C1）组织；summary 不再靠"题目 chap"硬关联，
而是**优先用教师显式指定的特征名**，没有才回落 chap（兼容旧结构）。
"""
from __future__ import annotations

import base64

import pytest

from assist.files import materials as M


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "kb").mkdir()
    return tmp_path


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def test_feature_name_dir_allowed(ws):
    """特征名（26C1）可作为目录名。"""
    d = M.ensure_chap(ws, "26C1")
    assert d == ws / "materials" / "26C1"


def test_illegal_feature_name_rejected(ws):
    with pytest.raises(M.MaterialsError):
        M.chap_dir(ws, "../etc")


def test_upload_by_kind_subdir(ws):
    """D155：上传按类型落 `_source/<类型>/`。"""
    r = M.save_uploads(ws, "26C1", [{"name": "plan.docx", "data_b64": _b64(b"x")}],
                       kind="plan")
    assert r["saved"], r
    assert r["saved"][0]["file"] == "_source/plan/plan.docx"
    assert (ws / "materials" / "26C1" / "_source" / "plan" / "plan.docx").is_file()


def test_upload_unknown_kind_falls_back_to_source(ws):
    r = M.save_uploads(ws, "26C1", [{"name": "a.pdf", "data_b64": _b64(b"x")}],
                       kind="nonsense")
    assert r["saved"][0]["file"] == "_source/a.pdf"


def test_files_of_reports_kind_dir(ws):
    M.save_uploads(ws, "26C1", [{"name": "p.pptx", "data_b64": _b64(b"x")}], kind="ppt")
    rows = M.files_of(ws, "26C1")
    assert rows[0]["kindDir"] == "ppt"


def test_summary_prefers_explicit_feature(ws):
    """D155：有 feature 时用它（即使题目 chap 指向别的目录）。"""
    import json
    from assist.grading import evaluate as EV
    from assist.files import materials as MM
    # 特征目录里有清单；chap 目录里没有
    d = MM.ensure_chap(ws, "26C1")
    (d / MM.KNOW_MD).write_text("## 核心知识点\n- 动量守恒\n", encoding="utf-8")
    item = {"序号": "1", "kind": "summary", "chap": "chap99", "feature": "26C1",
            "content": "总结本堂课", "tag": "summary"}
    p = EV.build_user_prompt([item], "学生作答", "张三", ws=ws)
    assert "本堂课应掌握的知识点" in p
    assert "动量守恒" in p


def test_summary_falls_back_to_chap(ws):
    """没有 feature → 回落 chap（旧结构仍可读）。"""
    from assist.grading import evaluate as EV
    from assist.files import materials as MM
    d = MM.ensure_chap(ws, "chap04")
    (d / MM.KNOW_MD).write_text("## 核心知识点\n- 角动量守恒\n", encoding="utf-8")
    item = {"序号": "1", "kind": "summary", "chap": "chap04",
            "content": "总结", "tag": "summary"}
    p = EV.build_user_prompt([item], "作答", "张三", ws=ws)
    assert "角动量守恒" in p


def test_summary_without_any_uses_fallback_block(ws):
    """两者都没有 → 走保底口径（不报错）。"""
    from assist.grading import evaluate as EV
    item = {"序号": "1", "kind": "summary", "chap": "chap77", "feature": "27X9",
            "content": "总结", "tag": "summary"}
    p = EV.build_user_prompt([item], "作答", "张三", ws=ws)
    assert "通用保底标准" in p
