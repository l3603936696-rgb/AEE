@echo off
chcp 65001 >nul
title XIA Runtime Launcher

set "XIA_DIR=%~dp0"
set "LOG_DIR=%XIA_DIR%logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo ========================================
echo   XIA Runtime Launcher
echo ========================================
echo.

:menu
echo Choose an action:
echo   [1] Start daemon
echo   [2] Start reach listener
echo   [3] Stop XIA processes
echo   [4] Check status
echo   [0] Exit
echo.
set /p choice=Enter choice [1-4, 0 exit]:

if "%choice%"=="1" goto start_daemon
if "%choice%"=="2" goto start_reach
if "%choice%"=="3" goto kill_all
if "%choice%"=="4" goto check_status
if "%choice%"=="0" goto end
goto menu

:start_daemon
echo.
echo [Daemon]
netstat -ano | findstr ":8765.*LISTENING" | findstr /V "0.0.0.0 ::" >nul
if %errorlevel%==0 (
    echo   Already running on port 8765.
) else (
    echo   Starting daemon...
    start /min "XIA-Daemon" cmd /c "cd /d %XIA_DIR% && python -m src.daemon.daemon --http-port 8765 --tick-interval 10 >> logs\daemon.log 2>&1"
    timeout /t 2 /nobreak >nul
    echo   Started.
)
echo.
goto menu

:start_reach
echo.
echo [Reach listener]
start "XIA-Reach" cmd /k "cd /d %XIA_DIR% && python reach_client.py"
echo   Started reach_client.py.
echo.
goto menu

:kill_all
echo.
echo Stopping XIA processes...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq XIA-Daemon*" 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq XIA-Reach*" 2>nul
echo Done.
echo.
goto menu

:check_status
echo.
echo ========================================
echo   XIA Status
echo ========================================
echo.
echo [Daemon HTTP API]
netstat -ano | findstr ":8765.*LISTENING" | findstr /V "0.0.0.0 ::"
if errorlevel 1 echo   Not listening on port 8765.
echo.
echo [Python processes]
tasklist | findstr /I "python.exe"
if errorlevel 1 echo   No python.exe process found.
echo.
goto menu

:end
exit
