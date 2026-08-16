@echo off
REM 在项目根创建 .venv 并安装依赖（与 vnpy/streamlit 等其它项目隔离）
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv ...
    python -m venv .venv
) else (
    echo .venv already exists, skipping venv creation.
)

call ".venv\Scripts\activate.bat"
python -m pip install -U pip
python -m pip install -r requirements.txt

echo.
echo Done. Next time run:  .venv\Scripts\activate.bat
echo Then:  python main.py
pause
