@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

set "YEELIGHT_HOST=127.0.0.1"
set "YEELIGHT_PORT=8000"
if exist ".env" (
    for /f "tokens=1,* delims==" %%A in ('findstr /b "YEELIGHT_HOST=" .env') do set "YEELIGHT_HOST=%%B"
    for /f "tokens=1,* delims==" %%A in ('findstr /b "YEELIGHT_PORT=" .env') do set "YEELIGHT_PORT=%%B"
)
if "%YEELIGHT_HOST%"=="0.0.0.0" set "YEELIGHT_HOST=127.0.0.1"
if "%YEELIGHT_HOST%"=="::" set "YEELIGHT_HOST=[::1]"
if "%YEELIGHT_HOST%"=="::1" set "YEELIGHT_HOST=[::1]"
set "YEELIGHT_PROBE_URL=http://%YEELIGHT_HOST%:%YEELIGHT_PORT%"
call :server_ready
if not errorlevel 1 goto open_browser

start "Yeelight Server" "%~dp0.venv\Scripts\python.exe" -m yeelight_network.server
for /l %%I in (1,1,30) do (
    timeout /t 1 /nobreak >nul
    call :server_ready
    if not errorlevel 1 goto open_browser
)
echo Server did not become ready within 30 seconds.
echo Check the server window, .env settings, and whether the port is already in use.
pause
exit /b 1

:server_ready
powershell.exe -NoProfile -Command "try { $base = '%YEELIGHT_PROBE_URL%'.TrimEnd('/'); $response = Invoke-WebRequest -Uri ($base + '/api/health') -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 } } catch { }; exit 1" >nul 2>nul
if errorlevel 1 exit /b 1
echo Yeelight server is responding at %YEELIGHT_PROBE_URL%.
exit /b 0

:open_browser
start "" "%YEELIGHT_PROBE_URL%/"
exit /b 0
