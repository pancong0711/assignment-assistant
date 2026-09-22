@echo off
REM ============================================================
REM  一键启动（R1.2 v3）：零依赖裸机起步 —— uv/Python/缓存/venv 全部装入 workspace
REM  修复：此前由于 mkdir 之前先挂日志重定向，目录缺失时所有后续命令
REM        的输出重定向也失败 → 'The system cannot find the path specified'。
REM        本次顺序改为：建目录 → 之后才挂日志。
REM ============================================================
setlocal enableextensions
chcp 65001 >nul
set "WORKSPACE=%~dp0"

IF "%WORKSPACE%"=="" set "WORKSPACE=%~dp0"
IF NOT EXIST "%WORKSPACE%" mkdir "%WORKSPACE%"
set "ROOT=%~dp0.."
set "LOG=%WORKSPACE%\start.log"
echo === START %DATE% %TIME% === >> "%LOG%"
set PATH=%WORKSPACE%\.runtime\uv;%WORKSPACE%\.runtime\uv\bin;%WORKSPACE%\.runtime\python;%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Programs\uv;%PATH%
set "UV_INSTALL_DIR=%WORKSPACE%\.runtime\uv"
set "UV_PYTHON_INSTALL_DIR=%WORKSPACE%\.runtime\python"
set "UV_CACHE_DIR=%WORKSPACE%\.runtime\cache\uv"
set "UV_PROJECT_ENVIRONMENT=%WORKSPACE%\.runtime\venv"
set "ASSIST_WORKSPACE=%WORKSPACE%"
echo [1/5] 确保工作区子目录
IF NOT EXIST "%WORKSPACE%\.runtime" mkdir "%WORKSPACE%\.runtime"
IF NOT EXIST "%WORKSPACE%\.runtime\cache\uv" mkdir "%WORKSPACE%\.runtime\cache\uv"
IF NOT EXIST "%WORKSPACE%\.runtime\browsers" mkdir "%WORKSPACE%\.runtime\browsers"
IF EXIST "%LOG%" DEL "%LOG%" >nul 2>nul
echo =============================== >> "%LOG%"
echo [2/5] 安装 uv（用户级，二进制放 workspace）
where uv >nul 2>nul
IF ERRORLEVEL 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  IF ERRORLEVEL 1 (
    echo uv 下载安装失败，请检查网络
    echo [uv install FAIL] >> "%LOG%"
    pause
    exit /b 1
  )
  REM 刷新 PATH（本会话可见）
  set PATH=%PATH%
)
where uv >nul 2>nul
IF ERRORLEVEL 1 ( echo uv 仍不可用（重启终端再试或看日志） >> "%LOG%" & echo uv 不可用 & pause & exit /b 1 )
echo [3/5] 为 workspace 准备 Python（uv 托管 Python 3.13）
uv python install 3.13 >> "%LOG%" 2>&1
IF ERRORLEVEL 1 echo [WARN] uv python install 失败（可能已有系统的 3.13）>> "%LOG%"
echo [4/5] 创建 venv（workspace/.runtime/venv，D14）
IF NOT EXIST "%WORKSPACE%\.runtime\venv\Scripts\python.exe" (
  uv venv --python 3.13 "%WORKSPACE%\.runtime\venv" >> "%LOG%" 2>&1
)
if not exist "%WORKSPACE%\.runtime\venv\Scripts\python.exe" (
  echo venv 创建失败，见日志 & notepad "%LOG%" & pause & exit /b 1
)
echo [5/5] 安装引擎依赖并启动
uv pip install -e "%ROOT%\engine" --python "%WORKSPACE%\.runtime\venv\Scripts\python.exe" >> "%LOG%" 2>&1
IF ERRORLEVEL 1 (
  echo.
  echo 依赖安装失败，详见日志（%LOG%）并按需返回上一步。
  notepad "%LOG%"
  pause & exit /b 1
)
echo [6/6] 启动引擎 http://127.0.0.1:8601/
start "" http://127.0.0.1:8601/
"%WORKSPACE%\.runtime\venv\Scripts\assist.exe" serve --port 8601 >> "%LOG%" 2>&1
echo 引擎已退出。日志： %LOG%
pause
endlocal
