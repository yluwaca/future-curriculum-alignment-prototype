[CmdletBinding()]
param(
    [string]$Username = 'admin',
    [string]$Email = 'admin@future.local'
)
. (Join-Path $PSScriptRoot 'Common.ps1')
Set-FutureRuntimeEnvironment
$secure = Read-Host 'Local examiner admin password' -AsSecureString
$credential = [System.Net.NetworkCredential]::new('', $secure)
$plain = $credential.Password
if ($plain.Length -lt 12) { throw 'Password must contain at least 12 characters.' }
$env:ENABLE_BOOTSTRAP_ADMIN = 'true'
$env:BOOTSTRAP_ADMIN_USERNAME = $Username
$env:BOOTSTRAP_ADMIN_EMAIL = $Email
$env:BOOTSTRAP_ADMIN_PASSWORD = $plain
$backend = Get-FutureBackendRoot
Push-Location $backend
try {
    Invoke-FuturePython -Arguments @('-c', "from app.core.bootstrap import ensure_admin_user; from app.db.session import SessionLocal; db=SessionLocal(); ensure_admin_user(db); db.close(); print('Local examiner admin created or repaired')")
} finally {
    Pop-Location
    Remove-Item Env:BOOTSTRAP_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:ENABLE_BOOTSTRAP_ADMIN -ErrorAction SilentlyContinue
    Remove-Item Env:BOOTSTRAP_ADMIN_USERNAME -ErrorAction SilentlyContinue
    Remove-Item Env:BOOTSTRAP_ADMIN_EMAIL -ErrorAction SilentlyContinue
    $plain = $null
}
