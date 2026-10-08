@echo off
cd /d "%~dp0"
title Yeelight - setup

if exist ".gitmodules" (
    git submodule update --init --recursive
    if errorlevel 1 (
        echo Could not initialize Git submodules.
        pause
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 (
        echo Could not create the virtual environment. Install Python 3.10 or newer.
        pause
        exit /b 1
    )
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo Created .env from .env.example. Edit it before connecting from a phone.
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo Setup complete. Use start-all.bat to start the server and Flet app.
pause
