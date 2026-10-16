"""D87 安全加固：脱敏扫描器（tools/check-secrets.sh）+ 密钥泄漏回归。

两个层面：
1) **扫描器行为**：用一次性 git 仓库/staged 内容驱动 check-secrets.sh，
   - 已知厂商前缀（sk-/ghp_/AKIA/AIza/hf_/xox）→ 判定失败；
   - 异形高熵 key（敏感键名 + ≥32 位随机值）→ 判定失败；
   - 占位/测试 fixture（placeholder/example/sk-secret-abcdefgh 等）→ 通过（不误报）；
2) **源码红线**：providers.public_config / serve / llm 不得把明文 key 回显或写日志。

不依赖网络；用 subprocess 调用仓库根 tools/check-secrets.sh。
"""
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "check-secrets.sh"


def _run_scan(tmp_path: Path, files: dict[str, str]) -> subprocess.CompletedProcess:
    """在临时 git 仓库里写文件 → git add → 跑脱敏脚本（脚本按 staged 文件扫描）。"""
    env = dict(os.environ)
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "t"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "t@example.com"
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=env)
    for name, content in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, env=env)
    return subprocess.run(["bash", str(SCRIPT)], cwd=tmp_path,
                          capture_output=True, text=True, env=env, timeout=120)


@pytest.mark.parametrize("name,content", [
    ("a.ts", 'const k = "sk-proj-AbCdEf1234567890XyZaBcDeFgHiJkLmN"\n'),
    ("b.txt", 'token="ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"\n'),
    ("c.yml", 'aws_key: "AKIAIOSFODNN7EXAMPLE"\n'),
    ("d.json", '{"api_key": "Xq7mZ2pL9vR4sT8uW1yB5nC3dF6gH0jK2mP"}\n'),
    ("e.toml", 'client_secret = "Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0Lm"\n'),
])
def test_scan_flags_real_looking_secrets(tmp_path, name, content):
    r = _run_scan(tmp_path, {name: content})
    assert r.returncode != 0, f"应拦截疑似密钥：{name}\n{r.stdout}{r.stderr}"
    assert "脱敏失败" in r.stdout


@pytest.mark.parametrize("name,content", [
    ("fixture1.py", 'api_key="sk-secret-abcdefgh"\n'),
    ("fixture2.py", 'api_key="sk-key-12345678"\n'),
    ("doc.md", 'api_key: "placeholder-not-real-xxxxxxxxxxxxxxxx"\n'),
    ("doc2.md", 'token = "<your-token-here>"\n'),
    ("code.py", 'self.api_key = str(settings.get("api_key") or "")\n'),
    ("code2.py", 'key = "stub-key-0000"\n'),
])
def test_scan_allows_placeholders(tmp_path, name, content):
    r = _run_scan(tmp_path, {name: content})
    assert r.returncode == 0, f"不应误报占位/代码：{name}\n{r.stdout}{r.stderr}"
    assert "脱敏检查通过" in r.stdout


def test_scan_flags_banned_paths(tmp_path):
    r = _run_scan(tmp_path, {"settings.local.json": '{"x":1}\n'})
    assert r.returncode != 0
    assert "红线" in r.stdout


# ---------------- 源码红线：绝不明文回显 key ----------------

def test_public_config_never_returns_plaintext_key(tmp_path):
    from assist.grading import providers
    ws = tmp_path / "ws"
    ws.mkdir()
    providers.save_provider(ws, "aliyun", base_url="https://example.com/v1",
                            api_key="sk-realplaintext-abcdefgh")
    cfg = providers.public_config(ws)
    blob = json.dumps(cfg, ensure_ascii=False)
    assert "sk-realplaintext-abcdefgh" not in blob, "public_config 不得回显明文 key"
    # 掩码形态存在
    assert any("****" in str(p.get("api_key", "")) for p in cfg["providers"])


def test_stage_endpoint_key_only_for_internal_use(tmp_path):
    """stage_endpoint 是给 LLMClient 用的（内部），单独存在没问题；
    但 serve 暴露的是 public_config（掩码），这里锁死源码不回显。"""
    src = (REPO / "engine" / "src" / "assist" / "serve.py").read_text(encoding="utf-8")
    # /llm/provider 与 /llm/config 的响应都走 public_config
    assert "providers.public_config(" in src
    # 明确不得把 stage_endpoint 直接塞进 _json 响应
    assert 'self._json(stage_endpoint' not in src


def test_no_raw_key_in_logger_calls():
    """grep 全部引擎源码：logger.* 行内不得出现 {api_key}/{key} 之类插值。"""
    bad = []
    for py in (REPO / "engine" / "src").rglob("*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if "logger." not in line:
                continue
            if re.search(r"\{[^}]*\b(api_?key|secret|authorization|bearer)\b[^}]*\}", line, re.I):
                bad.append(f"{py}:{i}: {line.strip()}")
    assert not bad, "日志行疑似记录密钥：\n" + "\n".join(bad)
