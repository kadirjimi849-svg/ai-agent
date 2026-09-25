@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===== Narto Drama Autopilot - Windows setup =====

python -c "import sys" >nul 2>nul || (
  echo [*] Installing Python...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo !!! Close this window and double-click setup_windows.bat again !!!
  pause & exit /b
)
where ffmpeg >nul 2>nul || (
  echo [*] Installing FFmpeg...
  winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
  echo.
  echo !!! Close this window and double-click setup_windows.bat again !!!
  pause & exit /b
)

if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\pip install -r requirements.txt || (echo pip install failed & pause & exit /b)

if not exist config.yaml copy config.example.yaml config.yaml >nul
if not exist .env copy .env.example .env >nul

.venv\Scripts\python -c "from bot.overlays import resolve_font; print('Arabic font:', resolve_font(None))"
ffmpeg -version | findstr /b "ffmpeg version"
echo.
echo ===== DONE =====
echo Now double-click start_dashboard.bat  (opens http://localhost:8080)
pause
