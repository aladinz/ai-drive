@echo off
set "PYTHON=python"
if exist "%~dp0.venv-1\Scripts\python.exe" set "PYTHON=%~dp0.venv-1\Scripts\python.exe"

echo ============================================
echo   Estate Knowledge Base - First-Time Setup
echo ============================================
echo.
echo Installing required packages...
"%PYTHON%" -m pip install pymupdf scikit-learn
echo.
echo Setup complete! You can close this window.
echo Next step: double-click start.bat
pause
