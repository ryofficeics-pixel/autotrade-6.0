@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -Command "$ports=@{8765='*autotrade.py*';8080='*freqtrade*trade*'}; foreach($port in $ports.Keys){$c=Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue; if($c){$p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $c[0].OwningProcess); if($p.CommandLine -notlike $ports[$port]){Write-Error ('Port ' + $port + ' belongs to another program.');exit 1}}}; try{Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/emergency-stop' -ContentType 'application/json' -Body '{}' -TimeoutSec 10|Out-Null;Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/system/shutdown' -ContentType 'application/json' -Body '{}' -TimeoutSec 10|Out-Null}catch{};Start-Sleep -Seconds 3;$root=(Get-Location).Path;Get-CimInstance Win32_Process|Where-Object{$_.Name -match '^(python|pythonw|py)\.exe$' -and $_.CommandLine -like ('*'+$root+'*') -and ($_.CommandLine -like '*autotrade.py*' -or $_.CommandLine -like '*freqtrade*trade*')}|ForEach-Object{Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"
if errorlevel 1 (pause & exit /b 1)

call "%~dp0scripts\start_autotrade.bat"
