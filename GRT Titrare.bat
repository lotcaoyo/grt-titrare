@echo off
rem ASCII only on purpose: cmd.exe misreads Cyrillic in .bat files.
rem All Russian text lives in the graphical interface.
setlocal enabledelayedexpansion
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
        set "OWN=runtime\python\Scripts\GRT Titrare.exe"
        if exist "!OWN!" (
            start "" "!OWN!" "app\main.py"
        ) else (
            start "" "%PY%" "app\main.py"
        )
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

rem Prefer our own executable: Windows takes the taskbar and pin icon from the
rem running .exe, and pythonw.exe carries the Python logo.
set "PY=runtime\python\Scripts\GRT Titrare.exe"
if not exist "%PY%" set "PY=runtime\python\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=runtime\python\pythonw.exe"
start "" "%PY%" "app\main.py"
exit /b 0
