# MRK-97: automatic Codex review of open pull requests. Every 10 minutes the task lists open PRs; for each head commit
# that has no "Codex-Verdict:" review yet, it checks that commit out in a DEDICATED review clone (never the production
# C:\StandaHub), runs Codex CLI read-only and posts Codex's answer as a PR review comment. The review gate workflow
# (.github/workflows/review-gate.yml) then lets the PR auto-merge on "Codex-Verdict: MERGE".
#   -Mode Check    : tools, logins, review clone, task - names and booleans only.
#   -Mode Register : scheduled task StandaHub-CodexReview, every 10 minutes, as the CURRENT user (gh and codex use that
#                    user's logins). Asks for the Windows password once; Windows stores it for the task. Not started.
#   -Mode Run      : one pass over the open PRs (what the task executes).
# Safety:
#   - Codex runs with --sandbox read-only: it reads the checkout and answers; only this script talks to GitHub.
#   - Every head commit is attempted at most once (state file per PR); a failed or verdict-less answer is not posted.
#   - The head is checked again right before posting: if a new commit arrived meanwhile, nothing is posted.
#   - Draft PRs and PRs labelled "manual-review" are skipped. One run at a time (lock file). Logs: last 30.
# The review clone is created once by hand (docs/operations.md): git clone https://github.com/Mrkev13/jarvis C:\StandaHub-review
[CmdletBinding()]
param(
    [ValidateSet('Check', 'Register', 'Run')][string]$Mode = 'Check',
    [string]$ReviewDirectory = 'C:\StandaHub-review',
    [string]$ProductionDirectory = 'C:\StandaHub',
    # Per user (the task runs as you, without admin rights): state, Codex answers and the lock file.
    [string]$Directory = (Join-Path $env:LOCALAPPDATA 'StandaHub\codex-review'),
    [string]$Repo = 'Mrkev13/jarvis'
)
$ErrorActionPreference = 'Stop'
$TaskName = 'StandaHub-CodexReview'
$KeepLogs = 30
# Case-sensitive like the gate workflow (-cmatch): a lowercase 'merge' would be posted but never accepted.
$VerdictPattern = '(?m)^Codex-Verdict:\s*(MERGE|BLOCK)\s*$'

function Step([string]$Text) { Write-Output ('[codex-review] ' + $Text) }

function Invoke-Lines([string]$What, [string]$Exe, [string[]]$Arguments) {
    # No stderr redirection (Windows PowerShell 5.1 turns redirected native stderr into a terminating error under
    # $ErrorActionPreference = 'Stop'); the exit code decides.
    $out = @(& $Exe @Arguments)
    if ($LASTEXITCODE -ne 0) { throw ($What + ' failed (exit ' + $LASTEXITCODE + ')') }
    return $out
}

function Get-Json([string]$What, [string[]]$Arguments) {
    $text = (Invoke-Lines $What 'gh' $Arguments) -join "`n"
    if (-not $text.Trim()) { return @() }
    return @($text | ConvertFrom-Json)
}

function Test-HasVerdict([int]$Number, [string]$Head) {
    $reviews = Get-Json 'gh api reviews' @('api', '--paginate', ('repos/' + $Repo + '/pulls/' + $Number + '/reviews'))
    foreach ($review in $reviews) {
        if ($review.commit_id -eq $Head -and ([string]$review.body) -cmatch $VerdictPattern) { return $true }
    }
    return $false
}

function Get-Prompt([int]$Number, [string]$Head) {
    # English and ASCII on purpose (this file stays ASCII); AGENTS.md tells Codex to answer in Czech.
    # ONE line without double quotes: Windows PowerShell 5.1 mangles embedded double quotes in native arguments, and an
    # npm-installed codex.cmd would cut a multi-line argument at the first line break.
    return @(
        ('You are the reviewer of pull request #' + $Number + ' in ' + $Repo + ' (AGENTS.md, workflow step 4).'),
        ('The current directory is a checkout of its head commit ' + $Head + '; the base is origin/main.'),
        'Review the change: git diff origin/main...HEAD (and git log origin/main..HEAD). Check correctness, scope',
        '(one Linear issue), the code rules in AGENTS.md, tests and the PR template rules. You cannot use the network.',
        'Write the review in Czech as markdown: blocking findings first (file:line, why, what to change), then',
        'non-blocking ones. Do not invent results you could not check (CI runs separately).',
        'End with exactly one line on its own: Codex-Verdict: MERGE when nothing blocks, otherwise',
        'Codex-Verdict: BLOCK (that line only, no other text on it).'
    ) -join ' '
}

function Read-State([string]$Name) {
    $path = Join-Path $Directory $Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return '' }
    return ([System.IO.File]::ReadAllText($path)).Trim()
}

function Write-State([string]$Name, [string]$Value) {
    [System.IO.File]::WriteAllText((Join-Path $Directory $Name), $Value, (New-Object System.Text.UTF8Encoding($false)))
}

function Write-Result([string]$Text) {
    Write-State 'last-result.txt' ((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') + ' ' + $Text)
    Step $Text
}

function Test-ReviewClone {
    if (-not (Test-Path -LiteralPath (Join-Path $ReviewDirectory '.git'))) { return $false }
    $review = (Resolve-Path -LiteralPath $ReviewDirectory).Path.TrimEnd('\')
    $production = if (Test-Path -LiteralPath $ProductionDirectory) { (Resolve-Path -LiteralPath $ProductionDirectory).Path.TrimEnd('\') } else { '' }
    return ($review -ne $production)   # never check out PR code in the production checkout
}

try {
    $logDir = Join-Path $Directory 'logs'

    if ($Mode -eq 'Register') {
        if (-not (Test-ReviewClone)) { throw ('Create the review clone first: git clone https://github.com/' + $Repo + ' ' + $ReviewDirectory) }
        foreach ($dir in @($Directory, $logDir)) {
            if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        }
        $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $cred = Get-Credential -UserName $user -Message 'Windows password of this account (not the PIN). The review task runs as you so gh and codex use your logins; Windows stores it for the task.'
        if (-not $cred) { throw 'No password entered' }
        $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 50) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        # First start in the future: a past start boundary plus StartWhenAvailable could run right at registration.
        $firstStart = (Get-Date).AddMinutes(15)
        $trigger = New-ScheduledTaskTrigger -Once -At $firstStart -RepetitionInterval (New-TimeSpan -Minutes 10)
        $taskArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Mode Run -ReviewDirectory "{1}" -ProductionDirectory "{2}" -Directory "{3}" -Repo {4}' -f $PSCommandPath, $ReviewDirectory, $ProductionDirectory, $Directory, $Repo
        $action = New-ScheduledTaskAction -Execute $shell -Argument $taskArgs -WorkingDirectory $ReviewDirectory
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User $cred.UserName -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null
        $cred = $null
        Write-Output ('{0} registered (every 10 minutes, as {1}); first automatic run at {2}.' -f $TaskName, $user, $firstStart.ToString('HH:mm'))
        exit 0
    }

    if ($Mode -eq 'Run') {
        if (-not (Test-Path -LiteralPath $logDir)) { throw 'Run -Mode Register first' }
        if (-not (Test-ReviewClone)) { throw 'Review clone missing or equal to the production checkout' }
        $lock = $null
        try { $lock = [System.IO.File]::Open((Join-Path $Directory 'run.lock'), 'OpenOrCreate', 'ReadWrite', 'None') } catch {
            Step 'Another run is in progress; nothing to do.'
            exit 0
        }
        try {
            $prs = Get-Json 'gh pr list' @('pr', 'list', '--repo', $Repo, '--state', 'open', '--json', 'number,headRefOid,isDraft,labels')
            $reviewed = 0
            foreach ($pr in $prs) {
                $number = [int]$pr.number
                $head = [string]$pr.headRefOid
                if ($pr.isDraft -or (@($pr.labels | ForEach-Object { $_.name }) -contains 'manual-review')) { continue }
                if ($head -notmatch '^[0-9a-f]{40}$') { continue }
                $stateName = 'pr-' + $number + '.txt'
                if ((Read-State $stateName) -eq $head) { continue }       # this commit was attempted already
                if (Test-HasVerdict $number $head) { Write-State $stateName $head; continue }   # reviewed by hand

                $short = $head.Substring(0, 7)
                $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
                $answer = Join-Path $logDir ($stamp + '-pr' + $number + '-' + $short + '.md')
                Write-State $stateName $head   # at most one attempt per commit, also when Codex fails
                Invoke-Lines 'git fetch' 'git' @('-C', $ReviewDirectory, 'fetch', '--quiet', 'origin', 'main', ('pull/' + $number + '/head')) | Out-Null
                Invoke-Lines 'git checkout' 'git' @('-C', $ReviewDirectory, 'checkout', '--quiet', '--detach', $head) | Out-Null
                Step ('Reviewing PR #' + $number + ' at ' + $short)
                $prompt = Get-Prompt $number $head
                & codex exec --sandbox read-only --cd $ReviewDirectory --output-last-message $answer $prompt | Out-Null
                $codexExit = $LASTEXITCODE
                $body = if (Test-Path -LiteralPath $answer) { [System.IO.File]::ReadAllText($answer) } else { '' }
                if ($codexExit -ne 0 -or $body -cnotmatch $VerdictPattern) {
                    Write-Result ('PR #' + $number + ' ' + $short + ': no review posted (codex exit ' + $codexExit + ', verdict line ' + ($body -cmatch $VerdictPattern) + ')')
                    continue
                }
                $now = Get-Json 'gh pr view' @('pr', 'view', [string]$number, '--repo', $Repo, '--json', 'headRefOid')
                if ([string]$now[0].headRefOid -ne $head) {
                    Write-Result ('PR #' + $number + ': new commit arrived during the review; ' + $short + ' not posted')
                    continue
                }
                Invoke-Lines 'gh pr review' 'gh' @('pr', 'review', [string]$number, '--repo', $Repo, '--comment', '--body-file', $answer) | Out-Null
                $verdict = ([regex]::Match($body, $VerdictPattern)).Groups[1].Value
                Write-Result ('PR #' + $number + ' ' + $short + ': review posted, verdict ' + $verdict)
                $reviewed++
            }
            if ($reviewed -eq 0 -and -not (Read-State 'last-result.txt')) { Write-Result 'no PR waiting for review' }
            Get-ChildItem -LiteralPath $logDir -Filter '*.md' -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -Skip $KeepLogs | Remove-Item -Force -ErrorAction SilentlyContinue
            exit 0
        } finally {
            if ($lock) { $lock.Dispose() }
        }
    }

    # Check
    $state = [ordered]@{
        gh_installed       = [bool](Get-Command gh -ErrorAction SilentlyContinue)
        codex_installed    = [bool](Get-Command codex -ErrorAction SilentlyContinue)
        review_clone_ready = Test-ReviewClone
    }
    if ($state.gh_installed) {
        & gh auth status --hostname github.com | Out-Null
        $state.gh_logged_in = ($LASTEXITCODE -eq 0)
    }
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $state.task_registered = [bool]$task
    $state.task_enabled = [bool]$task -and ($task.State -ne 'Disabled')
    foreach ($key in $state.Keys) { Write-Output ("{0}: {1}" -f $key, $state[$key]) }
    Write-Output ("last_result: {0}" -f $(if (Read-State 'last-result.txt') { Read-State 'last-result.txt' } else { 'none yet' }))
    $ready = -not ($state.Values -contains $false)   # MRK-93: piping to Where-Object yields $false itself
    Write-Output ("ready: {0}" -f $ready)
    if (-not $ready) { exit 2 }
    exit 0
} catch {
    $failure = $_.Exception.GetType().Name + ': ' + $_.Exception.Message + ' (line ' + $_.InvocationInfo.ScriptLineNumber + ')'
    [Console]::Error.WriteLine('[codex-review] ' + $failure)
    if ($Mode -eq 'Run' -and (Test-Path -LiteralPath $Directory)) {
        try { Write-State 'last-result.txt' ((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') + ' run failed: ' + $failure) } catch { }
    }
    exit 1
}
