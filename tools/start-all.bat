@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo The virtual environment is missing. Run tools\setup.bat first.
  pause
  exit /b 1
)
if not exist ".env" (
  echo The .env file is missing. Run tools\setup.bat first.
  pause
  exit /b 1
)

start "Yeelight Server" "%~dp0start-server.bat"
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8000/"
start "Yeelight Manager" "%~dp0start-manager.bat"
exit /b 0
