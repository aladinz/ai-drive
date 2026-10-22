@echo off
setlocal
title Aladdin WebUI (LM Studio)

set "ROOT=%~dp0.."
set "PY=py"
if exist "%ROOT%\.venv-1\Scripts\python.exe" (
  "%ROOT%\.venv-1\Scripts\python.exe" -V >nul 2>&1 && set "PY=%ROOT%\.venv-1\Scripts\python.exe"
)
if not exist "%ROOT%\WebUI\serve_webui.py" (
  echo ERROR: Missing WebUI proxy server script:
  echo   %ROOT%\WebUI\serve_webui.py
  pause
  exit /b 1
)

echo ============================================
echo   Aladdin WebUI ^+ LM Studio
echo ============================================
echo.
echo URL: http://127.0.0.1:8090/index.html
echo Backend: http://127.0.0.1:1234
echo.

echo Starting VoiceBox ^(background^)...
if exist "%ROOT%\ai-drive\modules\voicebox\docker-start-detached.bat" (
  call "%ROOT%\ai-drive\modules\voicebox\docker-start-detached.bat"
) else (
  echo VoiceBox start script not found; voice features will be unavailable.
)
echo.

powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){ Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }"

start "" "http://127.0.0.1:8090/index.html"
"%PY%" "%ROOT%\WebUI\serve_webui.py" --host 127.0.0.1 --port 8090 --backend http://127.0.0.1:1234

pause
