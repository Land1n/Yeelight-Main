@echo off
cd /d "%~dp0"
title Yeelight - server

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m yeelight_network.server
if errorlevel 1 (
    echo.
    echo Server stopped with an error. Check .env and whether the configured port is already in use.
    pause
)
