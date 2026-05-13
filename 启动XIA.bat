@echo off
chcp 65001 >nul
title XIA - 认知引擎启动器

set "XIA_DIR=%~dp0"
set "LOG_FILE=%XIA_DIR%logs\starter.log"

:: 创建日志目录
if not exist "%XIA_DIR%logs" mkdir "%XIA_DIR%logs"

echo ========================================
echo   XIA - 认知引擎
echo ========================================
echo.

:menu
echo 请选择操作:
echo   [1] 启动 XIA (完整启动)
echo   [2] 仅启动 Daemon
echo   [3] 仅启动前端界面
echo   [4] 关闭所有 XIA 进程
echo   [5] 检查进程状态
echo   [0] 退出
echo.
set /p choice=请输入选项 [1-5, 0退出]:

if "%choice%"=="1" goto start_all
if "%choice%"=="2" goto start_daemon
if "%choice%"=="3" goto start_frontend
if "%choice%"=="4" goto kill_all
if "%choice%"=="5" goto check_status
if "%choice%"=="0" goto end
goto menu

:start_all
echo.
echo [启动全部组件]
echo.
call :start_daemon
call :start_frontend
echo.
echo ========================================
echo   XIA 已启动!
echo   - Daemon: http://127.0.0.1:8765
echo   - 界面: Electron 窗口
echo ========================================
pause
goto menu

:start_daemon
echo [1/2] 启动 Daemon...
:: 检查 daemon 是否已运行
netstat -ano | findstr ":8765.*LISTENING" | findstr /V "0.0.0.0 ::" >nul
if %errorlevel%==0 (
    echo   [跳过] Daemon 已在运行 (端口 8765)
) else (
    echo   正在启动 daemon...
    start /min "XIA-Daemon" cmd /c "cd /d %XIA_DIR% && python -m src.daemon.daemon --http-port 8765 --tick-interval 10 >> logs\daemon.log 2>&1"
    timeout /t 2 /nobreak >nul
    echo   [OK] Daemon 已启动
)
goto :eof

:start_frontend
echo [2/2] 启动前端界面...

:: 检查 Electron 是否已运行
tasklist | findstr /I "electron.exe" >nul
if %errorlevel%==0 (
    echo   [跳过] 前端已在运行
) else (
    :: 构建前端 (如果 dist 不存在或需要更新)
    if not exist "%XIA_DIR%frontend\dist" (
        echo   正在构建前端...
        cd /d "%XIA_DIR%frontend"
        call npm run build >nul 2>&1
        if errorlevel 1 (
            echo   [错误] 前端构建失败
            goto :eof
        )
    )

    :: 启动 Electron (在新窗口)
    start "XIA-Frontend" cmd /k "cd /d %XIA_DIR%frontend && npm run electron:dev"
)
goto :eof

:kill_all
echo.
echo 正在关闭所有 XIA 进程...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq XIA-Daemon*" 2>nul
taskkill /F /IM electron.exe 2>nul
taskkill /F /IM node.exe /FI "WINDOWTITLE eq *vite*" 2>nul
echo [OK] 所有进程已关闭
echo.
goto menu

:check_status
echo.
echo ========================================
echo   XIA 进程状态
echo ========================================
echo.

echo [Daemon - Python]
netstat -ano | findstr ":8765.*LISTENING" | findstr /V "0.0.0.0 ::"
if errorlevel 1 echo   未运行 (端口 8765 未监听)

echo.
echo [Frontend - Electron]
tasklist | findstr /I "electron.exe"
if errorlevel 1 echo   未运行

echo.
echo [Dev Server - Node (vite)]
netstat -ano | findstr ":5173.*LISTENING"
if errorlevel 1 echo   未运行 (vite dev server)

echo.
goto menu

:end
exit
