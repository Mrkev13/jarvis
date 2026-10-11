[CmdletBinding()]
param(
    [string]$BackendUrl = 'http://127.0.0.1:8000',
    [string]$FrontendUrl = 'http://127.0.0.1:3000',
    [switch]$RequireHealthy
)
$ErrorActionPreference = 'Stop'
try {
    # URLs are operator arguments, never echoed (including on failures).
    $health = Invoke-RestMethod -Uri ($BackendUrl.TrimEnd('/') + '/health') -TimeoutSec 10 -Method Get
    if ($health.status -notin @('healthy', 'degraded')) { exit 1 }
    $page = Invoke-WebRequest -UseBasicParsing -Uri ($FrontendUrl.TrimEnd('/') + '/login') -TimeoutSec 10
    if ($page.StatusCode -ne 200) { exit 1 }
    Write-Output ('backend=' + $health.status + '; frontend=served')
    if ($RequireHealthy -and $health.status -ne 'healthy') { exit 2 }
    exit 0
} catch {
    [Console]::Error.WriteLine('Health probe failed or service unavailable')
    exit 1
}
