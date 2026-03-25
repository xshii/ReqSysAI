@echo off
chcp 65001 >nul
echo ========================================
echo   ReqSysAI 初始化 (Windows)
echo ========================================

cd /d "%~dp0\.."

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 未安装
    pause
    exit /b 1
)

if not exist "venv" (
    echo [INFO] 创建虚拟环境...
    python -m venv venv
)

call venv\Scripts\activate.bat
echo [INFO] 安装依赖...
pip install -r requirements.txt -q

if not exist "instance" mkdir instance

echo [INFO] 初始化数据库...
set FLASK_APP=app:create_app
python scripts\init_db.py

echo.
echo [OK] 初始化完成！运行 scripts\run_windows.bat 启动平台
pause
