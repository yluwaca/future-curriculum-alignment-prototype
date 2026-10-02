[CmdletBinding()]
param(
    [ValidatePattern('^[a-zA-Z0-9._-]+$')][string]$Environment = 'examiner',
    [ValidateRange(1,65535)][int]$Port = 8000,
    [string[]]$CorsOrigins = @('http://127.0.0.1:5173', 'http://localhost:5173')
)
. (Join-Path $PSScriptRoot 'Common.ps1')
foreach ($origin in $CorsOrigins) {
    $parsed = $null
    if (-not [Uri]::TryCreate($origin, [UriKind]::Absolute, [ref]$parsed) -or $parsed.Scheme -notin @('http','https')) {
        throw "CORS origin must be an absolute HTTP(S) URL: $origin"
    }
}
$corsJson = ConvertTo-Json -InputObject @($CorsOrigins) -Compress
$content = @(
    "ENVIRONMENT=$Environment"
    "APP_HOST=127.0.0.1"
    "APP_PORT=$Port"
    "CORS_ORIGINS=$corsJson"
    'DEBUG=false'
    'RELOAD=false'
    'ENABLE_BOOTSTRAP_ADMIN=false'
    'ENABLE_DOCS=true'
    'REQUIRE_HTTPS=false'
)
$path = Join-Path $PSScriptRoot 'config.env'
$content | Set-Content -LiteralPath $path -Encoding utf8
Write-Host "Wrote non-secret configuration to $path."
Write-Host 'Run provision-database.ps1 next; it sets the database URL and generates the application signing key in this PowerShell process.'
