"""D86 §7：batch 通道（JSONL 生成 / 说明 / plan→items）回归；不联网。"""

import json
from pathlib import Path

from assist.grading import llm_batch as B
from assist.grading import providers as P


def test_build_jsonl_and_readme(tmp_path: Path):
    items = [{"custom_id": "学生A", "system_prompt": "SYS", "user_text": "U1",
              "response_format": {"type": "json_object"}}]
    p = B.build_jsonl(items, tmp_path / "b" / "e.jsonl", model="m1")
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows[0]["custom_id"] == "学生A" and rows[0]["method"] == "POST"
    assert rows[0]["body"]["model"] == "m1"
    assert rows[0]["body"]["messages"][0]["role"] == "system"
    assert rows[0]["body"]["response_format"] == {"type": "json_object"}

    r = B.write_instructions(p, provider={"name": "Aliyun", "base_url": "https://x/v1",
                                          "batch_support": True})
    txt = r.read_text(encoding="utf-8")
    assert "batches" in txt and "https://x/v1" in txt and "本机无法联网实测" in txt


def test_submit_requires_batch_support(tmp_path: Path):
    P.save_provider(tmp_path, "A", base_url="https://x/v1", api_key="sk-abcdefgh1234")
    p = B.build_jsonl([{"custom_id": "s", "user_text": "u"}], tmp_path / "e.jsonl", model="m")
    rep = B.submit(tmp_path, "A", p)
    assert rep["ok"] is False and "batch_support" in rep["error"]


def test_plan_batch_items_from_transcripts_and_plan(tmp_path: Path):
    # 造 plan + 转录
    class_dir = "classes/demo"
    (tmp_path / class_dir / "grading" / "t1" / "transcripts").mkdir(parents=True)
    plan = {"taskId": "t1", "classDir": class_dir, "mode": "optimized",
            "students": [{"name": "学生A", "tag": "qa",
                          "questions": [{"no": 1, "content": "求 a", "solution": "a=2"}]}]}
    (tmp_path / class_dir / "grading" / "t1" / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    (tmp_path / class_dir / "grading" / "t1" / "transcripts" / "学生A.json").write_text(
        json.dumps({"student": "学生A", "markdown": "学生答案：a=3"}, ensure_ascii=False),
        encoding="utf-8")
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"id": "t1", "class_dir": class_dir,
                                "grade": {"steps": ["transcribe", "evaluate"]}}),
                    encoding="utf-8")
    P.save_provider(tmp_path, "A", base_url="https://x/v1", model="m-eval")
    P.set_stage(tmp_path, "evaluation", provider="A", model="m-eval")
    plan_items = B.plan_batch_items(tmp_path, task)
    assert plan_items["model"] == "m-eval" and plan_items["provider"] == "A"
    assert len(plan_items["items"]) == 1
    it = plan_items["items"][0]
    assert it["custom_id"] == "学生A"
    assert "求 a" in it["user_text"] and "a=2" in it["user_text"] and "学生答案：a=3" in it["user_text"]


def test_cli_batch_output_never_leaks_plaintext_key(tmp_path: Path):
    """回归（安全）：`assist llm batch` 输出必须只含掩码 key。"""
    from click.testing import CliRunner
    from assist.cli import cli

    P.save_provider(tmp_path, "A", base_url="https://x/v1", api_key="sk-secret-abcdefgh",
                    model="m1", batch_support=True)
    P.set_stage(tmp_path, "evaluation", provider="A", model="m1")
    class_dir = "classes/demo"
    (tmp_path / class_dir / "grading" / "t1" / "transcripts").mkdir(parents=True)
    (tmp_path / class_dir / "grading" / "t1" / "plan.json").write_text(
        json.dumps({"taskId": "t1", "classDir": class_dir,
                    "students": [{"name": "学生A", "tag": "qa", "questions": []}]}),
        encoding="utf-8")
    (tmp_path / class_dir / "grading" / "t1" / "transcripts" / "学生A.json").write_text(
        json.dumps({"student": "学生A", "markdown": "答案"}), encoding="utf-8")
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"id": "t1", "class_dir": class_dir}), encoding="utf-8")

    res = CliRunner().invoke(cli, ["llm", "batch", "--task", str(task), "-w", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert "sk-secret-abcdefgh" not in res.output
    assert "sk-****efgh" in res.output
    # 说明文件同样不含明文
    readme = (tmp_path / class_dir / "grading" / "t1" / "batch" / "BATCH-README.txt")
    assert readme.is_file() and "sk-" not in readme.read_text(encoding="utf-8")


def test_provider_public_masks():
    assert B.provider_public({"name": "A", "api_key": "sk-abcdefgh1234"})["api_key"] == "sk-****1234"
    assert B.provider_public({"name": "A", "api_key": ""})["api_key"] == ""
