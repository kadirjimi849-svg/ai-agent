@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Narto Drama (legacy config.yaml mode) (keep this window open)
.venv\Scripts\python -m bot sync
:loop
.venv\Scripts\python -m bot run
echo Bot stopped - restarting in 30s... (close window to quit)
timeout /t 30 >nul
goto loop
