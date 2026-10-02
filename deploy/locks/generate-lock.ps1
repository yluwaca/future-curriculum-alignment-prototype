[CmdletBinding()]
param([string]$Python = 'py')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
& $Python -3.12 -m piptools compile --generate-hashes --resolver=backtracking `
    --output-file (Join-Path $root 'backend\requirements.windows-py312.lock') `
    (Join-Path $root 'backend\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Windows hash-lock generation failed. Install a reviewed pip-tools version first.' }
Write-Host 'Generated backend/requirements.windows-py312.lock; review and clean-room test before commit.'
