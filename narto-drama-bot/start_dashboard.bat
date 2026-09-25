@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Narto Drama - Dashboard (keep this window open)
:loop
.venv\Scripts\python -m bot web --port 8080
echo Dashboard stopped - restarting in 20s... (close window to quit)
timeout /t 20 >nul
goto loop
