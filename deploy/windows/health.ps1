[CmdletBinding()]
param([ValidateRange(1,300)][int]$TimeoutSeconds = 180)
. (Join-Path $PSScriptRoot 'Common.ps1')
Import-FutureNonSecretConfig
$port = if ($env:APP_PORT) { $env:APP_PORT } else { '8000' }
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
$lastError = 'readiness endpoint returned a non-ready response'
do {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$port/ready" -TimeoutSec 5
        if ($response.status -eq 'ready') {
            $frontend = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/' -TimeoutSec 5 -UseBasicParsing
            if ($frontend.StatusCode -eq 200) { Write-Host "Backend ready on port $port; frontend ready on port 5173."; exit 0 }
        }
    } catch { $lastError = $_.Exception.Message }
    Start-Sleep -Seconds 2
} while ([DateTime]::UtcNow -lt $deadline)
$pidPath = Join-Path $PSScriptRoot 'future-backend.pid'
$processState = 'backend PID file is absent'
if (Test-Path -LiteralPath $pidPath) {
    $backendPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $processState = if (Get-Process -Id $backendPid -ErrorAction SilentlyContinue) { "backend process $backendPid is still running" } else { "backend process $backendPid has exited" }
}
$stderr = Join-Path $PSScriptRoot 'future-backend.stderr.log'
$details = if (Test-Path -LiteralPath $stderr) { (Get-Content -LiteralPath $stderr -Tail 40) -join "`n" } else { 'No backend error log was created.' }
throw "Backend did not become ready within $TimeoutSeconds seconds; $processState. Last request error: $lastError`nBackend error log tail:`n$details"
