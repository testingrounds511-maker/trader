@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PIP_NO_CACHE_DIR=1"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY_LAUNCHER=py -3"
) else (
    set "PY_LAUNCHER=python"
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [1/4] Creating virtual environment...
    %PY_LAUNCHER% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

echo [2/4] Updating pip...
python -m pip install --upgrade pip --no-cache-dir
if errorlevel 1 (
    echo Failed to update pip.
    pause
    exit /b 1
)

echo [3/4] Installing dependencies...
python -m pip install --no-cache-dir -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

if not exist ".env" (
    echo Missing .env file in project root.
    echo Add your keys first: ALPACA_API_KEY, ALPACA_SECRET_KEY.
    echo ANTHROPIC_API_KEY is optional. If missing, heuristic fallback is used.
    pause
    exit /b 1
)

echo [4/4] Launching dashboard...
python main.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Startup failed with code %EXIT_CODE%.
    echo Check your .env values and try again.
    pause
)

exit /b %EXIT_CODE%
