@echo off
REM [R1.2 v9] assignment-assistant launcher -- PYTHON-FIRST bootstrap (D32).
REM Order: detect system python (py/python) -> [fallback: Miniconda3 install from
REM TUNA into workspace] -> python venv (workspace) -> engine deps via venv pip
REM (TUNA index). uv is optional/not required. Everything lives under
REM <this bat dir>\.runtime\ ; uninstall = delete that dir.
setlocal enableextensions
echo [R1.2 v9] assignment-assistant launcher (python-first, TUNA mirrors by default)
set "WORKSPACE=%~dp0"
IF "%WORKSPACE:~-1%"=="" set "WORKSPACE=%WORKSPACE:~0,-1%"
set "LOG=%WORKSPACE%\start.log"
set "ROOT=%~dp0.."
IF NOT EXIST "%WORKSPACE%" mkdir "%WORKSPACE%" 2>nul
IF NOT EXIST "%WORKSPACE%\.runtime" mkdir "%WORKSPACE%\.runtime" 2>nul
IF NOT EXIST "%WORKSPACE%\.runtime\cache\uv" mkdir "%WORKSPACE%\.runtime\cache\uv" 2>nul
IF NOT EXIST "%WORKSPACE%\.runtime\browsers" mkdir "%WORKSPACE%\.runtime\browsers" 2>nul
IF EXIST "%LOG%" DEL "%LOG%" >nul 2>nul
echo =============================== >> "%LOG%"
set "UV_DEFAULT_INDEX=%UV_DEFAULT_INDEX%"
IF NOT DEFINED UV_DEFAULT_INDEX set "UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"
IF NOT DEFINED PLAYWRIGHT_DOWNLOAD_HOST set "PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/"
set "ASSIST_WORKSPACE=%WORKSPACE%"
echo [1/6] workspace = %WORKSPACE%
echo [2/6] detect python (system first; miniconda fallback from TUNA)
set PY=
py -3 --version >nul 2>nul
IF NOT ERRORLEVEL 1 (set "PY=py -3" & goto FOUND_PY)
python --version >nul 2>nul
IF NOT ERRORLEVEL 1 (set "PY=python" & goto FOUND_PY)
IF EXIST "%WORKSPACE%\.runtime\miniconda\python.exe" (set "PY=%WORKSPACE%\.runtime\miniconda\python.exe" & goto FOUND_PY)
echo [2/6] no system python - downloading Miniconda3-latest from TUNA (silent, into workspace)
curl -fL --retry 2 --connect-timeout 20 -o "%WORKSPACE%\.runtime\Miniconda3.exe" "https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-Windows-x86_64.exe"
IF ERRORLEVEL 1 (
  echo [FAIL] miniconda download failed - TUNA unreachable? see start.log
  notepad "%LOG%"
  pause
  exit /b 1
)
IF EXIST "%WORKSPACE%\.runtime\miniconda\python.exe" (echo [reuse miniconda]>>"%LOG%") else ("%WORKSPACE%\.runtime\Miniconda3.exe" /S /D=%WORKSPACE%\.runtime\miniconda >>"%LOG%" 2>&1)
set "PY=%WORKSPACE%\.runtime\miniconda\python.exe"
:FOUND_PY
echo using python: %PY%
echo [3/6] create venv (workspace/.runtime/venv, D14)
IF EXIST "%WORKSPACE%\.runtime\venv\Scripts\python.exe" goto HAVE_VENV
%PY% -m venv "%WORKSPACE%\.runtime\venv" >> "%LOG%" 2>&1
IF ERRORLEVEL 1 (
  echo [FAIL] venv creation failed - see start.log
  notepad "%LOG%"
  pause
  exit /b 1
)
:HAVE_VENV
set "VPIP=%WORKSPACE%\.runtime\venv\Scripts\pip.exe"
echo [5/6] install engine dependencies (TUNA pip index)
IF EXIST "%ROOT%\engine\pyproject.toml" goto ENGINE_LOCAL
IF EXIST "%WORKSPACE%\_repo\assignment-assistant\engine\pyproject.toml" (set "ENGINE_DIR=%WORKSPACE%\_repo\assignment-assistant\engine" & goto ENGINE_LOCAL)
echo [INFO] engine source missing - downloading repo zip (ghfast mirror first)
echo [INFO] engine zip source: Pages first, ghfast second, github last (D31)\ncurl -fL --retry 2 --connect-timeout 20 -o "%WORKSPACE%\_repo.zip" "https://pancong0711.github.io/assignment-assistant/dl/engine-main.zip"\nIF ERRORLEVEL 1 curl -fL --retry 2 --connect-timeout 20 -o "%WORKSPACE%\_repo.zip" "https://ghfast.top/https://github.com/pancong0711/assignment-assistant/archive/refs/heads/main.zip"\nIF ERRORLEVEL 1 curl -fL --retry 1 -o "%WORKSPACE%\_repo.zip" "https://github.com/pancong0711/assignment-assistant/archive/refs/heads/main.zip"
if not exist "%WORKSPACE%\_repo.zip" curl -fL --retry 1 -o "%WORKSPACE%\_repo.zip" "https://github.com/pancong0711/assignment-assistant/archive/refs/heads/main.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force %WORKSPACE%\_repo.zip %WORKSPACE%\_repo" >> "%LOG%" 2>&1
set "ENGINE_DIR=%WORKSPACE%\_repo\assignment-assistant\engine"
:ENGINE_LOCAL
IF NOT EXIST "%ENGINE_DIR%\pyproject.toml" (
  echo [INFO] engine source unavailable - installing assist-engine from PyPI (TUNA)
  "%VPIP%" install assist-engine --index-url "%UV_DEFAULT_INDEX%" >> "%LOG%" 2>&1
  IF ERRORLEVEL 1 (
    echo [FAIL] engine install (PyPI) failed - see start.log
    notepad "%LOG%"
    pause
    exit /b 1
  )
  GOTO AFTER_DEPS
)
"%VPIP%" install -e "%ENGINE_DIR%" --index-url "%UV_DEFAULT_INDEX%" >> "%LOG%" 2>&1
IF ERRORLEVEL 1 (
  echo [FAIL] engine dependency install failed - see start.log
  notepad "%LOG%"
  pause
  exit /b 1
)
:AFTER_DEPS
echo [6/6] start engine (auto port scan 8601..8649)
set "PORT=none"
FOR /L %%p IN (8601,1,8649) DO IF "%PORT%"=="none" (
  netstat -an | findstr /R ":%%p .*LISTENING" >nul 2>nul || set "PORT=%%p"
)
IF "%PORT%"=="none" (
  echo [FAIL] all ports 8601-8649 busy - close stale engine and retry
  pause
  exit /b 1
)
echo engine http://127.0.0.1:%PORT%/ (log: %LOG%)
start "" http://127.0.0.1:%PORT%/
"%WORKSPACE%\.runtime\venv\Scripts\assist.exe" serve --port %PORT% >> "%LOG%" 2>&1
echo engine exited. see %LOG%
pause
endlocal
