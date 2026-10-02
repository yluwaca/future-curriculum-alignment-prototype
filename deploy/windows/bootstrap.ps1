[CmdletBinding()]
param(
    [switch]$SkipPythonInstall,
    [switch]$InstallPostgreSQL,
    [switch]$SkipDependencies
)
. (Join-Path $PSScriptRoot 'Common.ps1')

function Get-Python312 {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3.12 -c "import struct,sys; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8"
        if ($LASTEXITCODE -eq 0) { return @($launcher.Source, '-3.12') }
    }
    $candidates = @(
        (Join-Path $env:LocalAppData 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python312\python.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            & $candidate -c "import struct,sys; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8"
            if ($LASTEXITCODE -eq 0) { return @($candidate) }
        }
    }
    return $null
}

$pythonInvocation = @(Get-Python312)
if (-not $pythonInvocation) {
    if ($SkipPythonInstall) { throw 'Supported 64-bit Python 3.12 was not found and -SkipPythonInstall was specified.' }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { throw 'Python 3.12 is absent and winget is unavailable. Install official 64-bit Python 3.12, then rerun bootstrap.' }
    Write-Host 'Python 3.12 (64-bit) is absent; installing it with winget...'
    & $winget.Source install --id Python.Python.3.12 --exact --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw 'Automatic Python 3.12 installation did not complete successfully.' }
    $pythonInvocation = @(Get-Python312)
    if (-not $pythonInvocation) { throw 'Python installed but could not be found in this session. Reopen PowerShell and rerun bootstrap.ps1.' }
}
$pythonExe = $pythonInvocation[0]
$pythonPrefix = @($pythonInvocation | Select-Object -Skip 1)
$version = & $pythonExe @pythonPrefix -c "import platform; print(platform.python_version() + ' ' + platform.machine())"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 validation failed.' }
Write-Host "Python $version detected."

function Get-PostgreSQL16Psql {
    $expected = Join-Path $env:ProgramFiles 'PostgreSQL\16\bin\psql.exe'
    if (Test-Path -LiteralPath $expected) { return $expected }
    $candidate = Get-Command psql -ErrorAction SilentlyContinue
    if ($candidate) {
        $reported = & $candidate.Source --version
        if ($LASTEXITCODE -eq 0 -and $reported -match 'PostgreSQL\) 16\.') { return $candidate.Source }
    }
    return $null
}

$psqlPath = Get-PostgreSQL16Psql
if ($InstallPostgreSQL -and -not $psqlPath) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { throw 'winget is unavailable; install PostgreSQL 16 using its official Windows installer.' }
    Write-Host 'PostgreSQL 16 is absent; installing it with winget...'
    & $winget.Source install --id PostgreSQL.PostgreSQL.16 --exact --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL installation did not complete successfully.' }
    $psqlPath = Get-PostgreSQL16Psql
}

if (-not $psqlPath) { throw 'PostgreSQL 16 psql was not found. Rerun with -InstallPostgreSQL or install PostgreSQL 16.' }
$postgresBin = Split-Path -Parent $psqlPath
if (($env:Path -split [IO.Path]::PathSeparator) -notcontains $postgresBin) {
    $env:Path = $postgresBin + [IO.Path]::PathSeparator + $env:Path
}
$psqlVersion = & $psqlPath --version
if ($LASTEXITCODE -ne 0 -or $psqlVersion -notmatch 'PostgreSQL\) 16\.') { throw "Unexpected PostgreSQL client: $psqlVersion" }
Write-Host "$psqlVersion detected at $psqlPath."

$vectorControl = Join-Path $env:ProgramFiles 'PostgreSQL\16\share\extension\vector.control'
if (-not (Test-Path -LiteralPath $vectorControl)) {
    Write-Host 'The PostgreSQL pgvector server extension is absent; installing pinned pgvector from its official source.'
    & (Join-Path $PSScriptRoot 'install-pgvector.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'pgvector server-extension installation failed.' }
}

$backend = Get-FutureBackendRoot
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $pythonExe @pythonPrefix -m venv (Join-Path $backend '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
}
if (-not $SkipDependencies) {
    $requirements = Join-Path $backend 'requirements.lock'
    if (-not (Test-Path -LiteralPath $requirements)) {
        throw 'backend/requirements.lock is required for a reproducible install; an unpinned requirements.txt is not accepted.'
    }
    & $venvPython -m pip install --disable-pip-version-check --requirement $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed.' }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Installed dependency consistency check failed.' }
}
Write-Host 'Bootstrap checks completed. Run configure.ps1, provision-database.ps1, database.ps1, and migrate.ps1 next.'
