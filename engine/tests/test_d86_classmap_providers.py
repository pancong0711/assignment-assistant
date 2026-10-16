"""D86 §1/§2：班级映射（按文件名建议）与 LLM provider 管理（含密钥拆分）回归。"""

import json
import os
from pathlib import Path

from assist import settings_store
from assist.grading import providers as P
from assist.xxt import classmap


# ---------------- §2 设置/密钥拆分 ----------------

def test_secrets_file_0600_and_split(tmp_path: Path):
    settings_store.update_settings(tmp_path, lambda d: d.setdefault("xxt", {}).__setitem__("write_allowlist", []))
    settings_store.update_secrets(tmp_path, lambda d: d.setdefault("llm", {}).setdefault("providers", {}).__setitem__("A", "sk-abcdefgh1234"))
    assert (tmp_path / "settings.local.json").is_file()
    sp = tmp_path / "settings.local.secrets.json"
    assert sp.is_file()
    if os.name != "nt":
        assert (sp.stat().st_mode & 0o777) == 0o600
    # 密钥只在其一文件里
    assert "api_key" not in (tmp_path / "settings.local.json").read_text(encoding="utf-8")
    assert "sk-abcdefgh1234" in sp.read_text(encoding="utf-8")


def test_mask_key():
    assert P.mask_key("sk-abcdefgh1234") == "sk-****1234"
    assert P.mask_key("short") == "****"
    assert P.mask_key("") == ""


def test_provider_crud_and_mask(tmp_path: Path):
    r = P.save_provider(tmp_path, "Aliyun", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                        api_key="sk-abcdefgh1234", batch_support=True, model="qwen-vl-max")
    assert r["ok"]
    lst = P.list_providers(tmp_path, mask=True)
    assert len(lst) == 1 and lst[0]["api_key"] == "sk-****1234" and lst[0]["has_key"]
    assert lst[0]["models"] == ["qwen-vl-max"] and lst[0]["batch_support"] is True
    # 明文只在内部视图（mask=False）
    assert P.list_providers(tmp_path, mask=False)[0]["api_key"] == "sk-abcdefgh1234"
    # 更新（不改 key）+ 模型历史去重前置
    P.save_provider(tmp_path, "Aliyun", model="qwen2.5")
    p = P.list_providers(tmp_path, mask=False)[0]
    assert p["api_key"] == "sk-abcdefgh1234" and p["models"][:2] == ["qwen2.5", "qwen-vl-max"]
    # 清除 key
    P.save_provider(tmp_path, "Aliyun", api_key="")
    assert P.list_providers(tmp_path)[0]["has_key"] is False
    # 删除
    assert P.delete_provider(tmp_path, "Aliyun")["ok"] is True
    assert P.list_providers(tmp_path) == []


def test_stages_and_model_history(tmp_path: Path):
    P.save_provider(tmp_path, "A", base_url="https://a.example/v1")
    P.save_provider(tmp_path, "B", base_url="https://b.example/v1")
    r = P.set_stage(tmp_path, "transcription", provider="A", model="glm-4v")
    assert r["ok"] and r["config"]["provider"] == "A"
    P.set_stage(tmp_path, "evaluation", provider="B", model="deepseek-chat", batch=True)
    st = P.stages(tmp_path)
    assert st["transcription"]["model"] == "glm-4v"
    assert st["evaluation"] == {"provider": "B", "model": "deepseek-chat", "batch": True}
    # 填写即记录：模型进入该 provider 的历史
    assert "glm-4v" in P.list_providers(tmp_path, mask=False)[0]["models"]
    # 不存在的 provider 拒绝
    assert P.set_stage(tmp_path, "evaluation", provider="Nope", model="x")["ok"] is False


def test_stage_endpoint_resolution(tmp_path: Path):
    P.save_provider(tmp_path, "A", base_url="https://a.example/v1", api_key="sk-key-12345678", model="m1")
    P.set_stage(tmp_path, "evaluation", provider="A", model="m2")
    ep = P.stage_endpoint(tmp_path, "evaluation")
    assert ep["base_url"] == "https://a.example/v1" and ep["model"] == "m2"
    assert ep["api_key"] == "sk-key-12345678" and ep["host"] == "a.example"


def test_legacy_migration_to_provider0(tmp_path: Path):
    def _fn(d):
        d["llm"] = {"base_url": "https://legacy.example/v1", "api_key": "sk-legacy-98765432",
                    "model": "legacy-model"}
    settings_store.update_settings(tmp_path, _fn)
    r = P.migrate_legacy(tmp_path)
    assert r["migrated"] and r["provider"] == P.LEGACY_PROVIDER_NAME
    data = settings_store.read_settings(tmp_path)
    assert "api_key" not in (data.get("llm") or {})          # key 已移出
    assert P.list_providers(tmp_path)[0]["api_key"] == "sk-****5432"
    assert P.stages(tmp_path).get("transcription", {}).get("provider") == P.LEGACY_PROVIDER_NAME
    assert P.migrate_legacy(tmp_path)["migrated"] is False   # 幂等


def test_public_config_has_no_plain_key(tmp_path: Path):
    P.save_provider(tmp_path, "A", base_url="https://a.example/v1", api_key="sk-plain-abcdefgh")
    cfg = P.public_config(tmp_path)
    blob = json.dumps(cfg, ensure_ascii=False)
    assert "sk-plain-abcdefgh" not in blob and "sk-****efgh" in blob


# ---------------- §1 班级映射 ----------------

def _mk_class(ws: Path, dirname: str, roster_file: str):
    d = ws / "classes" / dirname / "roster"
    d.mkdir(parents=True, exist_ok=True)
    (d / roster_file).write_text("x", encoding="utf-8")


def test_suggest_by_roster_filename(tmp_path: Path):
    _mk_class(tmp_path, "chem25", "化工25-点名册.xlsx")
    _mk_class(tmp_path, "env25", "示例乙班-点名册.xlsx")
    sug = classmap.suggest_class_dir(tmp_path, "化工25")
    assert sug and sug[0]["classDir"] == "classes/chem25"
    assert sug[0]["matchedFile"] == "化工25-点名册.xlsx"
    assert classmap.suggest_class_dir(tmp_path, "不存在的班") == []


def test_resolve_and_set_class_dir(tmp_path: Path):
    _mk_class(tmp_path, "chem25", "化工25C2-点名册.xlsx")
    r = classmap.resolve_class_dir(tmp_path, "100", "200", "化工25C2")
    assert r["classDir"] == "classes/chem25" and r["source"] == "suggest"
    classmap.set_class_dir(tmp_path, "100", "200", "classes/chem25")
    r2 = classmap.resolve_class_dir(tmp_path, "100", "200", "化工25C2")
    assert r2["source"] == "map" and r2["classDir"] == "classes/chem25"
    from assist.settings_store import read_settings
    cm = (read_settings(tmp_path).get("xxt") or {}).get("class_map")
    assert cm == {"100:200": "classes/chem25"}


def test_exact_filename_match_autowrite(tmp_path: Path):
    _mk_class(tmp_path, "chem25", "化工25.xlsx")
    r = classmap.resolve_class_dir(tmp_path, "1", "2", "化工25", auto_write=True)
    assert r["source"] == "auto"
    assert classmap.class_dir_for(tmp_path, "1", "2") == "classes/chem25"


def test_d91_forget_model(tmp_path):
    """D91-M3：可从 provider 的 models[] 删除指定候选。"""
    from assist.grading import providers
    ws = tmp_path / "ws"; ws.mkdir()
    providers.save_provider(ws, "aliyun", base_url="https://x/v1", api_key="sk-a")
    providers.save_provider(ws, "aliyun", model="qwen-max")
    providers.save_provider(ws, "aliyun", model="qwen-plus")
    pub = providers.public_config(ws)
    models = next(p["models"] for p in pub["providers"] if p["name"] == "aliyun")
    assert models[:2] == ["qwen-plus", "qwen-max"]
    # 删除 qwen-max
    providers.save_provider(ws, "aliyun", forget_model="qwen-max")
    models2 = next(p["models"] for p in providers.public_config(ws)["providers"]
                   if p["name"] == "aliyun")
    assert "qwen-max" not in models2 and "qwen-plus" in models2
