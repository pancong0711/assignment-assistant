"""D161：翻译题随机种子（新建时随机、记进作业纸、可重抽、可复现）。

问题：翻译题抽取用 `random_seed` 做确定性随机，但**新建时从不写** → 永远 0
→ 每次抽到同一道翻译题。CLI 也没有 `--seed`，同样永远是同题。
"""
from __future__ import annotations

import json
import time

import pytest

from assist.paper.task import ensure_random_seed
from assist.paper.compose import seed_index


@pytest.fixture()
def task_file(tmp_path):
    p = tmp_path / "pad.taskpad.json"
    p.write_text(json.dumps({"id": "pad1", "items": []}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def test_generates_seed_when_missing(task_file):
    task = json.loads(task_file.read_text(encoding="utf-8"))
    assert "random_seed" not in task
    s = ensure_random_seed(task, task_file)
    assert isinstance(s, int) and s > 0
    assert task["random_seed"] == s


def test_writes_back_to_file(task_file):
    """种子必须**落盘**（否则下次又变回 0）。"""
    task = json.loads(task_file.read_text(encoding="utf-8"))
    s = ensure_random_seed(task, task_file)
    saved = json.loads(task_file.read_text(encoding="utf-8"))
    assert saved["random_seed"] == s


def test_existing_seed_kept(task_file):
    """已有种子且未要求重抽 → **保持不变**（保证可复现）。"""
    task = {"id": "p", "random_seed": 12345}
    assert ensure_random_seed(task, task_file) == 12345
    assert task["random_seed"] == 12345


def test_reseed_changes_seed(task_file):
    task = {"id": "p", "random_seed": 12345}
    s = ensure_random_seed(task, task_file, reseed=True)
    assert s != 12345


def test_explicit_seed_wins(task_file):
    task = {"id": "p", "random_seed": 12345}
    assert ensure_random_seed(task, task_file, seed=777) == 777
    assert task["random_seed"] == 777


def test_two_new_pads_get_different_seeds(tmp_path):
    """新建两份作业纸应得到**不同**种子（不会永远抽同一题）。"""
    a = {"id": "a"}
    b = {"id": "b"}
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    sa = ensure_random_seed(a, pa)
    time.sleep(1.1)
    sb = ensure_random_seed(b, pb)
    assert sa != sb, f"两份新作业纸种子相同：{sa}"


def test_same_seed_same_translation():
    """同种子 → 同索引（可复现）；不同种子大概率不同。"""
    assert seed_index(12345, 20) == seed_index(12345, 20)
    picks = {seed_index(s, 20) for s in (1, 1000, 99999, 123456789)}
    assert len(picks) > 1, "不同种子应能抽到不同题"


def test_seed_is_stable_across_reloads(task_file):
    """落盘后重新读取，种子不变（复现性）。"""
    task = json.loads(task_file.read_text(encoding="utf-8"))
    s = ensure_random_seed(task, task_file)
    again = json.loads(task_file.read_text(encoding="utf-8"))
    assert ensure_random_seed(again, task_file) == s
