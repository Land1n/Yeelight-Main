@echo off
setlocal
cd /d "%~dp0.."

echo === Yeelight setup ===
echo Repository: %CD%

set "PYTHON=py -3"
where py >nul 2>nul
if errorlevel 1 set "PYTHON=python"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PYTHON% -m venv .venv
  if errorlevel 1 goto :fail
)

echo Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 echo Warning: pip upgrade failed; continuing.

echo Installing yeelight-logic, yeelight-manager and yeelight-server...
".venv\Scripts\python.exe" -m pip install -e "packages\yeelight-logic" -e "packages\yeelight-manager" -e "packages\yeelight-server"
if errorlevel 1 goto :fail

echo Preparing .env...
".venv\Scripts\python.exe" "tools\setup_env.py"
if errorlevel 1 goto :fail

echo.
echo Setup complete.
echo   1. Review .env (administrator username and password).
echo   2. Run start-server.bat.
echo   3. Open http://127.0.0.1:8000 and sign in.
echo   4. Create a pairing code under Managers and run start-manager.bat --pair CODE.
exit /b 0

:fail
echo.
echo Setup failed. Check the messages above.
exit /b 1
