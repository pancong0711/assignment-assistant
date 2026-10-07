"""D58：TinyTeX 网络安装/检测的离线单元测试（不访问网络）。"""

from pathlib import Path

import assist.paper.tinytex as tinytex


def test_find_xelatex_in_workspace_runtime(tmp_path: Path):
    exe = tmp_path / ".runtime" / "tex" / "bin" / "xelatex"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    found = tinytex.find_xelatex(tmp_path)
    assert found == str(exe.resolve())


def test_asset_name_known_platforms(monkeypatch):
    monkeypatch.setattr(tinytex.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tinytex.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(tinytex, "_is_musl", lambda: False)
    assert tinytex.asset_name() == "TinyTeX-1-linux-x86_64.tar.xz"

    monkeypatch.setattr(tinytex.platform, "system", lambda: "Windows")
    monkeypatch.setattr(tinytex.platform, "machine", lambda: "AMD64")
    assert tinytex.asset_name() == "TinyTeX-1-windows.exe"


def test_install_tinytex_with_mocked_download(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()

    def fake_download(url: str, dest: Path, emit):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake bundle")
        emit(f"fake download {url}")

    def fake_extract(archive: Path, staging: Path, emit):
        inner = staging / "TinyTeX"
        exe = inner / "bin" / "xelatex"
        exe.parent.mkdir(parents=True)
        exe.write_text("#!/bin/sh\n", encoding="utf-8")
        emit("fake extract")
        return inner

    monkeypatch.setattr(tinytex, "_download_with_fallback", fake_download)
    monkeypatch.setattr(tinytex, "_extract_bundle", fake_extract)
    monkeypatch.setattr(tinytex, "_run_xetex_postinstall", lambda tex_dir, emit: None)

    lines: list[str] = []
    rc = tinytex.install_tinytex(ws, lines.append)
    assert rc == 0
    assert (ws / ".runtime" / "tex" / "bin" / "xelatex").exists()
    assert tinytex.find_xelatex(ws)
    assert any("完成" in line for line in lines)


def test_serve_exposes_tinytex_install_item():
    import assist.serve as serve
    assert "tinytex" in serve.INSTALL_ITEMS
