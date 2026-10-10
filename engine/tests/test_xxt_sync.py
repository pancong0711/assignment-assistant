"""D74-7 回归：云同步/网盘检测（纯函数 + 本地临时目录）。"""

from assist.xxt import sync


def test_path_markers_hit_baidu():
    assert "baidusyncdisk" in sync.path_markers(r"D:\BaiduSyncdisk\toolsPy\2609assignment")
    assert sync.path_markers("/home/teacher/plain") == []


def test_stale_markers_and_detect(tmp_path):
    assert sync.detect(tmp_path)["detected"] is False
    (tmp_path / "x.baiduyun.p.downloading").write_text("x", encoding="utf-8")
    d = sync.detect(tmp_path)
    assert d["detected"] is True
    assert d["stale_markers"] and any("baiduyun" in x for x in d["stale_markers"])
