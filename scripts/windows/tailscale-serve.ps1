# MRK-24: private HTTPS for the production instance through Tailscale Serve (tailnet only - never Funnel).
#   https://<host>/       -> http://127.0.0.1:<FrontendPort>   (Next.js)
#   https://<host>:8443/  -> http://127.0.0.1:<BackendPort>    (FastAPI; browser API origin)
# Tailscale stores the Serve config itself, so it survives service and machine restarts; re-run -Mode Apply after a
# Tailscale reinstall/re-login. Run elevated. Exit codes: 0 = routes as expected (Reset: both removed),
# 1 = error (CLI unavailable/failed, Funnel on, HTTPS certs off), 2 = routes not as expected. docs/https-pwa-push.md
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
    $raw = (& $ts status --json) -join "`n"
    if ($LASTEXITCODE -ne 0 -or -not $raw.Trim()) { throw 'tailscale status failed (elevated? tailscaled running?)' }
    $status = $raw | ConvertFrom-Json
    if ($status.BackendState -ne 'Running') { throw 'Tailscale is not running/logged in' }
    $hostName = ([string]$status.Self.DNSName).TrimEnd('.')
    if (-not $hostName) { throw 'MagicDNS name unavailable' }
    if (@($status.CertDomains) -notcontains $hostName) { throw 'HTTPS certificates are not enabled for this tailnet' }
    return $hostName
}

function Get-ServeConfig($ts) {
    # A failed CLI call must never look like "nothing configured" (that would fail open).
    $raw = (& $ts serve status --json) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'tailscale serve status failed (elevated? tailscaled running?)' }
    $config = if ($raw.Trim()) { $raw | ConvertFrom-Json } else { $null }
    return @{ Raw = $raw; Config = $config }
}

function Test-Funnel($serve) {
    # Fail closed: any AllowFunnel entry set to true anywhere in the JSON - top level (--bg) or a foreground
    # session (Foreground.<id>.AllowFunnel) - means something is public.
    return [bool]($serve.Raw -match '"AllowFunnel"\s*:\s*\{[^{}]*:\s*true')
}

function Get-Upstream($serve, $hostName, $httpsPort) {
    $config = $serve.Config
    if (-not $config -or -not $config.Web) { return $null }
    $site = $config.Web.PSObject.Properties | Where-Object { $_.Name -eq "${hostName}:$httpsPort" } | Select-Object -First 1
    if (-not $site) { return $null }
    $root = $site.Value.Handlers.PSObject.Properties | Where-Object { $_.Name -eq '/' } | Select-Object -First 1
    if (-not $root) { return $null }
    return [string]$root.Value.Proxy
}

$routes = @(
    @{ Name = 'frontend'; Https = $FrontendHttpsPort; Expected = "http://127.0.0.1:$FrontendPort" },
    @{ Name = 'backend'; Https = $BackendHttpsPort; Expected = "http://127.0.0.1:$BackendPort" }
)

function Write-State($serve, $hostName) {
    $ok = $true
    foreach ($route in $routes) {
        $upstream = Get-Upstream $serve $hostName $route.Https
        $url = if ($route.Https -eq 443) { "https://$hostName/" } else { "https://${hostName}:$($route.Https)/" }
        $state = if ($upstream -eq $route.Expected) { 'ok' } elseif ($upstream) { "unexpected upstream $upstream" } else { 'not configured' }
        if ($state -ne 'ok') { $ok = $false }
        [Console]::Out.WriteLine(("{0}: {1} -> {2} [{3}]" -f $route.Name, $url, $route.Expected, $state))
    }
    [Console]::Out.WriteLine($(if (Test-Funnel $serve) { 'funnel: ON - NOT ALLOWED' } else { 'funnel: off' }))
    return $ok
}

try {
    foreach ($port in @($FrontendPort, $BackendPort)) { if ($port -lt 1 -or $port -gt 65535) { throw 'Invalid port' } }
    if ($FrontendHttpsPort -eq $BackendHttpsPort) { throw 'Frontend and backend need different HTTPS ports' }
    $ts = Get-TailscaleExe
    $hostName = Get-ServeHost $ts
    $before = Get-ServeConfig $ts

    if ($Mode -eq 'Apply') {
        if (Test-Funnel $before) { throw 'Tailscale Funnel is enabled; disable it first - Standa Hub must stay tailnet-only' }
        foreach ($route in $routes) {
            $current = Get-Upstream $before $hostName $route.Https
            if ($current -and $current -ne $route.Expected) { throw "HTTPS port $($route.Https) already serves another upstream; not overwriting" }
        }
        # Idempotent: re-applying the same mapping is a no-op. Upstreams are loopback only.
        foreach ($route in $routes) {
            & $ts serve --bg "--https=$($route.Https)" $route.Expected | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "tailscale serve ($($route.Name)) failed" }
        }
    } elseif ($Mode -eq 'Reset') {
        # Rollback must work even if Funnel got enabled; only listeners pointing at our upstreams are removed.
        foreach ($route in $routes) {
            $current = Get-Upstream $before $hostName $route.Https
            if ($current -eq $route.Expected) {
                & $ts serve "--https=$($route.Https)" off | Out-Null
                if ($LASTEXITCODE -ne 0) { throw 'tailscale serve off failed' }
            } elseif ($current) {
                [Console]::Out.WriteLine("HTTPS port $($route.Https) serves another upstream; left untouched")
            }
        }
    }

    $after = Get-ServeConfig $ts
    $ok = Write-State $after $hostName
    if (Test-Funnel $after) { throw 'Tailscale Funnel is enabled - Standa Hub must stay tailnet-only' }
    if ($Mode -eq 'Reset') {
        foreach ($route in $routes) { if ((Get-Upstream $after $hostName $route.Https) -eq $route.Expected) { exit 2 } }
        exit 0
    }
    if (-not $ok) { exit 2 }
    exit 0
} catch {
    [Console]::Error.WriteLine('Tailscale Serve: ' + $_.Exception.Message)
    exit 1
}
