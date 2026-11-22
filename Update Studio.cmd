@echo off
setlocal
REM One-click GitHub updater for Remove AI Watermarks Studio.
REM Pass -Upstream to sync directly from wiltodelta/remove-ai-watermarks.
title Remove AI Watermarks Studio - Updater
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo   Done. You can now launch "Start Studio.cmd".
) else (
  echo   Updater exited with code %RC%. See details above.
)
pause
exit /b %RC%
