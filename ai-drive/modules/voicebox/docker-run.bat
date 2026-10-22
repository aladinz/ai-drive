@echo off
setlocal
title VoiceBox (local build)

cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker was not found on PATH.
  pause
  exit /b 1
)

echo Building VoiceBox image: voicebox-local
docker build -t voicebox-local .
if errorlevel 1 (
  echo ERROR: Docker build failed.
  pause
  exit /b 1
)

echo.
echo VoiceBox listening on http://localhost:8790  (Ctrl+C to stop)
docker run --rm -p 127.0.0.1:8790:8790 -e VOICEBOX_TTS_ENGINE=kokoro -e VOICEBOX_DEFAULT_VOICE=af_heart voicebox-local

pause
