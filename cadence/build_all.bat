@echo off
REM  Compiles every example, runs the whole test suite, and writes the reports.
setlocal
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" (where python >nul 2>nul && set PY=python)
if "%PY%"=="" (echo Python was not found. & pause & exit /b 1)

echo ============================================================
echo  1. compiling every example program
echo ============================================================
%PY% -m cadence --all
echo.
echo ============================================================
echo  2. running the test suite
echo ============================================================
%PY% -m unittest discover -s tests -v
echo.
echo ============================================================
echo  3. writing the glass-box report for the showcase program
echo ============================================================
%PY% -m cadence examples\07_showcase.cad --report report.html
start "" report.html
pause
