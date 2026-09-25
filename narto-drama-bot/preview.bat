@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag an episode video file onto this preview.bat icon.
  pause & exit /b
)
.venv\Scripts\python -m bot preview "%~1" --count 2
echo.
echo Clips are in data\clips
start "" "%~dp0data\clips"
pause
