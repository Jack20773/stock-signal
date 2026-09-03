# run_daily_analysis.ps1 - scheduled once daily (task: ClaudeStockSignalDaily).
#
# ASCII ONLY ON PURPOSE. Do not put Chinese in this file.
#   The scheduled task runs it through run_ps_hidden.vbs, which launches
#   powershell.exe (Windows PowerShell 5.1). 5.1 reads a BOM-less .ps1 as the ANSI
#   code page (CP936 on this box), so any Chinese literal gets shredded and the
#   script dies with "The string is missing the terminator" before it can log
#   anything at all. Same warning, same reason, as
#   000_Agent\007_dashboard\run_ledger_sweep.ps1 (found the hard way 2026-08-27:
#   the task was registered, reported LastTaskResult=1, and produced no log -
#   registration is not proof that it runs).
#
# WHY THIS EXISTS (2026-09-03)
#   The LLM analysis moved from Gemini to Claude on a SUBSCRIPTION (local
#   `claude -p`, not a metered API key). GitHub Actions cannot reach that
#   subscription, so commit 10b91dd disabled the Actions cron and the daily
#   analysis now has to run on this machine.
#
# WHAT IT RUNS
#   python -X utf8 update.py --last 3
#     Step 1 download new transcripts (skips ones already on disk)
#     Step 2 batch analyse - ONLY episodes with no row in episode_analysis, so a
#            normal day is 0-1 Claude calls, never the full 691-episode back
#            catalogue
#     Step 3 fill entry prices + performance snapshot
#     Step 4 regenerate the HTML reports
#   NO --send. Mail stays a deliberate manual act; see notifier.py's ad gate.
#
# SMOKE MODE (how to prove the Claude leg really runs without burning quota)
#   Put an episode id (e.g. EP689) in ops\_smoke_request.txt. The next run
#   analyses that ONE episode through the real analyzer, then blanks the sentinel
#   file (blanks - never deletes; nothing in this repo deletes files). Because the
#   episode already has an episode_analysis row, save_result() returns -1 and
#   nothing is written to the database: a real Claude call, zero DB mutation.
#
# MISSED-RUN VISIBILITY (the point of last_run_status.json)
#   The task is LogonType=Interactive like all 10 sibling Claude tasks, so it
#   simply does not fire while nobody is logged in. This script does NOT try to
#   fix that. It makes it VISIBLE: every run rewrites ops\last_run_status.json
#   with last_attempt / last_success / days_since_last_success, and every run
#   logs a "STALE:" line when the previous success is more than 2 days old. One
#   look at that file answers "when did this last actually work".
#
# HONEST LIMITS - do not paper over these:
#   - Nothing here alerts Daniel. It writes a log and a status file; something
#     has to read them.
#   - A run that finds no new episode is NOT a failure and NOT a success of the
#     analysis step. It is logged as NO-NEW-EPISODES with the population count,
#     never as a bare OK. A green line with no population number is a lie.
#   - `python` is resolved from PATH, same as daily_db_backup.ps1 does.

# 'Stop' for OUR OWN cmdlets (a failed Set-Location or Get-Content must not be
# shrugged off), but see Invoke-Py below: the two `& python ... 2>&1` calls run
# with 'Continue', because under 'Stop' every stderr LINE from the child becomes a
# terminating error - and analyzer.py prints an informational [env] line to stderr
# on EVERY Claude call ("removed ANTHROPIC_API_KEY from the child env, keeping the
# OAuth subscription"). The first run of this script died on exactly that line.
# Child-process failure is judged by exit code and by the population line, never
# by "stderr was non-empty".
$ErrorActionPreference = 'Stop'

$ScriptPath = $MyInvocation.MyCommand.Path
$Here    = Split-Path -Parent $ScriptPath
$Proj    = Split-Path -Parent $Here
$LogDir  = Join-Path $Here 'logs'
$Log     = Join-Path $LogDir ('daily_' + (Get-Date -Format 'yyyy-MM') + '.log')
$Status  = Join-Path $Here 'last_run_status.json'
$Smoke   = Join-Path $Here '_smoke_request.txt'
$LastN   = 3

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

# Run python and return its merged stdout+stderr; sets $script:PyExit.
function Invoke-Py([string[]]$PyArgs) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $o = & python -X utf8 @PyArgs 2>&1
        $script:PyExit = $LASTEXITCODE
        return $o
    }
    finally { $ErrorActionPreference = $saved }
}

function Write-Log([string]$msg) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

function Read-Status {
    if (Test-Path $Status) {
        try { return (Get-Content -Path $Status -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
    }
    return $null
}

function Write-Status([string]$result, [string]$detail, [bool]$success) {
    $prev = Read-Status
    $now  = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $lastSuccess = $null
    if ($success) { $lastSuccess = $now }
    elseif ($prev -and $prev.last_success) { $lastSuccess = $prev.last_success }

    $days = -1
    if ($lastSuccess) {
        $days = [int][math]::Floor(((Get-Date) - [datetime]::Parse($lastSuccess)).TotalDays)
    }
    $obj = [ordered]@{
        task                     = 'ClaudeStockSignalDaily'
        script                   = $ScriptPath
        last_attempt             = $now
        last_attempt_result      = $result
        last_attempt_detail      = $detail
        last_success             = $lastSuccess
        days_since_last_success  = $days
        note                     = 'LogonType=Interactive: the task does not fire while nobody is logged in. Compare last_success against today to spot a silent gap.'
    }
    $obj | ConvertTo-Json -Depth 4 | Set-Content -Path $Status -Encoding UTF8
}

# --- staleness check up front, so a gap is visible even if this run also fails --
$prev = Read-Status
if ($prev -and $prev.last_success) {
    $gap = ((Get-Date) - [datetime]::Parse([string]$prev.last_success)).TotalDays
    if ($gap -gt 2) {
        Write-Log ('STALE: last successful run was {0} ({1:N1} days ago)' -f $prev.last_success, $gap)
    }
} elseif ($prev) {
    Write-Log 'STALE: no successful run has ever been recorded in last_run_status.json'
}

Set-Location -Path $Proj
$prevEnc = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

try {
    # ---- smoke mode -------------------------------------------------------
    $smokeEp = ''
    if (Test-Path $Smoke) { $smokeEp = (Get-Content -Path $Smoke -Raw -Encoding UTF8).Trim() }

    if ($smokeEp) {
        $t = Get-ChildItem -Path (Join-Path $Proj 'transcripts') -Filter ($smokeEp + '_*.md') -ErrorAction SilentlyContinue | Select-Object -First 1
        # Blank the sentinel first: a crash below must not turn into a smoke run
        # every single day from now on.
        Set-Content -Path $Smoke -Value '' -Encoding UTF8
        if (-not $t) {
            Write-Log ('SMOKE FAILED: no transcript found for {0}' -f $smokeEp)
            Write-Status 'SMOKE_FAILED' ('no transcript for ' + $smokeEp) $false
            exit 1
        }
        Write-Log ('SMOKE START: one real Claude analysis of {0} ({1})' -f $smokeEp, $t.Name)
        $out  = Invoke-Py @((Join-Path $Proj 'main.py'), $t.FullName)
        $code = $script:PyExit
        foreach ($l in $out) { Write-Log ('  | ' + $l) }
        if ($code -ne 0) {
            Write-Log ('SMOKE FAILED: exit={0}' -f $code)
            Write-Status 'SMOKE_FAILED' ('exit ' + $code) $false
            exit $code
        }
        $sig = ($out | Where-Object { $_ -match '^Signals\s*:' }) -join ' / '
        if (-not $sig) { $sig = 'NO Signals LINE FROM main.py - SUSPICIOUS' }
        Write-Log ('SMOKE OK: {0} :: {1}' -f $smokeEp, $sig)
        Write-Status 'SMOKE_OK' ($smokeEp + ' :: ' + $sig) $true
        exit 0
    }

    # ---- normal daily run -------------------------------------------------
    Write-Log ('RUN START: update.py --last {0} (no --send)' -f $LastN)
    $out  = Invoke-Py @((Join-Path $Proj 'update.py'), '--last', [string]$LastN)
    $code = $script:PyExit
    foreach ($l in $out) { Write-Log ('  | ' + $l) }

    if ($code -ne 0) {
        Write-Log ('RUN FAILED: exit={0}' -f $code)
        Write-Status 'FAILED' ('update.py exit ' + $code) $false
        exit $code
    }

    # Keep the population numbers. batch.py's tail line is the only place that
    # says how many episodes were actually looked at, and a run that analysed 0
    # episodes must stay distinguishable from a run that analysed 3.
    #
    # The line being matched is Chinese, but THIS FILE MUST STAY ASCII (see the
    # header), so the pattern is written with .NET regex \uXXXX escapes:
    #   U+5B8C U+6210 = 'done'      U+5171 = 'total'      U+96C6 = 'episodes'
    #   U+5206 U+6790 = 'analysed'  U+8DF3 U+904E = 'skipped'
    #   U+5931 U+6557 = 'failed'    U+FF5C = the fullwidth vertical bar separator
    # i.e. what batch.py prints: done|total N episodes|analysed D|skipped S|failed F
    $summaryPat = '\u5b8c\u6210\uff5c\u5171\s*(\d+)\s*\u96c6\uff5c\u5206\u6790\s*(\d+)\uff5c\u8df3\u904e\s*(\d+)\uff5c\u5931\u6557\s*(\d+)'
    # 'no new episodes' - update.py's other exit from Step 2
    $noNewPat   = '\u7121\u65b0\u96c6\u6578'

    $pop = $null; $anal = $null; $skip = $null; $fail = $null
    foreach ($l in $out) {
        if ([string]$l -match $summaryPat) {
            $pop  = [int]$Matches[1]; $anal = [int]$Matches[2]
            $skip = [int]$Matches[3]; $fail = [int]$Matches[4]
        }
    }

    if ($null -ne $pop) {
        Write-Log ('POPULATION: episodes_considered={0} analysed={1} skipped_already_done={2} failed={3}' -f $pop, $anal, $skip, $fail)
    } elseif (@($out | Where-Object { [string]$_ -match $noNewPat }).Count -gt 0) {
        $pop = 0; $anal = 0; $skip = 0; $fail = 0
        Write-Log 'POPULATION: episodes_considered=0 (update.py found no episode files in the --last window)'
    } else {
        Write-Log 'POPULATION: NO BATCH SUMMARY LINE FOUND - SUSPICIOUS. Cannot tell how many episodes were considered; treating this run as FAILED rather than reporting a green tick with no population number.'
        Write-Status 'FAILED' 'no batch summary line in update.py output' $false
        exit 1
    }

    if ($fail -gt 0) {
        Write-Log ('RUN FINISHED WITH FAILURES: {0} episode(s) failed to analyse - see the piped lines above for each reason' -f $fail)
        Write-Status 'PARTIAL' ('analysed=' + $anal + ' failed=' + $fail) $false
        exit 1
    }
    if ($anal -eq 0) {
        Write-Log ('RUN OK BUT NOTHING ANALYSED: 0 episodes went to Claude (considered={0}, all already in episode_analysis). This is NOT a check that passed - no analysis happened this run.' -f $pop)
    } else {
        Write-Log ('RUN OK: {0} of {1} considered episode(s) analysed by Claude this run' -f $anal, $pop)
    }
    Write-Status 'OK' ('considered=' + $pop + ' analysed=' + $anal + ' skipped=' + $skip) $true
    exit 0
}
catch {
    Write-Log ('RUN CRASHED: {0}' -f $_.Exception.Message)
    Write-Status 'CRASHED' ([string]$_.Exception.Message) $false
    exit 1
}
finally {
    [Console]::OutputEncoding = $prevEnc
}
