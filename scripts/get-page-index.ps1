# get-page-index.ps1
#
# Re-indexes the plans on 588 Boyland, waits for it to finish, then saves what
# was stored:
#   1. POST reindex-all on the project (asks you to type REINDEX first)
#   2. polls document-index-status every 30 seconds, printing progress, until
#      every PDF is fully indexed or marked "combined set - skipped"
#   3. saves the list_sheets dump to .\debug-out\list-sheets.json, the final
#      status to .\debug-out\index-status.json, and the four sheet dumps to
#      .\debug-out\<sheet>.json
#
# THIS WRITES TO THE SERVER. Step 1 queues a re-index. Without -Resume it first
# deletes the project's existing plan index, so WhatsApp plan questions on this
# project answer "nothing matched" until indexing finishes. Do not deploy while
# it runs; if a deploy or restart interrupts it, run again with -Resume.
#
# The password is read as a SecureString, used once in memory for the login
# request, and cleared. The token is never written to disk.
#
# Requires an admin or owner account: reindex-all and the page-index dump both
# refuse anyone else.
#
# Run from a PowerShell prompt:
#   powershell -ExecutionPolicy Bypass -File .\get-page-index.ps1
#   powershell -ExecutionPolicy Bypass -File .\get-page-index.ps1 -Resume
#   powershell -ExecutionPolicy Bypass -File .\get-page-index.ps1 -SkipReindex
#
# Re-index only some files (reindex-document per file, not reindex-all). Each
# value is part of a file name and must match exactly one PDF on the project:
#   powershell -ExecutionPolicy Bypass -File .\get-page-index.ps1 -Files "MH - 7.2.26,SP 4th floor after CO"
# That is, for each matched file:
#   POST https://api.levelog.com/api/projects/<project id>/reindex-document?resume=false
#   body: {"file_id": "<file id>"}
# resume=false deletes that file's stored pages first and indexes it again.
#
# Indexing runs from a queue stored in the database, so a container restart
# does not lose it: the server picks the queue up again on boot. Progress comes
# from that queue (document-index-status no longer downloads the PDFs).

param(
    [switch]$Resume,          # keep finished pages, index only the rest
    [switch]$SkipReindex,     # no re-index: just the dumps
    [string[]]$FileMatch,     # re-index only these files (parts of file names)
                              # NOT $Files: a param() type constraint outlives the
                              # binding, PowerShell variable names are case-
                              # insensitive, and `$files = @($status.files)` below
                              # then coerced every response object to a string.
    [int]$PollSeconds = 30,
    [int]$StallMinutes = 20   # stop waiting after this long with no progress
)

$ErrorActionPreference = 'Stop'

$BaseUrl      = 'https://api.levelog.com'
$Sheets       = @('S-001', 'S-100', 'A-500.00', 'P-100.00')
$AddressWords = @('588', 'boyland')
$OutDir       = Join-Path (Get-Location) 'debug-out'
$SkippedState = 'skipped_combined_set'

# Windows PowerShell 5.1 can default to TLS 1.0, which the API refuses.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Reads the JSON body out of a failed request so a 401 or 403 says why.
function Get-ErrorBody {
    param($ErrorRecord)
    try {
        $resp = $ErrorRecord.Exception.Response
        if ($null -eq $resp) { return $ErrorRecord.Exception.Message }
        $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
        $body = $reader.ReadToEnd()
        $reader.Close()
        $code = [int]$resp.StatusCode
        return "HTTP $code $body"
    }
    catch {
        return $ErrorRecord.Exception.Message
    }
}

# UTF-8 without a BOM. Out-File in 5.1 writes UTF-16, which most JSON tools
# misread.
function Save-Utf8 {
    param([string]$Path, [string]$Text)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

function Get-Stamp {
    return (Get-Date).ToString('HH:mm:ss')
}

# The per-file rows of a document-index-status response, and one rendered
# progress line. Both are functions so a test can drive them from a recorded
# response without a login — see tests/test_status_display.ps1.
#
# THE GUARD IS THE POINT. On 2026-09-16 a full re-index displayed blank names
# and 0/0 for its whole run, because the rows arrived here as [string] and
# every property read came back $null. A row that is not an object is a bug in
# this script, not a server that sent nothing, and it now says so instead of
# rendering zeroes for ninety minutes.
# AND AN EMPTY LIST IS NOT A QUIET DAY. The guard above catches rows that
# arrived as [string]. It does not catch there being NO rows, and that renders
# identically: "0/0 files finished ... 0/0 pages", no per-file lines, and an
# exit condition ($done -eq $statusRows.Count) that 0 -eq 0 satisfies only by
# accident — with `$statusRows.Count -gt 0` guarding it, the poll runs to the
# stall timeout instead. The endpoint filters by company and by the
# site-device allow-list, so a caller can be authorised for the project and
# still be handed nothing.
function Get-StatusRows {
    param($Status)
    $rows = @()
    foreach ($r in @($Status.files)) {
        if ($r -isnot [psobject] -or $null -eq $r.file_id) {
            throw "document-index-status row is $($r.GetType().Name), not an object — the response was coerced before it was read"
        }
        $rows += $r
    }
    if ($rows.Count -eq 0) {
        throw "document-index-status returned no files for this project — the account cannot see them, not that there are none to index"
    }
    return $rows
}

function Format-StatusLine {
    param($File)
    return ("    {0}  {1}/{2}  {3}" -f $File.file_name, [int]$File.indexed_pages,
            [int]$File.total_pages, $File.queue_status)
}

# One file's state from a document-index-status entry. The queue's own status
# decides when there is one; the page counts decide only for a file that was
# never queued (a server without the queue).
function Get-FileState {
    param($File)
    $indexed = [int]$File.indexed_pages
    $total = [int]$File.total_pages
    $q = $File.queue_status
    if ($null -ne $File.index_status -and $File.index_status.state -eq $SkippedState) {
        return 'skipped'
    }
    if ($q -eq 'skipped') { return 'skipped' }
    if ($q -eq 'done') { return 'complete' }
    if ($q -eq 'failed' -or $q -eq 'cancelled') { return 'failed' }
    if ($q -eq 'queued' -or $q -eq 'running') { return 'indexing' }
    if ($total -gt 0 -and $indexed -ge $total) {
        return 'complete'
    }
    return 'indexing'
}

# ── Credentials ─────────────────────────────────────────────────────────────

$email = Read-Host 'Email'
$securePassword = Read-Host 'Password' -AsSecureString

$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    $loginBody = @{ email = $email; password = $plainPassword } | ConvertTo-Json -Compress
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $plainPassword = $null
}

# ── Login ───────────────────────────────────────────────────────────────────

Write-Host 'Logging in...'
try {
    $login = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/login" `
        -ContentType 'application/json' -Body $loginBody
}
catch {
    $loginBody = $null
    Write-Host ("Login failed: " + (Get-ErrorBody $_)) -ForegroundColor Red
    exit 1
}
$loginBody = $null

if (-not $login.token) {
    Write-Host 'Login returned no token.' -ForegroundColor Red
    exit 1
}
$headers = @{ Authorization = "Bearer $($login.token)" }

# ── Find 588 Boyland by address ─────────────────────────────────────────────

Write-Host 'Looking up the project...'
$allProjects = @()
$skip = 0
do {
    try {
        $page = Invoke-RestMethod -Method Get `
            -Uri "$BaseUrl/api/projects?limit=200&skip=$skip" -Headers $headers
    }
    catch {
        Write-Host ("Project list failed: " + (Get-ErrorBody $_)) -ForegroundColor Red
        exit 1
    }
    $allProjects += @($page.items)
    $skip += 200
} while ($page.has_more)

# Every address word must appear, in the address or the name. More than one
# match stops the script rather than guessing which project was meant.
# Named $found, not $matches: $matches is a PowerShell automatic variable that
# any -match operator silently overwrites.
$found = @($allProjects | Where-Object {
    $haystack = ("$($_.address) $($_.location) $($_.name)").ToLower()
    $hit = $true
    foreach ($w in $AddressWords) {
        if (-not $haystack.Contains($w)) { $hit = $false }
    }
    $hit
})

if ($found.Count -eq 0) {
    Write-Host "No project matched: $($AddressWords -join ' + ')" -ForegroundColor Red
    Write-Host "Checked $($allProjects.Count) project(s)."
    exit 1
}
if ($found.Count -gt 1) {
    Write-Host 'More than one project matched. Not guessing:' -ForegroundColor Red
    foreach ($m in $found) {
        Write-Host "  $($m.id)  $($m.name)  $($m.address)"
    }
    exit 1
}

$project = $found[0]
$projectId = [Uri]::EscapeDataString($project.id)
Write-Host "Found: $($project.name) ($($project.address))  id=$($project.id)"

if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}

# ── 1. Re-index ─────────────────────────────────────────────────────────────

$queued = 0
$watchIds = @()

# powershell -File hands a comma list over as ONE string, so split it here.
$fileParts = @()
foreach ($entry in @($FileMatch)) {
    foreach ($part in ("$entry" -split ',')) {
        if ($part.Trim()) { $fileParts += $part.Trim() }
    }
}

if (-not $SkipReindex -and $fileParts.Count -gt 0) {
    # ── 1a. Re-index named files only ──────────────────────────────────────
    try {
        $listing = Invoke-RestMethod -Method Get -Headers $headers `
            -Uri "$BaseUrl/api/projects/$projectId/document-index-status"
    }
    catch {
        Write-Host ("Could not list the project's PDFs: " + (Get-ErrorBody $_)) -ForegroundColor Red
        exit 1
    }
    $pdfs = @($listing.files)
    $targets = @()
    foreach ($part in $fileParts) {
        $hits = @($pdfs | Where-Object { "$($_.file_name)".ToLower().Contains($part.ToLower()) })
        if ($hits.Count -eq 0) {
            Write-Host "No PDF on this project matches '$part'. Files are:" -ForegroundColor Red
            foreach ($p in $pdfs) { Write-Host "  $($p.file_name)" }
            exit 1
        }
        if ($hits.Count -gt 1) {
            Write-Host "'$part' matches more than one PDF. Not guessing:" -ForegroundColor Red
            foreach ($h in $hits) { Write-Host "  $($h.file_name)" }
            exit 1
        }
        if (@($targets | Where-Object { $_.file_id -eq $hits[0].file_id }).Count -eq 0) {
            $targets += $hits[0]
        }
    }

    Write-Host ''
    $resumeFlag = 'false'
    if ($Resume) {
        $resumeFlag = 'true'
        Write-Host 'RESUME: finished pages of these files are kept; only the rest are indexed.' -ForegroundColor Yellow
        $word = 'RESUME'
    }
    else {
        Write-Host "These files' stored pages are deleted first and indexed again:" -ForegroundColor Yellow
        $word = 'REINDEX'
    }
    foreach ($t in $targets) { Write-Host "  $($t.file_name)  (file_id $($t.file_id))" }
    Write-Host 'Plan questions answered from these files come back once they finish. Do not deploy while it runs.' -ForegroundColor Yellow
    $typed = Read-Host "Type $word to continue"
    if ($typed -cne $word) {
        Write-Host 'Not confirmed. Nothing was sent.' -ForegroundColor Red
        exit 1
    }

    foreach ($t in $targets) {
        $body = @{ file_id = $t.file_id } | ConvertTo-Json -Compress
        try {
            $r = Invoke-RestMethod -Method Post -Headers $headers -ContentType 'application/json' `
                -Uri "$BaseUrl/api/projects/$projectId/reindex-document?resume=$resumeFlag" -Body $body
            Write-Host "[$(Get-Stamp)] $($r.status): $($r.file_name) ($($r.total_pages) pages)"
            $queued += 1
            $watchIds += $t.file_id
        }
        catch {
            Write-Host ("reindex-document failed for $($t.file_name): " + (Get-ErrorBody $_)) -ForegroundColor Red
        }
    }
    if ($queued -eq 0) {
        Write-Host 'Nothing was queued.' -ForegroundColor Red
        exit 1
    }
}
elseif (-not $SkipReindex) {
    Write-Host ''
    if ($Resume) {
        Write-Host 'RESUME: finished pages are kept; only the rest are indexed.' -ForegroundColor Yellow
        $word = 'RESUME'
    }
    else {
        Write-Host 'FULL RE-INDEX: the existing plan index for this project is deleted first.' -ForegroundColor Yellow
        Write-Host 'WhatsApp plan questions on this project answer "nothing matched" until it finishes.' -ForegroundColor Yellow
        $word = 'REINDEX'
    }
    Write-Host 'Do not deploy while it runs.' -ForegroundColor Yellow
    $typed = Read-Host "Type $word to continue"
    if ($typed -cne $word) {
        Write-Host 'Not confirmed. Nothing was sent.' -ForegroundColor Red
        exit 1
    }

    $resumeFlag = 'false'
    if ($Resume) { $resumeFlag = 'true' }
    try {
        $reindex = Invoke-RestMethod -Method Post -Headers $headers -ContentType 'application/json' `
            -Uri "$BaseUrl/api/projects/$projectId/reindex-all?resume=$resumeFlag" -Body '{}'
    }
    catch {
        Write-Host ("reindex-all failed: " + (Get-ErrorBody $_)) -ForegroundColor Red
        exit 1
    }
    $queued = [int]$reindex.queued
    Write-Host "[$(Get-Stamp)] Queued $queued file(s):"
    foreach ($n in @($reindex.files)) {
        Write-Host "  $n"
    }
}

# ── 2. Wait for it ──────────────────────────────────────────────────────────

$status = $null
if ($queued -gt 0) {
    Write-Host ''
    Write-Host "Polling every $PollSeconds s. Ctrl+C stops the wait; indexing carries on server-side."
    $lastTotal = -1
    $lastChange = Get-Date
    $errors = 0
    while ($true) {
        Start-Sleep -Seconds $PollSeconds
        try {
            $status = Invoke-RestMethod -Method Get -Headers $headers `
                -Uri "$BaseUrl/api/projects/$projectId/document-index-status"
            $errors = 0
        }
        catch {
            $errors += 1
            Write-Host ("[$(Get-Stamp)] status check failed ($errors of 5): " + (Get-ErrorBody $_)) -ForegroundColor Yellow
            if ($errors -ge 5) {
                Write-Host 'Five failures in a row. Stopping the wait.' -ForegroundColor Red
                break
            }
            continue
        }

        $statusRows = @(Get-StatusRows $status)
        if ($watchIds.Count -gt 0) {
            # -FileMatch: wait for the files re-indexed, not the whole project.
            $statusRows = @($statusRows | Where-Object { $watchIds -contains $_.file_id })
        }
        $done = 0
        $skipped = 0
        $failed = @()
        $pagesIndexed = 0
        $pagesTotal = 0
        $pending = @()
        foreach ($f in $statusRows) {
            $state = Get-FileState $f
            if ($state -eq 'skipped') {
                $skipped += 1
                $done += 1
                continue
            }
            $pagesIndexed += [int]$f.indexed_pages
            $pagesTotal += [int]$f.total_pages
            if ($state -eq 'complete') {
                $done += 1
            }
            elseif ($state -eq 'failed') {
                $done += 1
                $failed += $f
            }
            else {
                $pending += $f
            }
        }

        Write-Host ("[{0}] {1}/{2} files finished ({3} skipped as combined sets, {4} failed)  {5}/{6} pages" -f `
            (Get-Stamp), $done, $statusRows.Count, $skipped, $failed.Count, $pagesIndexed, $pagesTotal)
        foreach ($f in $pending) {
            Write-Host (Format-StatusLine $f)
        }
        foreach ($f in $failed) {
            $why = ''
            if ($null -ne $f.queue) { $why = $f.queue.error }
            Write-Host ("    FAILED {0}: {1}" -f $f.file_name, $why) -ForegroundColor Red
        }

        if ($statusRows.Count -gt 0 -and $done -eq $statusRows.Count) {
            if ($failed.Count -gt 0) {
                Write-Host "[$(Get-Stamp)] Every file has finished; $($failed.Count) failed (listed above)." -ForegroundColor Yellow
            }
            else {
                Write-Host "[$(Get-Stamp)] Every file is indexed or skipped." -ForegroundColor Green
            }
            break
        }

        # A NUMBER THAT STOPS MOVING. The status endpoint does not count pages
        # stored as specification pages, and reports 0 total when it cannot
        # read a PDF, so a file can sit one short of "complete" for good.
        if ($pagesIndexed -ne $lastTotal) {
            $lastTotal = $pagesIndexed
            $lastChange = Get-Date
        }
        elseif (((Get-Date) - $lastChange).TotalMinutes -ge $StallMinutes) {
            Write-Host "No progress for $StallMinutes minutes. Stopping the wait." -ForegroundColor Yellow
            Write-Host '  Still short: a file with specification pages never reaches its total here,' -ForegroundColor Yellow
            Write-Host '  and a PDF the server could not read reports 0 pages. If a deploy or restart' -ForegroundColor Yellow
            Write-Host '  interrupted the run, start it again with -Resume.' -ForegroundColor Yellow
            break
        }
    }
}

# The final status, whether or not the wait ran.
try {
    $statusResp = Invoke-WebRequest -Method Get -Headers $headers -UseBasicParsing `
        -Uri "$BaseUrl/api/projects/$projectId/document-index-status"
    $statusPath = Join-Path $OutDir 'index-status.json'
    Save-Utf8 -Path $statusPath -Text $statusResp.Content
}
catch {
    $statusPath = $null
    Write-Host ("Final status failed: " + (Get-ErrorBody $_)) -ForegroundColor Yellow
}

$saved = @()
if ($statusPath) { $saved += $statusPath }

# ── 3. list_sheets dump ─────────────────────────────────────────────────────

Write-Host ''
Write-Host 'Fetching list_sheets...'
try {
    $resp = Invoke-WebRequest -Method Get -Headers $headers -UseBasicParsing `
        -Uri "$BaseUrl/api/whatsapp/debug/page-index?project_id=$projectId&list_sheets=true"
    $path = Join-Path $OutDir 'list-sheets.json'
    Save-Utf8 -Path $path -Text $resp.Content
    $saved += $path
    try {
        $ls = $resp.Content | ConvertFrom-Json
        $rows = @($ls.sheets)
        $v3 = @($rows | Where-Object { [int]$_.index_version -ge 3 }).Count
        $flagged = @($rows | Where-Object {
            $null -ne $_.extraction_flags -and @($_.extraction_flags.PSObject.Properties).Count -gt 0
        }).Count
        Write-Host ("  rows={0}  current={1}  without sheet number={2}  index v3={3}  with extraction flags={4}  chunks={5}" -f `
            $ls.rows, $ls.current_rows, $ls.rows_without_sheet_number, $v3, $flagged, $ls.chunks)
    }
    catch {
        Write-Host '  saved, but the body was not valid JSON' -ForegroundColor Yellow
    }
}
catch {
    Write-Host ("  failed: " + (Get-ErrorBody $_)) -ForegroundColor Red
}

# ── Each sheet ──────────────────────────────────────────────────────────────

foreach ($sheet in $Sheets) {
    $uri = "$BaseUrl/api/whatsapp/debug/page-index" +
        "?project_id=$projectId" +
        "&sheet=$([Uri]::EscapeDataString($sheet))&limit=25"

    Write-Host "Fetching $sheet..."
    try {
        # Invoke-WebRequest, not Invoke-RestMethod, so the body is saved exactly
        # as the server sent it rather than parsed and re-serialized.
        $resp = Invoke-WebRequest -Method Get -Uri $uri -Headers $headers -UseBasicParsing
    }
    catch {
        Write-Host ("  failed: " + (Get-ErrorBody $_)) -ForegroundColor Red
        continue
    }

    $path = Join-Path $OutDir "$sheet.json"
    Save-Utf8 -Path $path -Text $resp.Content
    $saved += $path

    # A one-line reading, so an empty or thin sheet is obvious without opening
    # the file.
    try {
        $data = $resp.Content | ConvertFrom-Json
        # Counted off the pages array, not $data.count: on a PSCustomObject the
        # JSON key and PowerShell's intrinsic .Count share a name.
        if (@($data.pages).Count -eq 0) {
            Write-Host "  0 pages stored for $sheet" -ForegroundColor Yellow
        }
        else {
            foreach ($pg in @($data.pages)) {
                Write-Host ("  page {0}: _searchable_chars={1}" -f $pg.page_number, $pg._searchable_chars)
            }
        }
    }
    catch {
        Write-Host '  saved, but the body was not valid JSON' -ForegroundColor Yellow
    }
}

$headers = $null
$login = $null

# ── Paths ───────────────────────────────────────────────────────────────────

Write-Host ''
if ($saved.Count -eq 0) {
    Write-Host 'Nothing was saved.' -ForegroundColor Red
    exit 1
}
Write-Host 'Saved:'
foreach ($p in $saved) {
    Write-Host "  $p"
}
