@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo The virtual environment is missing. Run tools\setup.bat first.
  exit /b 1
)
if not exist ".env" (
  echo The .env file is missing. Run tools\setup.bat first.
  exit /b 1
)

".venv\Scripts\python.exe" -m yeelight_server %*
exit /b %errorlevel%
