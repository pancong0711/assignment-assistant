"""tools/skill_installer.py：宿主 skill 安装/校验器（qwenwork / workbuddy）。"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "skill_installer.py"


def _run(args, cwd=None):
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, timeout=60, cwd=cwd or REPO)


def test_list_reports_both_hosts():
    r = _run(["list", "--json"])
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    hosts = {s["host"] for s in d["skills"]}
    assert "qwenwork" in hosts and "workbuddy" in hosts


def test_repo_skills_have_required_files():
    assert (REPO / "skills" / "qwenwork" / "assignment-grading" / "SKILL.md").is_file()
    wb = REPO / "skills" / "workbuddy" / "assignment-grading"
    for f in ("skill.yml", "run.py", "README.md"):
        assert (wb / f).is_file(), f


def test_install_and_verify_qwenwork(tmp_path):
    r = _run(["install", "--host", "qwenwork", "--dest", str(tmp_path), "--json"])
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["ok"] and d["installed"]
    name = d["installed"][0]["name"]
    assert (tmp_path / name / "SKILL.md").is_file()

    v = _run(["verify", "--host", "qwenwork", "--dest", str(tmp_path), "--json"])
    assert v.returncode == 0
    assert json.loads(v.stdout)["ok"] is True


def test_install_workbuddy_requires_dest():
    r = _run(["install", "--host", "workbuddy"])
    assert r.returncode == 2
    assert "--dest" in r.stdout


def test_verify_missing_dir_reports_not_installed(tmp_path):
    v = _run(["verify", "--host", "qwenwork", "--dest", str(tmp_path / "nope")])
    assert v.returncode == 1
    assert "未安装" in v.stdout


def test_workbuddy_install_includes_entry(tmp_path):
    r = _run(["install", "--host", "workbuddy", "--dest", str(tmp_path), "--json"])
    assert r.returncode == 0, r.stderr
    name = json.loads(r.stdout)["installed"][0]["name"]
    for f in ("skill.yml", "run.py", "README.md"):
        assert (tmp_path / name / f).is_file(), f
