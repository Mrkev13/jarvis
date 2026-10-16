# Native foreground production process with in-script supervision. Task Scheduler's restart-on-failure covers only
# a task that fails to LAUNCH, not an action that exits nonzero (verified on Windows), so this script restarts the
# backend itself after a crash. Exit 0 (clean shutdown) or 130 (Ctrl+C) ends supervision; stopping the task ends
# the whole process tree.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProjectDirectory,
    [Parameter(Mandatory=$true)][string]$EnvFile,
    [string]$PythonPath = '',
    [int]$Port = 8000,
    # MRK-24: 127.0.0.1 once Tailscale Serve is the only browser entry; 0.0.0.0 keeps direct tailnet HTTP.
    [string]$BindAddress = '0.0.0.0',
    [int]$RestartDelaySeconds = 10,
    [int]$MaxRestartDelaySeconds = 60
)
$ErrorActionPreference = 'Stop'
try {
    $root = (Resolve-Path -LiteralPath $ProjectDirectory).Path
    $config = (Resolve-Path -LiteralPath $EnvFile).Path
    if (-not $PythonPath) { $PythonPath = Join-Path $root '.venv\Scripts\python.exe' }
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Missing Python' }
    if ($Port -lt 1 -or $Port -gt 65535) { throw 'Invalid port' }
    if ($BindAddress -notin @('0.0.0.0', '127.0.0.1')) { throw 'Invalid bind address' }
    Set-Location -LiteralPath (Join-Path $root 'backend')
    $delay = [Math]::Max(1, $RestartDelaySeconds)
    while ($true) {
        $started = Get-Date
        & $PythonPath -m production --env-file $config --host $BindAddress --port $Port
        $code = $LASTEXITCODE
        if ($code -eq 0 -or $code -eq 130) { exit $code }
        # A run that stayed up for a while resets the back-off; a crash loop backs off up to the maximum.
        if (((Get-Date) - $started).TotalSeconds -ge 120) { $delay = [Math]::Max(1, $RestartDelaySeconds) }
        [Console]::Error.WriteLine("Backend exited with code $code; restarting in $delay s.")
        Start-Sleep -Seconds $delay
        $delay = [Math]::Min($delay * 2, [Math]::Max($delay, $MaxRestartDelaySeconds))
    }
} catch {
    # Never print raw PowerShell/native errors or the config/path.
    [Console]::Error.WriteLine('Backend production start failed; check configuration and protected installation.')
    exit 1
}
