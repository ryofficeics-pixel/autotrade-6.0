@echo off
setlocal
cd /d "%~dp0\.."
powershell -NoProfile -Command "try { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/emergency-stop' -ContentType 'application/json' -Body '{}' | Out-Null; Start-Sleep -Seconds 2; Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/system/shutdown' -ContentType 'application/json' -Body '{}' | Out-Null } catch { Write-Error $_; exit 1 }"
powershell -NoProfile -Command "if (Test-Path 'user_data\freqtrade.pid') { $id=[int](Get-Content 'user_data\freqtrade.pid'); $p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $id) -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -like '*freqtrade*') { Stop-Process -Id $id; Wait-Process -Id $id -Timeout 10 -ErrorAction SilentlyContinue } }"
echo Paper trader and supervisor stop requested; logs and databases preserved.
