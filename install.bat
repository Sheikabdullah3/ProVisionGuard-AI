@echo off
title ProVisionGuard AI — Installer
color 0B

echo.
echo  ============================================
echo   ProVisionGuard AI v8.0 — Installer
echo   Real-Time AI Surveillance System
echo  ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found!
    echo  Please install Python 3.10+ from https://python.org
    echo  Make sure to check "Add Python to PATH"
    pause
    exit /b 1
)

echo  [1/6] Python found. Creating virtual environment...
if not exist "venv" (
    python -m venv venv
    echo  [OK] Virtual environment created.
) else (
    echo  [OK] Virtual environment already exists.
)

echo.
echo  [2/6] Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo  [3/6] Installing core packages...
pip install --quiet --upgrade pip
pip install --quiet flask flask-socketio opencv-python ultralytics

echo.
echo  [4/6] Installing AI packages...
pip install --quiet insightface hsemotion-onnx onnxruntime
pip install --quiet easyocr reportlab pyttsx3

echo.
echo  [5/6] Installing GPU support (PyTorch CUDA)...
pip install --quiet torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

echo.
echo  [6/6] Creating required folders...
if not exist "data\snapshots"           mkdir data\snapshots
if not exist "data\reports"             mkdir data\reports
if not exist "data\known_faces\whitelist" mkdir data\known_faces\whitelist
if not exist "data\known_faces\blacklist" mkdir data\known_faces\blacklist
if not exist "data\known_faces\routine"   mkdir data\known_faces\routine
if not exist "demo"                     mkdir demo

echo.
echo  ============================================
echo   Installation Complete!
echo  ============================================
echo.
echo  To run ProVisionGuard AI:
echo.
echo    Option 1 (Normal):
echo      python app_v8.py
echo.
echo    Option 2 (Demo mode - no camera needed):
echo      python app_v8.py --demo
echo.
echo    Option 3 (Auto-restart):
echo      python run_pvg.py
echo.
echo  Then open: http://localhost:5000
echo  Login    : admin / pvg@admin123
echo  Setup    : http://localhost:5000/setup
echo.
echo  ============================================
echo.

set /p RUNOW="Run ProVisionGuard AI now? (y/n): "
if /i "%RUNOW%"=="y" (
    echo.
    echo  Starting ProVisionGuard AI...
    echo  Open http://localhost:5000 in your browser
    echo.
    python app_v8.py
)

pause