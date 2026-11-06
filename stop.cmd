@echo off
rem Stop the authorization service and certificate hook started by run.cmd.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title lptiyuQRBridge stop

where python >nul 2>nul
if errorlevel 1 (
    echo [x] Python 3.11+ not found in PATH.
    pause
    exit /b 1
)

python -B scripts\deploy_local.py --stop
set RC=%ERRORLEVEL%

echo %cmdcmdline% | find /i "%~nx0" >nul
if not errorlevel 1 pause >nul
exit /b %RC%
