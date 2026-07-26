# Audit follow-ups

Running log of deferred fixes surfaced during audits. Newest first.

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
