[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'Common.ps1')
Set-FutureRuntimeEnvironment
$python = Get-FuturePython
$verificationModule = Join-Path $PSScriptRoot 'verify_database.py'
if (-not (Test-Path -LiteralPath $verificationModule)) { throw 'Missing database verification module.' }
& $python $verificationModule
if ($LASTEXITCODE -ne 0) {
    throw 'Database/pgvector verification failed. Install a pgvector build matching PostgreSQL 16, then retry. See the Windows guide.'
}
