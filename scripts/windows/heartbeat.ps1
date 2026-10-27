# MRK-90: external heartbeat for the Hub host (healthchecks.io-style check). Run elevated.
# The Hub cannot report its own outage (it sends the Web Push), so the host pings an outside service every 5 minutes;
# missing pings (host off, asleep, offline) or an explicit /fail ping (Hub down) make that service alert the phone.
#   -Mode Prepare  : protected folder + empty ping-url.txt (SYSTEM + Administrators only). Fill it in an elevated notepad.
#   -Mode Check    : presence/ACL/https only - prints names and booleans, never the URL.
#   -Mode Register : scheduled task StandaHub-Heartbeat (SYSTEM, every 5 minutes) running -Mode Ping. Not started.
#   -Mode Ping     : loopback /health + /login probe; pings <url> when the Hub serves, <url>/fail when it does not.
# The ping URL is a secret (anyone holding it can fake "up"). Never paste it into chat, Linear, git, task arguments or logs.
[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Check', 'Register', 'Ping')][string]$Mode = 'Check',
    [string]$Directory = (Join-Path $env:ProgramData 'StandaHub\heartbeat'),
    [string]$BackendUrl = 'http://127.0.0.1:8000',
    [string]$FrontendUrl = 'http://127.0.0.1:3000'
)
$ErrorActionPreference = 'Stop'
$TaskName = 'StandaHub-Heartbeat'

# Same ACL policy as offsite-secrets.ps1: SYSTEM + BUILTIN\Administrators only, owner Administrators, no inheritance.
function Set-ProtectedAcl([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)
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

function Read-PingUrl([string]$File) {
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) { return $null }
    $url = ([System.IO.File]::ReadAllText($File)).Trim()
    if ($url -notmatch '^https://[^\s/]+/\S+$') { return $null }
    return $url.TrimEnd('/')
}

# True only when the backend answers healthy/degraded and the frontend serves /login. Degraded (e.g. a stale backup)
# is still "up": the Hub reports those itself via push; this check is about the Hub being reachable at all.
function Test-HubServes {
    try {
        $health = Invoke-RestMethod -Uri ($BackendUrl.TrimEnd('/') + '/health') -TimeoutSec 10 -Method Get
        if ($health.status -notin @('healthy', 'degraded')) { return $false }
        $page = Invoke-WebRequest -UseBasicParsing -Uri ($FrontendUrl.TrimEnd('/') + '/login') -TimeoutSec 10
        return ($page.StatusCode -eq 200)
    } catch {
        return $false
    }
}

try {
    $file = Join-Path $Directory 'ping-url.txt'
    if ($Mode -eq 'Prepare') {
        if (-not (Test-Path -LiteralPath $Directory)) { New-Item -ItemType Directory -Path $Directory -Force | Out-Null }
        Set-ProtectedAcl $Directory
        if (-not (Test-Path -LiteralPath $file)) {
            [System.IO.File]::WriteAllText($file, '', (New-Object System.Text.UTF8Encoding($false)))
        }
        Set-ProtectedAcl $file
        Write-Output ('Prepared. Paste the ping URL into the file in an elevated notepad: notepad "{0}"' -f $file)
        exit 0
    }

    if ($Mode -eq 'Register') {
        $script = $PSCommandPath
        $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        # Time-based repetition keeps firing after reboots; no duration = indefinitely (Windows 10/11).
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5)
        # Only the script path and directory: the URL stays in the protected file, never in task arguments.
        $taskArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Mode Ping -Directory "{1}"' -f $script, $Directory
        $action = New-ScheduledTaskAction -Execute $shell -Argument $taskArgs
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
        Write-Output ('{0} registered (every 5 minutes, SYSTEM); not started.' -f $TaskName)
        exit 0
    }

    if ($Mode -eq 'Ping') {
        $url = Read-PingUrl $file
        if (-not $url) { [Console]::Error.WriteLine('Heartbeat: ping URL missing or not https; nothing sent'); exit 2 }
        $serves = Test-HubServes
        $target = if ($serves) { $url } else { $url + '/fail' }
        # Windows PowerShell 5.1 on older .NET defaults may not offer TLS 1.2, which the ping service requires.
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $sent = $false
        foreach ($attempt in 1..3) {   # short retries for a network blip; the service's grace period covers the rest
            try {
                Invoke-WebRequest -UseBasicParsing -Uri $target -TimeoutSec 10 -Method Get | Out-Null
                $sent = $true
                break
            } catch {
                if ($attempt -lt 3) { Start-Sleep -Seconds 5 }
            }
        }
        $url = $null; $target = $null
        if (-not $sent) { [Console]::Error.WriteLine('Heartbeat: ping not delivered'); exit 1 }
        Write-Output ('hub=' + $(if ($serves) { 'up' } else { 'down' }) + '; ping=sent')
        if (-not $serves) { exit 3 }
        exit 0
    }

    # Check
    $state = [ordered]@{
        directory_protected = (Test-Path -LiteralPath $Directory) -and (Test-ProtectedAcl $Directory)
        url_file_present    = Test-Path -LiteralPath $file
    }
    if ($state.url_file_present) {
        $state.url_file_protected = Test-ProtectedAcl $file
        $state.url_is_https = [bool](Read-PingUrl $file)
    }
    $state.task_registered = [bool](Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
    foreach ($key in $state.Keys) { Write-Output ("{0}: {1}" -f $key, $state[$key]) }
    $ready = -not ($state.Values | Where-Object { $_ -eq $false })
    Write-Output ("ready: {0}" -f $ready)
    if (-not $ready) { exit 2 }
    exit 0
} catch {
    [Console]::Error.WriteLine('Heartbeat: ' + $_.Exception.GetType().Name + ' (run elevated; no URL printed)')
    exit 1
}
