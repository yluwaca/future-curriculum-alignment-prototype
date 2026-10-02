[CmdletBinding()]
param()
$pidPath = Join-Path $PSScriptRoot 'future-backend.pid'
if (Test-Path -LiteralPath $pidPath) {
    $backendPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $process = Get-Process -Id $backendPid -ErrorAction SilentlyContinue
    if ($process) { Stop-Process -Id $backendPid; $process.WaitForExit(10000) }
    Remove-Item -LiteralPath $pidPath -Force
}
$frontendPidPath = Join-Path $PSScriptRoot 'future-frontend.pid'
if (Test-Path -LiteralPath $frontendPidPath) {
    $frontendPid = [int](Get-Content -LiteralPath $frontendPidPath -Raw)
    $frontendProcess = Get-Process -Id $frontendPid -ErrorAction SilentlyContinue
    if ($frontendProcess) { Stop-Process -Id $frontendPid; $frontendProcess.WaitForExit(10000) }
    Remove-Item -LiteralPath $frontendPidPath -Force
}
Write-Host 'Backend and frontend stopped.'
