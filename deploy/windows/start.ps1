[CmdletBinding()]
param([switch]$Foreground)
. (Join-Path $PSScriptRoot 'Common.ps1')
Set-FutureRuntimeEnvironment
$backend = Get-FutureBackendRoot
$python = Get-FuturePython
$pidPath = Join-Path $PSScriptRoot 'future-backend.pid'
$backendRunning = $false
if (Test-Path -LiteralPath $pidPath) {
    $oldPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
        Write-Host "Backend already running as PID $oldPid."
        $backendRunning = $true
    } else {
        Remove-Item -LiteralPath $pidPath -Force
    }
}
$hostAddress = if ($env:APP_HOST) { $env:APP_HOST } else { '127.0.0.1' }
$port = if ($env:APP_PORT) { $env:APP_PORT } else { '8000' }
$arguments = @('-m','uvicorn','app.main:app','--host',$hostAddress,'--port',$port)
if ($Foreground) {
    Push-Location $backend
    try { & $python @arguments } finally { Pop-Location }
    exit $LASTEXITCODE
}
if (-not $backendRunning) {
    $stdout = Join-Path $PSScriptRoot 'future-backend.stdout.log'
    $stderr = Join-Path $PSScriptRoot 'future-backend.stderr.log'
    $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $backend -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath $pidPath -Value ([string]$process.Id) -Encoding ascii
    $oldPid = $process.Id
    Start-Sleep -Seconds 2
    $process.Refresh()
    if ($process.HasExited) {
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
        $details = if (Test-Path -LiteralPath $stderr) { (Get-Content -LiteralPath $stderr -Tail 40) -join "`n" } else { 'No backend error log was created.' }
        throw "Backend exited during startup with code $($process.ExitCode).`n$details"
    }
}
$frontendRoot = Join-Path (Get-FutureDeployRoot) 'frontend'
$frontendPidPath = Join-Path $PSScriptRoot 'future-frontend.pid'
$frontendRunning = $false
if (Test-Path -LiteralPath $frontendPidPath) {
    $frontendRunning = [bool](Get-Process -Id ([int](Get-Content -LiteralPath $frontendPidPath -Raw)) -ErrorAction SilentlyContinue)
}
if (-not $frontendRunning) {
    $frontendOut = Join-Path $PSScriptRoot 'future-frontend.stdout.log'
    $frontendErr = Join-Path $PSScriptRoot 'future-frontend.stderr.log'
    $frontendProcess = Start-Process -FilePath $python -ArgumentList @('-m','http.server','5173','--bind','127.0.0.1','--directory',$frontendRoot) -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath $frontendPidPath -Value ([string]$frontendProcess.Id) -Encoding ascii
}
Write-Host "Backend was launched as PID $oldPid; frontend is available at http://127.0.0.1:5173. Run health.ps1 to wait for verified readiness (a first ML-library import can take several minutes)."
