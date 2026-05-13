@echo off
chcp 65001 >nul
title XIA - Daemon 管理器

echo ========================================
echo   XIA Daemon 管理器 (Windows)
echo ========================================
echo.

cd /d "%~dp0"

REM 设置 LLM 为 DeepSeek
set XIA_LLM_CHAIN=deepseek

REM 加载 .env
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if /i "%%a"=="DEEPSEEK_API_KEY" set DEEPSEEK_API_KEY=%%b
    )
)

REM 创建必要目录
if not exist "data" mkdir data
if not exist "logs" mkdir logs

:menu
cls
echo ========================================
echo   XIA Daemon 管理器
echo ========================================
echo.
echo   1. 启动 daemon
echo   2. 停止 daemon
echo   3. 重启 daemon
echo   4. 查看状态
echo   5. 查看日志
echo   0. 退出
echo.
set /p choice=请选择 [1-5, 0退出]:

if "%choice%"=="1" goto :start
if "%choice%"=="2" goto :stop
if "%choice%"=="3" goto :restart
if "%choice%"=="4" goto :status
if "%choice%"=="5" goto :logs
if "%choice%"=="0" goto :eof

:start
echo.
echo [启动] 正在启动 daemon...
python -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',8766))==0; s.close(); exit(0 if r else 1)" 2>nul
if not errorlevel 1 (
    echo   Daemon 已在运行
) else (
    start /min "XIA Daemon" python -m src.daemon.daemon --http-port 8765
    echo   等待启动...
    timeout /t 3 /nobreak >nul
    python -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',8766))==0; s.close(); exit(0 if r else 1)" 2>nul
    if not errorlevel 1 (
        echo   [OK] Daemon 已启动
    ) else (
        echo   [失败] 请检查 logs/daemon.log
    )
)
echo.
pause
goto :menu

:stop
echo.
echo [停止] 正在停止 daemon...
taskkill /FI "WINDOWTITLE eq XIA Daemon*" /T /F >nul 2>&1
echo   [OK] Daemon 已停止
echo.
pause
goto :menu

:restart
echo.
echo [重启] 正在重启 daemon...
taskkill /FI "WINDOWTITLE eq XIA Daemon*" /T /F >nul 2>&1
timeout /t 1 /nobreak >nul
start /min "XIA Daemon" python -m src.daemon.daemon --http-port 8765
echo   等待启动...
timeout /t 3 /nobreak >nul
python -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',8766))==0; s.close(); exit(0 if r else 1)" 2>nul
if not errorlevel 1 (
    echo   [OK] Daemon 已重启
) else (
    echo   [失败] 请检查 logs/daemon.log
)
echo.
pause
goto :menu

:status
echo.
python -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',8766))==0; s.close(); exit(0 if r else 1)" 2>nul
if not errorlevel 1 (
    echo   Daemon 状态: 运行中
    echo   HTTP API: http://127.0.0.1:8765
    echo   IPC 端口: 127.0.0.1:8766
    echo   LLM Provider: DeepSeek API
) else (
    echo   Daemon 状态: 未运行
    echo   提示: 选择 1 启动
)
echo.
pause
goto :menu

:logs
if exist "logs\daemon.log" (
    powershell -Command "Get-Content logs\daemon.log -Tail 20 -Wait"
) else (
    echo   日志文件不存在
    pause
)
goto :menu
