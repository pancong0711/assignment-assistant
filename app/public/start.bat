@echo off
REM [R1.2 v5] start.bat -- zero-dependency bootstrap for assignment-assistant.
REM Distinguished convention (D28): the folder THIS .bat file lives in IS the workspace.
REM Everything (uv / python / venv / caches / logs) is installed under <that dir>\.runtime\.
REM Delete that dir = full uninstall. PWA settings page explains the same in Chinese.
setlocal enableextensions
echo [R1.2 v5] assignment-assistant launcher
set "WORKSPACE=%~dp0"
set "LOG=%WORKSPACE%\start.log"
set "ROOT=%~dp0.."
IF NOT EXIST "%WORKSPACE%" mkdir "%WORKSPACE%" 2>nul
IF NOT EXIST "%WORKSPACE%\.runtime" mkdir "%WORKSPACE%\.runtime" 2>nul
IF NOT EXIST "%WORKSPACE%\.runtime\cache\uv" mkdir "%WORKSPACE%\.runtime\cache\uv" 2>nul
IF NOT EXIST "%WORKSPACE%\.runtime\browsers" mkdir "%WORKSPACE%\.runtime\browsers" 2>nul
echo =============================== >> "%LOG%"
set PATH=%WORKSPACE%\.runtime\uv;%WORKSPACE%\.runtime\uv\bin;%WORKSPACE%\.runtime\python;%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Programs\uv;%PATH%
set "UV_INSTALL_DIR=%WORKSPACE%\.runtime\uv"
set "UV_PYTHON_INSTALL_DIR=%WORKSPACE%\.runtime\python"
set "UV_CACHE_DIR=%WORKSPACE%\.runtime\cache\uv"
set "UV_PROJECT_ENVIRONMENT=%WORKSPACE%\.runtime\venv"
set "ASSIST_WORKSPACE=%WORKSPACE%"
echo [1/6] workspace = %WORKSPACE%
echo [2/6] install uv if missing (user-level, into workspace)
where uv >nul 2>nul
IF ERRORLEVEL 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  IF ERRORLEVEL 1 (
    echo [FAIL] uv download failed - check network
    echo [uv install FAIL] >> "%LOG%"
    pause
    exit /b 1
  )
  REM refresh PATH for this session
  set PATH=%PATH%
)
where uv >nul 2>nul
IF ERRORLEVEL 1 (
  echo [FAIL] uv still not available - restart terminal and retry
  echo [uv not on PATH] >> "%LOG%"
  pause
  exit /b 1
)
echo [3/6] install managed python 3.13 (into workspace)
uv python install 3.13 >> "%LOG%" 2>&1
IF ERRORLEVEL 1 echo [WARN] uv python install failed; system python may exist >> "%LOG%"
echo [4/6] create venv (workspace/.runtime/venv, D14)
IF NOT EXIST "%WORKSPACE%\.runtime\venv\Scripts\python.exe" (
  uv venv --python 3.13 "%WORKSPACE%\.runtime\venv" >> "%LOG%" 2>&1
)
IF NOT EXIST "%WORKSPACE%\.runtime\venv\Scripts\python.exe" (
  echo [FAIL] venv creation failed - see start.log
  notepad "%LOG%"
  pause
  exit /b 1
)
echo [5/6] install engine dependencies
uv pip install -e "%ROOT%\engine" --python "%WORKSPACE%\.runtime\venv\Scripts\python.exe" >> "%LOG%" 2>&1
IF ERRORLEVEL 1 (
  echo.
  echo [FAIL] dependency install failed - see start.log
  notepad "%LOG%"
  pause
  exit /b 1
)
echo [6/6] start engine http://127.0.0.1:8601/
start "" http://127.0.0.1:8601/
"%WORKSPACE%\.runtime\venv\Scripts\assist.exe" serve --port 8601 >> "%LOG%" 2>&1
echo engine exited. log: %LOG%
pause
endlocal
