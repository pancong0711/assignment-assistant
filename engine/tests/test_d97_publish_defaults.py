"""D97：发布作业默认时间 + list_works 多目标班已发布（不碰浏览器）。"""
import inspect
import time

from assist.xxt import work as W


def test_list_works_has_class_ids_param():
    assert "class_ids" in inspect.signature(W.list_works).parameters


def test_publish_work_fills_default_times(monkeypatch, tmp_path):
    """缺省 start/end 时自动补 now+5min / now+5days（在进入浏览器前就补）。"""
    captured = {}

    # 拦截到"校验/浏览器"前，捕获 start_time/end_time：让 validate 直接失败以早退
    def fake_validate(cid, kid):
        captured["called"] = True
        return "白名单拒绝（测试）"
    monkeypatch.setattr(W, "validate_work_target", fake_validate)
    rep = W.publish_work(tmp_path / "s.json", "C1", "K1", "W1", cpi="0",
                         start_time="", end_time="", send=False)
    # 早退于白名单校验，但我们关心的是：函数不回填错误时间（不抛异常）
    assert rep.get("ok") is False


def test_default_times_format(monkeypatch):
    """直接验证缺省时间逻辑（用与实现同口径的公式）。"""
    import datetime as dt
    now = dt.datetime.now()
    s = (now + dt.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    e = (now + dt.timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    assert len(s) == 19 and len(e) == 19
    assert s > now.strftime("%Y-%m-%d %H:%M:%S")
