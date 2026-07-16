$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Url = "http://127.0.0.1:8765/"
$HealthUrl = "http://127.0.0.1:8765/api/plugin-progress"
$Port = 8765

function Test-Workbench {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Get-WorkbenchProcess {
    try {
        $Connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -First 1
        if ($null -eq $Connection) {
            return $null
        }

        $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($Connection.OwningProcess)" -ErrorAction Stop
        if ($ProcessInfo.CommandLine -notmatch 'desktop_tool\.py\s+--no-open') {
            return $null
        }
        return $ProcessInfo
    } catch {
        return $null
    }
}

function Get-LatestWorkbenchSourceWriteTime {
    $SourceFiles = @(
        (Join-Path $Root "desktop_tool.py"),
        (Join-Path $Root "main.py")
    )
    $SourceFiles += Get-ChildItem -LiteralPath (Join-Path $Root "skills") -Recurse -File -Filter "*.py" -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
    $SourceFiles += Get-ChildItem -LiteralPath (Join-Path $Root "templates") -Recurse -File -Filter "*.yaml" -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName

    return $SourceFiles |
        Where-Object { Test-Path -LiteralPath $_ } |
        ForEach-Object { (Get-Item -LiteralPath $_).LastWriteTime } |
        Sort-Object -Descending |
        Select-Object -First 1
}

function Stop-StaleWorkbench {
    $ProcessInfo = Get-WorkbenchProcess
    if ($null -eq $ProcessInfo) {
        return $false
    }

    $RunningProcess = Get-Process -Id $ProcessInfo.ProcessId -ErrorAction SilentlyContinue
    $LatestSourceWriteTime = Get-LatestWorkbenchSourceWriteTime
    if ($null -eq $RunningProcess -or $null -eq $LatestSourceWriteTime) {
        return $false
    }
    if ($LatestSourceWriteTime -le $RunningProcess.StartTime.AddSeconds(1)) {
        return $false
    }

    Write-Host "Detected updated workbench code. Restarting the stale background process..."
    Stop-Process -Id $RunningProcess.Id -Force
    $RunningProcess.WaitForExit(5000) | Out-Null
    return $true
}

if (Test-Workbench) {
    if (-not (Stop-StaleWorkbench)) {
        Start-Process $Url
        exit 0
    }
}

$Python = (Get-Command python -ErrorAction Stop).Source
Start-Process -FilePath $Python -ArgumentList @("desktop_tool.py", "--no-open") -WorkingDirectory $Root -WindowStyle Hidden

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Workbench) {
        Start-Process $Url
        exit 0
    }
}

Write-Host "PDD workbench did not respond after 30 seconds."
Write-Host "Please run desktop_tool.py manually to inspect Python errors."
Read-Host "Press Enter to close"
