# The progress display of get-page-index.ps1, driven from a RECORDED
# document-index-status response. No login, no server, no database.
#
# WHY THIS EXISTS
# ===============
# 2026-09-16, a full re-index of 588 Boyland: the poll printed blank file
# names, 0/0 for every file and 0/0 pages total, for the whole ninety-minute
# run, and never reported completion. The server was fine throughout — it
# returned all sixteen files, correctly named, and finished every one.
#
# The script declared `param([string[]]$Files)` for its -Files option and the
# poll loop then did `$files = @($status.files)`. PowerShell variable names are
# case-insensitive and a param() type constraint outlives the binding, so every
# response object was coerced to [string]; `.file_name` read as $null and
# `[int]$_.indexed_pages` as 0. Because `queue_status` was '' as well, every
# file counted as still indexing and the loop could not end.
#
# The JSON was never wrong. So this test asserts the RENDERED LINE, which is
# the thing that broke.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$fixture = Join-Path $root 'fixtures/document-index-status.json'

# Load the script's functions without running it: read the file and define only
# the two the display needs.
$src = Get-Content (Join-Path $root 'get-page-index.ps1') -Raw
foreach ($name in @('Get-StatusRows', 'Format-StatusLine', 'Get-FileState')) {
    $m = [regex]::Match($src, "(?ms)^function\s+$name\s*\{.*?^\}")
    if (-not $m.Success) { throw "get-page-index.ps1 no longer defines $name" }
    Invoke-Expression $m.Value
}

$SkippedState = 'skipped_combined_set'
$failures = @()
function Check($label, $condition, $detail) {
    if ($condition) { Write-Host "  ok   $label" }
    else { $script:failures += "$label — $detail"; Write-Host "  FAIL $label — $detail" -ForegroundColor Red }
}

$recorded = Get-Content $fixture -Raw | ConvertFrom-Json

# ── 1. mid-run: the exact state the display was broken in ────────────────
Write-Host 'mid-run response (37 of 129 pages, one file running, seven queued)'
$rows = Get-StatusRows $recorded.mid_run
Check 'sixteen files' ($rows.Count -eq 16) "got $($rows.Count)"

$running = @($rows | Where-Object { $_.queue_status -eq 'running' })[0]
$line = Format-StatusLine $running
Check 'the line names the file' ($line -match 'MH - 7\.2\.26\.pdf') "line was '$line'"
Check 'the line carries pages_done/pages_total' ($line -match '\b5/13\b') "line was '$line'"
Check 'the line carries queue_status' ($line -match 'running') "line was '$line'"
Check 'no blank name, ever' ($line -notmatch '\s{2,}/') "line was '$line'"

$indexed = 0; $total = 0
foreach ($r in $rows) {
    if ((Get-FileState $r) -eq 'skipped') { continue }
    $indexed += [int]$r.indexed_pages; $total += [int]$r.total_pages
}
Check 'totals are the recorded ones' ($indexed -eq 37 -and $total -eq 129) "got $indexed/$total"

# ── 2. complete: the run is recognised as finished ───────────────────────
Write-Host 'completed response (129 of 129)'
$rows = Get-StatusRows $recorded.complete
$done = 0; $skipped = 0
foreach ($r in $rows) {
    $state = Get-FileState $r
    if ($state -eq 'skipped') { $skipped += 1; $done += 1; continue }
    if ($state -eq 'complete') { $done += 1 }
}
Check 'every file finished' ($done -eq $rows.Count) "$done of $($rows.Count)"
Check 'the combined set is the one skip' ($skipped -eq 1) "got $skipped"

# ── 3. the coercion itself, which is what actually happened ──────────────
Write-Host 'a response whose rows have been coerced to strings'
function Invoke-TheOldBug { param([string[]]$Files)
    $files = @($recorded.complete.files)      # same name as the parameter
    return $files
}
$coerced = Invoke-TheOldBug
Check 'the coercion still reproduces' ($coerced[0] -is [string]) "got $($coerced[0].GetType().Name)"
$threw = $false
try { Get-StatusRows ([pscustomobject]@{ files = $coerced }) } catch { $threw = $true }
Check 'Get-StatusRows refuses coerced rows' $threw 'it accepted strings and would render zeroes'

# ── 4. the script cannot reintroduce the name collision ──────────────────
Write-Host 'the script itself'
# Statements only. The comment above the parameter quotes the line that broke,
# on purpose, so the next reader knows what not to write.
$code = ($src -split "`n" | Where-Object { $_ -notmatch '^\s*#' }) -join "`n"
Check 'no $files assignment in the poll loop' ($code -notmatch '\$files\s*=\s*@\(\$status') 'the parameter name is in use again'
Check 'the parameter is not called Files' ($code -notmatch '\[string\[\]\]\$Files\b') 'param([string[]]$Files) is back'

Write-Host ''
if ($failures.Count -gt 0) {
    Write-Host "$($failures.Count) failure(s)" -ForegroundColor Red
    exit 1
}
Write-Host 'status display: all checks passed' -ForegroundColor Green
exit 0
