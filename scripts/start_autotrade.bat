@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (echo Run scripts\setup_windows.bat first. & exit /b 1)
if not exist ".env" (echo Missing .env. Run scripts\setup_windows.bat. & exit /b 1)
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"
".venv\Scripts\python.exe" autotrade.py validate || exit /b 1

powershell -NoProfile -Command "$c=Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue; if (-not $c) { exit 0 }; $p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $c[0].OwningProcess); if ($p.CommandLine -notlike '*autotrade.py*') { exit 2 }; try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8765/' -TimeoutSec 5 | Out-Null; exit 1 } catch { Stop-Process -Id $c[0].OwningProcess -Force; Start-Sleep -Seconds 1; exit 0 }"
if errorlevel 2 (echo Port 8765 is used by another program. & pause & exit /b 1)
if errorlevel 1 (
  echo Dashboard is already running.
) else (
  powershell -NoProfile -Command "$p=Start-Process -FilePath '.venv\Scripts\python.exe' -ArgumentList @('autotrade.py','serve') -WorkingDirectory '%CD%' -WindowStyle Hidden -PassThru; $p.Id | Set-Content -LiteralPath 'user_data\autotrade.pid'"
  powershell -NoProfile -Command "Start-Sleep -Seconds 2"
)

powershell -NoProfile -Command "$c=Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue; if (-not $c) { exit 0 }; $p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $c[0].OwningProcess); if ($p.CommandLine -like '*freqtrade*') { exit 1 }; exit 2"
if errorlevel 2 (echo Port 8080 is used by another program. & pause & exit /b 1)
if errorlevel 1 (
  echo Paper trader is already running.
) else (
  powershell -NoProfile -Command "$p=Start-Process -FilePath '.venv\Scripts\python.exe' -ArgumentList @('-m','freqtrade','trade','--config','user_data/config.json','--strategy','AutotradeBaseline','--logfile','user_data/logs/freqtrade.log') -WorkingDirectory '%CD%' -WindowStyle Hidden -PassThru; $p.Id | Set-Content -LiteralPath 'user_data\freqtrade.pid'"
  echo Paper trader is loading Gate.io markets. This can take up to 3 minutes.
)
start "" "http://127.0.0.1:8765"
powershell -NoProfile -Command "$end=(Get-Date).AddMinutes(3); do { if (Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue) { exit 0 }; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $end); exit 1"
if errorlevel 1 (
  echo ERROR: Paper trader did not start. Recent log:
  powershell -NoProfile -Command "Get-Content 'user_data\logs\freqtrade.log' -Tail 15"
  pause
  exit /b 1
)
powershell -NoProfile -Command "$end=(Get-Date).AddMinutes(1); do { try { $s=Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/status' -TimeoutSec 10; if ($s.risk_reason -notlike '*requires explicit resume*') { exit 0 }; if ($s.data_health -in @('DATA_HEALTHY','DATA_DELAYED')) { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/trading/resume' -ContentType 'application/json' -Body '{}' -TimeoutSec 10 | Out-Null; exit 0 } } catch {}; Start-Sleep -Seconds 3 } while ((Get-Date) -lt $end); exit 1"
if errorlevel 1 (
  echo Services started, but the safety gate refused to resume trading. Check the dashboard.
  pause
  exit /b 1
)
echo Autotrade 6.0 PAPER services started. Dashboard: http://127.0.0.1:8765
