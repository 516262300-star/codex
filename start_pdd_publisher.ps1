$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Url = "http://127.0.0.1:8765/"
$HealthUrl = "http://127.0.0.1:8765/api/plugin-progress"

function Test-Workbench {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (Test-Workbench) {
    Start-Process $Url
    exit 0
}

$Command = "cd /d `"$Root`" && python desktop_tool.py"
Start-Process -FilePath "cmd.exe" -ArgumentList @("/k", $Command) -WorkingDirectory $Root

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Workbench) {
        Start-Process $Url
        exit 0
    }
}

Write-Host "PDD workbench did not respond after 30 seconds."
Write-Host "Please check the command window for Python errors."
Read-Host "Press Enter to close"
