[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'Common.ps1')
Set-FutureRuntimeEnvironment
$backend = Get-FutureBackendRoot
$python = Get-FuturePython
Push-Location $backend
try {
    & $python -m alembic -c (Join-Path $backend 'alembic.ini') upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Alembic migration failed.' }
    & $python -m alembic -c (Join-Path $backend 'alembic.ini') current
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify the current migration revision.' }
} finally { Pop-Location }
