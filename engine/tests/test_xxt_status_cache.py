"""D68 回归：登录 CLI 刚写 storage 后，/xxt/status 不能被旧 dead 缓存挡住。"""

import os
import time

import assist.serve as serve


def test_status_cache_invalidated_when_storage_newer(tmp_path, monkeypatch):
    storage = tmp_path / "xxt-storage.json"
    storage.write_text("{}", encoding="utf-8")
    future = time.time() + 30
    os.utime(storage, (future, future))

    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    monkeypatch.setattr(serve, "_XXT_CHECK", (time.time(), {"verdict": "dead"}))
    monkeypatch.setattr("assist.xxt.session.check_session",
                        lambda _storage: {"verdict": "alive"})

    assert serve._xxt_session_check_cached()["verdict"] == "alive"
