[CmdletBinding()]
param(
    [string]$PostgreSQLRoot = 'C:\Program Files\PostgreSQL\16',
    [string]$PgvectorVersion = '0.8.6'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$sourceSha256 = 'E93A1567219C9CE523CA16473F6C41CC80E01345B2D91CCDEE40B473B7C5DD0A'

function Receive-VerifiedDownload {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$OutFile
    )
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing
            return
        } catch {
            Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
            if ($attempt -eq 3) { throw "Download failed after three attempts: $Uri. Check VM internet/proxy access. $($_.Exception.Message)" }
            Start-Sleep -Seconds (2 * $attempt)
        }
    }
}

$controlFile = Join-Path $PostgreSQLRoot 'share\extension\vector.control'
if (Test-Path -LiteralPath $controlFile) {
    Write-Host "pgvector is already installed at $controlFile."
    exit 0
}
if (-not (Test-Path -LiteralPath (Join-Path $PostgreSQLRoot 'include\server\postgres.h'))) {
    throw "PostgreSQL server development headers are absent under $PostgreSQLRoot. Modify/reinstall PostgreSQL 16 with development files."
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) { throw 'Installing pgvector into Program Files requires an Administrator PowerShell session.' }

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) {
    Write-Host 'Installing Microsoft C++ Build Tools required by the official pgvector Windows build...'
    $buildToolsInstaller = Join-Path $env:TEMP "future-vs-buildtools-$PID.exe"
    Receive-VerifiedDownload -Uri 'https://aka.ms/vs/17/release/vs_BuildTools.exe' -OutFile $buildToolsInstaller
    $signature = Get-AuthenticodeSignature -LiteralPath $buildToolsInstaller
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft') {
        throw "Microsoft Build Tools installer signature validation failed: $($signature.Status)"
    }
    try {
        $install = Start-Process -FilePath $buildToolsInstaller -ArgumentList '--quiet','--wait','--norestart','--add','Microsoft.VisualStudio.Workload.VCTools','--includeRecommended' -Wait -PassThru
        if ($install.ExitCode -notin @(0, 3010)) { throw "Visual Studio C++ Build Tools installation failed with exit code $($install.ExitCode)." }
    } finally {
        Remove-Item -LiteralPath $buildToolsInstaller -Force -ErrorAction SilentlyContinue
    }
}
if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Visual Studio locator was not found after Build Tools installation.' }
$vsRoot = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsRoot) { throw 'The Visual Studio x64 C++ toolchain is not installed.' }
$vsDevCmd = Join-Path $vsRoot 'Common7\Tools\VsDevCmd.bat'

$archive = Join-Path $env:TEMP "future-pgvector-$PgvectorVersion-$PID.zip"
$extractRoot = Join-Path $env:TEMP "future-pgvector-source-$PID"
$workRoot = Join-Path $extractRoot "pgvector-$PgvectorVersion"
Receive-VerifiedDownload -Uri "https://github.com/pgvector/pgvector/archive/refs/tags/v$PgvectorVersion.zip" -OutFile $archive
$actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
if ($actualSha256 -ne $sourceSha256) {
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    throw "pgvector source checksum mismatch. Expected $sourceSha256 but received $actualSha256."
}
if (Test-Path -LiteralPath $extractRoot) { Remove-Item -LiteralPath $extractRoot -Recurse -Force }
Expand-Archive -LiteralPath $archive -DestinationPath $extractRoot
Remove-Item -LiteralPath $archive -Force
if (-not (Test-Path -LiteralPath (Join-Path $workRoot 'Makefile.win'))) { throw 'Verified pgvector archive did not contain the expected Windows build file.' }

$commandFile = Join-Path $env:TEMP "future-build-pgvector-$PID.cmd"
try {
    @(
        '@echo off',
        "call `"$vsDevCmd`" -arch=amd64 -host_arch=amd64",
        'if errorlevel 1 exit /b %errorlevel%',
        "set `"PGROOT=$PostgreSQLRoot`"",
        "cd /d `"$workRoot`"",
        'nmake /F Makefile.win',
        'if errorlevel 1 exit /b %errorlevel%',
        'nmake /F Makefile.win install'
    ) | Set-Content -LiteralPath $commandFile -Encoding Ascii
    & cmd.exe /d /c $commandFile
    if ($LASTEXITCODE -ne 0) { throw 'Official pgvector source build/install failed.' }
} finally {
    Remove-Item -LiteralPath $commandFile -Force -ErrorAction SilentlyContinue
}
if (-not (Test-Path -LiteralPath $controlFile)) { throw 'Build completed but vector.control is still absent.' }
Write-Host "Installed pgvector $PgvectorVersion from the SHA-256-verified official source archive for PostgreSQL 16."
