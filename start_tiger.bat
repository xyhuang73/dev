@echo off
REM TigerTrade 启动脚本 - 使用 Python 3.11 环境
REM 需要确保 QMT 已启动并登录

echo Starting TigerTrade with Python 3.11...
echo.

REM 优先使用当前项目虚拟环境；缺失时回退到原 Python 3.11 环境。
set "TIGER_PROJECT_DIR=%~dp0"
set "TIGER_PYTHON_EXE=%TIGER_PROJECT_DIR%.venv311\Scripts\python.exe"
if not exist "%TIGER_PYTHON_EXE%" set "TIGER_PYTHON_EXE=C:\Users\86176\.conda\envs\py311\python.exe"

REM 检查 Python 是否存在
if not exist "%TIGER_PYTHON_EXE%" (
    echo ERROR: Python 3.11 not found at %TIGER_PYTHON_EXE%
    pause
    exit /b 1
)

REM 启动 TigerTrade
"%TIGER_PYTHON_EXE%" "%TIGER_PROJECT_DIR%main.py"

pause
