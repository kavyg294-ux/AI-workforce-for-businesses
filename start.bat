@echo off
echo ============================================================
echo   AI WORKFORCE FOR BUSINESSES
echo   Autonomous Multi-Agent Orchestration System
echo ============================================================
echo.

REM Check for .env file
if not exist ".env" (
    echo [!] .env file not found. Creating template...
    echo GEMINI_API_KEY=your_gemini_api_key_here > .env
    echo.
    echo [!] Please edit .env and add your Gemini API key.
    echo     Get your key at: https://aistudio.google.com/app/apikey
    echo.
    pause
    exit /b
)

REM Check Python
python --version 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b
)

echo [*] Starting AI Workforce server...
echo [*] Dashboard: http://localhost:8000
echo.
echo Press Ctrl+C to stop.
echo.

set PYTHONIOENCODING=utf-8
python server.py

pause
