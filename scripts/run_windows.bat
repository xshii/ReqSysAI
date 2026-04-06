@echo off
chcp 65001 >nul
echo ========================================
echo   ReqSysAI 研发协作平台 - Windows 启动
echo ========================================

cd /d "%~dp0\.."

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 未安装，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM Create venv if not exists
if not exist "venv" (
    echo [INFO] 创建虚拟环境...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install dependencies
echo [INFO] 安装依赖...
pip install -r requirements.txt -q

REM Init DB if not exists
if not exist "instance\reqsys.db" (
    echo [INFO] 初始化数据库...
    if not exist "instance" mkdir instance
    python scripts\init_db.py
)

REM Set env
set FLASK_APP=app:create_app
set FLASK_ENV=development
set TZ=Asia/Shanghai

REM Get local IP
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set LOCAL_IP=%%a
)
set LOCAL_IP=%LOCAL_IP: =%

REM Read port from config (match exactly "  port:" to avoid ssh_local_port etc.)
for /f "tokens=2 delims=: " %%p in ('findstr /r /c:"^  port:" config.yml') do set PORT=%%p
if "%PORT%"=="" set PORT=5001

echo.
echo [OK] 平台启动中...
echo [OK] 本机访问: http://127.0.0.1:%PORT%
echo [OK] 局域网访问: http://%LOCAL_IP%:%PORT%
echo [OK] 按 Ctrl+C 停止
echo.

flask run --host 0.0.0.0 --port %PORT%
