@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
if %errorlevel% neq 0 if %errorlevel% neq 2 pause
