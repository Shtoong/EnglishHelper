@echo off
cd /d "%~dp0"
chcp 65001 >nul

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

REM Проверяем наличие любого пакета из requirements
if not exist ".venv\Lib\site-packages\requests" (
    echo Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
)

echo Starting EnglishHelper...
".venv\Scripts\pythonw.exe" "main.pyw"

if errorlevel 1 (
    echo ERROR: Program crashed
    pause
)
