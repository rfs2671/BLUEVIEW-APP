# CO disagreement — what should happen when DOB tells us a different number

> **CORRECTION, 2026-09-03 -- read this before the document below.**
>
> This document was written believing the CofO ingest worked. It did not. The
> query named six columns the dataset does not have, starting with an `$order`
> on `issuance_date` where the real column is `c_of_o_issuance_date`, and
> Socrata rejected the whole request. **It returned HTTP 400 on every call, 96
> times a day, from the day the feature shipped. Zero certificate-of-occupancy
> records were ever ingested.**
>
> That was established by running the shipped query against the live dataset
> beside the corrected one: 400 against 200-with-50-rows. The production audit
> showing no `cofo` rows was therefore never a data gap; it was a broken query,
> and the audit was right for a reason nobody had found.
>
> Specific claims below that were FALSE when written:
> - that rows land in `dob_logs` carrying `co_number`, `issuance_date` and the
>   rest -- nothing landed;
> - that we "store the answer and then throw it away" -- the storing half never
>   happened;
> - that a `cofo` row is "fetched once and never refreshed" -- it was never
>   fetched;
> - that `_classify_cofo` sorts rows into `cofo_final` / `cofo_temporary` /
>   `cofo_pending` -- all three collapsed to `cofo_final`, because
>   `c_of_o_status` is the constant `'CO Issued'` across all 81,264 rows and the
>   classifier matched `"ISSUED"` first.
>
> Claims below that were CORRECT and are confirmed: no `cofo` branch in
> `_determine_severity`; the notification routing table has no production
> consumer; `cofo` rows are excluded from the compliance rollup.
>
> Both defects are fixed in #380 (`8dd1e76`). Ingest now works and renewals no
> longer classify as completions, so the argument this document makes -- that an
> attested CO number is currently unfalsifiable by the software -- is about to
> stop being true for the first time. **The reasoning stands; the premise about
> what the pipe was doing did not.**


Report only. **No product code was changed.** The completion field itself is
being built concurrently in `backend/lib/project_retention.py` and the retention
region of `backend/server.py`; nothing here touches either.

The operator's question, verbatim:

> report what the app does if it later learns of a CO that disagrees with what
> was entered. Not tonight, but the field should not be a place a wrong number
> lives forever unchallenged.

## 0. The short answer, and a correction to the premise

**Today the app does nothing, and it will keep doing nothing — but not because
it has never heard of a Certificate of Occupancy.** It has. Every 15 minutes,
for every tracked project, LeveLog queries DOB NOW's Certificate of Occupancy
dataset (`pkdm-hqz6`), extracts `co_number` and `issuance_date`, and writes them
to `dob_logs` (`backend/server.py:28019-28040`, `:29115-29125`, `:30144-30145`).

The plumbing exists. It is also completely inert:

- Nothing reads `co_number` after the write. There is no comparator, no
  consumer, and no query for it anywhere outside the ingest path.
- A `cofo` row is fetched **once and never refreshed** — a DOB amendment or
  revocation of the same CO number is invisible to this app forever
  (`server.py:30096`, § 2.3).
- `_determine_severity` has no `cofo` branch, so every CO record falls through
  to `"Good"` (`server.py:29583`) and therefore never reaches the alert path,
  which fires only on `"Action"` (`server.py:30247-30248`).
- The routing table that says a final CofO should email immediately
  (`backend/lib/dob_signal_notifications.py:78`) has **no production consumer**
  — it is imported by tests and by nothing else.
- On screen, a CO record renders as an unstyled generic card labelled `cofo`
  with the summary "DOB record detected", and the CO number appears only in a
  small grey `ID:` line when the card is expanded
  (`frontend/app/project/[id]/dob-logs.jsx:821-862`, `:856`).

So the honest statement is sharper and less comfortable than "we have no
source": **we already pay for the source, poll it 96 times a day, store the
answer, and then throw it away.** An attested CO number is not unfalsifiable in
principle. It is unfalsified in practice, by omission.

The operator's other framing is worth stating explicitly and is true: **a manual
entry with no external check is not a weakness of this design — it is the
current reality of every compliance fact in this product.** SST classes, permit
numbers, and site-safety registrations all arrive by a human typing them. The
attestation (a named admin, a timestamp, an `audit_logs` row) is what stands in
for verification. That is a legitimate control, not a placeholder for one. What
this document argues is that when a second, independent statement of the same
fact is already sitting in `dob_logs`, declining to compare them is a choice,
and not a defensible one for a field that gates a hard delete.

---

## 1. What is ingested today

### 1.1 The DOB sync

`nightly_dob_scan` (`server.py:30678`) is misnamed; it runs on
`IntervalTrigger(minutes=15)` (`server.py:40139-40141`, id `dob_nightly_scan`),
96 times a day. It selects projects with `track_dob_status: True` intersected
with `ACTIVE_PROJECT_FILTER` (`server.py:30700-30707`), capped at 500.

`ACTIVE_PROJECT_FILTER` (`backend/lib/project_state.py:35-38`) is
`{is_deleted: {$ne: true}, marked_for_deletion: {$ne: true}}`. **A project
marked for deletion stops syncing.** That matters here: the moment an admin
marks a completed project for deletion (`server.py:11516`, TIER 1), DOB stops
being consulted about it — which is exactly the window in which a late CO
correction would matter most. Any disagreement check must run before that mark,
or must be exempted from the filter deliberately.

Per project, `_query_dob_apis` (`server.py:27821`) builds up to ~20 Socrata
endpoints across ten record types: violations (BIS, DOB NOW, ECB/OATH), permits
(DOB NOW Build, DOB NOW Electrical, BIS legacy), complaints, job status, stop
work orders, CofO, façade FISP, boiler, elevator. Results land in `dob_logs`
with `project_id`, `company_id`, `nyc_bin`, `record_type`, `raw_dob_id`,
`current_status`, `signal_kind`, `detected_at` and per-type extras
(`server.py:30153-30186`).

### 1.2 The CofO endpoint, exactly

`server.py:28019-28040`:

```python
# ── CERTIFICATE OF OCCUPANCY (pkdm-hqz6) - DOB NOW: CofO ──
if bin_usable:
    endpoints.append({
        "url": "https://data.cityofnewyork.us/resource/pkdm-hqz6.json",
        "params": {"bin": nyc_bin, "$limit": "50", "$order": "issuance_date DESC"},
        "record_type": "cofo",
        "id_field": "co_number",
    })
if house_num and street_name:
    endpoints.append({
        "url": "https://data.cityofnewyork.us/resource/pkdm-hqz6.json",
        "params": {
            "house_number": house_num,
            "$where": f"upper(street_name) like '%{street_name}%'",
            "$limit": "50",
            "$order": "issuance_date DESC",
        },
        "record_type": "cofo",
        "id_field": "co_number",
    })
```

Extraction, `server.py:29115-29125`:

```python
def _extract_cofo_fields(rec: dict) -> dict:
    """MR.14 (commit 2b) — extract from pkdm-hqz6 (DOB NOW: CofO)."""
    return {
        "co_number": rec.get("co_number") or rec.get("certificate_of_occupancy_number") or None,
        "cofo_type": rec.get("co_type") or rec.get("type") or None,
        "current_status": rec.get("co_status") or rec.get("status") or None,
        "issuance_date": rec.get("issuance_date") or rec.get("issued_date") or None,
        "expiration_date": rec.get("expiration_date") or None,
        "job_filing_number": rec.get("job_filing_number") or rec.get("job_number") or None,
    }
```

**Both of the fields the completion entry will require are already captured:
the number and the date.** That is the whole reason this document can recommend
anything at all.

`current_status` is mapped for diffing at `server.py:28977`. `signal_kind` is
classified into `cofo_temporary` / `cofo_final` / `cofo_pending` by
`backend/lib/dob_signal_classifier.py:199-210`, reached from `server.py:30186`
via the shim at `:28984`.

### 1.3 Answer to question 2, plainly

**A certificate of occupancy does appear in an ingested payload today.** The
dataset is `pkdm-hqz6` (DOB NOW: Certificate of Occupancy), keyed on BIN, polled
every 15 minutes, `$limit=50`, ordered `issuance_date DESC`. The CO number is
written to `dob_logs.co_number` and to `dob_logs.raw_dob_id`.

What is *not* true is the rest of the sentence. Nothing reads it. See § 2.

---

## 2. The join key, and five reasons the existing data cannot be trusted as-is

### 2.1 The join key is `project_id`, and it is real

The join is not made on the CO number at all. It is made at ingest time:
`run_dob_sync_for_project` (`server.py:29890`) resolves the project's BIN and
stamps `project_id` on every row it writes. So a checker asks

```
dob_logs.find({project_id: <id>, record_type: "cofo"})
```

and never has to match a number against a number.

This is the class of defect the brief warned about — a field a reader names and
no writer produces — so it was verified rather than assumed. **`nyc_bin` has
real writers and self-healing:**

- `fetch_nyc_bin_from_address` (`server.py:1806`) resolves BIN + BBL from NYC
  GeoSearch and rejects `X000000` placeholders (`:1884-1892`).
- It is called at project creation (`server.py:11224-11225`) and at company
  signup (`server.py:6448-6449`).
- BBL→BIN pre-heal runs on every sync when the stored BIN is missing or a
  placeholder (`server.py:29915-29945`), and backfills the project doc.
- Record-harvest heal votes a real BIN out of returned records and backfills it
  (`server.py:29953-29985`).
- The admin config endpoint writes it directly (`server.py:31121-31124`).

`track_dob_status` likewise has real writers (`server.py:6473`, `:11220`,
`:29937`, `:29978`, `:31136`). This is not a phantom field.

### 2.2 But BIN is a *building* key, not a project key

Two LeveLog projects at the same address share a BIN and would both receive the
same CofO rows. A building accumulates many COs over its life (TCO, amended,
final), all of which arrive together, `$limit=50`. There is no field on a
`cofo` row that says *this CO is the one that closed out your job* — except
`job_filing_number` (`server.py:29123`), which LeveLog does not currently
correlate with the project's own permits.

### 2.3 A `cofo` row is written once and never updated

`server.py:30093-30097`:

```python
# NOTE: we don't skip on existing_ids for permits here — the
# update path below refreshes status/expiration from the newest
# filing. Only skip for non-permit types where the record is
# immutable.
if rec.get("_record_type") != "permit" and raw_id in existing_ids:
    continue
```

`existing_ids` is project-scoped (`server.py:30069-30072`). Permits are exempt;
`cofo` is not. So the status-diffing block below it (`server.py:30190-30246`),
the one that would notice a CO going from issued to revoked, **is unreachable
for CofO records after the first insert.** A CO that DOB later amends or pulls
stays `ISSUED` in `dob_logs` forever.

This is the single largest piece of work behind any disagreement feature. It is
not a CofO problem; it is a shared-ingest problem that also silences boiler,
elevator, façade, complaint and violation status changes.

### 2.4 The diffing lookup is not tenant-scoped

`server.py:30196-30199`:

```python
existing = await db.dob_logs.find_one(
    {"raw_dob_id": raw_id},
    sort=[("detected_at", -1)],
)
```

No `project_id`, no `company_id`. `raw_dob_id` for a `cofo` row is the bare CO
number — a DOB-global identifier. If company A already holds CO `123456` and
company B syncs the same building, B's sync finds A's row, sees a matching
status, and **updates A's document instead of inserting B's**
(`server.py:30200-30215`). B never gets its own row. Any disagreement checker
reading `dob_logs` must not assume one row per project.

### 2.5 The address fallback has no borough constraint

The address variant at `server.py:28030-28040` filters on `house_number` and
`upper(street_name) like '%…%'` and nothing else. `100 MAIN STREET` matches in
all five boroughs. A project whose BIN never resolved will collect CofO rows
for buildings it has no relationship to. **This alone disqualifies
auto-correction** (§ 4.2): the system cannot currently distinguish "DOB says
your CO number is wrong" from "we matched a street name in the wrong borough".

### 2.6 Whether any `cofo` row exists in production is unknown

The most recent production audit (`docs/audits/production-data-audit-2026-05-04.md`,
§ 4) reports 622 `dob_logs` rows across `complaint` (223), `inspection` (148),
`permit` (115), `job_status` (69), `violation` (65), `swo` (2). **Zero `cofo`,
zero `boiler`, zero `elevator`, zero `facade_fisp`.**

That audit ran on 2026-05-05, one day after MR.14 commit 2b shipped the CofO
endpoint (dated 2026-05-03 in the source comment at `server.py:28020`). It is
therefore evidence of nothing about today. Sixteen months have passed. **The
count of `cofo` rows in production right now could not be determined from the
repository and must be measured before anything is built.** See § 8.

---

## 3. What should happen: flag, and hold the brake

**Recommendation: flag, notify, hold the delete brake, and record. Do not
refuse the entry. Do not auto-correct.**

The reasoning runs from what each option costs when it is wrong.

**Refusing the entry** — blocking the attestation when DOB disagrees — is wrong
because DOB's data is not authoritative enough to block on. § 2.5 alone means a
refusal can be triggered by a street-name collision. Worse, refusal has the
wrong failure direction for an admin doing the right thing: a real CO was issued
on paper, the open-data set lags by days or weeks, and the admin cannot record
the truth. The system would be telling a human with the certificate in hand that
their certificate does not exist. That is how a control gets routed around.

**Auto-correcting** is argued separately in § 4.

**Doing nothing** is the current state, and it is what the operator has already
ruled out.

**Flagging** is the option whose failure mode is a false alarm on an admin's
screen. That is the cheapest wrong answer available. It also has a property the
others lack: it produces a durable record of the disagreement, which is what
makes the attestation stronger rather than weaker. An attestation that has been
tested against an independent source and survived is worth more than one that
was never tested. An attestation that was tested and *failed* is exactly the
thing an auditor needs to see.

Concretely, a disagreement is any of:

1. **Number mismatch.** A `cofo` row on the project whose `co_number` differs
   from the attested number, where the attested number matches no `cofo` row on
   the project.
2. **Date mismatch.** A `cofo` row whose `co_number` matches the attested
   number but whose `issuance_date` differs from the attested date by more than
   a normalisation tolerance (the two values arrive in different formats;
   `dob_logs` date fields are stored as strings, see
   `backend/scripts/backfill_dob_logs_dates.py`).
3. **Status contradiction.** A matching `cofo` row whose `current_status` is
   revoked, superseded, or amended. *(Unreachable until § 2.3 is fixed.)*
4. **Absence, after a grace period.** No `cofo` row for the project N days
   after the attested issuance date, on a project whose BIN is real and whose
   sync is healthy.

Case 4 deserves care. Absence is weak evidence — DOB open data lags, and a
project's BIN may be wrong. It should raise the weakest possible signal (a
notice on the project's compliance surface, no email, no brake) and should be
suppressed entirely when the project has no real BIN or has not synced
successfully in the interval. Cases 1–3 are strong signals.

---

## 4. Against auto-correction

### 4.1 The argument, stated at full strength

The completion entry is an **attested act by a named human**. Its value is not
the number; the number is available from DOB for free. Its value is that a
specific person, identifiable in `audit_logs` at a specific timestamp, put their
name to the claim that this project completed on this date under this
certificate. That is the thing a records-retention obligation actually rests on,
and it is the thing that makes someone careful when they type it.

Silently overwriting that value with a scraped one destroys precisely that
property. After an auto-correction the field says something no human ever
asserted, while still carrying a human's name. The audit trail now attributes to
an admin a statement they did not make. If the scraped value is later shown to
be wrong — a DOB data-entry error, a borough collision per § 2.5, a CO belonging
to a different project in the same building per § 2.2 — there is nobody to ask,
because the person named on the record never saw the number that is now on it.
An attestation that the system can rewrite is not an attestation. It is a cache
of DOB with a name stapled to it, and everyone who learns that will stop reading
the name as meaningful.

There is a second-order cost. Auto-correction teaches admins that the field
self-heals, which is an invitation to type carelessly and let the system sort it
out. The care the attestation is supposed to induce is the control. Removing the
consequence removes the control.

### 4.2 Do I still recommend it, and under what conditions

**No — not in any form that mutates the attested value.**

There is one narrow variant worth naming so it can be rejected explicitly rather
than rediscovered: auto-correction *in a separate field*. The system may record
`dob_observed_co_number` and `dob_observed_issuance_date` alongside the attested
pair, refresh them freely, and let every surface display both. That is not
auto-correction; it is presenting a second witness. The attested fields stay
immutable except by a new attestation.

The conditions under which even a proposal to overwrite could be revisited are
all conditions that do not hold today and are not cheap to establish:

1. The borough ambiguity in the address fallback is closed (§ 2.5), so a match
   is a match.
2. `job_filing_number` on the `cofo` row is correlated against the project's own
   permit filings (§ 2.2), so the CO is provably *this project's* CO and not
   another job in the same building.
3. Non-permit refresh is live (§ 2.3), so an amended or revoked CO is visible
   rather than frozen at first sight.
4. Measured false-positive rate across real tracked projects is zero over a
   meaningful window.

Even with all four, the correct action is still to *ask* the attesting admin to
re-attest with the corrected value, producing a second `audit_logs` row and a
second named act — not to write it for them. **A correction to an attestation
should itself be an attestation.**

---

## 5. The retention clock while a disagreement is open

The completion entry starts a seven-year clock and is the brake on the hard
delete path (`server.py:11643`, `hard_delete_project`, owner-only, which sweeps
~50 project-owned collections listed at `:11577-11599` including `dob_logs`,
purges the project's R2 objects at `:11698-11740`, deletes the project's own
`audit_logs` rows at `:11797-11801`, and finally removes the project document at
`:11806`). It is irreversible in the strongest sense available in this system.

**Rule: an open disagreement holds the brake on. It never releases it.**

Three cases, and they are not symmetric:

**A disagreement that would shorten the clock must never take effect
automatically.** If DOB reports an issuance date *earlier* than the attested
date, the purge-eligible date moves earlier — potentially into the past. An
automatic application of that value could make a project's records purgeable the
moment the sync writes the row. That is the failure the seven-year clock exists
to prevent, arriving through the mechanism meant to protect it. Shortening
requires a new human attestation, always.

**A disagreement that would lengthen the clock may hold automatically, but not
by rewriting the field.** The eligibility computation should read
`max(attested_date, any disagreeing observed date)` while a disagreement is
open. Retaining records longer than required is the safe direction; that is the
same argument that removed the `dob_logs` TTL indexes
(`server.py:41065-41096`, `docs/runbooks/dob-logs-ttl-removal-2026-07-24.md`)
and the same argument written into `docs/coi-retention-guarantee.md`. The stored
attested value stays untouched; only the derived eligibility date moves, and it
moves in the direction of holding.

**While any disagreement is open, `hard_delete_project` refuses.** Not "warns" —
refuses, with a message naming the open disagreement and the route to resolve
it. This is the whole point: the completion entry is a brake, and a brake whose
input is under dispute should be stuck on, not released on a coin flip. The
owner can resolve the disagreement (§ 6) and then purge; they cannot purge past
an unresolved one.

A note on the delete path's interaction with § 1.1: marking a project for
deletion removes it from `ACTIVE_PROJECT_FILTER` and therefore from the sync. So
a disagreement can only be *discovered* while the project is still active. The
check must run at attestation time and on each subsequent sync, not at purge
time — by purge time the data has stopped arriving.

---

## 6. Who is notified, and where

Three audiences, three surfaces, in descending urgency.

**The attesting admin, by name.** They made the claim; they are the only person
who can competently resolve it. In-app inbox via
`backend/lib/notifications_inbox.dispatch_notification` (`:163`), which already
does per-user dedup on `(user_id, source_kind, source_id)` and deeplinks into a
project screen. Severity `warning` for a number mismatch, `info` for the
absence case. Email as well for a number mismatch — this is a rare, high-stakes
event, and the existing routing table already classifies `cofo_final` as an
immediate-email milestone (`backend/lib/dob_signal_notifications.py:78`), a
policy that is currently written down and never executed.

**Company admins and the owner.** The owner is the only role that can purge
(`server.py:11643`, `Depends(get_owner_user)`), so the owner must be able to see
why a purge is being refused before they attempt it. Inbox only; no email.

**The project itself, persistently.** A disagreement must be a *state on the
project*, not a notification that ages out of an inbox. Two surfaces:

- The project's completion/retention panel — wherever the attested CO number is
  displayed, the disagreeing value is displayed beside it, with both dates and
  the source dataset. Never one value alone.
- The DOB logs screen (`frontend/app/project/[id]/dob-logs.jsx`). This needs a
  `cofo` card renderer regardless (§ 0); today a CO record shows as a generic
  card whose only visible detail rows are `log.status` and `log.description`
  (`:847-848`) — neither of which `_extract_cofo_fields` writes. The CO number
  is in the `ID:` line at `:856` and nowhere else.

Explicitly **not** a transient banner. The operator's phrasing — "should not be
a place a wrong number lives forever unchallenged" — is a statement about
durability. A dismissible toast satisfies the letter and defeats the purpose.

---

## 7. What is recorded

The disagreement must outlive the banner, the session, and the person. Three
writes, none of which mutate the attestation.

**1. A `co_disagreements` document**, one per (project, attested value,
observed value), with:

- `project_id`, `company_id`
- `attested_co_number`, `attested_issuance_date`, `attested_by_user_id`,
  `attested_at` — copied, not referenced, so the row is self-describing after a
  cascade
- `observed_co_number`, `observed_issuance_date`, `observed_status`
- `observed_source`: the dataset slug, which the ingest already stamps as
  `dob_logs.dataset` (`server.py:30175`, value `pkdm-hqz6`)
- `observed_dob_log_id`, `observed_match_shape`: `"bin"` or `"addr"` — the
  address-matched case is weaker evidence and must say so on its face
  (`server.py:28191`, where the fetch already computes `query_shape`)
- `kind`: `number_mismatch` | `date_mismatch` | `status_contradiction` | `absent`
- `state`: `open` | `resolved_reattested` | `resolved_dismissed`
- `opened_at`, `resolved_at`, `resolved_by_user_id`, `resolution_note`
- `retention_hold_effect`: the derived eligibility date while open, so the
  brake's behaviour is reconstructable years later

Resolution is append-only in effect: a resolved row is never deleted, and a
recurrence opens a new row rather than reopening the old one.

**2. `audit_logs` rows** via `audit_log` (`server.py:1069`) for
`co_disagreement_opened`, `co_disagreement_resolved`, and — when the admin
corrects the entry — a fresh `co_attested` row carrying the old and new values.
The correction is a new attestation with its own actor and timestamp, per § 4.2.
The product has no delete endpoint or admin UI for `audit_logs`
(`docs/coi-retention-guarantee.md` § 3), which is what makes this the durable
half.

**3. Nothing on the attested fields.** They are never written by the detector.
The `dob_observed_*` pair (§ 4.2) may be refreshed freely, and lives beside
them.

One honest limitation: `hard_delete_project` deletes the project's own
`audit_logs` rows (`server.py:11797-11801`) and would delete `co_disagreements`
if it is added to `_PROJECT_OWNED_COLLECTIONS`. That is acceptable *only*
because § 5 requires every disagreement to be resolved before a purge can run —
the record has done its job by then. If the brake in § 5 is not built, the
audit rows are purgeable and this section is worth much less.

---

## 8. What it would cost

Rough, in engineer-days, and deliberately front-loaded on the parts that are not
the feature.

**Prerequisite — measure first (0.5 day).** Query production for
`dob_logs.count({record_type: "cofo"})` and inspect a sample. If the count is
zero, find out whether the live `pkdm-hqz6` schema actually exposes a column
named `co_number`. The ingest drops any record with an empty id field
(`server.py:28108-28111`, `:30077-30079`), so a column-name mismatch would
silently discard every CofO record and produce exactly the zero the 2026-05-04
audit shows. **Nothing else on this list is worth starting until this is
answered.** This is a read-only production query plus one Socrata call.

**Fix non-permit refresh (2–3 days).** `server.py:30096`. Shared ingest path
across all ten record types, so it needs a control run showing the current
behaviour failing before the fix, per repo convention. The upside is much larger
than CofO: it restores status transitions for boiler, elevator, façade,
complaint and violation too.

**Scope the diffing lookup (0.5–1 day).** `server.py:30196`. Small change,
real blast radius, plus a decision about existing cross-tenant rows.

**Borough-constrain the address fallback (0.5–1 day).** `server.py:28030-28040`
and the sibling address endpoints. Cheap to write; the cost is validating
against live Socrata that the borough column exists and is populated on
`pkdm-hqz6`.

**The detector itself (1 day).** Runs at attestation time and at the end of each
project sync. Pure comparison over rows that already exist. This is the smallest
line item on the list.

**Surfaces and notification (1.5–2 days).** A `cofo` card renderer for
`dob-logs.jsx`, the paired display on the completion panel, inbox dispatch, and
a resolve action. `dispatch_notification` already exists; the email path needs
the routing table in `dob_signal_notifications.py` wired to a real caller for
the first time.

**Retention hold + purge refusal (1 day),** coupled to whatever shape
`project_retention.py` lands in — cannot be estimated more precisely until that
exists.

**Total: roughly 7–10 engineer-days**, of which about 60% is repairing the
ingest path rather than building the disagreement feature. That ratio is the
honest headline. The comparison is trivial; the data underneath it is not
currently trustworthy enough to compare.

A materially cheaper variant exists and is worth considering as a first step:
**detector + paired display + inbox notice only, on BIN-matched rows only,
skipping the ingest repairs (≈2.5 days).** It catches the case that actually
motivates the question — a wrong number typed at attestation time against a CO
that DOB already published — and does not catch later amendments or revocations.
It should ship with the limitation written on the screen, not just in this file.

---

## 9. What could not be established

Named plainly, because the recommendations above are conditional on them.

1. **Whether any `cofo` row exists in production today.** The only audit in the
   repo is `docs/audits/production-data-audit-2026-05-04.md`, generated one day
   after the CofO ingest shipped. It shows zero. That is expected for a
   one-day-old feature and tells us nothing about sixteen months later.

2. **Whether `pkdm-hqz6` actually has a column named `co_number`.** The
   extractor hedges with a fallback (`server.py:29118`), but `id_field` does
   not (`server.py:28027`, `:28039`) — and `id_field` is what the dedup and the
   `raw_dob_id` write use. If the live column is named otherwise, every CofO
   record is dropped at `server.py:28110`. This requires a network call to
   settle and is the highest-value unknown on the list.

3. **Whether the CO number on the paper certificate an admin reads from is the
   same string as `pkdm-hqz6`'s `co_number`.** Formatting, prefixes and check
   digits are unverified. If they differ, the comparator needs a normaliser, and
   every mismatch is noise until it has one.

4. **Date format alignment.** `dob_logs` date fields are stored as strings in
   per-dataset formats (`server.py:41086-41089`;
   `backend/lib/statistical_engine/baselines.py:1397`;
   `backend/scripts/backfill_dob_logs_dates.py` exists precisely because of
   this). The tolerance in § 3 case 2 cannot be specified without knowing what
   `pkdm-hqz6` returns.

5. **The completion field's final shape.** `backend/lib/project_retention.py`
   does not exist on `origin/main` (a1e2657) and is being written concurrently.
   Field names, the attestation record's location, and how the seven-year clock
   is computed are all assumed here, not read.

6. **Whether `cofo` rows were ever subject to the `dob_logs` TTL.** They were
   not — neither `dob_logs_ttl_short` (permit/complaint/inspection/job_status)
   nor `dob_logs_ttl_long` (violation/swo) covers `cofo`, per the table in
   `docs/runbooks/dob-logs-ttl-removal-2026-07-24.md`. But that runbook is
   marked *not yet executed*, so the two indexes may still be live in Atlas.
   This does not affect CofO retention; it is recorded so the next reader does
   not have to re-derive it.
