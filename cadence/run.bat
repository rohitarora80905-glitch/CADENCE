@echo off
REM ===================================================================
REM  Cadence -- double-click this file to open the Glass-Box window.
REM  Nothing to install: Python 3.10 or newer is the only requirement.
REM ===================================================================
setlocal
cd /d "%~dp0"

set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" (where python >nul 2>nul && set PY=python)
if "%PY%"=="" (
  echo Python was not found on this machine.
  echo Install Python 3 from https://python.org and tick "Add to PATH".
  pause
  exit /b 1
)

echo Starting Cadence...
%PY% -m cadence --gui
if errorlevel 1 (
  echo.
  echo The window could not open. Writing the HTML report instead...
  %PY% -m cadence examples\07_showcase.cad --report report.html
  start "" report.html
)
pause
