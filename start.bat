@echo off
echo.
echo ========================================
echo    Amazon Product Crawler - Starter
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

REM Check if requirements are installed
echo [INFO] Checking dependencies...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
)

REM Setup database if first run
if not exist amazon_crawler.db (
    echo [INFO] First run detected, setting up database...
    python main.py setup
    if errorlevel 1 (
        echo [ERROR] Database setup failed
        pause
        exit /b 1
    )
)

REM Start the application
echo [INFO] Starting Amazon Crawler...
echo [INFO] Dashboard will be available at: http://127.0.0.1:8000
echo [INFO] Press Ctrl+C to stop the application
echo.

python main.py web

echo.
echo [INFO] Application stopped
pause 