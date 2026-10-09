"""D65-P0 回归：浏览器优先级、dry-run 解析、镜像 URL 真实性。不触网。"""

from pathlib import Path

from assist.xxt import browsers as B
from assist.xxt import installer as I


DRY_RUN_SAMPLE = """
browser: chromium version 143.0.7499.4
  Install location:    /tmp/pw/chromium-1200
  Download url:        https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/1200/chromium-linux.zip
  Download fallback 1: https://example.invalid/fallback1.zip
  Download fallback 2: https://example.invalid/fallback2.zip

browser: ffmpeg
  Install location:    /tmp/pw/ffmpeg-1011
  Download url:        https://cdn.playwright.dev/dbazure/download/playwright/builds/ffmpeg/1011/ffmpeg-linux.zip

browser: chromium-headless-shell version 143.0.7499.4
  Install location:    /tmp/pw/chromium_headless_shell-1200
  Download url:        https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/1200/chromium-headless-shell-linux.zip

browser: ffmpeg
  Install location:    /tmp/pw/ffmpeg-1011
  Download url:        https://cdn.playwright.dev/dbazure/download/playwright/builds/ffmpeg/1011/ffmpeg-linux.zip
"""


def test_parse_dry_run_dedupes_by_location():
    jobs = I._parse_dry_run(DRY_RUN_SAMPLE, skip_headless=False)
    assert [Path(j["loc"]).name for j in jobs] == [
        "chromium-1200", "ffmpeg-1011", "chromium_headless_shell-1200"
    ]


def test_parse_dry_run_can_skip_headless_shell():
    jobs = I._parse_dry_run(DRY_RUN_SAMPLE, skip_headless=True)
    names = [Path(j["loc"]).name for j in jobs]
    assert names == ["chromium-1200", "ffmpeg-1011"]
    assert all("headless_shell" not in n for n in names)


def test_job_urls_use_verified_mirrors_not_huawei():
    job = {
        "loc": "/tmp/pw/chromium-1200",
        "official": "https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/1200/chromium-linux.zip",
        "urls": ["https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/1200/chromium-linux.zip"],
    }
    urls = I._job_urls(job)
    joined = " ".join(urls.values())
    assert "huaweicloud" not in joined
    assert urls["npmmirror_cdn"] == (
        "https://cdn.npmmirror.com/binaries/playwright/builds/chromium/1200/chromium-linux.zip"
    )
    assert urls["azureedge"] == (
        "https://playwright.azureedge.net/builds/chromium/1200/chromium-linux.zip"
    )
    assert urls["official"] == job["official"]


def _fake_env(monkeypatch):
    monkeypatch.setenv("XXT_CHROME", "/bin/sh")
    monkeypatch.setattr(B, "_candidates", lambda: [
        ("msedge", ["edge"]),
        ("chrome", ["chrome"]),
    ])
    paths = {"edge": "/usr/bin/edge", "chrome": "/usr/bin/chrome"}

    def fake_find(cands: list[str]) -> str | None:
        c = cands[0]
        if c == "/bin/sh":
            return c
        return paths.get(c)

    monkeypatch.setattr(B, "_find", fake_find)


def test_launch_attempts_priority_order(monkeypatch):
    _fake_env(monkeypatch)
    attempts = B.launch_attempts()
    assert attempts[0] == {"executable_path": "/bin/sh"}
    assert attempts[1]["channel"] == "msedge"
    assert attempts[2]["channel"] == "chrome"
    assert attempts[-1] == {"channel": "chromium"}


def test_inventory_probe_skips_bad_tier_and_picks_next(monkeypatch):
    _fake_env(monkeypatch)
    calls: list[dict] = []

    def fake_probe(kwargs: dict, timeout_ms: int = 20000) -> None:
        calls.append(kwargs)
        if kwargs.get("executable_path") == "/bin/sh":
            raise RuntimeError("bad env path")

    monkeypatch.setattr(B, "_probe", fake_probe)
    inv = B.inventory(probe=True)
    assert len(calls) == 2
    assert inv["pick"]["kind"] == "channel"
    assert "Edge" in inv["pick"]["name"]
    assert all("_kwargs" not in t for t in inv["tiers"])


def test_start_bat_does_not_reuse_workspace_engine_without_optin():
    root = Path(__file__).resolve().parents[2]
    data = (root / "tools" / "start.bat").read_bytes()
    assert b"ASSIST_ENGINE_LOCAL" in data
    assert b"engine-version.json" in data
    assert b"FC /B" in data
    # 旧的“无条件命中 workspace\\engine 就复用”必须消失
    assert b'\r\nIF EXIST "%WORKSPACE%\\engine\\pyproject.toml" goto ENGINE_LOCAL\r\n' not in data
