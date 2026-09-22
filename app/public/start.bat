@echo off
REM ============================================================
REM  一键启动（R1.2 v2）：假设机器是"零依赖裸机"——
REM   1) 装 uv（\\ user 级，装在 workspace 内）
REM   2) 用 uv 托管 Python 3.13（也装进 workspace）
REM   3) 建/更新 workspace/.runtime/venv 并装引擎依赖（缓存也在 workspace）
REM   4) 起引擎 8601（占用则顺延 8602..）并打开浏览器
REM  全过程看得到的日志写 %WS%\start.log；结束时 pause 不闪退。
REM  用法：双击；或 cmd 里运行 start.bat [workspace]
REM ============================================================
setlocal enableextensions
chcp 65001 >nul
SET WORKSPACE=%~1
IF "%WORKSPACE%"=="" IF "%ASSIST_WORKSPACE%"=="" SET WORKSPACE=%USERPROFILE%\assignment-assistant-workspace
IF NOT DEFINED WORKSPACE SET "WORKSPACE=%USERPROFILE%\assignment-assistant-workspace"
SET "ROOT=%~dp0.."
SET "LOG=%WORKSPACE%\start.log"
SET "PATH=%WORKSPACE%\.runtime\uv;%WORKSPACE%\.runtime\uv\bin;%WORKSPACE%\.runtime\python;%USERPROFILE%\.local\bin;%PATH%"
set UV_TOOL_BIN_DIR=%WORKSPACE%\.runtime\uv
set UV_PYTHON_INSTALL_DIR=%WORKSPACE%\.runtime\python
set UV_CACHE_DIR=%WORKSPACE%\.runtime\cache\uv
set UV_PROJECT_ENVIRONMENT=%WORKSPACE%\.runtime\venv
set ASSIST_WORKSPACE=%WORKSPACE%


echo [1/4] 确保工作区 %WORKSPACE% 并初始化……
if not exist "%WORKSPACE%" mkdir "%WORKSPACE%" 2>>"%LOG%"
echo === START %DATE% %TIME% === >> "%LOG%"

echo [2/5] 安装 uv（用户级，二进制放 workspace）…
where uv >nul 2>nul
IF ERRORLEVEL 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  IF ERRORLEVEL 1 (
    echo uv 下载安装失败，请检查网络或查看日志 %LOG%
    pause & exit /b 1
  )
  :: 刷新 PATH 使 uv 可见
  set "PATH=%PATH%;%LOCALAPPDATA%\Programs\uv"
)
where uv >nul 2>nul || (echo uv 仍不可用，环境变量 PATH 更新可能延迟
  echo [uv 未在 PATH（重启终端或重跑一次脚本可解决）] >> "%LOG%" & pause & exit /b 1)

echo [3/5] 为工作区准备 Python 3.13（uv 托管，装在 workspace）…
uv python install 3.13 >> "%LOG%" 2>&1
IF ERRORLEVEL 1 echo [WARN] uv python install 失败（可能已有系统的 3.13 可用）>> "%LOG%"

echo [3/5] 创建 venv（workspace/.runtime/venv，D14）…
if not exist "%WORKSPACE%\.runtime\venv\Scripts\python.exe" uv venv --python 3.13 "%WORKSPACE%\.runtime\venv" >> "%LOG%" 2>&1

echo [4/5] 安装引擎依赖…
uv pip install -e "%ROOT%\engine" --python "%WORKSPACE%\.runtime\venv\Scripts\python.exe" >> "%LOG%" 2>&1
IF ERRORLEVEL 1 (
  echo.
  echo 依赖安装失败：请查看日志 %LOG%
  notepad "%LOG%"
  pause & exit /b 1
)

echo [5/5] 启动引擎 http://127.0.0.1:8601/ …
start "" http://127.0.0.1:8601/
"%WORKSPACE%\.runtime\venv\Scripts\assist.exe" serve --port 8601 >> "%LOG%" 2>&1
echo 引擎已退出（窗口可能自动关闭）。日志： %LOG%
pause
endlocal
