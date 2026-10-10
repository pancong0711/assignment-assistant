@echo off
REM [R1.2 v9] assignment-assistant launcher -- PYTHON-FIRST bootstrap (D32).
REM Order: detect system python (py/python) -> [fallback: Miniconda3 install from
REM TUNA into workspace] -> python venv (workspace) -> engine deps via venv pip
REM (TUNA index). uv is optional/not required. Everything lives under
REM <this bat dir>\.runtime\ ; uninstall = delete that dir.
setlocal enableextensions
echo [R1.2 v9] assignment-assistant launcher (python-first, TUNA mirrors by default)
set "WORKSPACE=%~dp0"
IF "%WORKSPACE:~-1%"=="\" set "WORKSPACE=%WORKSPACE:~0,-1%"
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
set "ASSIST_SUPERVISED=1"
set "STAGE=%WORKSPACE%\_engine\staging"
set "PENDING=%WORKSPACE%\_engine\update.pending"
echo [1/6] workspace = %WORKSPACE%
echo [2/6] detect python (system first; miniconda fallback from TUNA)
set PY=
py -3 --version >nul 2>nul
IF NOT ERRORLEVEL 1 set "PY=py -3" & goto FOUND_PY
python --version >nul 2>nul
IF NOT ERRORLEVEL 1 set "PY=python" & goto FOUND_PY
IF EXIST "%WORKSPACE%\.runtime\miniconda\python.exe" set "PY=%WORKSPACE%\.runtime\miniconda\python.exe" & goto FOUND_PY
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
call %PY% -m venv "%WORKSPACE%\.runtime\venv" >> "%LOG%" 2>&1
IF ERRORLEVEL 1 (
  echo [FAIL] venv creation failed - see start.log
  notepad "%LOG%"
  pause
  exit /b 1
)
:HAVE_VENV
set "VPIP=%WORKSPACE%\.runtime\venv\Scripts\pip.exe"
echo [5/6] install engine dependencies (TUNA pip index)
set "ENGINE_DIR=%WORKSPACE%\_engine\engine"
set "VERSION_LOCAL=%WORKSPACE%\_engine\engine-version.json"
set "VERSION_TMP=%WORKSPACE%\engine-version.remote.json"
set "VERSION_URL=https://pancong0711.github.io/assignment-assistant/dl/engine-version.json"

REM D65-P0.0: stale local engine must not shadow bootstrapped engine.
REM Developer opt-in: set ASSIST_ENGINE_LOCAL=1 to reuse workspace or repo engine.
IF /I "%ASSIST_ENGINE_LOCAL%"=="1" IF EXIST "%WORKSPACE%\engine\pyproject.toml" goto ENGINE_LOCAL
IF /I "%ASSIST_ENGINE_LOCAL%"=="1" IF EXIST "%ROOT%\engine\pyproject.toml" goto ENGINE_LOCAL

IF NOT EXIST "%ENGINE_DIR%\pyproject.toml" goto ENGINE_DOWNLOAD

echo [5/6] check engine version
curl -fsSL --connect-timeout 8 --max-time 15 -o "%VERSION_TMP%" "%VERSION_URL%"
IF ERRORLEVEL 1 (
  echo [5/6] version check unavailable - check local engine integrity
  goto ENGINE_CHECK
)
IF NOT EXIST "%VERSION_LOCAL%" goto ENGINE_DOWNLOAD
FC /B "%VERSION_LOCAL%" "%VERSION_TMP%" >nul
IF ERRORLEVEL 1 goto ENGINE_DOWNLOAD
echo [5/6] engine up to date - check local engine integrity
goto ENGINE_CHECK

:ENGINE_DOWNLOAD
echo [5/6] engine update required - downloading latest
curl -fsSL --connect-timeout 8 --max-time 15 -o "%VERSION_TMP%" "%VERSION_URL%"
REM D73-12: never reuse a stale zip from a previous failed download
del /Q "%WORKSPACE%\engine-main.zip" >nul 2>nul

echo [5/6a] engine source: PRIMARY mirror = github.io Pages dl (5 attempts x retry-delay)
set "DELURL=https://pancong0711.github.io/assignment-assistant/dl/engine-main.zip"
set "ATTEMPT=0"
:P_RETRY
IF %ATTEMPT% GEQ 5 GOTO TRY_STD
echo [attempt %ATTEMPT%] downloading engine-main.zip from Pages (5 retry chain)
curl -fL --connect-timeout 60 --max-time 180 --retry 3 --retry-delay 10 -o "%WORKSPACE%\engine-main.zip" "%DELURL%"
IF EXIST "%WORKSPACE%\engine-main.zip" goto EXTRACT_ENGINE
IF ERRORLEVEL 1 GOTO SKIP_ATTEMPT
:SKIP_ATTEMPT
set /a ATTEMPT=%ATTEMPT%+1
IF %ATTEMPT% LSS 5 GOTO P_RETRY

:TRY_STD
echo [5/6b] engine source: github release dl (github.com - proven reachable)
curl -fL --retry 3 --connect-timeout 60 --retry-delay 10 -o "%WORKSPACE%\engine-main.zip" "https://github.com/pancong0711/assignment-assistant/releases/download/dl/engine-main.zip"
IF EXIST "%WORKSPACE%\engine-main.zip" goto EXTRACT_ENGINE

echo [5/6c] engine source: ghfast + github full-repo fallback (last resort, 41MB+)
del /Q "%WORKSPACE%\full-repo.zip" >nul 2>nul
curl -fL --retry 2 --connect-timeout 20 -o "%WORKSPACE%\full-repo.zip" "https://ghfast.top/https://github.com/pancong0711/assignment-assistant/archive/refs/heads/main.zip"
IF NOT EXIST "%WORKSPACE%\full-repo.zip" curl -fL --retry 2 --connect-timeout 20 -o "%WORKSPACE%\full-repo.zip" "https://github.com/pancong0711/assignment-assistant/archive/refs/heads/main.zip"
IF EXIST "%WORKSPACE%\full-repo.zip" powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force %WORKSPACE%\full-repo.zip %WORKSPACE%\_enginefull" >> "%LOG%" 2>&1
IF EXIST "%WORKSPACE%\_enginefull\assignment-assistant-main\engine\pyproject.toml" set "ENGINE_DIR=%WORKSPACE%\_enginefull\assignment-assistant-main\engine"
goto ENGINE_CHECK

:EXTRACT_ENGINE
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force %WORKSPACE%\engine-main.zip %WORKSPACE%\_engine" >> "%LOG%" 2>&1
set "ENGINE_DIR=%WORKSPACE%\_engine\engine"
IF EXIST "%ENGINE_DIR%\src" for /d /r "%ENGINE_DIR%\src" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" >nul 2>nul
IF EXIST "%VERSION_TMP%" copy /Y "%VERSION_TMP%" "%VERSION_LOCAL%" >nul

:ENGINE_CHECK
IF NOT EXIST "%ENGINE_DIR%\pyproject.toml" (
  echo [FAIL] engine zip not usable - download all mirrors unavailable
  notepad "%LOG%"
  pause
  exit /b 1
)
REM D73-12: local engine integrity; missing xxt\session.py forces one re-download
IF EXIST "%ENGINE_DIR%\src\assist\xxt\session.py" goto ENGINE_LOCAL
IF DEFINED REDOWNLOADED (
  echo [FAIL] engine source incomplete after redownload: missing src\assist\xxt\session.py
  echo        delete "%WORKSPACE%\_engine" and rerun start.bat
  notepad "%LOG%"
  pause
  exit /b 1
)
echo [5/6] local engine incomplete - forcing re-download (missing src\assist\xxt\session.py)
set "REDOWNLOADED=1"
goto ENGINE_DOWNLOAD

:ENGINE_LOCAL
REM engine dir validated at :ENGINE_CHECK (D34 chain)
"%VPIP%" install -e "%ENGINE_DIR%" --index-url "%UV_DEFAULT_INDEX%" >> "%LOG%" 2>&1
IF ERRORLEVEL 1 (
  echo [FAIL] engine dependency install failed - see start.log
  notepad "%LOG%"
  pause
  exit /b 1
)
:AFTER_DEPS
if exist "%PENDING%" (
  echo [update] pending staging detected; applying before start...
  call :APPLY_UPDATE
  if errorlevel 1 goto UPDATE_APPLY_FAILED
)
echo [6/6] start engine (auto port scan 8601..8649)
set "PORT="
FOR /L %%p IN (8601,1,8649) DO (
  IF NOT DEFINED PORT (
    netstat -an | findstr /C:":%%p " | findstr /I LISTENING >nul 2>nul || set "PORT=%%p"
  )
)
IF NOT DEFINED PORT (
  echo [FAIL] all ports 8601-8649 busy - close stale engine and retry
  pause
  exit /b 1
)
echo engine http://127.0.0.1:%PORT%/ (log: %LOG%)
start "" http://127.0.0.1:%PORT%/

:ENGINE_LOOP
if exist "%PENDING%" (
  echo [update] applying staged engine before restart...
  call :APPLY_UPDATE
  if errorlevel 1 goto UPDATE_APPLY_FAILED
)
if exist "%ENGINE_DIR%\run_engine.bat" (
  call "%ENGINE_DIR%\run_engine.bat" "%WORKSPACE%\.runtime\venv\Scripts\python.exe" "%WORKSPACE%" "%PORT%" >> "%LOG%" 2>&1
) else (
  REM migration fallback for pre-D71 engine
  "%WORKSPACE%\.runtime\venv\Scripts\python.exe" -m assist.cli serve --workspace "%WORKSPACE%" --port "%PORT%" >> "%LOG%" 2>&1
)

set "RC=%ERRORLEVEL%"
if "%RC%"=="75" (
  echo [restart] engine restart requested; restarting...
  timeout /t 1 /nobreak >nul 2>nul
  goto ENGINE_LOOP
)

echo engine exited. see %LOG%
pause
exit /b 0

:UPDATE_APPLY_FAILED
echo [FAIL] engine update/install failed; see %LOG%
notepad "%LOG%"
pause
exit /b 1

:APPLY_UPDATE
if not exist "%STAGE%\engine\pyproject.toml" (
  echo [update] staging missing: %STAGE%\engine\pyproject.toml
  exit /b 1
)
set "ENGINE_BAK=%ENGINE_DIR%.bak"
if exist "%ENGINE_BAK%" rmdir /S /Q "%ENGINE_BAK%" >nul 2>nul
if exist "%ENGINE_DIR%" move "%ENGINE_DIR%" "%ENGINE_BAK%" >nul 2>nul
if not exist "%ENGINE_BAK%\pyproject.toml" (
  echo [update] failed to move current engine to backup
  exit /b 1
)
REM D73-12: robocopy /MIR first (reliable mirror), xcopy as fallback
robocopy "%STAGE%\engine" "%ENGINE_DIR%" /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:1 >nul 2>nul
IF ERRORLEVEL 8 xcopy /E /I /Y "%STAGE%\engine" "%ENGINE_DIR%" >nul 2>nul
if not exist "%ENGINE_DIR%\pyproject.toml" (
  echo [update] failed to copy staging engine
  call :RESTORE_ENGINE
  exit /b 1
)
REM D73-12: verify critical files, not just pyproject.toml
IF NOT EXIST "%ENGINE_DIR%\src\assist\xxt\session.py" (
  echo [update] copy incomplete - missing src\assist\xxt\session.py; rolling back
  call :RESTORE_ENGINE
  exit /b 1
)
IF NOT EXIST "%ENGINE_DIR%\src\assist\serve.py" (
  echo [update] copy incomplete - missing src\assist\serve.py; rolling back
  call :RESTORE_ENGINE
  exit /b 1
)
echo [update] installing dependencies from staged engine...
"%VPIP%" install -e "%ENGINE_DIR%" --index-url "%UV_DEFAULT_INDEX%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [update] pip install failed; rolling back...
  call :RESTORE_ENGINE
  exit /b 1
)
if exist "%STAGE%\engine-version.json" copy /Y "%STAGE%\engine-version.json" "%VERSION_LOCAL%" >nul
if exist "%ENGINE_BAK%" rmdir /S /Q "%ENGINE_BAK%" >nul 2>nul
if exist "%PENDING%" del "%PENDING%" >nul 2>nul
if exist "%STAGE%" rmdir /S /Q "%STAGE%" >nul 2>nul
echo [update] engine update applied successfully.
exit /b 0

:RESTORE_ENGINE
if exist "%ENGINE_DIR%" rmdir /S /Q "%ENGINE_DIR%" >nul 2>nul
if exist "%ENGINE_BAK%" move "%ENGINE_BAK%" "%ENGINE_DIR%" >nul 2>nul
echo [update] reinstalling previous engine...
"%VPIP%" install -e "%ENGINE_DIR%" --index-url "%UV_DEFAULT_INDEX%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [update] rollback reinstall also failed; see %LOG%
  exit /b 1
)
if exist "%PENDING%" (
  if exist "%PENDING%.failed" del "%PENDING%.failed" >nul 2>nul
  ren "%PENDING%" "update.failed" >nul 2>nul
)
exit /b 1
