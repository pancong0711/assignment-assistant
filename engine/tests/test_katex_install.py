"""D55/H1 回归：KaTeX 离线包服务端直装（复制同源 dist → workspace/sheets/katex）。"""

from pathlib import Path

import assist.serve as serve


def test_install_katex_from_static_root(tmp_path, monkeypatch):
    static = tmp_path / "dist"
    kat = static / "katex"
    (kat / "contrib").mkdir(parents=True)
    (kat / "fonts").mkdir(parents=True)
    (kat / "katex.min.css").write_text("body{}", encoding="utf-8")
    (kat / "katex.min.js").write_text("//k", encoding="utf-8")
    (kat / "contrib" / "auto-render.min.js").write_text("//a", encoding="utf-8")
    (kat / "fonts" / "KaTeX_Main-Regular.woff2").write_bytes(b"w")
    monkeypatch.setattr(serve, "_static_root", lambda: static)

    ws = tmp_path / "ws"
    ws.mkdir()
    lines: list[str] = []
    rc = serve.install_katex(ws, lines.append)
    assert rc == 0
    assert (ws / "sheets" / "katex" / "katex.min.css").read_text() == "body{}"
    assert (ws / "sheets" / "katex" / "contrib" / "auto-render.min.js").exists()
    assert (ws / "sheets" / "katex" / "fonts" / "KaTeX_Main-Regular.woff2").exists()
    assert any("完成" in l for l in lines)


def test_install_katex_reports_when_no_assets(tmp_path, monkeypatch):
    """无 dist 且无网 → 返回 1 且给出失败行（不抛异常）。"""
    monkeypatch.setattr(serve, "_static_root", lambda: None)

    def _boom(*a, **k):
        raise OSError("offline")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    ws = tmp_path / "ws"
    ws.mkdir()
    lines: list[str] = []
    rc = serve.install_katex(ws, lines.append)
    assert rc == 1 and any("失败" in l for l in lines)
