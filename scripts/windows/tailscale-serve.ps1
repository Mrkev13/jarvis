# MRK-24: private HTTPS for the production instance through Tailscale Serve (tailnet only - never Funnel).
#   https://<host>/       -> http://127.0.0.1:<FrontendPort>   (Next.js)
#   https://<host>:8443/  -> http://127.0.0.1:<BackendPort>    (FastAPI; browser API origin)
# Tailscale stores the Serve config itself, so it survives service and machine restarts; re-run -Mode Apply after a
# Tailscale reinstall/re-login. Run as Administrator (or a user allowed to change tailscaled), see docs/operations.md.
[CmdletBinding()]
param(
    [ValidateSet('Status', 'Apply', 'Reset')][string]$Mode = 'Status',
    [int]$FrontendPort = 3000,
    [int]$BackendPort = 8000,
    # Tailscale Serve accepts HTTPS only on 443, 8443 and 10000.
    [ValidateSet(443, 8443, 10000)][int]$FrontendHttpsPort = 443,
    [ValidateSet(443, 8443, 10000)][int]$BackendHttpsPort = 8443
)
$ErrorActionPreference = 'Stop'

function Get-TailscaleExe {
    $cmd = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $default = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (Test-Path -LiteralPath $default -PathType Leaf) { return $default }
    throw 'Tailscale CLI not found'
}

function Get-ServeHost($ts) {
    $status = & $ts status --json | ConvertFrom-Json
    if ($status.BackendState -ne 'Running') { throw 'Tailscale is not running/logged in' }
    $hostName = ([string]$status.Self.DNSName).TrimEnd('.')
    if (-not $hostName) { throw 'MagicDNS name unavailable' }
    if (@($status.CertDomains) -notcontains $hostName) { throw 'HTTPS certificates are not enabled for this tailnet' }
    return $hostName
}

function Get-ServeConfig($ts) {
    $raw = (& $ts serve status --json) -join "`n"
    if (-not $raw.Trim()) { return $null }
    return $raw | ConvertFrom-Json
}

function Assert-NoFunnel($config) {
    # Any AllowFunnel entry means something is publicly exposed: refuse to continue rather than silently keep it.
    if ($config -and $config.AllowFunnel -and @($config.AllowFunnel.PSObject.Properties | Where-Object { $_.Value }).Count) {
        throw 'Tailscale Funnel is enabled; disable it first (tailscale funnel reset) - Standa Hub must stay tailnet-only'
    }
}

function Get-Upstream($config, $hostName, $httpsPort) {
    if (-not $config -or -not $config.Web) { return $null }
    $site = $config.Web.PSObject.Properties | Where-Object { $_.Name -eq "${hostName}:$httpsPort" } | Select-Object -First 1
    if (-not $site) { return $null }
    $root = $site.Value.Handlers.PSObject.Properties | Where-Object { $_.Name -eq '/' } | Select-Object -First 1
    if (-not $root) { return $null }
    return [string]$root.Value.Proxy
}

function Write-State($config, $hostName) {
    $routes = @(
        @{ Name = 'frontend'; Https = $FrontendHttpsPort; Expected = "http://127.0.0.1:$FrontendPort" },
        @{ Name = 'backend'; Https = $BackendHttpsPort; Expected = "http://127.0.0.1:$BackendPort" }
    )
    $ok = $true
    foreach ($route in $routes) {
        $upstream = Get-Upstream $config $hostName $route.Https
        $url = if ($route.Https -eq 443) { "https://$hostName/" } else { "https://${hostName}:$($route.Https)/" }
        $state = if ($upstream -eq $route.Expected) { 'ok' } elseif ($upstream) { "unexpected upstream $upstream" } else { 'not configured' }
        if ($state -ne 'ok') { $ok = $false }
        [Console]::Out.WriteLine(("{0}: {1} -> {2} [{3}]" -f $route.Name, $url, $route.Expected, $state))
    }
    [Console]::Out.WriteLine('funnel: off')
    return $ok
}

try {
    foreach ($port in @($FrontendPort, $BackendPort)) { if ($port -lt 1 -or $port -gt 65535) { throw 'Invalid port' } }
    if ($FrontendHttpsPort -eq $BackendHttpsPort) { throw 'Frontend and backend need different HTTPS ports' }
    $ts = Get-TailscaleExe
    $hostName = Get-ServeHost $ts
    $before = Get-ServeConfig $ts
    Assert-NoFunnel $before

    if ($Mode -eq 'Apply') {
        # Idempotent: re-applying the same mapping replaces it. Upstreams are loopback only.
        & $ts serve --bg "--https=$FrontendHttpsPort" "http://127.0.0.1:$FrontendPort" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'tailscale serve (frontend) failed' }
        & $ts serve --bg "--https=$BackendHttpsPort" "http://127.0.0.1:$BackendPort" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'tailscale serve (backend) failed' }
    } elseif ($Mode -eq 'Reset') {
        # Only the two Standa Hub listeners; other Serve entries (if any) are left alone.
        foreach ($port in @($FrontendHttpsPort, $BackendHttpsPort)) {
            if (Get-Upstream $before $hostName $port) {
                & $ts serve "--https=$port" off | Out-Null
                if ($LASTEXITCODE -ne 0) { throw 'tailscale serve off failed' }
            }
        }
    }

    $after = Get-ServeConfig $ts
    Assert-NoFunnel $after
    $ok = Write-State $after $hostName
    if ($Mode -eq 'Apply' -and -not $ok) { exit 2 }
    if ($Mode -eq 'Reset' -and ((Get-Upstream $after $hostName $FrontendHttpsPort) -or (Get-Upstream $after $hostName $BackendHttpsPort))) { exit 2 }
    exit 0
} catch {
    [Console]::Error.WriteLine('Tailscale Serve: ' + $_.Exception.Message)
    exit 1
}
