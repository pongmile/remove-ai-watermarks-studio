@echo off
setlocal
REM One-click universal installer for Remove AI Watermarks Studio on Windows.
REM Double-click this file after unzipping a GitHub Release or cloning the repo.
REM Auto-detects NVIDIA RTX/GTX, AMD Radeon (DirectML), Intel Arc / NPU, or CPU.
title Remove AI Watermarks Studio - Installer
cd /d "%~dp0"

echo.
echo   Remove AI Watermarks Studio - Universal Windows Installer
echo   Auto-detecting GPU / NPU / CPU and setting up .venv...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo   ============================================================
  echo   Installation complete!
  echo   Double-click "Start Studio.cmd" (or the Desktop shortcut) to launch.
  echo   ============================================================
) else (
  echo   Installer exited with code %RC%. See details above.
)
echo.
pause
exit /b %RC%
