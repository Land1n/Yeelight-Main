@echo off
cd /d "%~dp0"
title Yeelight - Flet app

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m yeelight_app
if errorlevel 1 (
    echo.
    echo Flet app stopped with an error. Check .env and installed dependencies.
    pause
)
