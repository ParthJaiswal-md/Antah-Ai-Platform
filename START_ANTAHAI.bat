@echo off
setlocal
title AntahAI - Learning Pathways prototype
echo ============================================================
echo   AntahAI  -  SIH26101 prototype (Learning Pathways + Round 1)
echo ============================================================

cd /d "%~dp0System-3 Complete_Linker"
if errorlevel 1 (
  echo Could not find the "System-3 Complete_Linker" folder next to this file.
  pause & exit /b 1
)

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH" during setup^), then run this file again.
  pause & exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating a private Python environment ^(first run only^)...
  %PY% -m venv .venv
  if errorlevel 1 ( echo Failed to create the environment. & pause & exit /b 1 )
)

echo [2/3] Installing requirements ^(first run needs internet, ~1 minute^)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q flask python-dotenv pypdf
if errorlevel 1 ( echo Package install failed. Check your internet connection. & pause & exit /b 1 )

echo [3/3] Starting AntahAI on http://127.0.0.1:8080
echo.
echo   Demo logins:  demo_asha / demo1234   ^(strong Python^)
echo                 demo_ravi / demo1234   ^(beginner^)
echo.
echo   Keep this window open while using the app. Close it to stop.
echo ============================================================
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8080/login"
".venv\Scripts\python.exe" app.py
pause
