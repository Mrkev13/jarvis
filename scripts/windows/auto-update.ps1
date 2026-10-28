# MRK-98: automatic deploy on the Windows host. Every 10 minutes the task looks at origin/main; when it moved, it runs
# update.ps1 (fresh-backup check, stop, build, migrate, start, rollback - all decided there) and reports the result.
#   -Mode Prepare  : protected folder + empty deploy-ping-url.txt (SYSTEM + Administrators only). Optional alert URL.
#   -Mode Check    : task, alert URL file (presence/ACL/https), pause and last result - names, booleans, short SHAs.
#   -Mode Register : scheduled task StandaHub-AutoUpdate, every 10 minutes, as the CURRENT user with highest privileges
#                    (git fetch then uses that user's GitHub login). Asks for the Windows password once; Windows stores
#                    it for the task, this script never prints or saves it. Not started.
#   -Mode Run      : one look at origin/main and, if it moved, one update.ps1 run (what the task executes).
#   -Mode Pause / -Mode Resume : stop or allow automatic deploys (manual update.ps1 still works).
# Safety:
#   - A commit whose update failed (update.ps1 exit 1 = rolled back, 3 = failed after migration) is NEVER retried
#     automatically; the next automatic attempt is a newer commit on origin/main (or a manual update.ps1). Otherwise a
#     broken commit would stop, rebuild and roll back the Hub every 10 minutes.
#   - update.ps1 exit 2 (preconditions, e.g. backup not fresh yet, local changes) changed nothing: retried next run.
#   - One run at a time (lock file). One log per deploy attempt in <Directory>\logs (last 30 kept), never env values.
# Alert (optional): deploy-ping-url.txt = a healthchecks.io check "Hub deploy" (period 10 min, grace ~30 min). Every
# finished run pings <url>, or <url>/fail while a failed commit is pending or deploys have not started for 6 hours.
# Missing pings (task disabled, password changed, git cannot fetch) make the service alert as well.
# The URL is a secret (anyone holding it can fake "ok"): never paste it into chat, Linear, git, task arguments or logs.
[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Check', 'Register', 'Run', 'Pause', 'Resume')][string]$Mode = 'Check',
    [string]$ProjectDirectory = 'C:\StandaHub',
    [string]$Directory = (Join-Path $env:ProgramData 'StandaHub\auto-update'),
    [string]$Ref = 'origin/main'
)
$ErrorActionPreference = 'Stop'
$TaskName = 'StandaHub-AutoUpdate'
$KeepLogs = 30
$NotStartedAlertRuns = 36   # 36 x 10 min = 6 h of update.ps1 refusing to start (exit 2) before alerting

function Step([string]$Text) { Write-Output ('[auto-update] ' + $Text) }

# Same ACL policy as heartbeat.ps1 / offsite-secrets.ps1: SYSTEM + BUILTIN\Administrators only, no inheritance.
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

function Send-Ping([bool]$Ok) {
    # No alert file = no alert (the log and -Mode Check still show the result). Failures to send are not fatal.
    $url = Read-PingUrl $pingFile
    if (-not $url) { return }
    $pingTarget = if ($Ok) { $url } else { $url + '/fail' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    foreach ($attempt in 1..3) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $pingTarget -TimeoutSec 10 -Method Get | Out-Null
            break
        } catch {
            if ($attempt -lt 3) { Start-Sleep -Seconds 5 }
        }
    }
    $url = $null; $pingTarget = $null
}

function Read-State([string]$Name) {
    $path = Join-Path $Directory $Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return '' }
    return ([System.IO.File]::ReadAllText($path)).Trim()
}

function Write-State([string]$Name, [string]$Value) {
    [System.IO.File]::WriteAllText((Join-Path $Directory $Name), $Value, (New-Object System.Text.UTF8Encoding($false)))
}

function Clear-State([string]$Name) { Remove-Item -LiteralPath (Join-Path $Directory $Name) -Force -ErrorAction SilentlyContinue }

function Write-Result([string]$Text) {
    Write-State 'last-result.txt' ((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') + ' ' + $Text)
    Step $Text
}

function Git-Line([string]$What, [string[]]$GitArgs) {
    # Plain git calls (no stderr redirection: Windows PowerShell 5.1 turns redirected native stderr into a terminating
    # error under $ErrorActionPreference = 'Stop'). The exit code decides. Arguments as an array, so "--quiet" is never
    # read as a PowerShell parameter.
    $out = @(& git -C $root @GitArgs)
    if ($LASTEXITCODE -ne 0) { throw ($What + ' failed (exit ' + $LASTEXITCODE + ')') }
    if ($out.Count -eq 0 -or $null -eq $out[-1]) { return '' }   # git fetch --quiet prints nothing
    return ([string]$out[-1]).Trim()
}

function Get-Revision([string]$What, [string[]]$GitArgs) {
    $sha = Git-Line $What $GitArgs
    if ($sha -notmatch '^[0-9a-f]{40}$') { throw ($What + ' returned no commit') }
    return $sha
}

function Remove-OldLogs {
    Get-ChildItem -LiteralPath $logDir -Filter '*.log' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -Skip $KeepLogs |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

try {
    $pingFile = Join-Path $Directory 'deploy-ping-url.txt'
    $logDir = Join-Path $Directory 'logs'

    if ($Mode -eq 'Prepare') {
        foreach ($dir in @($Directory, $logDir)) {
            if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        }
        Set-ProtectedAcl $Directory
        if (-not (Test-Path -LiteralPath $pingFile)) {
            [System.IO.File]::WriteAllText($pingFile, '', (New-Object System.Text.UTF8Encoding($false)))
        }
        Set-ProtectedAcl $pingFile
        Write-Output ('Prepared. Optional alert: paste the deploy check URL in an elevated notepad: notepad "{0}"' -f $pingFile)
        exit 0
    }

    if ($Mode -eq 'Register') {
        $root = (Resolve-Path -LiteralPath $ProjectDirectory).Path
        if (-not (Test-Path -LiteralPath (Join-Path $root 'scripts\windows\update.ps1') -PathType Leaf)) { throw 'Missing update.ps1' }
        if (-not (Test-Path -LiteralPath $Directory)) { throw 'Run -Mode Prepare first' }
        $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $cred = Get-Credential -UserName $user -Message 'Windows password of this account (not the PIN). The deploy task runs as you so git can use your GitHub login; Windows stores it for the task.'
        if (-not $cred) { throw 'No password entered' }
        $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 50) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        # Time-based repetition keeps firing after reboots; no duration = indefinitely (Windows 10/11).
        # First start 15 minutes in the FUTURE: a start boundary in the past plus StartWhenAvailable can make Task
        # Scheduler run the (highest-privileged) deploy right at registration, before the manual first -Mode Run.
        $firstStart = (Get-Date).AddMinutes(15)
        $trigger = New-ScheduledTaskTrigger -Once -At $firstStart -RepetitionInterval (New-TimeSpan -Minutes 10)
        # Only paths and the mode: the alert URL stays in the protected file, never in task arguments.
        $taskArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Mode Run -ProjectDirectory "{1}" -Directory "{2}"' -f $PSCommandPath, $root, $Directory
        $action = New-ScheduledTaskAction -Execute $shell -Argument $taskArgs -WorkingDirectory $root
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User $cred.UserName -Password $cred.GetNetworkCredential().Password -RunLevel Highest -Force | Out-Null
        $cred = $null
        Write-Output ('{0} registered (every 10 minutes, as {1}, highest privileges); first automatic run at {2}.' -f $TaskName, $user, $firstStart.ToString('HH:mm'))
        exit 0
    }

    if ($Mode -eq 'Pause') {
        Write-State 'paused' ((Get-Date).ToUniversalTime().ToString('o'))
        Write-Output 'Automatic deploys paused (manual update.ps1 still works). Resume: -Mode Resume'
        exit 0
    }

    if ($Mode -eq 'Resume') {
        Clear-State 'paused'
        Write-Output 'Automatic deploys resumed.'
        exit 0
    }

    if ($Mode -eq 'Run') {
        if (-not (Test-Path -LiteralPath $logDir)) { throw 'Run -Mode Prepare first' }
        # One run at a time, also against a manual -Mode Run while the task is running.
        $lock = $null
        try { $lock = [System.IO.File]::Open((Join-Path $Directory 'run.lock'), 'OpenOrCreate', 'ReadWrite', 'None') } catch {
            Step 'Another run is in progress; nothing to do.'
            exit 0
        }
        try {
            if (Read-State 'paused') {
                Step 'Paused; nothing deployed.'
                Send-Ping $true
                exit 0
            }
            $root = (Resolve-Path -LiteralPath $ProjectDirectory).Path
            # The task user is the owner of the checkout, but an explicit safe.directory for this process and its
            # children (update.ps1, git) avoids "dubious ownership" if the folder owner is SYSTEM/Administrators.
            $env:GIT_CONFIG_COUNT = '1'
            $env:GIT_CONFIG_KEY_0 = 'safe.directory'
            $env:GIT_CONFIG_VALUE_0 = $root.Replace('\', '/')
            $updateScript = Join-Path $root 'scripts\windows\update.ps1'

            Git-Line 'git fetch' @('fetch', '--quiet', 'origin') | Out-Null
            $current = Get-Revision 'git rev-parse HEAD' @('rev-parse', 'HEAD')
            $target = Get-Revision ('git rev-parse ' + $Ref) @('rev-parse', '--verify', '--quiet', ($Ref + '^{commit}'))
            $failed = Read-State 'failed-commit.txt'

            if ($target -eq $current) {
                # Up to date (also after a manual update.ps1 fixed a failed commit): nothing pending. Recorded, so
                # -Mode Check shows that the task really runs.
                Clear-State 'failed-commit.txt'
                Clear-State 'not-started-count.txt'
                Write-Result ('up to date at ' + $current.Substring(0, 7))
                Send-Ping $true
                exit 0
            }
            if ($failed -and $failed -eq $target) {
                # Never retried automatically; a newer commit or a manual update.ps1 clears this.
                Step ('Commit ' + $target.Substring(0, 7) + ' failed before; waiting for a newer commit or a manual update.ps1.')
                Send-Ping $false
                exit 0
            }

            $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
            $log = Join-Path $logDir ($stamp + '-' + $target.Substring(0, 7) + '.log')
            $errLog = $log + '.stderr'
            Step ('Deploying ' + $current.Substring(0, 7) + ' -> ' + $target.Substring(0, 7) + ' (log: ' + $log + ')')
            $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
            $updateArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -ProjectDirectory "{1}" -Ref {2}' -f $updateScript, $root, $target
            $process = Start-Process -FilePath $shell -ArgumentList $updateArgs -RedirectStandardOutput $log -RedirectStandardError $errLog -WindowStyle Hidden -PassThru
            $null = $process.Handle   # keeps ExitCode readable after WaitForExit (Windows PowerShell 5.1)
            $process.WaitForExit()
            $code = $process.ExitCode
            if (Test-Path -LiteralPath $errLog) {
                Add-Content -LiteralPath $log -Value (Get-Content -LiteralPath $errLog)
                Remove-Item -LiteralPath $errLog -Force
            }

            if ($code -eq 0) {
                Clear-State 'failed-commit.txt'
                Clear-State 'not-started-count.txt'
                Write-Result ('deployed ' + $target.Substring(0, 7))
                Send-Ping $true
            } elseif ($code -eq 2) {
                # Nothing changed (backup not fresh yet, local changes, Hub unreachable...): retried next run.
                $count = 1 + [int]('0' + (Read-State 'not-started-count.txt'))
                Write-State 'not-started-count.txt' ([string]$count)
                Write-Result ('not started for ' + $target.Substring(0, 7) + ' (attempt ' + $count + '; see log)')
                Send-Ping ($count -lt $NotStartedAlertRuns)
            } else {
                Write-State 'failed-commit.txt' $target
                Clear-State 'not-started-count.txt'
                $what = if ($code -eq 1) { 'rolled back to ' + $current.Substring(0, 7) } else { 'FAILED after migration - Hub may be partly down, see docs/operations.md' }
                Write-Result ('update to ' + $target.Substring(0, 7) + ' failed (exit ' + $code + '): ' + $what)
                Send-Ping $false
            }
            Remove-OldLogs
            exit 0
        } finally {
            if ($lock) { $lock.Dispose() }
        }
    }

    # Check
    $state = [ordered]@{
        directory_protected = (Test-Path -LiteralPath $Directory) -and (Test-ProtectedAcl $Directory)
        update_script_present = Test-Path -LiteralPath (Join-Path $ProjectDirectory 'scripts\windows\update.ps1') -PathType Leaf
    }
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $state.task_registered = [bool]$task
    $state.task_enabled = [bool]$task -and ($task.State -ne 'Disabled')   # antivirus "gaming" modes disable tasks
    foreach ($key in $state.Keys) { Write-Output ("{0}: {1}" -f $key, $state[$key]) }
    # Optional parts: reported, but they do not decide readiness.
    $alert = Test-Path -LiteralPath $pingFile
    Write-Output ("alert_file_present: {0}" -f $alert)
    if ($alert) {
        Write-Output ("alert_file_protected: {0}" -f (Test-ProtectedAcl $pingFile))
        Write-Output ("alert_url_is_https: {0}" -f [bool](Read-PingUrl $pingFile))
    }
    Write-Output ("paused: {0}" -f [bool](Read-State 'paused'))
    $failedCommit = Read-State 'failed-commit.txt'
    Write-Output ("failed_commit_pending: {0}" -f $(if ($failedCommit) { $failedCommit.Substring(0, 7) } else { 'none' }))
    Write-Output ("last_result: {0}" -f $(if (Read-State 'last-result.txt') { Read-State 'last-result.txt' } else { 'none yet' }))
    $ready = -not ($state.Values -contains $false)   # MRK-93: piping to Where-Object yields $false itself
    Write-Output ("ready: {0}" -f $ready)
    if (-not $ready) { exit 2 }
    exit 0
} catch {
    # Line number only (no values): enough to find a failure reported from the Windows host.
    [Console]::Error.WriteLine('[auto-update] ' + $_.Exception.GetType().Name + ': ' + $_.Exception.Message +
        ' (line ' + $_.InvocationInfo.ScriptLineNumber + '; run elevated; no URL printed)')
    exit 1
}
