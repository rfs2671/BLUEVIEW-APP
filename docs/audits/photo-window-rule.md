# The photo window — a clock, not a permission model

**Date:** 2026-09-03
**Branch point:** `origin/main` @ `6a40658`
**Scope:** the photo code only. The report renderer, the startup/scheduler region, the
create region, `sweep_stale_end_of_day_logs`, the superintendent log, `offlineQueue`, and
`daily_jobsite`'s time fields belong to other workers and are not touched here.

## The ruling being implemented

> Photos can be added or removed until the end of that log's day. After that the photo set
> is closed. No removal, no append, no exceptions.

No per-photo permission model. No `added_after_filing` predicate. No chain-walking. No
tombstones. No new R2 deletion path.

---

## 1. What defines end-of-day

**Recommendation: 03:00 America/New_York on the day after the log's `date` — the existing
sweep boundary.**

Expressed so that it needs no offset arithmetic and no server clock on the client:

```
window_day(now) = eastern_date(now - 3 hours)
window is OPEN  iff  logbook["date"] >= window_day(now)
```

At 02:59 Eastern on D+1, `now - 3h` is 23:59 Eastern on D, so `window_day` is D and a log
dated D is still open. At 03:00 Eastern on D+1, `now - 3h` is 00:00 Eastern on D+1,
`window_day` becomes D+1, and the log dated D is closed. Subtracting three hours is a pure
UTC subtraction; the only timezone operation is `eastern_date`, which both halves of the
system already have (`backend/server.py:1523` `eastern_date`, `frontend/src/utils/dates.js:31`
`easternDate`). Everything after that is a `YYYY-MM-DD` string comparison, so Python and
JavaScript cannot disagree, and DST cannot move the answer.

### Why this and not the other two

**Not "hours after filing."** There is no filing instant to anchor to. Grep-verified: the
logbook document carries no `filed_at`, no `log_date`, no `work_date`. `submitted_at` is not
written on every path, and the client's own `filedAttestation`
(`frontend/src/utils/filedLogSummary.js:282`) resolves `filedAt` as
`updated_at || submitted_at || created_at` — a display value that an amendment moves. Three
further objections, any one of which is fatal:

- A log that is **never filed** would never close. `sweep_stale_end_of_day_logs` deliberately
  declines to freeze a stale unsigned log (`backend/server.py:4383-4390`) and flags it
  instead, so those logs exist in production — 65 submitted logs carry an unaffirmed
  signature per the note at `server.py:22887`. An anchor that requires a filing gives the
  one class of record that most needs closing an infinite window.
- Two logs for the **same day** would close at different times, so there is no sentence a CP
  can learn. "Your photos close tonight" becomes "your photos close at some hour that
  depends on when you happened to press Submit."
- It is a *permission-ish* rule wearing a clock's clothes — it makes the window a function
  of an actor's behaviour rather than of the calendar. The ruling is explicitly a clock.

**Not plain midnight Eastern** (the log's Eastern date rolling over). It is the right
*idea* — it is the same predicate `sweep_stale_end_of_day_logs` uses, `date < eastern_date(now)`
(`server.py:4368`) — but it is not the boundary the system actually observes. The sweep
evaluates that predicate at 03:00, not at 00:00 (`CronTrigger(hour=3, minute=0,
timezone="America/New_York")`, `server.py:41949`). So the instant a daily narrative really
stops being live is already 03:00 on D+1. Choosing midnight would introduce a **second**
boundary three hours before the one that already exists, and a CP would have to hold two
different end-of-days in his head for the same document.

**And it is the answer to the operator's own objection.** The 23:00 filer gets four hours
instead of one. That is not a large number, but it is four times the number, it is bought
with no new concept, and the alternative that would buy him more is the filing-anchored
window that fails for the three reasons above.

### A log filed at 02:00

Two different logs get filed at 02:00 and the rule separates them correctly, because the
rule keys on the log's `date` and not on the wall clock at filing.

- **Filed at 02:00 stamped with today (D).** `window_day` at that moment is D-1, so `D >= D-1`:
  the window is **open**, and stays open until 03:00 on D+1 — about 25 hours. Nothing
  surprising.
- **Filed at 02:00 for the shift that ended last night (`date` = D-1)** — the night-shift CP
  writing up the day that just finished. `window_day` at 02:00 on D is D-1, so `D-1 >= D-1`:
  the window is **open**, and closes one hour later at 03:00. Under a plain-midnight rule it
  would have been **already closed at the moment he filed** — he would file a log and be
  unable to attach a photograph to it, ever, with no action available that could change
  that. This case is the strongest single argument for the sweep boundary over midnight.

Both of those are the same arithmetic; neither needs a special case.

### One rule for every log type

The ruling says "that log's day," not "end-of-day logs only," and the window is applied
uniformly. An IMMEDIATE type (fall protection, hot work) locks the moment it is signed, so
its photo set was already closed by the lock long before 03:00 — the window changes nothing
for it. A `visit` type (`site_superintendent_log`) is excluded from the freeze sweep but is
not excluded from the clock: its day still ends. Keeping one rule avoids a second table
readers would have to consult, and `LOGBOOK_TIMING_CLASS` is not consulted at all.

---

## 2. How the append endpoint lives under this rule

`POST /api/logbooks/{id}/activity-photo` — `append_activity_photo`,
`backend/server.py:23127-23130`.

**Today it is unbounded in every direction.** It is the one write path that reads status
without gating on it — its own comment says so: "STATUS IS READ, NOT GATED ON"
(`server.py:23120`). It accepts a draft, it accepts a submitted log, it accepts a log
frozen by the sweep, and it accepts all of them for a log dated any number of years ago.
The status is consulted only to decide whether to stamp `added_after_filing`. So the
endpoint is currently the only way to change the content of a frozen compliance record, and
there is no clock on it at all.

Note the asymmetry that made this reachable: the sibling capture route
`upload_logbook_photo` already refuses a filed log with **409
`FILED_LOG_PHOTO_CAPTURE_REFUSED`** (`server.py:21851-21855`), and `update_logbook`/
`create_logbook` already refuse a data write to a filed log with **409
`FILED_LOG_DATA_IMMUTABLE`** (`server.py:22896-22899`, `22596-22599`). Every neighbour of
this endpoint has a gate. It has none.

**The change.** After `_authorize_logbook_view` returns the document and **before the bytes
are read**, the window is evaluated and a closed window is refused:

```
409  {"code": "PHOTO_WINDOW_CLOSED", "closed_after": "<the log's date>"}
```

**Why 409 and not 423.** 423 means *locked*, and the log frequently is not. A stale unsigned
daily narrative is `is_locked: false` forever — the sweep refuses to freeze it — so a 423
would be a false statement about the document for exactly the class of log where this gate
matters most. 409 follows the established convention in this file: the server names the
condition, the client owns the wording (`FILED_LOG_DATA_IMMUTABLE`,
`FILED_LOG_PHOTO_CAPTURE_REFUSED`, `LOGBOOK_WITHDRAWN`, `ACTIVITY_HAS_NO_IDENTITY` all do
this).

**Why 4xx specifically, and not 5xx.** This is load-bearing for the offline queue.
`shouldQueueError` in `frontend/src/utils/filedPhotoQueue.js:94-100` retains an item on 5xx
or on a network failure and **drops it on any 4xx**, recording it in the rejected list with
its `code`. A 5xx here would make a phone retry a photograph for a permanently closed log at
every app launch, forever. The 409 makes the queue stop, and the rejected-list UI already on
the photos screen (`frontend/app/logbooks/photos.jsx:305-329`) renders the reason.

**Why before the bytes are read.** The capture route's docstring states the principle —
"it runs BEFORE the bytes are read, so a refusal costs no storage and no transfer. That
ordering is what makes 'nothing is stored' true by construction rather than by luck"
(`server.py:21836-21838`). The append route's existing shape reads the file first; the gate
goes above that read so a refused append cannot park bytes in R2 for a row that will never
be written. Given finding 5 below — nothing ever reclaims an orphan — this ordering is not
a nicety.

**What is deliberately NOT changed.** `added_after_filing` and its stamp stay exactly as they
are. Under the new rule a photograph can still be appended to a filed log within the same
day, so the flag still has a job (the report renderer's caption, which another worker owns).
The ruling forbids using it as a *predicate*; it does not retire it as a *record*.

---

## 3. The window is enforced server-side

**The rule.** `logbook_photo_window_is_open(logbook, now)` in `backend/server.py`, evaluated
inside `append_activity_photo` against the **stored** document. The client sends no date, no
timestamp and no window claim — the only fields on the wire remain `activity_id`, `photo_id`
and the file. There is nothing a device can assert that moves the boundary, which is the
property that makes this a rule rather than an affordance. A device with a wrong clock, a
device in another timezone, a replayed request, a curl against the API, and a queued upload
draining a week late all get the same answer.

**The affordance.** `isOpenForPhotoAppend(log)` in
`frontend/src/utils/logbookEditable.js:79-82` — today literally `!isOpenForEditing(log)`,
with no time in it — gains the same window, computed from `log.date` and the device clock.
This is what makes the controls disappear rather than fail (item 4). It is not trusted by
anything.

**They can disagree, and the disagreement is safe in both directions.** A fast device clock
hides the control while the server would still have accepted — the CP loses an affordance
he could recover by fixing his clock, and nothing false is written. A slow device clock
shows the control and the server refuses on tap — the one case the operator wants avoided,
and it is now bounded by the size of the clock error rather than being the permanent state
of affairs.

**Two paths remain open server-side, and both are already closed by an existing guard —
except one.**

- *Capture* (`upload_logbook_photo`) already 409s on a filed log, so a closed filed log
  cannot get bytes. But a log that is **closed by the clock and never filed** (stale,
  unsigned, `status: draft`) still passes that guard, and `update_logbook` will still accept
  a whole new `data` for it, photos included.
- **This is a real remaining hole and I am not closing it in this change**, for the reason
  the append feature's own test file already records: a server-side diff of the client's blob
  is not a sound way to detect "only the photos changed," because "the blob is not a faithful
  echo of the stored document (hydrate reconciles crews on any submitted-but-unlocked log,
  and `photoForPayload` is lossy and conditional)"
  (`backend/tests/test_filed_log_photo_append.py:16-21`). Closing it properly means either
  refusing every `data` write to a clock-closed log — which would also block the affirmation
  repair path that `FILED_LOG_DATA_IMMUTABLE` was deliberately scoped to preserve
  (`server.py:22882-22886`) — or giving photos their own sub-document. **Flagged for the
  operator as the next decision, not silently left as an assumed non-issue.** Its blast
  radius today is narrower than it sounds: it needs a log that is past its day AND was never
  submitted, and the client will not offer the editor for one because the entry points
  already route by filed state.

---

## 4. What the CP sees when it closes

**Controls disappear; nothing fails on tap.** The window is asked of the same shared
predicate the screens already ask, so the affordances vanish at four layers without any
screen learning about dates:

1. **The entry row.** `filedPhotoTarget` in `frontend/app/logbooks/index.jsx:432-439` decides
   whether the "Photographs" row renders under a filed card at all. With the window applied,
   a log whose day has ended has no row — the CP never navigates to the screen.
2. **The screen guard.** `frontend/app/logbooks/photos.jsx:277` already refuses with a card
   when `!isOpenForPhotoAppend(log)`. A closed window now lands there, so a typed URL or a
   stale back-stack entry gets an explanation rather than a camera button.
3. **The add buttons.** `photos.jsx:382` renders per-row add controls only when the row is
   addable; a closed window removes them for every row.
4. **`FiledLogView`'s "Add photographs" button** (`frontend/src/components/logbookStepper/FiledLogView.jsx:229-237`)
   is behind the same predicate.

The read path is untouched at every layer. A closed log still shows its photographs, full
size, in the lightbox — closing the set is not hiding it.

**How the client learns the window state — and why it works offline.** It computes it. It
does **not** ask the server, and it does not need the server's clock:

- The only input is `log.date`, a `YYYY-MM-DD` string already on every logbook object the
  client holds (read today at `photos.jsx:237`, used as a query param at
  `frontend/src/utils/api.js:1048`, the sort key at `server.py:21995`). It is in the cached
  document, so it survives an app launch with no network.
- The other input is the device's own clock, converted with `easternDate` from
  `frontend/src/utils/dates.js` — `Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' })`,
  the pattern already used in eight places in this app, no native module and no new
  dependency.

So a phone in a cellar with no signal for two days still hides the control on a log whose
day has ended, and still shows it on today's. **This is the decisive practical argument for
a date-derived boundary over a filing-derived one:** `date` is on the wire and is stable,
and a filing instant is neither.

**The offline photograph taken inside the window and drained outside it.** A photo shot at
23:50 on D, queued because the cellar had no signal, drained at 09:00 on D+1: the server
refuses it, 409, and `filedPhotoQueue` moves it to the rejected list where the CP sees it
with a reason. **This is the correct outcome and it should not be softened.** The alternative
is to honour a client-supplied capture time, which is exactly the "signature whose wording
the client chooses" problem the codebase already refuses elsewhere (`server.py:4227-4230`) —
a device could claim any capture time and the window would stop being a rule. The rule is
about when the *record changes*, not when the shutter fired. What the CP must get is a
truthful message, and the rejected-list UI is already built to give him one.

---

## 5. Does the existing sweep reclaim the orphaned R2 objects? **No. Nothing does.**

**This overturns the premise in the instruction.** The instruction says removed-in-window R2
objects "are reclaimed by the EXISTING sweep." There is no such sweep. It does not exist in
this codebase, and it is not scheduled anywhere.

- The 03:00 job (`_logbook_nightly_tick`, `server.py:41916`, registered at `41947-41954`) is
  **entirely Mongo**. `sweep_stale_end_of_day_logs` sets `is_locked`/`finalized_at`/`status`
  and touches no object storage. Neither does `sweep_signature_ledger_gaps`, nor the missing/
  deficiency detectors it also runs.
- Nothing anywhere lists the R2 bucket and asks Mongo whether a key is still referenced. The
  bucket is enumerated in exactly one function, `_r2_delete_prefix` (`server.py:12116-12153`),
  which is a blind prefix wipe — its docstring says it exists "for artefacts that no DB row
  enumerates" — and its only caller is `hard_delete_project`, an owner-only, manual,
  irreversible HTTP DELETE.
- There is no bucket lifecycle rule (`put_bucket_lifecycle` / `LifecycleConfiguration`: zero
  hits) and no minimum-age grace period on any object. `SOFT_DELETE_RETENTION_DAYS` and the
  7-year `RETENTION_YEARS` are both Mongo-side.
- Every R2 deletion in the repo, complete: `_r2_delete_prefix` (`12116`), the per-file delete
  inside `hard_delete_project` (`12248`), `delete_project_file` (`21425`), and a rename in
  `repair_file_names` (`39517`). All four are synchronous and human-initiated.
- `backend/scripts/audit_r2_photo_exposure.js` measures the *inverse* exposure — Mongo rows
  that would lose their objects — and is manual and read-only.

**And this deserves its own item, because the leak is on every use, not on an edge case.**
The pre-filing remove control orphans an object *every single time it is used while online*.
The upload happens at **capture**, not at save: `frontend/app/logbooks/daily_jobsite.jsx:1305-1315`
fires `uploadOneCapture` → `uploadCapturePhoto` as soon as compression finishes, seconds
after the shutter. And every remove control is local-state only — there is no photo DELETE
call anywhere in the client (the only `apiClient.delete` touching logbooks is whole-log
delete, `frontend/src/utils/api.js:1080`):

- `daily_jobsite.jsx:1458-1461` `removeActivityPhoto` — `filter` on local state
- `daily_jobsite.jsx:247-251` `dropPhoto` — `filter` on local state
- `daily_jobsite.jsx:1451-1456` `handleDeleteShot` (the in-camera X) — same, plus a local
  cache delete
- `fall_protection.jsx:304-307` `removePhoto` — same

So: CP takes a photo, looks at it, doesn't like it, taps the X. The bytes are already in R2
under `logbook-photos/{project_id}/{activity_id}/{photo_id}.jpg`. The document never
references them. **Nothing will ever delete them** short of hard-deleting the whole project,
which is owner-only, manual, and refused for seven years after job completion by
`retention_refusal()`. Every discarded shot on every jobsite is permanent, billed storage.

**Consequence for this change — the ruling's reclaim clause has no implementation to rely
on.** The instruction is explicit that no new deletion path is to be written here, and I have
written none. But the operator should know that "removed-in-window objects are reclaimed"
is currently false for every removal the app has ever performed, and that the number is not
small: it is one object per discarded shot since the capture-time upload landed. The
remedy is a reconciliation job (walk `logbook-photos/{project_id}/` prefixes, subtract the
keys `db.logbooks` still references, delete what is left older than some grace period) —
sized and scheduled as its own piece of work, with the grace period non-negotiable because
an object is written *before* the document row that names it.

---

## Two findings recorded regardless

### A. `/signature-events/verify` cannot see photo removal at all

`verify_signature_integrity`, `backend/server.py:17550-17610`.

```python
stored_hash = evt.get("content_hash", "")
recomputed_hash = compute_content_hash(evt.get("content_snapshot", {}))
is_valid = stored_hash == recomputed_hash
```

The recomputation reads `evt["content_snapshot"]` — the copy stored **inside the signature
event** — and compares it to a hash also stored inside that same event. The live
`db.logbooks` document is never loaded. The endpoint takes `document_type` and `document_id`
and uses them only as a query filter to find the events.

So the check answers "has this ledger row been altered since it was written," and it is
sound for that. It does **not** answer "does the document still match what was signed," which
is what its name, its docstring ("Verify that no signature events have been tampered with")
and its `all_valid: true` are read as meaning. Delete every photograph from a filed logbook
and this endpoint returns `all_valid: true`, `has_version_gaps: false` — a clean bill of
health on a record that no longer matches its attestation.

The version-gap check has the same shape: it detects a *missing ledger row*, not a modified
*document*. Both are ledger-integrity checks presented as document-integrity checks.

This is why the photo window must be enforced at the write, not detected after the fact:
**the app's own tamper check would never report it.** Recorded here rather than fixed —
comparing a live document against a snapshot is a design decision with real consequences
(what counts as a material difference, what a mismatch should do to a filed record) and it
belongs to the operator, not to this change.

### B. `_logbook_photo_is_renderable` drops a missing photograph silently

`backend/server.py:353-355`, consumed at `27432` (a count) and `27503` (the tile loop):

```python
if not _logbook_photo_is_renderable(_photo):
    continue
```

`_logbook_photo_sources` returns the list of surviving copies — enhanced, thumb, original,
and the two base64 rungs. When all of them are gone the helper returns `False` and the
report `continue`s past the tile with **no output of any kind**. The `photo_count` at 27432
excludes it too, so the count on page 1 and the grid agree with each other and both disagree
with the signed record.

The result: a filed compliance document renders with fewer photographs than it was signed
with, and says nothing. A reader — a lender, an inspector, counsel — sees a complete-looking
report. There is no way to tell "this crew took three photographs" from "this crew took five
and two are gone."

**What it should render instead: a placeholder tile in the photograph's own position, the
same 160×120 footprint as a real one**, so the grid geometry and the ordinal position of
every surviving photograph are preserved, carrying:

- a plain statement that an image is unavailable — the wording is the renderer's to choose,
  but it must say *missing*, never "loading," never blank;
- the photograph's own identifying facts where they exist — `photo_id` and `added_at` are on
  the document even when every image copy is gone, so the tile can name *which* photograph
  this was;
- no `<img>` and no URL. A broken-image glyph is a rendering failure; this is a statement of
  fact about the record and must not be able to look like a network problem.

And **`photo_count` at 27432 must count it.** The count's job is to say how many photographs
the record carries, not how many still resolve — the current behaviour quietly makes the
count agree with the loss.

Styling to match the existing tiles: inline styles only, no flex. The same string is emailed
as HTML and rendered to PDF by WeasyPrint, and
`_photo_added_after_filing_caption` (`server.py:377-405`) documents that constraint for the
adjacent caption.

**Not built here — the report renderer belongs to another worker.** Reported so it lands with
whoever owns it.

---

## What is built in this change

1. `logbook_photo_window_is_open()` / `logbook_photo_window_day()` in `backend/server.py`,
   in the photo helper region — one definition of the boundary, expressed as the
   `eastern_date(now - 3h)` string comparison above.
2. The window gate in `append_activity_photo`, above the file read, returning
   **409 `PHOTO_WINDOW_CLOSED`**.
3. The mirrored client predicate in `frontend/src/utils/logbookEditable.js`, so
   `isOpenForPhotoAppend` carries the clock and the four affordance layers above vanish on
   their own.
4. Tests on both sides, shown failing first.

Both sides fail **closed** on a logbook with no `date`: the client hides the control and the
server refuses. A logbook without a date is not a thing the create path can produce — it is
the dedupe key — and of the two ways to be wrong, refusing a photograph is recoverable by a
conversation and appending to a closed compliance record is not.
