@echo off
rem ASCII only on purpose: cmd.exe misreads Cyrillic in .bat files.
rem All Russian text lives in the graphical interface.
setlocal
cd /d "%~dp0"

if exist "runtime\python\pythonw.exe" (
    start "" "runtime\python\pythonw.exe" "app\main.py"
    exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -File "bootstrap.ps1"
if errorlevel 1 (
    echo.
    echo Setup failed. Press any key to close.
    pause >nul
    exit /b 1
)

start "" "runtime\python\pythonw.exe" "app\main.py"
exit /b 0
