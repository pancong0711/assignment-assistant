"""D190：重新扫码时要先出二维码，登录成功后才显示头像。

现场：点「🔁 重新扫码登录」后提示“已生成二维码，等待手机扫码”，
但二维码位仍显示上一次登录的头像，根本找不到可扫的码。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import assist.serve as serve


def test_login_state_ignores_stale_logged_in_before_task(tmp_path: Path, monkeypatch):
    """上一轮遗留的 logged_in 不得冒充当轮状态（否则前端会立即收尾成“成功”）。"""
    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    state = tmp_path / "xxt-login-state.json"
    state.write_text(json.dumps({"stage": "logged_in"}), encoding="utf-8")
    old = time.time() - 600
    os.utime(state, (old, old))

    st = serve._xxt_login_state(tmp_path, since=time.time())
    assert st["stage"] == ""
    assert st["updatedAt"] == int(old)


def test_login_state_accepts_state_written_after_task_start(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    state = tmp_path / "xxt-login-state.json"
    state.write_text(json.dumps({"stage": "waiting_scan",
                                 "url": "https://passport2.chaoxing.com/login"}),
                     encoding="utf-8")
    started = time.time() - 5
    st = serve._xxt_login_state(tmp_path, since=started)
    assert st["stage"] == "waiting_scan"
    assert st["urlHost"] == "passport2.chaoxing.com"


def test_login_state_without_since_keeps_legacy_behaviour(tmp_path: Path):
    state = tmp_path / "xxt-login-state.json"
    state.write_text(json.dumps({"stage": "waiting_scan"}), encoding="utf-8")
    assert serve._xxt_login_state(tmp_path)["stage"] == "waiting_scan"


def test_task_started_at_reads_job_start():
    with serve._JOBS_LOCK:
        serve._JOBS["job-d190"] = {"item": "xxt_login", "status": "running",
                                   "started_at": 1234.5}
    try:
        assert serve._xxt_task_started_at("job-d190") == 1234.5
    finally:
        with serve._JOBS_LOCK:
            serve._JOBS.pop("job-d190", None)
    assert serve._xxt_task_started_at("missing-job") == 0.0


def test_start_stream_job_records_started_at(monkeypatch):
    """新登录任务必须带 started_at，/xxt/login/state?job_id= 才有基准。"""
    monkeypatch.setattr(serve.subprocess, "Popen", _FakePopen)
    seen = {}
    with serve._JOBS_LOCK:
        before = set(serve._JOBS)
    serve.Handler._start_stream_job(
        serve.Handler.__new__(serve.Handler), "job-d190-start",
        ["true"], {}, "xxt_login", "xxt-login", None, journal_kind="xxt_login")
    deadline = time.time() + 10
    while time.time() < deadline:
        with serve._JOBS_LOCK:
            info = dict(serve._JOBS.get("job-d190-start") or {})
        if info.get("status") != "running":
            break
        time.sleep(0.05)
    seen.update(info)
    try:
        assert seen.get("started_at")
        assert seen.get("status") == "done"
    finally:
        with serve._JOBS_LOCK:
            for k in set(serve._JOBS) - before:
                serve._JOBS.pop(k, None)


class _FakeStdout:
    def __iter__(self):
        return iter(["ok\n"])


class _FakePopen:
    def __init__(self, *a, **kw):
        self.stdout = _FakeStdout()
        self.returncode = 0

    def wait(self, timeout=None):
        return 0


def test_source_contract_for_d190():
    """源码契约：扫码期间头像位让给二维码 + 登录成功后才刷新头像。"""
    root = Path(__file__).resolve().parents[2]
    view = (root / "app/src/views/XxetongView.vue").read_text(encoding="utf-8")
    client = (root / "app/src/lib/engineClient.ts").read_text(encoding="utf-8")
    serve_py = (root / "engine/src/assist/serve.py").read_text(encoding="utf-8")
    assert "loginFlowActive" in view
    assert "const loginFlowActive = computed(() => qrLoading.value || qrcode.value !== '')" in view
    assert "restartLogin: false" not in view
    # 二维码优先于头像
    assert view.index('v-if="qrcode"') < view.index('verdict===\'alive\' && avatar')
    # 头像只属于登录成功收尾
    assert "refreshAvatarAfterLogin" in view
    assert "void refreshAvatarAfterLogin()" in view
    # 发起扫码立即清旧头像
    start_body = view.split("async function startScan() {")[1].split("async function relogin()")[0]
    assert "avatar.value = null" in start_body
    # 客户端把 job_id 传给只读状态接口
    assert "job_id=" in client
    # 引擎清理旧头像缓存（避免状态轮询先跑 25s 抓头像）
    assert "_XXT_AVATAR = None" in serve_py
    assert "started_at" in serve_py
