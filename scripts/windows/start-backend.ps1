# Native foreground production process; Task Scheduler observes this script's exit code.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProjectDirectory,
    [Parameter(Mandatory=$true)][string]$EnvFile,
    [string]$PythonPath = '',
    [int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
try {
    $root = (Resolve-Path -LiteralPath $ProjectDirectory).Path
    $config = (Resolve-Path -LiteralPath $EnvFile).Path
    if (-not $PythonPath) { $PythonPath = Join-Path $root '.venv\Scripts\python.exe' }
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Missing Python' }
    if ($Port -lt 1 -or $Port -gt 65535) { throw 'Invalid port' }
    Set-Location -LiteralPath (Join-Path $root 'backend')
    & $PythonPath -m production --env-file $config --host '0.0.0.0' --port $Port
    exit $LASTEXITCODE
} catch {
    # Never print raw PowerShell/native errors or the config/path.
    [Console]::Error.WriteLine('Backend production start failed; check configuration and protected installation.')
    exit 1
}
