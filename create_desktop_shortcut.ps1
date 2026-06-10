$ErrorActionPreference = "Stop"

$Root = (Resolve-Path -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$Launcher = Join-Path $Root "start_pdd_publisher.ps1"
$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutName = (-join ([char[]](0x62FC, 0x591A, 0x591A, 0x81EA, 0x52A8, 0x4E0A, 0x67B6))) + ".lnk"
$ShortcutPath = Join-Path $Desktop $ShortcutName
$TempShortcutPath = Join-Path $Desktop "pdd-auto-listing.lnk"

if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "Cannot find launcher: $Launcher"
}

if (Test-Path -LiteralPath $TempShortcutPath) {
    Remove-Item -Force -LiteralPath $TempShortcutPath
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($TempShortcutPath)
$Shortcut.TargetPath = $PowerShell
$Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Launcher`""
$Shortcut.WorkingDirectory = $Root
$Shortcut.Description = "Start PDD auto listing workbench"
$Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
$Shortcut.Save()

Move-Item -Force -LiteralPath $TempShortcutPath -Destination $ShortcutPath
Write-Host "Desktop shortcut created: $ShortcutPath"
