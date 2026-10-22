@echo off
setlocal
rem Starts VoiceBox in the background (detached). Safe to run repeatedly.
rem Stop it with: docker stop voicebox

set "MODULE_DIR=%~dp0"
set "NAME=voicebox"
set "IMAGE=voicebox-local"

where docker >nul 2>&1
if errorlevel 1 (
  echo [VoiceBox] Docker was not found on PATH. Start Docker Desktop and retry.
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo [VoiceBox] Docker is not running. Start Docker Desktop and retry.
  exit /b 1
)

for /f %%i in ('docker ps -q -f "name=^%NAME%$"') do (
  echo [VoiceBox] Already running.
  exit /b 0
)

rem Remove a stopped container with the same name so the run below succeeds.
docker rm -f %NAME% >nul 2>&1

docker image inspect %IMAGE% >nul 2>&1
if errorlevel 1 (
  echo [VoiceBox] Building %IMAGE% from source ^(first run only^)...
  docker build -t %IMAGE% "%MODULE_DIR%."
  if errorlevel 1 (
    echo [VoiceBox] Build failed.
    exit /b 1
  )
)

docker run -d --rm --name %NAME% -p 127.0.0.1:8790:8790 -e VOICEBOX_TTS_ENGINE=kokoro -e VOICEBOX_DEFAULT_VOICE=af_heart %IMAGE% >nul
if errorlevel 1 (
  echo [VoiceBox] Failed to start the container.
  exit /b 1
)

echo [VoiceBox] Started on http://localhost:8790
exit /b 0
