@echo off
REM [R1.2 v6] assignment-assistant launcher (all-ASCII, cmd-parser safe).
REM D28: the folder THIS bat lives in IS the workspace; uv/python/venv/caches all
REM live under that dir .runtime; delete that dir = full uninstall.
setlocal enableextensions
echo [R1.2 v6] assignment-assistant launcher
echo workspace = (this bat folder)
set "WORKSPACE=%~dp0"
IF "%WORKSPACE:~-1%"=="\\" set "WORKSPACE=%WORKSPACE:~0,-1%"
set "LOG=%WORKSPACE%\start.log"
set "ROOT=%~dp0.."
IF NOT EXIST "%WORKSPACE%" mkdir "%WORKSPACE%" 2>nul
IF NOT EXIST "%WORKSPACE%\.runtime" mkdir "%WORKSPACE%\.runtime" 2>nul
IF NOT EXIST "%WORKSPACE%\.runtime\cache\uv" mkdir "%WORKSPACE%\.runtime\cache\uv" 2>nul
IF NOT EXIST "%WORKSPACE%\.runtime\browsers" mkdir "%WORKSPACE%\.runtime\browsers" 2>nul
IF EXIST "%LOG%" DEL "%LOG%" >nul 2>nul
echo =============================== >> "%LOG%"
set "PATH=%WORKSPACE%\.runtime\uv;%WORKSPACE%\.runtime\uv\bin;%WORKSPACE%\.runtime\python;%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Programs\uv;%PATH%"
set "UV_INSTALL_DIR=%WORKSPACE%\.runtime\uv"
set "UV_PYTHON_INSTALL_DIR=%WORKSPACE%\.runtime\python"
set "UV_CACHE_DIR=%WORKSPACE%\.runtime\cache\uv"
set "UV_PROJECT_ENVIRONMENT=%WORKSPACE%\.runtime\venv"
[D29-cn] China mirror trio: pypi tuna + python-build-standalone ghfast + playwright npmmirror

IF NOT DEFINED UV_DEFAULT_INDEX set "UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"

IF NOT DEFINED UV_PYTHON_INSTALL_MIRROR set "UV_PYTHON_INSTALL_MIRROR=https://ghfast.top/https://github.com/astral-sh/python-build-standalone/releases/download"

IF NOT DEFINED PLAYWRIGHT_DOWNLOAD_HOST set "PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/"
set "ASSIST_WORKSPACE=%WORKSPACE%"
echo [1/6] workspace = %WORKSPACE%
:TRY_UV
where uv >nul 2>nul
IF NOT ERRORLEVEL 1 goto HAVE_UV
echo [2/6] install uv: direct single-file uv.exe into workspace (no system residue)
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri https://ghfast.top/https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip -OutFile $env:ASSIST_WORKSPACE\.runtime\uv.zip -UseBasicParsing } catch { Invoke-WebRequest -Uri https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip -OutFile $env:ASSIST_WORKSPACE\.runtime\uv.zip -UseBasicParsing }"
IF ERRORLEVEL 1 GOTO UV_VIA_INSTALLER
IF NOT EXIST "%WORKSPACE%\.runtime\uv.zip" GOTO UV_VIA_INSTALLER
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force $env:ASSIST_WORKSPACE\.runtime\uv.zip $env:ASSIST_WORKSPACE\.runtime\uv"
IF ERRORLEVEL 1 GOTO UV_VIA_INSTALLER
echo [INFO] direct uv.exe OK (workspace-only, no system residue)
GOTO UV_AFTER
:UV_VIA_INSTALLER
echo [INFO] fallback to official installer
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
IF ERRORLEVEL 1 (
  echo [FAIL] uv download failed - check network
  echo [uv install FAIL] >> "%LOG%"
  pause
  exit /b 1
)
:UV_AFTER
REM NOTE: no 'set PATH=%^PATH%' inside paren blocks - see docs/13 M-D (D28/R1.2)
where uv >nul 2>nul
IF ERRORLEVEL 1 (
  echo [FAIL] uv not on PATH - restart terminal and retry
  echo [uv not on PATH] >> "%LOG%"
  pause
  exit /b 1
)
:HAVE_UV
echo [3/6] install managed python 3.13 (into workspace)
uv python install 3.13 >> "%LOG%" 2>&1
IF ERRORLEVEL 1 echo [WARN] uv python install failed; system python may exist >> "%LOG%"
echo [4/6] create venv (workspace/.runtime/venv, D14)
IF EXIST "%WORKSPACE%\.runtime\venv\Scripts\python.exe" goto HAVE_VENV
uv venv --python 3.13 "%WORKSPACE%\.runtime\venv" >> "%LOG%" 2>&1
IF ERRORLEVEL 1 (
  echo [FAIL] venv creation failed - see start.log
  notepad "%LOG%"
  pause
  exit /b 1
)
:HAVE_VENV
echo [5/6] install engine dependencies
IF EXIST "%ROOT%\engine\pyproject.toml" goto ENGINE_LOCAL
if exist "%WORKSPACE%\_repo\assignment-assistant\engine\pyproject.toml" (
  set "ENGINE_DIR=%WORKSPACE%\_repo\assignment-assistant\engine"
  goto ENGINE_LOCAL
)
echo [INFO] engine source missing - downloading repo zip via ghfast mirror
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri https://ghfast.top/https://github.com/pancong0711/assignment-assistant/archive/refs/heads/main.zip -OutFile $env:ASSIST_WORKSPACE\_repo.zip -UseBasicParsing } catch { Invoke-WebRequest -Uri https://github.com/pancong0711/assignment-assistant/archive/refs/heads/main.zip -OutFile $env:ASSIST_WORKSPACE\_repo.zip -UseBasicParsing }"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force $env:ASSIST_WORKSPACE\_repo.zip $env:ASSIST_WORKSPACE\_repo"
set "ENGINE_DIR=%WORKSPACE%\_repo\assignment-assistant\engine"
echo [INFO] installing assist-engine from PyPI as last resort
uv pip install assist-engine --python "%WORKSPACE%\.runtime\venv\Scripts\python.exe" >> "%LOG%" 2>&1
GOTO AFTER_DEPS
:ENGINE_LOCAL
:ENGINE_LOCAL
uv pip install -e "%ROOT%\engine" --python "%WORKSPACE%\.runtime\venv\Scripts\python.exe" >> "%LOG%" 2>&1
:AFTER_DEPS
IF ERRORLEVEL 1 (
  echo.
  echo [FAIL] dependency install failed - see start.log
  notepad "%LOG%"
  pause
  exit /b 1
)
echo [6/6] start engine (port scan 8601..8649 for free port)
set "PORT="
FOR /L %%p IN (8601,1,8649) DO (
  IF NOT DEFINED PORT (
    netstat -an | findstr /R ":%%p .*LISTENING" >nul 2>nul || set "PORT=%%p"
  )
)
IF NOT DEFINED PORT (
  echo [FAIL] all ports 8601-8649 busy
  echo [ports busy] >> "%LOG%"
  pause
  exit /b 1
)
echo using engine port %PORT%
start "" http://127.0.0.1:%PORT%/
"%WORKSPACE%\.runtime\venv\Scripts\assist.exe" serve --port %PORT% >> "%LOG%" 2>&1
echo engine exited. log: %LOG%
pause
endlocal
