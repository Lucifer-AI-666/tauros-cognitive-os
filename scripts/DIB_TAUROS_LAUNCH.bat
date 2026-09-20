@echo off
title DIB TAUROS launcher
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0DIB_TAUROS_LAUNCH.ps1"
if errorlevel 1 pause
