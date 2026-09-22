@echo off
REM 一键启动（R1.2）：教师双击即得 Companion 模式（Windows）。
setlocal
SET WS=%ASSIST_WORKSPACE%
IF "%WS%"=="" SET WS=%USERPROFILE%\assignment-assistant-workspace
IF NOT EXIST "%WS%" mkdir "%WS%"
SET ASSIST_WORKSPACE=%WS%
where uv >nul 2>nul || (
  echo 安装 uv…
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
SET VENV=%WS%\.runtime\venv
IF NOT EXIST "%VENV%\Scripts\python.exe" uv venv --python 3.13 "%VENV%"
set "UV_CACHE_DIR=%WS%\.runtime\cache\uv"
set "UV_PROJECT_ENVIRONMENT=%VENV%"
uv pip install -e "%~dp0..\engine" --python "%VENV%\Scripts\python.exe"
start "" http://127.0.0.1:8601/
"%VENV%\Scripts\assist.exe" serve --port 8601
endlocal
