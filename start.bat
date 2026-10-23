@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" koan.py %*
    goto :eof
)
py -3 --version >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 koan.py %*
) else (
    python koan.py %*
)
if errorlevel 1 pause
