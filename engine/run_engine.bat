@echo off
REM D71 stable engine adapter: external launcher calls this file by path;
REM engine internals (assist.cli / future entrypoints) are adapted here.
setlocal enableextensions
set "PY=%~1"
set "WORKSPACE=%~2"
set "PORT=%~3"
if "%PY%"=="" set "PY=python"
if "%WORKSPACE%"=="" set "WORKSPACE=%~dp0..\.."
if "%PORT%"=="" set "PORT=8601"
REM D73-12: install integrity preflight (clear message instead of serve tracebacks)
"%PY%" -c "import assist.xxt.session" >> "%WORKSPACE%\start.log" 2>&1
IF ERRORLEVEL 1 (
  echo [FAIL] engine install incomplete: cannot import assist.xxt.session
  echo        fix: close this window, delete "%WORKSPACE%\_engine", then run start.bat again
  echo        if on BaiduNetdisk/OneDrive, pause sync + exit client before retrying
  pause
  exit /b 1
)
"%PY%" -m assist.cli serve --workspace "%WORKSPACE%" --port "%PORT%"
exit /b %ERRORLEVEL%
