"""D95：多班发布 —— publish_work 多班参数（校验路径，不碰浏览器）。"""
import pytest

from assist.xxt import work as W


def test_publish_work_accepts_class_ids_signature():
    import inspect
    params = inspect.signature(W.publish_work).parameters
    assert "class_ids" in params, "应支持 class_ids 多班参数"


def test_publish_work_rejects_non_whitelisted(tmp_path, monkeypatch):
    """非白名单班 → 逐班校验失败并返回错误（不进入浏览器）。"""
    # 让白名单为空
    monkeypatch.setattr(W, "validate_work_target", lambda cid, kid: f"班级 {kid} 未在白名单")
    rep = W.publish_work(tmp_path / "storage.json", "C1", "K1", "W1",
                         cpi="0", start_time="2030-01-01 08:00:00",
                         end_time="2030-02-01 08:00:00", send=False,
                         class_ids=["K1", "K2"])
    assert rep["ok"] is False
    assert "K1" in rep["error"] and "K2" in rep["error"]


def test_publish_work_dup_blocked_before_browser(tmp_path, monkeypatch):
    """send=True 且索引里已有该班 → 直接拒绝（多班逐班查）。"""
    monkeypatch.setattr(W, "validate_work_target", lambda cid, kid: None)
    monkeypatch.setattr(W, "_load_index", lambda: {"C1|W1|K2": {"at": "x"}})
    rep = W.publish_work(tmp_path / "s.json", "C1", "K1", "W1", cpi="0",
                         start_time="2030-01-01 08:00:00", end_time="2030-02-01 08:00:00",
                         send=True, class_ids=["K1", "K2"])
    assert rep["ok"] is False and "K2" in rep["error"]
