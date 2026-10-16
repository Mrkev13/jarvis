# MRK-57: protected secret files for off-machine backups (restic -> Backblaze B2). Run elevated.
#   -Mode Prepare  : create the folder + files with an ACL of SYSTEM + Administrators only (inheritance off).
#                    b2.env gets a commented template; -GeneratePassword writes a random restic repository password
#                    straight into restic-password.txt (never printed). Existing files are never overwritten.
#   -Mode Check    : verify presence, ACL and that b2.env is filled - prints only names/booleans, never values.
# Fill b2.env yourself in an elevated editor (notepad). Never paste these values into chat, Linear, git or logs.
[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Check')][string]$Mode = 'Check',
    [string]$Directory = (Join-Path $env:ProgramData 'StandaHub\offsite'),
    [switch]$GeneratePassword
)
$ErrorActionPreference = 'Stop'

function Set-ProtectedAcl([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)   # no inheritance; drop inherited Users/Authenticated Users
    # Owner = Administrators: a pre-existing file owned by a standard user would otherwise let that user re-grant itself.
    $acl.SetOwner((New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRule($rule) }
    $isDir = (Get-Item -LiteralPath $Path).PSIsContainer
    $inherit = if ($isDir) { 'ContainerInherit,ObjectInherit' } else { 'None' }
    foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {   # SYSTEM, BUILTIN\Administrators (locale independent)
        $identity = (New-Object System.Security.Principal.SecurityIdentifier($sid)).Translate([System.Security.Principal.NTAccount])
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', $inherit, 'None', 'Allow')))
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Test-ProtectedAcl([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    $sids = @($acl.Access | ForEach-Object {
        try { $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { 'unknown' } })
    $owner = try { (New-Object System.Security.Principal.NTAccount($acl.Owner)).Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { 'unknown' }
    return $acl.AreAccessRulesProtected -and ($owner -in @('S-1-5-18', 'S-1-5-32-544')) -and
        -not ($sids | Where-Object { $_ -notin @('S-1-5-18', 'S-1-5-32-544') })
}

$template = @'
# Standa Hub off-machine backup (MRK-57). Filled locally by the owner; never commit, paste or log these values.
# Repository: Backblaze B2 through its S3-compatible API (restic recommends S3 over the native b2 backend).
#   RESTIC_REPOSITORY=s3:https://s3.<region>.backblazeb2.com/<bucket-name>/standa-hub
# Upload key = bucket-restricted application key (keyID / applicationKey), see docs/offsite-backups.md.
RESTIC_REPOSITORY=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
'@

try {
    $b2 = Join-Path $Directory 'b2.env'
    $password = Join-Path $Directory 'restic-password.txt'
    if ($Mode -eq 'Prepare') {
        if (-not (Test-Path -LiteralPath $Directory)) { New-Item -ItemType Directory -Path $Directory -Force | Out-Null }
        Set-ProtectedAcl $Directory
        if (-not (Test-Path -LiteralPath $b2)) {
            [System.IO.File]::WriteAllText($b2, $template, (New-Object System.Text.UTF8Encoding($false)))
        }
        if (-not (Test-Path -LiteralPath $password)) {
            if ($GeneratePassword) {
                $bytes = New-Object byte[] 32
                [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
                $secret = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
                [System.IO.File]::WriteAllText($password, $secret, (New-Object System.Text.UTF8Encoding($false)))
                $secret = $null
            } else {
                [System.IO.File]::WriteAllText($password, '', (New-Object System.Text.UTF8Encoding($false)))
            }
        }
        foreach ($file in @($b2, $password)) { Set-ProtectedAcl $file }
    }

    $state = [ordered]@{
        directory_protected = (Test-Path -LiteralPath $Directory) -and (Test-ProtectedAcl $Directory)
        b2_env_present      = Test-Path -LiteralPath $b2
        password_present    = Test-Path -LiteralPath $password
    }
    if ($state.b2_env_present) {
        $values = @{}
        foreach ($line in [System.IO.File]::ReadAllLines($b2)) {
            if ($line -match '^\s*(RESTIC_REPOSITORY|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY)\s*=\s*(.*)$') { $values[$Matches[1]] = $Matches[2].Trim() }
        }
        $state.b2_env_protected = Test-ProtectedAcl $b2
        $state.repository_is_s3_https = [bool]($values['RESTIC_REPOSITORY'] -match '^s3:https://')
        $state.key_id_filled = [bool]$values['AWS_ACCESS_KEY_ID']
        $state.application_key_filled = [bool]$values['AWS_SECRET_ACCESS_KEY']
        $values = $null
    }
    if ($state.password_present) {
        $state.password_protected = Test-ProtectedAcl $password
        $state.password_filled = ((Get-Item -LiteralPath $password).Length -ge 20)
    }
    foreach ($key in $state.Keys) { Write-Output ("{0}: {1}" -f $key, $state[$key]) }
    $ready = -not ($state.Values | Where-Object { $_ -eq $false })
    Write-Output ("ready: {0}" -f $ready)
    if ($Mode -eq 'Check' -and -not $ready) { exit 2 }
    exit 0
} catch {
    [Console]::Error.WriteLine('Off-site secrets: ' + $_.Exception.GetType().Name + ' (run elevated; no values printed)')
    exit 1
}
