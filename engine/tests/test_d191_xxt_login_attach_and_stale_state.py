"""D191：409「已有扫码登录任务」不应把教师卡死；上一轮遗留状态不得伪装成“等待扫码”。

现场：点「重新扫码」后页面长期显示
  「已有扫码登录任务在进行中…」+「已生成二维码，等待手机扫码」，
但既拿不到二维码、红字“会话已失效”也不消失。
根因：
  1) 409 被前端当失败显示，从不接管正在运行的任务；
  2) 没有任务在跑时，`xxt-login-state.json`/`xxt-qr.png` 的上一轮遗留仍被当真；
  3) 登录成功后，旧的 loginRedirect 记录继续亮红字。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import assist.serve as serve


def _utime(path: Path, ts: float) -> None:
    os.utime(path, (ts, ts))


def test_login_state_readonly_ignores_stale_logged_in(tmp_path: Path):
    """没有任务在跑时，上一轮遗留的 logged_in 不得被回显。"""
    p = tmp_path / "xxt-login-state.json"
    p.write_text(json.dumps({"stage": "logged_in"}), encoding="utf-8")
    _utime(p, time.time() - 600)
    st = serve._xxt_login_state(tmp_path, readonly_since=time.time() - 5)
    assert st["stage"] == ""
    assert st["qrExists"] is False


def test_login_state_readonly_rejects_stale_qr(tmp_path: Path):
    """没有任务在跑且二维码是上一轮残留 → qrExists=False（页面不再显示等待扫码）。"""
    (tmp_path / "xxt-qr.png").write_bytes(b"png")
    _utime(tmp_path / "xxt-qr.png", time.time() - 600)
    st = serve._xxt_login_state(tmp_path, readonly_since=time.time() - 5)
    assert st["qrExists"] is False


def test_login_state_readonly_accepts_fresh_qr(tmp_path: Path):
    (tmp_path / "xxt-qr.png").write_bytes(b"png")
    st = serve._xxt_login_state(tmp_path, readonly_since=time.time() - 60)
    assert st["qrExists"] is True


def test_login_state_job_based_window_still_works(tmp_path: Path):
    p = tmp_path / "xxt-login-state.json"
    p.write_text(json.dumps({"stage": "waiting_scan"}), encoding="utf-8")
    st = serve._xxt_login_state(tmp_path, since=time.time() - 30)
    assert st["stage"] == "waiting_scan"


def test_login_job_running_info_reports_age():
    with serve._JOBS_LOCK:
        serve._JOBS["job-d191-busy"] = {"item": "xxt_login", "status": "running",
                                        "started_at": time.time() - 42}
    try:
        info = serve._xxt_login_job_running_info()
        assert info and info["job_id"] == "job-d191-busy"
        assert 40 <= info["age"] <= 60
    finally:
        with serve._JOBS_LOCK:
            serve._JOBS.pop("job-d191-busy", None)
    assert serve._xxt_login_job_running_info() is None


def test_login_completed_after_detects_success(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    p = tmp_path / "xxt-login-state.json"
    p.write_text(json.dumps({"stage": "logged_in"}), encoding="utf-8")
    assert serve._xxt_login_completed_after(time.time() - 60) is not None
    assert serve._xxt_login_completed_after(time.time() + 60) is None
    p.write_text(json.dumps({"stage": "waiting_scan"}), encoding="utf-8")
    assert serve._xxt_login_completed_after(time.time() - 60) is None


def test_login_completed_after_safe_on_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(serve, "_xxt_home", lambda: tmp_path)
    assert serve._xxt_login_completed_after(time.time()) is None
    assert serve._xxt_login_completed_after(0) is None


def test_busy_409_payload_contract():
    """409 必须带 job_id + 可读 hint，前端才能接管而不是报死。"""
    src = (Path(__file__).resolve().parents[1] / "src/assist/serve.py").read_text(encoding="utf-8")
    body = src.split('u.path == "/xxt/login/start"')[1].split("job_id = secrets.token_urlsafe")[0]
    assert '"stage": "busy"' in body
    assert "startedAt" in body and "ageSec" in body
    assert "接管" in body  # hint 明确告诉教师页面会接管
    assert "关闭引擎窗口后重启" not in body  # 不再要求重启引擎
    # /xxt/status 透传 loginCompletedTs 与 loginJob
    assert 'view["loginCompletedTs"]' in src
    assert 'view["loginJob"]' in src
    # /jobs 透传 started_at
    assert '"started_at": float(job.get("started_at") or 0.0)' in src


def test_frontend_contract_for_d191():
    root = Path(__file__).resolve().parents[2]
    view = (root / "app/src/views/XxetongView.vue").read_text(encoding="utf-8")
    client = (root / "app/src/lib/engineClient.ts").read_text(encoding="utf-8")
    # 409 接管，而不是显示“已有任务”
    assert "kind: 'busy'" in client
    assert "started.kind === 'busy'" in view
    assert "已接上正在进行的扫码任务" in view
    assert "⚠ ${msg}" not in view
    # 无任务 + 二维码非本轮 → 明确失效，不再空转等待
    assert "!loginJobId && !qrFiled" in view
    assert "没有正在等待的扫码任务" in view
    assert "qrStale" in view
    # job 不存在（引擎重启）→ 停止轮询
    assert "job.status === 'missing'" in view
    assert "status: 'missing'" in client
    # 旧 loginRedirect 在登录成功后不再红
    assert "r.login_completed_ts" in view
    assert "staleRedirect" in view
