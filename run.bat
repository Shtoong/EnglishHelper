@echo off
cd /d "%~dp0"

if not exist .venv (
    python -m venv .venv
    call .venv\Scripts\activate
    pip install -r requirements.txt
)

call .venv\Scripts\activate
start "" pythonw main.pyw
exit
