<#
.SYNOPSIS
    Creates a Linux-compatible zip from the UAT folder.
.DESCRIPTION
    Delegates to create_zip.py which uses Python's zipfile module.
    PowerShell's Compress-Archive uses backslashes which break on Linux.
.USAGE
    .\create-uat-zip.ps1
#>

$ErrorActionPreference = "Stop"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PY_SCRIPT = Join-Path $SCRIPT_DIR "create_zip.py"

Write-Host "=== Creating Linux-compatible zip ===" -ForegroundColor Cyan

# Find Python
$python = $null
foreach ($dir in $env:PATH.Split(';')) {
    $p = Join-Path $dir "python.exe"
    if (Test-Path $p) { $python = $p; break }
}
if (-not $python) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    Write-Host "ERROR: Python not found in PATH" -ForegroundColor Red
    exit 1
}

Write-Host "Python: $python"
& $python $PY_SCRIPT
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: zip creation failed" -ForegroundColor Red
    exit 1
}

Write-Host "`nNext: Copy to Linux and run:"
Write-Host "  cd /opt && unzip -o future-uat.zip -d /opt/future-uat"
