@echo off
setlocal
title Aladdin Local AI

:: ---------------------------------------------------------------
:: Resolve drive/root from wherever this script lives
:: ---------------------------------------------------------------
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "DRIVE=%ROOT:~0,2%"
set "ENGINE_DIR="
set "WEB_DIR="
set "WEB_PY="
set "WEB_SERVER_SCRIPT="
set "WEB_PORT=8090"
set "WEB_URL=http://localhost:8090/index.html"
set "WEB_LOG=%ROOT%\History\Logs\webui-server.log"
set "ENGINE_BIN="
set "MODEL_PATH="
set "ENGINE_PORT="

if exist "%ROOT%\Llamafile\run-engine.bat" set "ENGINE_DIR=%ROOT%\Llamafile"
if not defined ENGINE_DIR if exist "%ROOT%\llamafile\run-engine.bat" set "ENGINE_DIR=%ROOT%\llamafile"
if not defined ENGINE_DIR (
  for /d %%D in ("%ROOT%\llamafile-*" "%ROOT%\Llamafile-*") do (
    if exist "%%~fD\run-engine.bat" set "ENGINE_DIR=%%~fD"
  )
)

if not defined ENGINE_DIR (
  echo.
  echo ERROR: Missing AI engine launcher.
  echo Expected: %ROOT%\Llamafile\run-engine.bat
  echo.
  echo Please restore the Llamafile folder and run this script again.
  echo See README drive layout for required files.
  echo.
  pause
  exit /b 1
)

if exist "%ENGINE_DIR%\bin\llamafile.exe" set "ENGINE_BIN=%ENGINE_DIR%\bin\llamafile.exe"
if not defined ENGINE_BIN if exist "%ENGINE_DIR%\bin\llamafile" set "ENGINE_BIN=%ENGINE_DIR%\bin\llamafile"
if not defined ENGINE_BIN (
  echo.
  echo ERROR: Engine binary not found in %ENGINE_DIR%\bin
  echo.
  pause
  exit /b 1
)

if exist "%ROOT%\miniweb\htdocs\index.html" set "WEB_DIR=%ROOT%\miniweb\htdocs"
if not defined WEB_DIR if exist "%ROOT%\WebUI\index.html" set "WEB_DIR=%ROOT%\WebUI"
if exist "%ROOT%\.venv-1\Scripts\python.exe" set "WEB_PY=%ROOT%\.venv-1\Scripts\python.exe"
if not defined WEB_PY if exist "%ROOT%\.venv\Scripts\python.exe" set "WEB_PY=%ROOT%\.venv\Scripts\python.exe"
if defined WEB_DIR if exist "%WEB_DIR%\serve_webui.py" set "WEB_SERVER_SCRIPT=%WEB_DIR%\serve_webui.py"

echo  Found AI drive at: %DRIVE%
echo  Root folder: %ROOT%
echo  Engine folder: %ENGINE_DIR%
if defined WEB_DIR echo  Web folder: %WEB_DIR%

if not exist "%ROOT%\History" mkdir "%ROOT%\History"
if not exist "%ROOT%\History\Memory" mkdir "%ROOT%\History\Memory"
if not exist "%ROOT%\History\Chats" mkdir "%ROOT%\History\Chats"
if not exist "%ROOT%\History\Config" mkdir "%ROOT%\History\Config"
if not exist "%ROOT%\History\Logs" mkdir "%ROOT%\History\Logs"

echo.
echo ============================================
echo   Performance Mode
echo ============================================
echo.
echo  Performance profile active.

cd /d "%ENGINE_DIR%"

echo.
echo ============================================
echo    Aladdin Local AI  --  Model Selector
echo ============================================
echo.
echo   [1]  Qwen 2.5 Coder 7B
echo   [2]  Llama 3.1 8B Lexi
echo   [3]  DarkIdol Llama 3.1 8B 
echo   [4]  BigTalker 8B
echo   [5]  Dirty_Harry 8B
echo   [6]  Dark Planet 8B
echo   [7]  Meta Llama 3.1 8B Instruct (stock tools)
echo.

CHOICE /C 1234567 /N /M "   Press 1-7 to select: "

IF %ERRORLEVEL%==1 (
  SET MODEL_FILE=qwen2.5-coder-7b-instruct-q4_k_m.gguf
  SET MODEL_LABEL=Qwen 2.5 Coder 7B
  SET CTX_SIZE=8192
  SET WAIT=120
)
IF %ERRORLEVEL%==2 (
  SET MODEL_FILE=Llama-3.1-8B-Lexi-Uncensored-V2-Q6_K.gguf
  SET MODEL_LABEL=Llama 3.1 8B Lexi
  SET CTX_SIZE=8192
  SET WAIT=150
)
IF %ERRORLEVEL%==3 (
  SET MODEL_FILE=DarkIdol-Llama-3.1-8B-Instruct-1.2-Uncensored.Q4_K_M.gguf
  SET MODEL_LABEL=DarkIdol Llama 3.1 8B
  SET CTX_SIZE=8192
  SET WAIT=150
)
IF %ERRORLEVEL%==4 (
  SET MODEL_FILE=L3.1-RP-Hero-BigTalker-8B-D_AU-Q4_k_m.gguf
  SET MODEL_LABEL=L3.1-RP-Hero-BigTalker 8B
  SET CTX_SIZE=8192
  SET WAIT=150
)
IF %ERRORLEVEL%==5 (
  SET MODEL_FILE=L3.1-RP-Hero-Dirty_Harry-8B-D_AU-Q4_k_m.gguf
  SET MODEL_LABEL=L3.1-RP-Hero-Dirty_Harry 8B
  SET CTX_SIZE=8192
  SET WAIT=150
)
IF %ERRORLEVEL%==6 (
  SET MODEL_FILE=Llama-3.1-128k-Dark-Planet-Uncensored-8B-Q4_k_m.gguf
  SET MODEL_LABEL=Dark Planet 8B
  SET CTX_SIZE=8192
  SET WAIT=150
)
IF %ERRORLEVEL%==7 (
  SET MODEL_FILE=Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
  SET MODEL_LABEL=Meta Llama 3.1 8B Instruct
  SET CTX_SIZE=8192
  SET WAIT=150
)

if defined WEB_DIR (
  echo %MODEL_LABEL%> "%WEB_DIR%\current_model.txt"
  echo %MODEL_FILE%> "%WEB_DIR%\current_model_id.txt"
) else (
  echo WARNING: Web UI folder not found, skipping current_model.txt update.
)

echo.
echo ============================================
echo   Starting AI Engine (llamafile)
echo ============================================
echo.

echo Selecting available engine port...
for /f %%P in ('powershell -NoProfile -Command "$ports=@(8080,8081,8082,8083); foreach($port in $ports){ $c=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if(-not $c){ Write-Output $port; exit 0 }; $p=Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; if($p -and $p.ProcessName -ieq 'llamafile'){ Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Output $port; exit 0 } }; exit 1"') do set "ENGINE_PORT=%%P"
if not defined ENGINE_PORT (
  echo ERROR: No free engine port found in 8080-8083.
  echo Close any app using those ports and rerun this launcher.
  pause
  exit /b 1
)
echo Using engine port: %ENGINE_PORT%

:: ---------------------------------------------------------------
:: Start llamafile via helper (keeps window open so crashes are visible)
:: --no-mmap  : load model into RAM (essential for USB/portable drives)
:: --ctx-size : uses fallback profiles in run-engine.bat
:: ---------------------------------------------------------------
set "ENGINE_MODEL_FILE=%MODEL_FILE%"
set "MODEL_FILE=%ENGINE_MODEL_FILE%"
set "MODEL_PATH=%ROOT%\Models\%MODEL_FILE%"
if not exist "%MODEL_PATH%" (
  echo ERROR: Selected model file not found:
  echo   %MODEL_PATH%
  pause
  exit /b 1
)
start "Aladdin AI Engine" "%ENGINE_BIN%" -m "%MODEL_PATH%" --server --host 127.0.0.1 --port %ENGINE_PORT% --ctx-size %CTX_SIZE% --parallel 1 --no-mmap

echo Waiting for engine API on 127.0.0.1:%ENGINE_PORT% to become reachable...
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(%WAIT%); $ok=$false; while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:%ENGINE_PORT%/v1/models' -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 500){ $ok=$true; break } } catch {}; Start-Sleep -Milliseconds 500 }; if($ok){ exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Engine API did not become reachable on port %ENGINE_PORT%.
  echo Check the "Aladdin AI Engine" window for startup errors, then rerun this launcher.
  pause
  exit /b 1
)

echo.
echo ============================================
echo   Interface Mode
echo ============================================
echo.
echo   [1]  Custom Aladdin UI (recommended)
echo   [2]  llama.cpp UI (advanced)
echo.
echo   Auto-selecting Custom Aladdin UI in 8 seconds...
CHOICE /C 12 /N /T 8 /D 1 /M "   Press 1 for Custom UI or 2 for llama.cpp UI: "

if %ERRORLEVEL%==1 goto launch_custom
if %ERRORLEVEL%==2 goto launch_llamacpp

:launch_llamacpp
echo Checking llama.cpp UI availability...
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(20); $ok=$false; while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:%ENGINE_PORT%' -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 500){ $ok=$true; break } } catch {}; Start-Sleep -Milliseconds 500 }; if($ok){ exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
  echo WARNING: llama.cpp UI is not reachable yet. Opening browser anyway.
)
start "" "http://127.0.0.1:%ENGINE_PORT%"
goto launch_done

:launch_custom

if defined WEB_DIR (
  if defined WEB_PY (
    powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort %WEB_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){ Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1
    powershell -NoProfile -Command "try { $r=Invoke-WebRequest -Uri '%WEB_URL%' -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 500){ exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
    if errorlevel 1 (
      type nul > "%WEB_LOG%"
      if defined WEB_SERVER_SCRIPT (
        start "Aladdin WebUI Server" /min "%WEB_PY%" "%WEB_SERVER_SCRIPT%" --host 127.0.0.1 --port %WEB_PORT% --backend http://127.0.0.1:%ENGINE_PORT%
      ) else (
        start "Aladdin WebUI Server" /min "%WEB_PY%" -m http.server %WEB_PORT% --bind 127.0.0.1 --directory "%WEB_DIR%"
      )
      powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(24); while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -Uri '%WEB_URL%' -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 500){ exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1" >nul 2>&1
      if errorlevel 1 (
        start "Aladdin WebUI Server (fallback)" /min "%WEB_PY%" -m http.server %WEB_PORT% --bind 127.0.0.1 --directory "%WEB_DIR%"
        powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(12); while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -Uri '%WEB_URL%' -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 500){ exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1" >nul 2>&1
      )
    )

    powershell -NoProfile -Command "try { $r=Invoke-WebRequest -Uri '%WEB_URL%' -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 500){ exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
    if errorlevel 1 (
      echo WARNING: WebUI server on port %WEB_PORT% is still starting.
      echo Waiting a bit longer...
      timeout /t 3 /nobreak >nul
      powershell -NoProfile -Command "try { $r=Invoke-WebRequest -Uri '%WEB_URL%' -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 500){ exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
      if errorlevel 1 (
        echo WARNING: WebUI still not ready. Opening browser to custom UI anyway - it will load when ready.
      )
    )
    start "" "%WEB_URL%?model=%MODEL_FILE%"
  ) else (
    echo WARNING: Python runtime for WebUI not found. Opening llama.cpp UI on port %ENGINE_PORT%.
    start "" "http://127.0.0.1:%ENGINE_PORT%"
  )
) else (
  start "" "http://127.0.0.1:%ENGINE_PORT%"
)

:launch_done

echo.
echo Your Local AI is now running.
echo Close this window to stop the servers.
echo.

pause