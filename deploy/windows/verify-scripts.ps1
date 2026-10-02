[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$required = @('Common.ps1','bootstrap.ps1','install-pgvector.ps1','configure.ps1','provision-database.ps1','database.ps1','migrate.ps1','create-admin.ps1','start.ps1','health.ps1','stop.ps1')
foreach ($name in $required) {
    $path = Join-Path $PSScriptRoot $name
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing Windows deployment script: $name" }
    # Get-Command loads command metadata and therefore validates script syntax
    # without executing the deployment action. It also works under constrained
    # language policies commonly applied to examiner workstations.
    Get-Command -Name $path -ErrorAction Stop | Out-Null
}
$databaseVerifier = Join-Path $PSScriptRoot 'verify_database.py'
if (-not (Test-Path -LiteralPath $databaseVerifier)) { throw 'Missing Windows database verification module: verify_database.py' }
$databaseVerifierText = Get-Content -LiteralPath $databaseVerifier -Raw
if (-not $databaseVerifierText.Contains("vector_dims('[1,2,3]'::vector)")) {
    throw 'The database verifier does not exercise a real pgvector operation.'
}
$allText = ($required | ForEach-Object { Get-Content -LiteralPath (Join-Path $PSScriptRoot $_) -Raw }) -join "`n"
$allTextLower = $allText.ToLowerInvariant()
foreach ($unsafe in @('postgresql+psycopg2://future:future@','SECRET_KEY=changeme','POSTGRES_PASSWORD=postgres')) {
    if ($allText.Contains($unsafe)) { throw "Unsafe embedded credential marker found: $unsafe" }
}
if (-not $allTextLower.Contains('create extension if not exists vector')) { throw 'Idempotent pgvector setup is absent.' }
if (-not $allText.Contains('alembic') -or -not $allText.Contains('upgrade') -or -not $allText.Contains('head')) { throw 'Alembic head migration contract is absent.' }
if (-not $allText.Contains('Python.Python.3.12') -or -not $allText.Contains('Get-Python312')) {
    throw 'Automatic Python 3.12 detection/installation contract is absent.'
}
if (-not $allText.Contains('Get-PostgreSQL16Psql') -or -not $allText.Contains('$InstallPostgreSQL -and -not $psqlPath')) {
    throw 'Idempotent PostgreSQL 16 detection-before-install contract is absent.'
}
$backendRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\backend')).Path
$migrationEnvironment = Join-Path $backendRoot 'migrations\env.py'
$migrationText = Get-Content -LiteralPath $migrationEnvironment -Raw
if (-not $migrationText.Contains('escape_for_alembic(database_url)')) {
    throw 'Alembic URL interpolation escaping contract is absent.'
}
$bootstrapText = Get-Content -LiteralPath (Join-Path $backendRoot 'app\core\bootstrap.py') -Raw
if (-not $bootstrapText.Contains('admin.tenant_id = default_tenant.tenant_id') -or -not $bootstrapText.Contains('Tenant.tenant_key == "cput"')) {
    throw 'Bootstrap admin is not bound to the active institutional tenant.'
}
$adminScriptText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'create-admin.ps1') -Raw
if (-not $adminScriptText.Contains('Push-Location $backend') -or -not $adminScriptText.Contains('Pop-Location')) {
    throw 'Admin bootstrap does not establish and restore the backend import context.'
}
$configureScriptText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'configure.ps1') -Raw
if (-not $configureScriptText.Contains('ConvertTo-Json -InputObject @($CorsOrigins) -Compress') -or -not $configureScriptText.Contains('http://127.0.0.1:5173')) {
    throw 'Windows CORS configuration is not serialized to the native frontend JSON-array contract.'
}
$startScriptText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'start.ps1') -Raw
$healthScriptText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'health.ps1') -Raw
if (-not $startScriptText.Contains('$process.HasExited') -or -not $healthScriptText.Contains('Backend error log tail')) {
    throw 'Windows startup/readiness diagnostics do not expose early backend failures.'
}
if (-not $healthScriptText.Contains('[int]$TimeoutSeconds = 180')) {
    throw 'Windows readiness timeout does not accommodate a bounded cold ML-library start.'
}
$smokeWrapper = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\smoke\run-smoke.ps1') -Raw
if (-not $smokeWrapper.Contains('backend\.venv\Scripts\python.exe') -or -not $smokeWrapper.Contains("Read-Host 'Local demo password' -AsSecureString")) {
    throw 'Windows smoke wrapper does not use the locked runtime and secure interactive credentials.'
}
if (-not $allText.Contains('pgvector/archive/refs/tags') -or -not $allText.Contains("PgvectorVersion = '0.8.6'") -or -not $allText.Contains('E93A1567219C9CE523CA16473F6C41CC80E01345B2D91CCDEE40B473B7C5DD0A')) {
    throw 'Pinned and checksummed official pgvector source-install contract is absent.'
}
Write-Host 'Windows deployment script contract verification passed.'
