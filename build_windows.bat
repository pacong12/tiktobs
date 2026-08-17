@echo off
REM ====================================================================
REM  build_windows.bat - Build TikTokOBS.exe on Windows (double-click)
REM ====================================================================
setlocal
cd /d "%~dp0"

echo ==================================================
echo    TikTok OBS - Windows EXE Builder
echo ==================================================
echo.

REM 1. Find Python (prefer the 'py' launcher, fall back to 'python')
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
        echo dan centang "Add Python to PATH" saat instalasi.
        pause
        exit /b 1
    )
)
echo Menggunakan Python: %PY%

REM 2. Create virtual environment if missing
if not exist ".venv\Scripts\python.exe" (
    echo Membuat virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 ( echo [ERROR] Gagal membuat venv. & pause & exit /b 1 )
)

REM 3. Install dependencies + PyInstaller
echo Menginstall dependensi...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
call ".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 ( echo [ERROR] Gagal install dependensi. & pause & exit /b 1 )

REM 4. Run the build
echo.
echo Membangun executable...
call ".venv\Scripts\python.exe" build_exe.py
if errorlevel 1 ( echo [ERROR] Build gagal. & pause & exit /b 1 )

echo.
echo ==================================================
echo  SELESAI! File versi terbaru ada di folder dist\
echo  (contoh: dist\TikTokOBS-1.0.0.exe)
echo ==================================================
pause
