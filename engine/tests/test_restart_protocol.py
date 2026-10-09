"""D67 回归：平台/supervised → 重启执行模式（不真正 kill/exec）。"""

from pathlib import Path

from assist.serve import restart_plan


def test_posix_restart_keeps_execv():
    assert restart_plan("posix", supervised=False) == "execv"
    assert restart_plan("posix", supervised=True) == "execv"


def test_windows_supervised_uses_exit75():
    assert restart_plan("nt", supervised=True) == "exit75"


def test_windows_unsupervised_requires_manual_restart():
    assert restart_plan("nt", supervised=False) == "manual"


def test_start_bat_has_supervisor_loop_and_restart_code():
    """Windows 主路径必须保留 ASSIST_SUPERVISED=1 / 75 退出码 / :ENGINE_LOOP。"""
    root = Path(__file__).resolve().parents[2]
    for name in ("tools/start.bat", "app/public/start.bat"):
        raw = (root / name).read_bytes()
        assert b"ASSIST_SUPERVISED=1" in raw, name
        assert b":ENGINE_LOOP" in raw, name
        assert b'"%RC%"=="75"' in raw, name
