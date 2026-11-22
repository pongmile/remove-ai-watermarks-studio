@echo off
setlocal
REM One-click smart launcher for Remove AI Watermarks Studio.
REM - Single-instance: if Studio is already running on RAIW_PORT, opens the browser directly.
REM - Auto-shutdown: closes server & frees VRAM ~12s after last browser tab closes (when idle).
REM - Auto-restart: seamlessly restarts when "Restart Studio" is clicked in the Web UI (exit 75).
title Remove AI Watermarks Studio
cd /d "%~dp0"

if "%RAIW_HOST%"=="" set "RAIW_HOST=127.0.0.1"
if "%RAIW_PORT%"=="" set "RAIW_PORT=8000"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo.
  echo   No virtual environment found at .venv
  echo   Run the universal installer first:
  echo.
  echo     powershell -ExecutionPolicy Bypass -File .\install.ps1
  echo.
  pause
  exit /b 1
)

set PYTHONUTF8=1
REM Disable hf-xet on Windows to prevent stalled Hugging Face downloads.
set HF_HUB_DISABLE_XET=1
if "%RAIW_AUTO_SHUTDOWN%"=="" set "RAIW_AUTO_SHUTDOWN=1"
set "RAIW_ALLOW_RESTART=1"

set "URL=http://%RAIW_HOST%:%RAIW_PORT%"

REM Smart single-instance check: if Studio is already running, just open the existing tab & exit!
powershell -NoProfile -WindowStyle Hidden -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 -Uri '%URL%/health'; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"
if "%ERRORLEVEL%"=="0" (
  echo.
  echo   Remove AI Watermarks Studio is already running at %URL%
  echo   Opening browser...
  start "" "%URL%"
  exit /b 0
)

echo.
echo   Remove AI Watermarks Studio - starting local server...
echo   Opening %URL%
echo   (Closes automatically after last browser tab closes, or click Quit in the app)
echo.

REM Wait until the port accepts connections (up to 25s), then open the browser once.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "$h='%RAIW_HOST%'; $p=%RAIW_PORT%; $u='%URL%'; $deadline=(Get-Date).AddSeconds(25); while((Get-Date) -lt $deadline){ try { $c=New-Object System.Net.Sockets.TcpClient($h,$p); $c.Close(); Start-Process $u; break } catch { Start-Sleep -Milliseconds 250 } }"

:run_server
"%PY%" -m uvicorn webapp.server:app --host %RAIW_HOST% --port %RAIW_PORT%
set "RC=%ERRORLEVEL%"

if "%RC%"=="75" (
  echo.
  echo   Restarting Remove AI Watermarks Studio...
  echo.
  goto run_server
)

if "%RC%"=="0" (
  exit /b 0
)

echo.
echo   Server exited with code %RC%.
pause
exit /b %RC%
