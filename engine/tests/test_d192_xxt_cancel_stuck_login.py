"""D192：扫码任务卡住时能真正取消并重新出码；无需退出学习通账号。

现场：点「重新扫码」后二维码一直不出现，页面提示“已有扫码任务在进行中/已生成二维码，
等待扫码”。根因是登录任务单实例：旧任务（等待窗口 30 分钟）一直占锁，新二维码永远
出不来，也没有终止旧任务的手段，只能关引擎。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import assist.serve as serve


class _FakeProc:
    def __init__(self, pid: int = 4321):
        self.pid = pid
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


def _register(job_id: str, **extra):
    proc = _FakeProc()
    with serve._JOBS_LOCK:
        serve._JOBS[job_id] = {"item": "xxt_login", "status": "running",
                               "started_at": time.time() - 60, "proc": proc, **extra}
    return proc


def _cleanup(job_id: str):
    with serve._JOBS_LOCK:
        serve._JOBS.pop(job_id, None)


def test_running_info_reports_pid_and_stale():
    job = "job-d192-run"
    _register(job)
    try:
        info = serve._xxt_login_job_running_info()
        assert info and info["job_id"] == job
        assert info["pid"] == 4321
        assert info["stale"] is False
        with serve._JOBS_LOCK:
            serve._JOBS[job]["started_at"] = time.time() - serve._XXT_LOGIN_MAX_AGE - 5
        assert serve._xxt_login_job_running_info()["stale"] is True
    finally:
        _cleanup(job)


def test_cancel_xxt_login_job_terminates_process():
    job = "job-d192-cancel"
    proc = _register(job)
    try:
        rep = serve.cancel_xxt_login_job(reason="replace")
        assert rep["cancelled"] is True and rep["job_id"] == job
        assert proc.terminated is True
        with serve._JOBS_LOCK:
            assert serve._JOBS[job]["cancelled"] is True
    finally:
        _cleanup(job)


def test_cancel_without_running_job_is_noop():
    rep = serve.cancel_xxt_login_job()
    assert rep["ok"] is True and rep["cancelled"] is False


def test_cancel_unknown_job_fails_cleanly():
    rep = serve.cancel_job("no-such-job")
    assert rep["ok"] is False and "no such job" in rep["error"]
    assert serve.cancel_job("")["ok"] is False


def test_cancel_job_without_handle_fails_cleanly():
    job = "job-d192-nohandle"
    with serve._JOBS_LOCK:
        serve._JOBS[job] = {"item": "xxt_login", "status": "running",
                            "started_at": time.time(), "proc": None}
    try:
        rep = serve.cancel_job(job)
        assert rep["ok"] is False and "no process handle" in rep["error"]
    finally:
        _cleanup(job)


def test_login_state_not_running_never_trusts_old_files(tmp_path: Path):
    """本进程没有任务在跑：即使状态文件/二维码刚被旧任务刷新，也不得回显等待扫码。"""
    p = tmp_path / "xxt-login-state.json"
    p.write_text(json.dumps({"stage": "waiting_scan",
                             "url": "https://passport2.chaoxing.com/login"}),
                 encoding="utf-8")
    (tmp_path / "xxt-qr.png").write_bytes(b"png")
    st = serve._xxt_login_state(tmp_path, job_running=False)
    assert st["stage"] == "" and st["qrExists"] is False
    assert st["urlHost"] == "" and st["cookies"] == []


def test_login_state_running_honours_fresh_state(tmp_path: Path):
    p = tmp_path / "xxt-login-state.json"
    p.write_text(json.dumps({"stage": "waiting_scan",
                             "url": "https://passport2.chaoxing.com/login"}),
                 encoding="utf-8")
    st = serve._xxt_login_state(tmp_path, since=time.time() - 30, job_running=True)
    assert st["stage"] == "waiting_scan"


def test_login_state_running_rejects_state_older_than_job(tmp_path: Path):
    p = tmp_path / "xxt-login-state.json"
    p.write_text(json.dumps({"stage": "logged_in"}), encoding="utf-8")
    old = time.time() - 600
    os.utime(p, (old, old))
    st = serve._xxt_login_state(tmp_path, since=time.time() - 30, job_running=True)
    assert st["stage"] == ""


def test_login_state_does_not_leak_secrets_when_not_running(tmp_path: Path):
    p = tmp_path / "xxt-login-state.json"
    p.write_text(json.dumps({"stage": "failed", "error": "token=abc123",
                             "url": "https://passport2.chaoxing.com/login?token=abc123"}),
                 encoding="utf-8")
    st = serve._xxt_login_state(tmp_path, job_running=False)
    dumped = json.dumps(st, ensure_ascii=False)
    assert "abc123" not in dumped


def test_replace_flag_and_cancel_endpoint_contract():
    src = (Path(__file__).resolve().parents[1] / "src/assist/serve.py").read_text(encoding="utf-8")
    assert 'fullmatch(r"/jobs/([A-Za-z0-9_\\-]+)/cancel", u.path)' in src
    assert 'get("replace", [""])[0]' in src
    assert "cancel_xxt_login_job(reason=\"replace\")" in src
    assert '"replacedJob": replaced_job' in src
    assert '"canReplace": True' in src
    # 标准启动流程未被破坏
    assert "_start_stream_job(job_id, cmd, env, \"xxt_login\"" in src


def test_frontend_contract_for_d192():
    root = Path(__file__).resolve().parents[2]
    view = (root / "app/src/views/XxetongView.vue").read_text(encoding="utf-8")
    client = (root / "app/src/lib/engineClient.ts").read_text(encoding="utf-8")
    assert "export async function cancelXxtJob" in client
    assert "replace?: boolean" in client
    assert "async function forceReissueQr" in view
    assert "⚡ 强制重新出码" in view
    assert "不需要退出学习通账号" in view
    assert "await startScan({ replace: true })" in view
    assert "qrBlocked" in view
    assert "jobRunning" in client
