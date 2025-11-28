@echo off
:: Переходим в папку, где лежит этот батник (чтобы запускать от имени админа или с ярлыка)
cd /d "%~dp0"

chcp 65001 >nul

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

if not exist ".venv\Lib\site-packages\pynput" (
    echo Installing dependencies...
    pip install -r requirements.txt
)

echo Starting EnglishHelper...


:: Запускаем скрипт через pythonw.exe из папки venv
:: pythonw (с буквой w) нужен, чтобы не висело черное окно консоли
start "" ".venv\Scripts\pythonw.exe" "main.pyw"

exit

:: test comment