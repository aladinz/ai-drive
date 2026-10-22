@echo off
set "PYTHON=python"
if exist "%~dp0.venv-1\Scripts\python.exe" set "PYTHON=%~dp0.venv-1\Scripts\python.exe"
set "DOCS_DIR=%~dp0docs"

echo ============================================
echo   Estate Knowledge Base - Starting...
echo ============================================
echo.
echo Looking for PDF or DOCX files in: %DOCS_DIR%
echo Opening your browser in a few seconds...
timeout /t 3 /nobreak >nul
start http://localhost:8899
"%PYTHON%" app.py
pause
