# Build separately during deployment; production start never rebuilds on restart.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProjectDirectory,
    [int]$Port = 3000,
    [switch]$Build
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
    & $npm @startArgs
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('Frontend production start/build failed; verify config, Node/npm and build.')
    exit 1
}
