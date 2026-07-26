# Audit follow-ups

Running log of deferred fixes surfaced during audits. Newest first.

---

## 2026-07-26 — Violation-type code labels need an official DOB source

DOB violation-type codes (`JVIOS`, `JVCAT5`, `E`, `LBLVIO`, the `LL*` family,
and DOB NOW Safety `FTC-*/FTF-*` codes) are currently shown to customers as
`DOB code: {code}` — the honest raw code — because there is **no verified
official label** for them yet. The DOB Violations dataset (`3h2n-5cm9`) embeds a
description in its `violation_type` column, but that is dataset text, not a
dedicated authoritative DOB violation-type code list, so it is treated as
UNVERIFIED.

A transcribed-from-dataset map exists but is **quarantined** behind
`UNVERIFIED_VIOLATION_TYPE_LABELS_PENDING_SOURCE` in
`backend/dob_complaint_codes.py`, with a comment that it must not be displayed;
`violation_type_display()` deliberately does not read it, and a test
(`test_display_never_returns_an_unverified_label`) enforces that.

**To close:** confirm each code→label against DOB's official published
violation-type reference (or the `855j-jady` data-dictionary xlsx for the
`FTC-*/FTF-*` family), then promote the verified entries into the display path.
Until then, violation types stay prefixed. (Complaint category + disposition
labels already have official sources and DO display.)

---

## 2026-07-26 — OverviewByBinServlet: code was already clean; risk is stored data + doc drift

**Finding.** A repoint of violation tier-3 links off the decommissioned
`OverviewByBinServlet` was requested, but the builder was **already** clean: every
BIN fallback (`_build_dob_link` violation/permit/job_status/inspection/final)
routes through `_bis_bin_overview_url` → `PropertyProfileOverviewServlet?bin=`
(the confirmed-live BIN profile), and there is **zero** `OverviewByBinServlet` URL
construction in the deployed tree. The only residue was **stale docstring text**
in `_build_dob_link` (three "→ BIS OverviewByBin" lines plus an outdated
permit/job_status routing summary) — corrected this pass. `_bis_property_profile_link`
does not exist. The `SourceInvariantTest` guard already forbade the dead URL; a
functional guard (`test_no_record_type_emits_overviewbybin`) was added so no
future branch can reintroduce it regardless of URL literal.

**Why links can still LOOK dead (data, not code):** `dob_link` is written at
ingest, but the dob-logs read path (`server.py` ~18085) rebuilds it from each
row's `raw_record` on every read — so a stale stored `OverviewByBin` value is
replaced with the live URL at read time **iff the row has a `raw_record`**. A row
with no `raw_record` keeps its stale stored link. Remedy for those is a re-poll
(`/projects/{id}/dob-sync`), not a code change. `backend/scripts/violation_link_check.py`
reports, per record, stored-vs-freshly-built link and whether a `raw_record`
exists (auto-heal) or is missing (genuinely stale).

**Lesson — BIS legacy servlets are being retired mid-lifecycle.** DOB has quietly
decommissioned `OverviewByBinServlet` (now BIS "Page not found") while
`PropertyProfileOverviewServlet` stays live. BIS-based deep links therefore need
**periodic** re-verification, not one-time confirmation; treat any BIS servlet as
"confirmed as of <date>", and keep all BIN links flowing through the single
`_bis_bin_overview_url` helper so a future swap is one edit.

---

## 2026-07-26 — Permit / job_status links repointed to BIN property profile

**Done.** DOB NOW permit/job_status filings had no public per-record URL (DOB NOW
is a login-walled Angular SPA whose Job-Number search does not encode the job in
the URL — confirmed by live fetch; its result URL is `…/Index.html#!/search`),
and the old `data.cityofnewyork.us/w9ak-ipjd.html?job_filing_number=` link landed
on a generic dataset page because Socrata's `.html` surface ignores the column
filter. All permit/job_status now resolve to the SAME confirmed-working BIS BIN
property profile used for the violation fallback
(`PropertyProfileOverviewServlet?bin=`, via `_bis_bin_overview_url`); legacy
BIS-numeric permits (previously `JobsQueryByNumberServlet`) share it too. No BIN
→ no link.

**Candidate to verify when BIS is reliably up: `JobsQueryByLocationServlet` for
I1/inspection-suffix filings.** This per-location servlet was *proposed as a
possible per-filing surface but never fetch-confirmed* — it did not appear as a
tested/working destination in the link diagnostic. It was therefore NOT adopted;
I1 filings fall back to the BIN property profile like the rest. If a live fetch
(when BIS is not throwing its intermittent high-traffic / Access-Denied errors)
returns a real per-filing page for a DOB NOW `…-I1` job, it could be adopted for
that subset. Until fetch-confirmed, do not build it.

Note: BIS (a810-bisweb) was intermittently Akamai Access-Denied during
verification — `PropertyProfileOverviewServlet?bin=` loaded live (twice) while
`JobsQueryByNumberServlet` and `OverviewByBinServlet?requestid=2&allbin=` both
errored (the latter a genuine "Page not found", confirming that shape is dead —
only `PropertyProfileOverviewServlet?bin=` is the working BIN form).

---

## 2026-07-25 — Check-in date handling fixed, but never tested via a real NFC tap

**Done.** Bucketing check-ins by NYC-local day was fixed across all six date
sites (4 backend UTC-midnight `strptime(...tzinfo=utc)` sites → `get_day_range_est`,
frontend `getByDate` → NYC-local date, dashboard `on_site_now` → EST-today to
match the project ON SITE tile). Verified against synthetic boundary records
(8:30pm EDT rollover + early-EST lower boundary) via
`backend/scripts/checkin_tz_verify.py`.

**Deferred — physical device test required before customer reliance.** The full
NFC-tap → kiosk write → display path has **never** been exercised on a real
device; verification to date is synthetic records only. Per the
device-test-before-production principle, run a real on-device check-in end to
end before relying on the feature with a customer. Note: zero real check-ins
exist on either live project today, so the write path is unproven in production.

---

## 2026-07-25 — Rodent-inspection (p937-wjvj) removal: deferred statistical-engine scope

**Context.** `p937-wjvj` is NYC **DOHMH Rodent Inspection** data (rat inspections),
which the app ingested and labeled as **DOB inspections**. The `PC` (Pest Control)
job prefix was additionally fabricated into a `"Plumbing"` trade category by
`DOB_JOB_PREFIX_CATEGORY` / `_decode_job_prefix`. Verified against live Socrata
(source result = "Failed for Rat Activity") and the dataset metadata API
(name = "Rodent Inspection", attribution = DOHMH).

**Done (COMMIT 1, 2026-07-25).** Removed the two `p937-wjvj` ingest endpoints and
the inspection-only composite raw-id fallback in `server.py:_query_dob_apis`;
removed the now-callerless `DOB_JOB_PREFIX_CATEGORY` map, `_decode_job_prefix`,
and its three call sites (`_extract_inspection_fields`, `_generate_summary`
inspection branch, the read-time re-enrichment block). No new `record_type=
"inspection"` rows enter `dob_logs`.

**Deferred — folded into the score rebuild (NOT patched now, because the risk
score is getting a full rebuild and patching its rat-fed dimensions now is
throwaway work the rebuild redoes correctly):**

`DATASET_DOB_INSPECTIONS = "p937-wjvj"` (`lib/statistical_engine/socrata_client.py:85`)
still feeds the risk model **live via Socrata** on four surfaces — all currently
ranking/predicting on DOHMH **rat** inspections:

- **Peer inspection dimension** — `lib/statistical_engine/baselines.py`
  (`compare_project_to_peers`, ~lines 880/900/1163/1273) → `peer_compare["inspections"]`
  → `inspections_percentile` → averaged into the peer subscore
  (`score.py:_normalize_peer_comparison`). Both the project and its peer set are
  ranked on rat-inspection counts.
- **Borough-sweep trigger** — `lib/statistical_engine/triggers.py:741–907`
  (`borough_inspection_counts_90d` / `last_7d_count`, `TRIGGER_BOROUGH_SWEEP`).
- **Inspection prediction** — `lib/statistical_engine/predictions.py`
  (`predict_inspection_from_complaint`, chunked `bbl IN (...)` against p937-wjvj).
- **Calibration** — `lib/statistical_engine/calibration.py:89`
  (`TRIGGER_BOROUGH_SWEEP → (DATASET_DOB_INSPECTIONS, "inspection_date")`).

**Required in the rebuild.** Redesign these against the CORRECT DOB inspection
source(s). Per-trade construction inspections are **not** in NYC Open Data (they
live only in the DOB NOW public portal, per job); the open-data DOB inspection
sources are the periodic safety programs — Boiler `52dp-yji6`, Elevator
`e5aq-a4j2`, Facade FISP `xubg-57si`, CO/TCO `pkdm-hqz6` — each BIN-keyed with
plain-English results. Until then, the peer/trigger/prediction inspection
dimensions are contaminated by rodent data and must not be trusted.

**Also deferred (harmless display/link cleanup, no data behind it):** the
`record_type=="inspection"` display/link/template/notification code in
`server.py` (`_build_dob_link` inspection branch ~16899, severity map entry,
`dob-logs.jsx` `renderInspectionCard`) and the existing `dob_logs` rodent rows
(deleted separately in COMMIT 2).
