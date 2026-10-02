Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-FutureDeployRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}

function Get-FutureBackendRoot {
    $path = Join-Path (Get-FutureDeployRoot) 'backend'
    if (-not (Test-Path -LiteralPath (Join-Path $path 'app\main.py'))) {
        throw "Portable backend not found at $path. Copy/build the Deploy package before running this command."
    }
    return $path
}

function Get-FuturePython {
    $python = Join-Path (Get-FutureBackendRoot) '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Virtual environment is absent. Run bootstrap.ps1 first."
    }
    return $python
}

function Import-FutureNonSecretConfig {
    $configPath = Join-Path $PSScriptRoot 'config.env'
    if (-not (Test-Path -LiteralPath $configPath)) { return }
    foreach ($line in Get-Content -LiteralPath $configPath) {
        if ($line -match '^\s*([A-Z][A-Z0-9_]*)=(.*)$') {
            Set-Item -Path ("Env:" + $Matches[1]) -Value $Matches[2]
        }
    }
    if ($env:CORS_ORIGINS) {
        try { $parsedOrigins = @($env:CORS_ORIGINS | ConvertFrom-Json -ErrorAction Stop) }
        catch { throw 'CORS_ORIGINS in config.env must be a JSON array. Rerun configure.ps1.' }
        if ($parsedOrigins.Count -eq 0) { throw 'CORS_ORIGINS must contain at least one origin. Rerun configure.ps1.' }
    }
}

function Set-FutureRuntimeEnvironment {
    Import-FutureNonSecretConfig
    if (-not $env:FUTURE_DATABASE_URL) {
        throw 'FUTURE_DATABASE_URL is required in this PowerShell session. It must be a PostgreSQL SQLAlchemy URL.'
    }
    if (-not $env:FUTURE_SECRET_KEY -or $env:FUTURE_SECRET_KEY.Length -lt 32) {
        throw 'FUTURE_SECRET_KEY (at least 32 characters) is required in this PowerShell session.'
    }
    $env:DATABASE_URL = $env:FUTURE_DATABASE_URL
    $env:SECRET_KEY = $env:FUTURE_SECRET_KEY
}

function Invoke-FuturePython {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $python = Get-FuturePython
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed with exit code $LASTEXITCODE." }
}
