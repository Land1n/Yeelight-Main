@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

set "YEELIGHT_PROBE_URL=http://127.0.0.1:8000"
if exist ".env" (
    for /f "tokens=1,* delims==" %%A in ('findstr /b "YEELIGHT_SERVER_URL=" .env') do set "YEELIGHT_PROBE_URL=%%B"
)
call :server_ready
if not errorlevel 1 goto server_ready

start "Yeelight Server" "%~dp0.venv\Scripts\python.exe" -m yeelight_network.server
for /l %%I in (1,1,30) do (
    timeout /t 1 /nobreak >nul
    call :server_ready
    if not errorlevel 1 goto server_ready
)
echo Server did not become ready within 30 seconds.
echo Check the server window, .env settings, and whether the port is already in use.
pause
exit /b 1

:server_ready
powershell.exe -NoProfile -Command "try { $base = '%YEELIGHT_PROBE_URL%'.TrimEnd('/'); $response = Invoke-WebRequest -Uri ($base + '/api/health') -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 } } catch { }; exit 1" >nul 2>nul
if errorlevel 1 exit /b 1
echo Yeelight server is responding at %YEELIGHT_PROBE_URL%.
goto :start_app

:start_app
start "Yeelight Flet App" "%~dp0.venv\Scripts\python.exe" -m yeelight_app
exit /b 0
