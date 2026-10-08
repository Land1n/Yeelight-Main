@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

start "Yeelight Server" "%~dp0.venv\Scripts\python.exe" -m yeelight_network.server
timeout /t 2 /nobreak >nul
start "Yeelight Flet App" "%~dp0.venv\Scripts\python.exe" -m yeelight_app
