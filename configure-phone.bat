@echo off
cd /d "%~dp0"
title Yeelight - phone setup

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" configure_phone.py
if errorlevel 1 (
    echo Could not configure phone access.
    pause
    exit /b 1
)

echo.
echo Check the LAN URL above, then run start-all.bat.
pause
