# MRK-92: one-command production update for the Windows host. Run elevated, e.g.
#   powershell -ExecutionPolicy Bypass -File C:\StandaHub\scripts\windows\update.ps1
# Safe order: everything that can fail (checkout, pip, npm ci, build, config check) happens BEFORE the migration.
# The migration runs in one transaction (alembic env.py), so a failed migration leaves the schema untouched.
#   failure up to and including the migration -> automatic rollback to the previous commit, Hub started again
#   failure after a successful migration      -> backend started (reminders, backups), no data downgrade, ask for help
# Exit codes: 0 updated or already up to date, 1 failed and rolled back, 2 preconditions not met (nothing changed),
#             3 failed after the migration (Hub may be partly down; see docs/operations.md).
# Never prints env values: the production env file is only loaded inside Python by production.py.
[CmdletBinding()]
param(
    [string]$ProjectDirectory = 'C:\StandaHub',
    [string]$EnvFile = '',
    [string]$Ref = 'origin/main',
    [string]$BackendUrl = 'http://127.0.0.1:8000',
    [string]$FrontendUrl = 'http://127.0.0.1:3000',
    # Only when /health cannot confirm a fresh backup and you have a backup another way.
    [switch]$AllowStaleBackup
)
$ErrorActionPreference = 'Stop'
$Tasks = @('StandaHub-Frontend', 'StandaHub-Backend')
$HeartbeatTask = 'StandaHub-Heartbeat'
# MRK-90 heartbeat reads this marker (protected SYSTEM + Administrators folder) and reports "up" until the UTC time in it.
$MaintenanceFile = Join-Path $env:ProgramData 'StandaHub\heartbeat\maintenance-until.txt'
$MaintenanceMinutes = 45

function Step([string]$Text) { Write-Output ('[update] ' + $Text) }

function Invoke-Native([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw ($What + ' failed (exit ' + $LASTEXITCODE + ')') }
}

function Get-Health {
    try { return Invoke-RestMethod -Uri ($BackendUrl.TrimEnd('/') + '/health') -TimeoutSec 10 -Method Get } catch { return $null }
}

function Wait-SchedulerIdle {
    # The hourly job (backup + off-site copy) runs relative to backend start, not on the hour: wait until no job runs.
    foreach ($i in 1..60) {
        $health = Get-Health
        if (-not $health) { return }
        $busy = @($health.scheduler.jobs | Where-Object { $_.running })
        if ($busy.Count -eq 0) { return }
        if ($i -eq 1) { Step 'Waiting for a running scheduler job (backup) to finish...' }
        Start-Sleep -Seconds 10
    }
    throw 'Scheduler job still running after 10 minutes'
}

function Stop-Hub {
    foreach ($name in $Tasks) { Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue }
    foreach ($i in 1..30) {
        $listening = Get-NetTCPConnection -LocalPort 8000, 3000 -State Listen -ErrorAction SilentlyContinue
        if (-not $listening) { return }
        Start-Sleep -Seconds 1
    }
    throw 'Ports 8000/3000 still in use after stopping the tasks'
}

function Start-Backend {
    Start-ScheduledTask -TaskName 'StandaHub-Backend'
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 3
        $health = Get-Health
        if ($health -and $health.status -in @('healthy', 'degraded') -and $health.migrations.status -eq 'current') { return $health }
    }
    throw 'Backend did not become healthy with current migrations within 3 minutes'
}

function Start-Frontend {
    Start-ScheduledTask -TaskName 'StandaHub-Frontend'
    foreach ($i in 1..40) {
        Start-Sleep -Seconds 3
        try {
            $page = Invoke-WebRequest -UseBasicParsing -Uri ($FrontendUrl.TrimEnd('/') + '/login') -TimeoutSec 10
            if ($page.StatusCode -eq 200) { return }
        } catch { }
    }
    throw 'Frontend did not serve /login within 2 minutes'
}

function Install-And-Build([string]$Commit) {
    Invoke-Native 'git checkout' { git -C $root checkout --quiet --detach $Commit }
    Invoke-Native 'pip install' { & $python -m pip install --disable-pip-version-check -q -r (Join-Path $root 'backend\requirements.txt') }
    Push-Location (Join-Path $root 'frontend')
    try { Invoke-Native 'npm ci' { & $npm ci --no-audit --no-fund --loglevel=error } } finally { Pop-Location }
    # Child process: start-frontend.ps1 changes the working directory and calls exit.
    Invoke-Native 'frontend build' { & $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $buildScript -ProjectDirectory $root -Build }
}

function Get-DbRevision {
    Push-Location (Join-Path $root 'backend')
    try {
        # Only single quotes inside the Python code: Windows PowerShell 5.1 mangles embedded double quotes in native args.
        $code = 'import sys; from production import load_production_environment; load_production_environment(sys.argv[1]); ' +
            'from sqlalchemy import create_engine, text; import os; e = create_engine(os.environ[''DATABASE_URL'']); ' +
            'c = e.connect(); print('',''.join(sorted(r[0] for r in c.execute(text(''select version_num from alembic_version''))))); c.close()'
        $rev = & $python -c $code $EnvFile
        if ($LASTEXITCODE -ne 0) { throw 'Reading the schema revision failed' }
        return ($rev | Select-Object -Last 1)
    } finally { Pop-Location }
}

function Invoke-Migration {
    Push-Location (Join-Path $root 'backend')
    try {
        Invoke-Native 'production config check' { & $python -m production --env-file $EnvFile --check }
        $code = 'import sys; from production import load_production_environment; load_production_environment(sys.argv[1]); ' +
            'from alembic.config import Config; from alembic import command; command.upgrade(Config(''alembic.ini''), ''head'')'
        Invoke-Native 'migration' { & $python -c $code $EnvFile }
    } finally { Pop-Location }
}

function Enter-Maintenance {
    # No task is disabled: the marker expires by itself, so an interrupted update (crash, power loss) can never
    # silence the external heartbeat for longer than $MaintenanceMinutes minutes.
    if (-not (Test-Path -LiteralPath (Split-Path -Parent $MaintenanceFile))) { return }   # heartbeat not set up
    $until = (Get-Date).ToUniversalTime().AddMinutes($MaintenanceMinutes).ToString('o')
    [System.IO.File]::WriteAllText($MaintenanceFile, $until, (New-Object System.Text.UTF8Encoding($false)))
    # A heartbeat run that started before the marker may still be probing: let it finish before the Hub stops.
    foreach ($i in 1..30) {
        $task = Get-ScheduledTask -TaskName $HeartbeatTask -ErrorAction SilentlyContinue
        if (-not $task -or $task.State -ne 'Running') { return }
        Start-Sleep -Seconds 5
    }
}

function Exit-Maintenance { Remove-Item -LiteralPath $MaintenanceFile -Force -ErrorAction SilentlyContinue }

# ---------------------------------------------------------------- preconditions (nothing is changed here)
try {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) { throw 'Run from an elevated PowerShell (Run as administrator)' }
    $root = (Resolve-Path -LiteralPath $ProjectDirectory).Path
    if (-not $EnvFile) { $EnvFile = Join-Path $root 'backend\.env.production' }
    $EnvFile = (Resolve-Path -LiteralPath $EnvFile).Path
    $python = Join-Path $root '.venv\Scripts\python.exe'
    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $buildScript = Join-Path $root 'scripts\windows\start-frontend.ps1'
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    foreach ($path in @($python, $buildScript)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw ('Missing ' + $path) } }
    foreach ($name in $Tasks) { if (-not (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue)) { throw ('Missing task ' + $name) } }

    $dirty = git -C $root status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0) { throw 'git status failed (if it says "dubious ownership": git config --global --add safe.directory C:/StandaHub)' }
    if ($dirty) { throw 'Tracked files were changed locally; update refuses to overwrite them' }

    $previous = (git -C $root rev-parse HEAD).Trim()
    Invoke-Native 'git fetch' { git -C $root fetch --quiet origin }
    $target = git -C $root rev-parse --verify --quiet ($Ref + '^{commit}')
    if ($LASTEXITCODE -ne 0 -or -not $target) { throw ('Unknown ref ' + $Ref) }
    $target = $target.Trim()
    # A clean tree does not prove the running commit is part of the target: never silently drop a local commit.
    git -C $root merge-base --is-ancestor $previous $target
    if ($LASTEXITCODE -ne 0) { throw ('Current commit ' + $previous.Substring(0, 7) + ' is not contained in ' + $Ref + '; refusing to discard it') }
    if ($target -eq $previous) {
        Step ('Already up to date at ' + $previous.Substring(0, 7) + '. Nothing changed.')
        exit 0
    }
    Step ('Update ' + $previous.Substring(0, 7) + ' -> ' + $target.Substring(0, 7))
    Write-Output (git -C $root log --oneline --no-decorate ($previous + '..' + $target) | Select-Object -First 15)

    $health = Get-Health
    if (-not $AllowStaleBackup) {
        if (-not $health) { throw 'Hub /health is not reachable, so a fresh backup cannot be confirmed (use -AllowStaleBackup only with another backup)' }
        if ($health.backup.status -ne 'fresh') { throw ('Backup is not fresh (status: ' + $health.backup.status + '); wait for the daily backup') }
    }
    Wait-SchedulerIdle
    $revisionBefore = Get-DbRevision
    Enter-Maintenance
} catch {
    Exit-Maintenance
    [Console]::Error.WriteLine('[update] Not started: ' + $_.Exception.Message)
    exit 2
}

# ---------------------------------------------------------------- update
# Exit code is decided inside; the maintenance marker is removed on every path before exiting (expiry covers the rest).
$exitCode = 3
$migrated = $false
try {
    try {
        Step 'Stopping the Hub (heartbeat in maintenance mode)'
        Stop-Hub
        Step 'Installing the new version (git, pip, npm ci, frontend build) - takes a few minutes'
        Install-And-Build $target
        Step 'Checking config and migrating the database'
        Invoke-Migration
        $migrated = ((Get-DbRevision) -ne $revisionBefore)
        Step 'Starting the Hub'
        $health = Start-Backend
        Start-Frontend
        Step ('Done: ' + $target.Substring(0, 7) + ', backend ' + $health.status + ', frontend served' + $(if ($migrated) { ', schema migrated' } else { '' }))
        $exitCode = 0
    } catch {
        [Console]::Error.WriteLine('[update] FAILED: ' + $_.Exception.Message)
        # A failed migration rolls back as a whole; compare the live revision instead of trusting the step that threw.
        try { $migrated = ((Get-DbRevision) -ne $revisionBefore) } catch { $migrated = $true }
        if ($migrated) {
            # New schema in the DB: the old code may not understand it. Never downgrade data; keep the backend running.
            [Console]::Error.WriteLine('[update] The database was already migrated, so the old version is NOT restored.')
            try { Start-Backend | Out-Null; Start-Frontend } catch { [Console]::Error.WriteLine('[update] Hub is not fully up: ' + $_.Exception.Message) }
            [Console]::Error.WriteLine('[update] Stop here and ask for help (docs/operations.md, One-command update).')
            $exitCode = 3
        } else {
            try {
                Step ('Rolling back to ' + $previous.Substring(0, 7))
                Stop-Hub
                Install-And-Build $previous
                Start-Backend | Out-Null
                Start-Frontend
                Step ('Rolled back: the Hub runs the previous version ' + $previous.Substring(0, 7) + '. Nothing was lost.')
                $exitCode = 1
            } catch {
                [Console]::Error.WriteLine('[update] Rollback failed too: ' + $_.Exception.Message + '. Ask for help.')
                $exitCode = 3
            }
        }
    }
} finally {
    Exit-Maintenance
}
exit $exitCode
