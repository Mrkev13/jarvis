# Build separately during deployment; production start never rebuilds on restart. Start supervises the Next server
# itself (Task Scheduler does not restart an action that exits nonzero): exit 0/130 ends, a crash restarts with
# back-off; stopping the task ends the whole process tree.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProjectDirectory,
    [int]$Port = 3000,
    [switch]$Build,
    [int]$RestartDelaySeconds = 10,
    [int]$MaxRestartDelaySeconds = 60
)
$ErrorActionPreference = 'Stop'
try {
    $root = (Resolve-Path -LiteralPath $ProjectDirectory).Path
    $frontend = Join-Path $root 'frontend'
    if ($Port -lt 1 -or $Port -gt 65535) { throw 'Invalid port' }
    # Next prioritizes .env.local even in production. Refuse ambiguous dev configuration.
    foreach ($name in @('.env', '.env.local')) {
        if (Test-Path -LiteralPath (Join-Path $frontend $name)) { throw 'Development env file present' }
    }
    $config = Join-Path $frontend '.env.production.local'
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) { throw 'Missing production frontend config' }
    # Refuse missing/blank browser API setting; the operator supplies only this public URL.
    if (-not (Select-String -LiteralPath $config -Pattern '^NEXT_PUBLIC_API_URL=\S+' -Quiet)) { throw 'Missing API URL' }
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    Set-Location -LiteralPath $frontend
    $env:NODE_ENV = 'production'
    # Next env loader prefers inherited process.env to files: never bake a dev API URL.
    Remove-Item Env:NEXT_PUBLIC_API_URL -ErrorAction SilentlyContinue
    if ($Build) {
        & $npm run build
        exit $LASTEXITCODE
    }
    if (-not (Test-Path -LiteralPath (Join-Path $frontend '.next\BUILD_ID') -PathType Leaf)) { throw 'Missing production build' }
    $startArgs = @('run', 'start', '--', '--hostname', '0.0.0.0', '--port', $Port.ToString())
    $delay = [Math]::Max(1, $RestartDelaySeconds)
    while ($true) {
        $started = Get-Date
        & $npm @startArgs
        $code = $LASTEXITCODE
        if ($code -eq 0 -or $code -eq 130) { exit $code }
        if (((Get-Date) - $started).TotalSeconds -ge 120) { $delay = [Math]::Max(1, $RestartDelaySeconds) }
        [Console]::Error.WriteLine("Frontend exited with code $code; restarting in $delay s.")
        Start-Sleep -Seconds $delay
        $delay = [Math]::Min($delay * 2, [Math]::Max($delay, $MaxRestartDelaySeconds))
    }
} catch {
    [Console]::Error.WriteLine('Frontend production start/build failed; verify config, Node/npm and build.')
    exit 1
}
