# PREPARE ONLY in cloud. Run explicitly on Windows after smoke tests, as Administrator.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProjectDirectory,
    [Parameter(Mandatory=$true)][string]$BackendEnvFile,
    [string]$PythonPath = ''
)
$ErrorActionPreference = 'Stop'
try {
    $root = (Resolve-Path -LiteralPath $ProjectDirectory).Path
    $config = (Resolve-Path -LiteralPath $BackendEnvFile).Path
    if (-not $PythonPath) { $PythonPath = Join-Path $root '.venv\Scripts\python.exe' }
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Missing Python' }
    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = 'PT30S'
    $backendScript = Join-Path $root 'scripts\windows\start-backend.ps1'
    $frontendScript = Join-Path $root 'scripts\windows\start-frontend.ps1'
    foreach ($script in @($backendScript, $frontendScript)) {
        if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw 'Missing start script' }
    }
    # Native argument quoting handles spaces. No credentials or secret env values in task arguments.
    $backendArgs = '-NoProfile -NonInteractive -File "{0}" -ProjectDirectory "{1}" -EnvFile "{2}" -PythonPath "{3}"' -f $backendScript, $root, $config, $PythonPath
    $frontendArgs = '-NoProfile -NonInteractive -File "{0}" -ProjectDirectory "{1}"' -f $frontendScript, $root
    $backendAction = New-ScheduledTaskAction -Execute $shell -Argument $backendArgs -WorkingDirectory (Join-Path $root 'backend')
    $frontendAction = New-ScheduledTaskAction -Execute $shell -Argument $frontendArgs -WorkingDirectory (Join-Path $root 'frontend')
    Register-ScheduledTask -TaskName 'StandaHub-Backend' -Action $backendAction -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Register-ScheduledTask -TaskName 'StandaHub-Frontend' -Action $frontendAction -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Write-Output 'Production tasks registered; not started. Run Windows acceptance checklist.'
    exit 0
} catch {
    [Console]::Error.WriteLine('Task registration failed; verify elevation, installation and task settings locally.')
    exit 1
}
