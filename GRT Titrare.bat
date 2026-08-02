@echo off
rem ASCII only on purpose: cmd.exe misreads Cyrillic in .bat files.
rem All Russian text lives in the graphical interface.
setlocal
cd /d "%~dp0"

set "PY=runtime\python\Scripts\pythonw.exe"
set "PYC=runtime\python\Scripts\python.exe"
if not exist "%PY%" (
    set "PY=runtime\python\pythonw.exe"
    set "PYC=runtime\python\python.exe"
)

rem A folder copied from another machine carries an environment that no longer
rem points anywhere. Verify before trusting it, otherwise the window would open
rem and vanish with no explanation.
if exist "%PYC%" (
    "%PYC%" -c "import tkinter, yaml" >nul 2>&1
    if not errorlevel 1 (
        start "" "%PY%" "app\main.py"
        exit /b 0
    )
)

powershell -NoProfile -ExecutionPolicy Bypass -File "bootstrap.ps1"
if errorlevel 1 (
    echo.
    echo Setup failed. Press any key to close.
    pause >nul
    exit /b 1
)

set "PY=runtime\python\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=runtime\python\pythonw.exe"
start "" "%PY%" "app\main.py"
exit /b 0
