@echo off
REM TigerTrade 启动脚本 - 使用 Python 3.11 环境
REM 需要确保 QMT 已启动并登录

echo Starting TigerTrade with Python 3.11...
echo.

REM Python 3.11 路径
set PYTHON_EXE=C:\Users\86176\.conda\envs\py311\python.exe

REM 检查 Python 是否存在
if not exist "%PYTHON_EXE%" (
    echo ERROR: Python 3.11 not found at %PYTHON_EXE%
    pause
    exit /b 1
)

REM 启动 TigerTrade
"%PYTHON_EXE%" "e:\MinQMT\F3_0614\main.py"

pause
