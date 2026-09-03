# What happens when a real CO disagrees with the one an admin typed

**Status: REPORT ONLY. Nothing in this document is built.** It answers a
question the operator asked when he ruled that job completion is a manual admin
entry of a CO number and a date: *"report what the app does if it later learns
of a CO that disagrees with what was entered. Not tonight, but the field should
not be a place a wrong number lives forever unchallenged."*

The short answer is at the top because it is the part that matters.

---

## The answer

**Today the app does nothing, and it could not notice.** Nothing compares
`projects.job_completion_co_number` against anything. The attested number is
currently **unfalsifiable by the software**: an admin can type any string that
is text, non-blank, under 64 characters and on one line, and no code path in
this repository will ever contradict it.

**But the raw material for a comparison already exists.** This app has ingested
NYC DOB certificate-of-occupancy records every fifteen minutes for some time.
It just never connected them to the completion field. So the honest statement is
not "we have no data" — it is "we have the data on one side of the house and the
claim on the other, and no wire between them."

---

## What the app already ingests

`_query_dob_apis` (`backend/server.py`, around line 28114) polls NYC Open Data
Socrata datasets for each tracked project, keyed on BIN with a house-number /
street `$where` fallback. Among roughly a dozen datasets, one is the relevant
one:

| Dataset | Name | Stored `record_type` |
| --- | --- | --- |
| `pkdm-hqz6` | DOB NOW: Certificate of Occupancy | `cofo` |

Rows land in the `dob_logs` collection. `_extract_cofo_fields`
(`backend/server.py` ~29408) pulls these into `extras`:

- `co_number` — read as `co_number` **or** `certificate_of_occupancy_number`
- `cofo_type` — read as `co_type` **or** `type`
- `current_status` — read as `co_status` **or** `status`
- `issuance_date` — read as `issuance_date` **or** `issued_date`
- `expiration_date`
- `job_filing_number`

`_classify_cofo` (`backend/lib/dob_signal_classifier.py` ~198) then labels the
row `cofo_final`, `cofo_temporary` (a TCO), or `cofo_pending`.

The sync is **automatic**: `nightly_dob_scan` runs on a 15-minute
`IntervalTrigger` (registered ~`backend/server.py:40430`) despite its name, plus
a manual `POST /projects/{id}/dob-sync` and a re-sync fired when a project's BIN
changes. The join key — `nyc_bin`, with `bbl` beside it — is stored per project
and self-heals during sync when it is missing or a `…000000` placeholder.

There is a **second, independent CO reader**:
`backend/lib/statistical_engine/daily_panel.py` (`_fetch_cos`, ~521) queries the
same `pkdm-hqz6` for `c_of_o_issuance_date` and `c_of_o_filing_type`, filtered to
`Final`, and uses final-CO issuance as the project-duration endpoint for
milestone calibration.

## The gap, stated precisely

`projects.job_completion_date` and `projects.job_completion_co_number` have
exactly one writer: `PUT /projects/{project_id}` → `update_project`. Nothing in
`run_dob_sync_for_project` touches them; the only project write in the sync tail
is `last_dob_sync_at`.

That separation is **deliberate and should stay**. `lib/project_retention.py`
argues it at length: this field governs the physical destruction of statutory
records, and the `dob_logs` TTL incident
(`docs/runbooks/dob-logs-ttl-removal-2026-07-24.md`) is what happened the last
time a retention clock in this product was keyed on something the app inferred
rather than something a human asserted. Two TTL indexes keyed on `detected_at`
— when the app first *saw* a record, not when the event happened — would have
destroyed a 2019 violation and a 2026 violation on the same day.

So the recommendation below is **never** "auto-populate the completion from the
ingested CO."

## Two things to verify before building any of this

Both were found while answering this question, and both are load-bearing for any
comparison. Neither is changed here.

1. **The two CO readers disagree about the dataset's column names.**
   `_extract_cofo_fields` reads `co_number` / `co_type` / `issuance_date`;
   `daily_panel._fetch_cos` asks the same dataset for `c_of_o_issuance_date` /
   `c_of_o_filing_type`. Both cannot be right. At least one is reading `None`
   into a field that then looks merely empty rather than broken — the exact
   "a check that runs, returns a well-formed answer, and never reaches its
   subject" shape this codebase keeps producing. **Any reconciliation work must
   start by confirming, against live `pkdm-hqz6` rows, which spelling is real
   and whether `extras.co_number` is actually populated in production or has
   been silently null the whole time.** A comparison built on a field that is
   always null would report "no disagreement" forever and look like it worked.

2. **`cofo` rows are excluded from the compliance rollup.** The dashboard
   aggregation (~`backend/server.py:11036`) filters `record_type` to
   `violation`, `swo`, `complaint`, `permit`. A final CO does not appear in any
   summary today; it surfaces only in the activity feed and signal
   notifications.

## What a comparison would take

Assuming (1) is resolved and `extras.co_number` is genuinely populated:

- **Join**: `dob_logs` where `project_id == <project>` and
  `record_type == "cofo"`, preferring rows classified `cofo_final`. No new
  ingest, no new external call, no new dataset. The data is already local.
- **Normalise at the point of comparison, not at storage.**
  `normalize_co_number` deliberately stores the admin's entry verbatim — a
  rewritten identifier is no longer the one on the certificate. Case-folding
  and punctuation-stripping belong in the comparator, where both formats are in
  view, and the comparator should be lenient: `B-123456` vs `B123456` is a
  formatting difference, not a disagreement.
- **Compare two things, not one**: the number, and the issuance date against
  `job_completion_date`. A date that is off by a few days is likely
  issuance-vs-sign-off; a date off by years is a different certificate.
- **Handle the legitimately-plural case.** A building can have a TCO, several
  renewed TCOs, and then a final CO. "The attested number matches a TCO but a
  later final CO exists" is a *correct* entry that has gone stale, not a wrong
  one, and it needs different wording from "this number matches nothing."

## On disagreement: flag, refuse, or notify?

**Flag and notify. Never refuse, and never overwrite.**

- **Refusing is wrong** because the retention brake would then be released or
  tightened by an external feed. Socrata is anonymous-tier, unauthenticated,
  occasionally stale, and matched on a BIN this app admits is sometimes a
  placeholder. Letting it move a destruction clock reintroduces exactly the
  `detected_at` failure mode in a new costume. It is also the wrong direction of
  risk: a false "disagreement" would block a legitimate cleanup, and a false
  agreement would silently bless a wrong number.
- **Overwriting is worse**, for the same reason plus one more: it would destroy
  the attestation, which is the only record of who claimed what.
- **Flagging is right** because the attested value's whole purpose is to be a
  named human claim. The remedy for a claim that looks wrong is to show it to a
  human beside the contradicting evidence, not to have software decide.

Concretely, the shape that fits this codebase:

1. A **computed, never-stored** discrepancy view — the same discipline as
   `purge_eligible_at`, which is recalculated on every read and stored nowhere
   precisely so nothing can ever sort or act on it.
2. Surfaced on the **project retention card** and, more importantly, in the
   **pending-deletion review**, beside the block reason. The person about to
   destroy seven years of records is the one who needs to know the completion
   date might be wrong.
3. A **notification** on the existing DOB signal path when a `cofo_final`
   arrives for a project whose attested number does not match it. That path
   already exists (`lib/dob_signal_notifications.py`,
   `lib/notification_preferences.py`) and already handles `cofo_*` kinds.
4. **No change to `retention_refusal`.** A discrepancy is displayed; it does not
   refuse, and it does not clear. The purge stays gated on a human, always.

One asymmetry is worth building in: if the ingested final CO is **later** than
the attested date, the discrepancy is *safe* to ignore for retention purposes —
a later completion only extends the period. If it is **earlier**, the attested
date is holding records longer than required, which is the harmless direction.
The genuinely alarming case is a `cofo_final` that matches no attested number at
all on a project whose records are about to be destroyed.

## What exists today to catch a wrong number

Not nothing, but not much, and none of it is automatic:

- Every write of the pair is audit-logged as `project_completion_set` **with the
  previous value of both the date and the number**, so a correction leaves a
  trail of what was claimed before.
- The number and date can only be written together, so a corrected date cannot
  leave a stale number describing a day it no longer describes.
- `completion_source` is server-stamped to `admin_attested` and cannot be raised
  to `final_co` from the request body, so the record never overstates its own
  provenance.

That is the whole of it. It makes a wrong number *traceable*. It does not make
it *detectable*.
