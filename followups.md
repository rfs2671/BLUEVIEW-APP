# Follow-ups

Known gaps and deferred work, newest first.

- **[HIGH] Full responsive-layout audit across the supported device-size range.**
  Verify EVERY screen at the smallest supported size (iPhone SE / 4.7") and the
  largest (Pro Max / 6.9"), on both iOS and Android: nothing clipped, truncated,
  or overflowing horizontally; headers, cards, tables, and modals reflow instead
  of pushing off-screen; and touch targets are large enough for **gloved hands**
  on a jobsite (min ~44–48pt, adequate spacing). Especially check the dense/new
  UIs — logbook editors (crane/excavation/scaffold checklists, slump-test rows),
  the worker sign-in table, the camera overlay chrome, and the reports screen.
  Not gated to any build; a standalone QA sweep. Separate from the camera work.

- **[HIGH] SSC daily-log compliance toggles are two-state (seeded false) — a value the human never affirmed.**
  In `ssc_daily_safety_log.jsx`, five compliance fields — `incidents_reported`,
  `safety_meetings_held`, `fire_protection_in_place`, `housekeeping_satisfactory`,
  `ppe_compliance` — are two-state `ToggleRow`s seeded `false`. There is no
  untouched-vs-explicit-No distinction, so an untouched toggle persists as `false`
  and, on the DOB report, a bare "No" on e.g. PPE Compliance / Fire Protection
  reads as an affirmative self-incriminating safety-violation finding the CP may
  never have made (and a false "Yes" would be a fabricated attestation). The
  report now qualifies this with a footnote, but the real fix is at the source:
  make these tri-state (unset / Yes / No) or required-before-submit so an
  untouched toggle can't masquerade as either a compliance finding or a
  violation. Rides the batched native build. Same class as the CP-signature
  replay and the orientation false-cover — a stored value asserting something the
  human never affirmed.

- **[HIGH] Orientation coverage matching is heuristic — can FALSE-cover and hide an LL196 gap.**
  The combined-report subcontractor-orientation coverage number ("X of N on-site
  workers with first-time orientation on file", `generate_combined_report`) matches
  on-site check-ins to orientation docs by `worker_id` OR normalized name. Manual
  orientations mint a synthetic `worker_id` (`manual_<ts>_...`), so a name fallback
  is required — but two on-site workers sharing a normalized name can mark an
  un-oriented worker as covered, HIDING a real LL196 first-timer violation on a
  compliance document (false-negative — the dangerous direction). Real fix: persist
  an orientation flag/link on the WORKER record, keyed to the real worker and
  resolved at orientation time (rides the batched native build), so coverage is a
  direct lookup, not a name heuristic. Caveat in the same area: the coverage
  denominator uses `status == "checked_in"` as the on-site proxy; on a PAST-date
  report that means "checked in that day and never checked out," not literally "was
  on site" — fine for the live daily report, a caveat for historical dates.

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

- **Free text where a picker belongs — company and trade.** Device round 6,
  finding 5, ruled STORED-NOT-RENDERED and deliberately not fixed as a string.
  An OSHA register row on 588 Thomas S Boyland reads `A AZ`; every other row on
  the same filed document reads `AAZ`. `_capitalize_first` (server.py:18274)
  upper-cases the first non-space character and preserves the rest exactly, so
  nothing in the renderers inserted that space — somebody typed it into a row he
  had added by hand, and it filed.

  SAME CLASS as `Concrete` vs `Concrete / Cement`: a field the app already knows
  the answers to, offered as free text. The gate holds the companies on site and
  the taxonomy holds the trades, and neither is offered at the point of entry, so
  every hand-added row is one typo away from a filed document that disagrees with
  itself.

  THE TRADE PICKER on the backlog closes both — one control, sourced from what
  the project already knows, replacing free text on the company and trade fields.
  Recorded here rather than patched: normalising the stored string would hide the
  entry gap that produced it, and the next row would read `AA Z`.

- **[MED] `daily_jobsite` activity rows have no emptiness gate on EITHER renderer.**
  Device round 6, reported not fixed. `render_logbook_html`'s daily_jobsite
  branch (`act_rows`, server.py:13084) iterates `data.activities` and emits a
  row for every entry, with no test for whether the entry says anything — an
  untouched crew row prints as a line on a filed §3301.2 record carrying a CP's
  count of 0 and nothing else. The report-side rendering, which the round-6
  notes recorded as NOT LOCATED, was located while writing this entry:
  `generate_combined_report` builds its own activity table the same way
  (server.py:19228) and has the same gap. Two renderers, one missing rule.
  The OSHA register, the pre-shift sheet and (as of this round) the toolbox
  attendee table all gate their rows; these two do not.

  NOT THE SAME RULE, which is why it was reported rather than patched with the
  others. Those three are PERSON-owned records — every row names a man, so "no
  name, no row" is the rule and it is the same rule in all three. An activity
  row is CREW-owned: it names a company and a crew id, and what makes it real
  is arguable in a way the others are not (a crew that showed up and did
  nothing recordable is a fact about the day). Deciding the minimum content for
  an activity row is the per-form ruling `finalize_logbook` still defers to the
  operator, and inventing one in the renderer would assert a minimum the form
  has never declared.

- **[MED] `preshift_signin` can STORE a nameless worker row, though it never prints one.**
  Device round 6, reported not fixed. Both renderers gate the row on
  `if w.get("name", "").strip()`, so a nameless row has never reached a
  document — but the sheet is deliberately absent from
  `_SUBMIT_ROW_CONTENT_RULES` (`_SUBMIT_ROW_CONTENT_RULES_DEFERRED`), so the
  row is accepted and stored. The STORED record and the FILED record therefore
  differ: an inspector reading the PDF and an auditor reading the collection
  see different sheets, and only the second one shows the row.

  THE DEFERRAL STANDS and its reason is unchanged: `preshift_signin.jsx` has no
  client gate, so turning the server rule on would create a refusal a live CP
  meets for the first time mid-shift, at the gate, on the one form where being
  stopped costs a man the start of his day. It comes back when that form is
  ported onto the shared stepper and has a client gate in front of it — exactly
  the sequence `osha_log` followed, and exactly what item 1 of this round added
  to `osha_log` at FINAL SUBMIT.

- **[LOW] Two surfaces were NOT traced in device round 6 and are unverified.**
  Stated so neither is mistaken for cleared:
  - **The kiosk inspector view** (`app/site/logbooks.jsx`) was not traced for
    `osha_log` or `toolbox_talk`. The nameless-row rule was applied to the two
    PDF renderers and to what is filed; whether the on-site kiosk shows such a
    row is unknown.
  - **`daily_jobsite`'s report-side activity rendering** was recorded as not
    located; it has since been found (server.py:19228) and folded into the
    activity-row item above. Nothing about it is outstanding except the ruling
    that item is waiting on.
