@echo off
REM ====================================================================
REM  run_windows.bat - Run TikTokOBS from source on Windows (dev mode)
REM ====================================================================
setlocal
cd /d "%~dp0"

echo ==================================================
echo    TikTok OBS - Menjalankan dari source
echo ==================================================
echo.

REM 1. Find Python
where py >nul 2>&1
if %errorlevel%==0 (
    set "PY=py"
) else (
    where python >nul 2>&1
    if %errorlevel%==0 (
        set "PY=python"
    ) else (
        echo [ERROR] Python tidak ditemukan.
        echo Install Python dari https://www.python.org/downloads/
        echo dan centang "Add Python to PATH".
        pause
        exit /b 1
    )
)

REM 2. Create venv if missing
if not exist ".venv\Scripts\python.exe" (
    echo Membuat virtual environment...
    %PY% -m venv .venv
    call ".venv\Scripts\python.exe" -m pip install --upgrade pip
    call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

REM 3. Run the app (browser will open automatically)
echo Menjalankan server di http://127.0.0.1:8000 ...
call ".venv\Scripts\python.exe" run_app.py
pause
