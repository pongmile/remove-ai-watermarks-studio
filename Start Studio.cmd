@echo off
setlocal
REM One-click launcher for Remove AI Watermarks Studio.
REM Double-click this file, or use the desktop shortcut created by make_shortcut.ps1.
title Remove AI Watermarks Studio
cd /d "%~dp0"

if "%RAIW_HOST%"=="" set "RAIW_HOST=127.0.0.1"
if "%RAIW_PORT%"=="" set "RAIW_PORT=8000"

REM Invoke the virtualenv Python directly rather than `uv run` so installed GPU
REM PyTorch wheels (e.g. cu128, xpu, directml) are never overwritten by a lock sync.
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

set "URL=http://%RAIW_HOST%:%RAIW_PORT%"

echo.
echo   Remove AI Watermarks Studio - starting local server...
echo   Opening %URL%   (close this window to stop)
echo.

REM Wait until the port accepts connections (up to 25s), then open the browser.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "$h='%RAIW_HOST%'; $p=%RAIW_PORT%; $u='%URL%'; $deadline=(Get-Date).AddSeconds(25); while((Get-Date) -lt $deadline){ try { $c=New-Object System.Net.Sockets.TcpClient($h,$p); $c.Close(); Start-Process $u; break } catch { Start-Sleep -Milliseconds 250 } }"

"%PY%" -m uvicorn webapp.server:app --host %RAIW_HOST% --port %RAIW_PORT%

echo.
echo   Server stopped.
pause
