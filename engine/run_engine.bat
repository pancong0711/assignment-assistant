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
"%PY%" -m assist.cli serve --workspace "%WORKSPACE%" --port "%PORT%"
exit /b %ERRORLEVEL%
