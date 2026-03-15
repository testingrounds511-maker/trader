@echo off
title PHANTOM WOLF v3.6 - QUANTUM PREDATOR
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

:: ─── Detect Python ───
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo.
    echo   ERROR: Python not found. Install Python 3.11+ and add to PATH.
    echo.
    pause
    exit /b 1
)

echo   Using: %PY%

:: ─── Check requirements.txt ───
echo   Generating requirements.txt...
(
    echo alpaca-py^>=0.28.0
    echo massive^>=2.0.1
    echo anthropic^>=0.42.0
    echo streamlit^>=1.40.0
    echo pandas^>=2.2.0
    echo numpy^>=1.26.0
    echo plotly^>=5.24.0
    echo ta^>=0.11.0
    echo python-dotenv^>=1.0.0
    echo requests^>=2.32.0
    echo apscheduler^>=3.10.0
    echo feedparser^>=6.0.0
    echo beautifulsoup4^>=4.12.0
    echo praw^>=7.8.0
    echo streamlit-autorefresh^>=1.0.1
    echo pytz^>=2024.1
    echo py-clob-client^>=0.18.0
    echo yfinance^>=0.2.36
    echo finnhub-python^>=2.4.0
    echo # v3.6 Quantum Predator
    echo aiohttp^>=3.9.0
    echo websockets^>=12.0
) > requirements.txt

:: ─── Create data directory ───
if not exist "data" mkdir data

:: ─── First-time setup (only runs once) ───
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo.
    echo   =============================================
    echo     PHANTOM WOLF v3.6 - First Time Setup
    echo   =============================================
    echo.
    echo   [1/3] Creating virtual environment...
    %PY% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo   ERROR: Could not create venv.
        pause
        exit /b 1
    )
    call "%VENV_DIR%\Scripts\activate.bat"
    echo   [2/3] Installing dependencies (may take a minute^)...
    python -m pip install --upgrade pip -q >nul 2>&1
    python -m pip install -r requirements.txt -q
    if errorlevel 1 (
        echo   ERROR: Failed to install dependencies.
        pause
        exit /b 1
    )
    echo   [3/3] Setup complete!
    echo.
    :: GPU acceleration (optional)
    where nvidia-smi >nul 2>nul
    if not errorlevel 1 (
        echo   [GPU] NVIDIA GPU detected. Installing CuPy...
        python -m pip install cupy-cuda12x -q 2>nul || echo   [GPU] CuPy install failed (non-critical^)
    )
    echo.
    goto :check_env
)

:: ─── Activate existing venv ───
call "%VENV_DIR%\Scripts\activate.bat" >nul 2>&1

:: ─── Check for dependency updates ───
call :check_deps

:check_env
:: ─── Check .env exists ───
if not exist ".env" (
    echo.
    echo   =============================================
    echo     ERROR: Missing .env file
    echo   =============================================
    echo.
    echo   Crea un archivo .env con al menos:
    echo     ALPACA_API_KEY=your_key
    echo     ALPACA_SECRET_KEY=your_secret
    echo.
    echo   v3.6 Quantum Predator (opcional^):
    echo     GROQ_API_KEY=your_key              ^(NLP Sniper - llama3^)
    echo     QUIVER_API_KEY=your_key            ^(Congress trades^)
    echo     INITIAL_CAPITAL_USD=100.00
    echo     MAX_SLIPPAGE_TOLERANCE_PCT=0.001
    echo.
    pause
    exit /b 1
)

:: ─── Quick import check ───
python -c "import importlib.util, sys; required=('streamlit','alpaca','aiohttp'); ok=all(importlib.util.find_spec(m) for m in required); sys.exit(0 if ok else 1)" >nul 2>&1
if errorlevel 1 (
    echo   Dependencies missing. Installing...
    python -m pip install -r requirements.txt -q
    if errorlevel 1 (
        echo   ERROR: Could not install dependencies.
        pause
        exit /b 1
    )
)

:: ─── Mode Selection ───
echo.
echo   ====================================================
echo     PHANTOM WOLF v3.6 - QUANTUM PREDATOR
echo   ====================================================
echo.
echo     [1] Dashboard only       (Streamlit + integrated v3.6 engine)
echo     [2] Wolf Engine only     (v3.6 async CLI)
echo     [3] Full Stack           (Dashboard v3.5 + Wolf Engine v3.6)
echo.
set /p MODE="   Selecciona modo [1/2/3]: "

if "%MODE%"=="2" goto :wolf_engine
if "%MODE%"=="3" goto :both
goto :dashboard

:: ═══════════════════════════════════════════
:: MODE 1: Dashboard only (Streamlit + integrated v3.6)
:: ═══════════════════════════════════════════
:dashboard
set DASHBOARD_ENGINE_MODE=wolf
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8502"

:dashboard_loop
if not defined ALPACA_DATA_FEED set ALPACA_DATA_FEED=sip

echo.
echo   ====================================================
echo     MODE: DASHBOARD (Streamlit + integrated v3.6 engine)
echo   ====================================================
echo     URL:        http://localhost:8502
echo     Press Ctrl+C to stop
echo   ====================================================
echo.

python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502 --server.headless true --theme.base dark --theme.primaryColor "#00ff88" --theme.backgroundColor "#0a0e17" --theme.secondaryBackgroundColor "#0d1421" --theme.textColor "#e0e6ed"

echo.
echo   DASHBOARD CRASHED. RESTARTING IN 5 SECONDS...
timeout /t 5
goto dashboard_loop

:: ═══════════════════════════════════════════
:: MODE 2: Wolf Engine v3.6 (async CLI)
:: ═══════════════════════════════════════════
:wolf_engine
echo.
echo   ====================================================
echo     PHANTOM WOLF v3.6 - QUANTUM PREDATOR ENGINE
echo   ====================================================
echo     Modules:    NLP + Arbitrage + Ratchet + Compliance
echo     Orders:     Sniper Limit Only (zero market orders)
echo     Log:        data/wolf_engine.log
echo     Press Ctrl+C for graceful shutdown
echo   ====================================================
echo.

python wolf_main.py

echo.
echo   Wolf Engine stopped. Check data/wolf_engine.log
pause
exit /b 0

:: ═══════════════════════════════════════════
:: MODE 3: Full Stack (Dashboard + Engine)
:: ═══════════════════════════════════════════
:both
set DASHBOARD_ENGINE_MODE=legacy
echo.
echo   ====================================================
echo     FULL STACK: Dashboard v3.5 + Wolf Engine v3.6
echo   ====================================================
echo     Dashboard:  http://localhost:8502
echo     Engine:     v3.6 async (background window)
echo     Press Ctrl+C to stop dashboard
echo     Close the Wolf Engine window to stop engine
echo   ====================================================
echo.

:: Start Wolf Engine in a separate minimized window
start "Wolf Engine v3.6" /min cmd /c "cd /d "%~dp0" && call .venv\Scripts\activate.bat && python wolf_main.py && pause"

:: Start Dashboard in foreground
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8502"

:both_loop
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502 --server.headless true --theme.base dark --theme.primaryColor "#00ff88" --theme.backgroundColor "#0a0e17" --theme.secondaryBackgroundColor "#0d1421" --theme.textColor "#e0e6ed"

echo.
echo   DASHBOARD CRASHED. RESTARTING IN 5 SECONDS...
timeout /t 5
goto both_loop

:: ─── Subroutine: check if requirements.txt changed ───
:check_deps
if not exist "%VENV_DIR%\.deps_hash" (
    certutil -hashfile requirements.txt MD5 2>nul | findstr /v "hash MD5" >"%VENV_DIR%\.deps_hash"
    goto :eof
)
set "NEW_HASH="
for /f %%A in ('certutil -hashfile requirements.txt MD5 2^>nul ^| findstr /v "hash MD5"') do set "NEW_HASH=%%A"
set /p OLD_HASH=<"%VENV_DIR%\.deps_hash"
if not "!NEW_HASH!"=="!OLD_HASH!" (
    echo   Dependencies changed. Updating...
    python -m pip install -r requirements.txt -q
    echo !NEW_HASH!>"%VENV_DIR%\.deps_hash"
)
goto :eof
