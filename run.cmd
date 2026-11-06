@echo off
rem lptiyuQRBridge one-click deploy (Windows)
rem Keep this file ASCII-only: it runs under the OEM code page before chcp applies.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title lptiyuQRBridge deploy

where python >nul 2>nul
if errorlevel 1 (
    echo [x] Python 3.11+ not found in PATH.
    echo     Install Python, tick "Add python.exe to PATH", then run this again.
    pause
    exit /b 1
)

python -B scripts\deploy_local.py %*
set RC=%ERRORLEVEL%

echo %cmdcmdline% | find /i "%~nx0" >nul
if not errorlevel 1 (
    echo.
    if not "%RC%"=="0" echo [x] deploy failed, exit code %RC%
    echo Press any key to close this window.
    pause >nul
)
exit /b %RC%
