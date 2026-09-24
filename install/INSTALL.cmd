@echo off
title EqUpdater - installer
REM ---------------------------------------------------------------------------
REM  Double-click this file.
REM
REM  It installs Python if you do not have it, runs the test suite, and builds
REM  EqUpdater.exe. It does not touch your game folder: EqUpdater finds that
REM  itself, and imports your Octo Updater settings the first time it runs.
REM
REM  No administrator rights needed. Safe to run more than once.
REM ---------------------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" (
    echo The installer did not finish successfully. See the messages above.
)
pause
exit /b %RC%
