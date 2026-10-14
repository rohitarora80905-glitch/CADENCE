@echo off
REM ===================================================================
REM  Cadence Studio -- double-click to start the web front end.
REM  Needs Python 3.10+ and:  pip install -r requirements-studio.txt
REM  Optional: set GROQ_API_KEY=...  for the AI composer (or paste the
REM  key into the Studio's AI panel once it is open).
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

%PY% -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo Installing the Studio's requirements ^(one time^)...
  %PY% -m pip install -r requirements-studio.txt
)

echo Starting Cadence Studio at http://127.0.0.1:8000/ ...
%PY% -m studio --open
pause
