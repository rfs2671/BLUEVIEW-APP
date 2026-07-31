# Follow-ups

Known gaps and deferred work, newest first.

- **[MED] osha_log review-state depends on the fabricated-cert cleanup being APPLIED.**
  The combined-report osha_log renderer surfaces each cert's `needs_review` /
  `review_reason` by joining to `worker.certifications`. Those flags are WRITTEN by
  `backend/scripts/audit_fabricated_certs.py --apply`, which has NOT been run in
  production yet (narrowed rule landed; dry run pending confirmation of 2/2/2/0).
  Until `--apply` runs, the DB carries no `needs_review` flags for the two legacy
  workers (Jose David Hernandez Pena, Jhonatan Tipantuna), so the packet still
  renders their SST rows without a ⚠. Run the dry-run-confirmed `--apply` to make
  the review-state surfacing effective (it also drops the 2 fabricated OSHA rows).

- **[MED] Compliance-packet capture gaps — new EDITOR fields (batch with next native build).**
  Surfaced while building the report renderers (item C). The renderers can only
  show what the editors persist; these fields an inspector needs are NOT captured
  today and must be ADDED to the editor `data:{}` blocks (`frontend/app/logbooks/*.jsx`),
  then ride the NEXT native build — do not ship piecemeal:
  - **hot_work.jsx** — FDNY hot-work permit #; Certificate of Fitness # for the
    operator AND the fire-watch holder. (Today: no permit/C.O.F. number at all.)
  - **crane_operations.jsx** — rigger name, signal-person name, lift-director name
    (OSHA 1926.1400 qualified roles); measured wind-speed VALUE (today only a
    `wind_speed_checked` bool exists — no reading).
  - **excavation_monitoring.jsx** — units on every reading (depth, vibration
    threshold/current, baseline/current building readings); a per-reading
    timestamp on each adjacent-building row (a monitoring log needs reading times).
  - **subcontractor_orientation.jsx** — worker signature. `handleCreateNew` writes
    `worker_signature: null` hardcoded; the orientation acknowledgment is
    UNATTESTED without it (same integrity class as the CP signature). Capture the
    worker's signature at orientation.

- **[LOW] Concrete special-inspection fields — only if it becomes a TR record.**
  `concrete_operations.jsx` captures no cylinder/sample IDs and no special-inspector
  / TR# reference. Only matters if the concrete log is used as a special-inspection
  (TR1) record rather than an internal QA/pour log. Deferred until that's required.

- **[HIGH] Compliance packet incomplete — several logbook types under-render.**
  Found while extending report capitalization (commit 16df52c). In the report
  renderers (`backend/server.py`):
  - **hot_work, concrete_operations, crane_operations, excavation_monitoring,
    ssc_daily_safety_log** render in `generate_combined_report` as a raw
    `data.items()` key-value dump with NO field map — every field emitted
    generically, per-field semantics unknown (which is why capitalization was
    excluded, not applied blindly).
  - **osha_log, scaffold_maintenance, subcontractor_orientation** render NO
    structured fields at all: `generate_single_logbook_html` shows a bare
    `Status:` stub and `generate_combined_report` skips them entirely.
  These are the documents an inspector asks for BY NAME, so the gap is
  **completeness of the compliance packet, not formatting**. Fixing it needs a
  per-type field map for each type in BOTH renderers
  (`generate_single_logbook_html` and `generate_combined_report`). Capitalization
  then falls out for free via the existing `_capitalize_first` / `_sentence_case`.

- **Exception-surface drift on the logbooks screen (`app/logbooks/index.jsx`).**
  Three exception signals now render three different ways: `unsigned_orientations`
  is an invisible list-visibility gate (no count shown), `missing_toolbox_talk` is
  a Bell card, and `unaffirmed_logbooks` is an AlertTriangle card. PR B added the
  unknown-SST badge but deliberately REUSED the expired `reviewCard` treatment on
  site/checkins rather than adding a fourth one-off. The logbooks screen still
  carries three treatments and should be unified into one exception-row pattern —
  the same drift the semantic color taxonomy overhaul was meant to end. Not fixed
  in PR B (out of scope); logged here.

- **Signature-audit hole — first-submit logbooks (pre-PR-F).** For `daily_jobsite`,
  `toolbox_talk`, `preshift_signin`, and `scaffold_maintenance`, a `const created`
  block-scope ReferenceError threw on the FIRST submit of a new log, before
  `recordSignatureEvent`. The record was written but no signature audit event was
  recorded on first submit. PR F fixed the scope going forward, but **nothing
  reconstructs the missing events** — the `signature_events` audit trail has a
  permanent hole for every first-submit logbook of those four types filed before
  the PR-F commit. Second-submits and other log types are unaffected. If a
  backfill is ever needed, source of truth is the `logbooks` rows themselves
  (created_at / cp_signature) — the events cannot be recovered, only approximated.
