[CmdletBinding()]
param(
    [string]$DatabaseName = 'future',
    [string]$ApplicationRole = 'future',
    [string]$AdministratorRole = 'postgres',
    [string]$HostName = '127.0.0.1',
    [ValidateRange(1,65535)][int]$Port = 5432
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

foreach ($value in @($DatabaseName, $ApplicationRole, $AdministratorRole)) {
    if ($value -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
        throw "Database and role names may contain only letters, digits and underscores and may not start with a digit: $value"
    }
}

$psql = Get-Command psql -ErrorAction SilentlyContinue
if (-not $psql) { throw 'psql is not on PATH. Install PostgreSQL 16 command-line tools and reopen PowerShell.' }

$adminSecure = Read-Host "Password for PostgreSQL administrator '$AdministratorRole'" -AsSecureString
$appSecure = Read-Host "New password for application role '$ApplicationRole'" -AsSecureString
$appConfirm = Read-Host 'Repeat the application-role password' -AsSecureString

$adminPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminSecure)
$appPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($appSecure)
$confirmPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($appConfirm)
try {
    $adminPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($adminPtr)
    $appPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($appPtr)
    $confirmPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($confirmPtr)
    if ($appPassword -ne $confirmPassword) { throw 'Application-role passwords do not match.' }
    if ($appPassword.Length -lt 16) { throw 'Use an application-role password of at least 16 characters.' }

    $escapedPassword = $appPassword.Replace("'", "''")
    $env:PGPASSWORD = $adminPassword
    $roleSql = @"
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', '$ApplicationRole', '$escapedPassword')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$ApplicationRole') \gexec
ALTER ROLE "$ApplicationRole" WITH LOGIN PASSWORD '$escapedPassword';
SELECT format('CREATE DATABASE %I OWNER %I', '$DatabaseName', '$ApplicationRole')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$DatabaseName') \gexec
"@
    $roleSql | & $psql.Source --host $HostName --port $Port --username $AdministratorRole --dbname postgres --set ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) { throw 'Database/role provisioning failed.' }

    'CREATE EXTENSION IF NOT EXISTS vector;' | & $psql.Source --host $HostName --port $Port --username $AdministratorRole --dbname $DatabaseName --set ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) { throw 'pgvector extension creation failed. Install a PostgreSQL-16-compatible pgvector package and retry.' }

    $encodedPassword = [uri]::EscapeDataString($appPassword)
    $env:FUTURE_DATABASE_URL = "postgresql+psycopg2://$ApplicationRole`:$encodedPassword@$HostName`:$Port/$DatabaseName"
    if (-not $env:FUTURE_SECRET_KEY -or $env:FUTURE_SECRET_KEY.Length -lt 32) {
        $env:FUTURE_SECRET_KEY = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))
    }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    if ($adminPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($adminPtr) }
    if ($appPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($appPtr) }
    if ($confirmPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($confirmPtr) }
    $adminPassword = $null
    $appPassword = $null
    $confirmPassword = $null
    $escapedPassword = $null
    $encodedPassword = $null
}

Write-Host "Database '$DatabaseName', role '$ApplicationRole', and pgvector are ready."
Write-Host 'FUTURE_DATABASE_URL is set for this PowerShell process using the application-role password.'
Write-Host 'FUTURE_SECRET_KEY is set to a generated application signing key for this PowerShell process.'
Write-Host 'These values are intentionally not written to disk. Keep this PowerShell window open for the remaining commands.'
