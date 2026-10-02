[CmdletBinding()]
param(
    [string]$BaseUrl = $(if ($env:PCLMAS_BASE_URL) { $env:PCLMAS_BASE_URL } else { 'http://localhost:8080' }),
    [string]$Report = ''
)
$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$deployRoot = (Resolve-Path (Join-Path $scriptRoot '..\..')).Path
$python = Join-Path $deployRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Locked backend virtual environment is absent. Run deploy\windows\bootstrap.ps1 first.' }

$temporaryUsername = -not [bool]$env:PCLMAS_SMOKE_USERNAME
$temporaryPassword = -not [bool]$env:PCLMAS_SMOKE_PASSWORD
if ($temporaryUsername) { $env:PCLMAS_SMOKE_USERNAME = Read-Host 'Local demo username' }
if ($temporaryPassword) {
    $securePassword = Read-Host 'Local demo password' -AsSecureString
    $credential = [System.Net.NetworkCredential]::new('', $securePassword)
    $env:PCLMAS_SMOKE_PASSWORD = $credential.Password
}
$arguments = @((Join-Path $scriptRoot 'run_smoke.py'), '--base-url', $BaseUrl)
if ($Report) { $arguments += @('--report', $Report) }
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Synthetic demo smoke failed with exit code $LASTEXITCODE" }
} finally {
    if ($temporaryPassword) { Remove-Item Env:PCLMAS_SMOKE_PASSWORD -ErrorAction SilentlyContinue }
    if ($temporaryUsername) { Remove-Item Env:PCLMAS_SMOKE_USERNAME -ErrorAction SilentlyContinue }
    $securePassword = $null
    $credential = $null
}
