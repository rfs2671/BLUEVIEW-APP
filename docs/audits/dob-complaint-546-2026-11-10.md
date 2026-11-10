# 546 Saratoga Ave: two DOB safety complaints LeveLog did not surface (2026-11-10)

This is kept separate from the 588 Boyland benchmark. No 546 data enters 588's evidence.

All production reads were read-only probes (find and count only, with a write guard). Nothing in production was written, and nothing was sent.

## What happened

| Complaint | Received by DOB | Category | DOB's text | State at 19:48 UTC |
|---|---|---|---|---|
| 3A88489 | 11/10 11:22 ET | 8A Construction Safety Compliance, priority D | NO ROOF PROTECTION, NO WINDOW PROTECTION NO DOCS | ACTIVE, not inspected |
| 3A88492 | 11/10 11:25 ET | 8A, priority D | FENCE CONTRARY, HOUSEKEEPING, FIRE EXTINGUISHERS, INFO PANELS, UNSAFE CONDITIONS | ACTIVE, not inspected |

Both are at BIN 3255205 (block 3514, lot 153, owner KHLA TWO LLC). BIS lists a second BIN on the lot, 3423445 ("546 REAR").

## Monitoring setup (production, read-only)

- **Project:** `6ace527e…` "546 Saratoga Ave", company BLUEVIEW CONSTRUCTION INC (not a test company). Created 2026-10-13.
- **Identifiers:** `nyc_bin` 3255205 and BBL 3035140153 are both correct. `track_dob_status` is true, so the project is scanned every 15 minutes.
- **Complaint feed:** `dob_complaints` last synced 19:34 UTC, healthy.
- **Violations feed:** `dob_violations` has never been first-synced (see R4).
- **Second BIN:** 3423445 is not monitored.
- **WhatsApp:** no WhatsApp group is confirmed for this project, and `whatsapp_notification_ledger` has no group rows for it.

## Detection timeline (2026-11-10, ET)

| Time | Event | Source |
|---|---|---|
| 00:00 | Open Data cuts its daily extract (`dobrundate` 20261110000000) | eabe-havv rows |
| 11:22 / 11:25 | DOB receives 3A88489 / 3A88492 | BIS detail "Received" |
| 12:15 | eabe-havv republished; newest Brooklyn complaint is 3A88386 (filed 11/09); neither new complaint is in it | Socrata `rowsUpdatedAt` 17:15 UTC |
| 14:34 | LeveLog's last complaint sync for 546; Open Data has nothing new for it | `source_sync_state` |
| 14:48 | First BIS check: both complaints listed, ACTIVE | BIS ComplaintsByAddress |
| ~14:55 | BIS answers from the production container (HTTP 200, 0.2 s) | `railway ssh` probe |
| 11/11 about 12:15–13:30 (expected) | eabe-havv includes them; LeveLog stores them within 15 minutes | measured precedent below |

**Measured precedent for the Open Data path:** about 41 hours from midnight of the filing day to the stored row, which is about 25 hours after the DOB receipt time.
- 3A86084, filed 10/23, stored 10/24 16:35 UTC.
- 3A79940, filed 9/10, stored 9/11 16:55 UTC.
- 3A78809, filed 9/2, was not stored until 10/22, 50 days later. It is on 588's second BIN, which was not read until site BINs shipped.

**Measured alert latency for these two complaints under current code: never.** Even after tomorrow's ingest:
- The **email path** requires severity "Action". An open 8A complaint with no disposition scores "Good" (R2).
- The **WhatsApp group path** needs a confirmed group, and 546 has none.
- There is **no push or in-app path**.

## Classification

Both complaints have the same classification:
- **Unavailable upstream:** yes, in the only source LeveLog reads. Open Data is a daily extract, and BIS had them.
- **Missed during ingestion:** no. The sync ran and answered correctly for what that source held.
- **Mismatched to a project:** no. The BIN is correct.
- **Stored but hidden:** not yet stored. Once stored, the assistant would still not have mentioned them (R3).
- **Suppressed by alerting:** yes, once stored. The severity is "Good" and no WhatsApp group is bound.

## Root causes

1. **R1, no same-day complaint source.** eabe-havv is a once-a-day extract, so polling it every 15 minutes cannot make it fresher. BIS was assumed unreachable: `lib/server_http.AKAMAI_BLOCKED_HOSTS` lists `a810-bisweb`. It is reachable from production; the Akamai wall is DOB NOW, not BIS.
2. **R2, open complaints scored "Good".** `dob_complaint_codes.classify_complaint` used the status word "ACTIVE" in place of a missing disposition code. That gave risk MEDIUM, severity "Good", and so no email.
3. **R3, the assistant read violations only.** `_handle_dob_status` answered "No recent violations on file." It never looked at complaints and gave no freshness.
4. **R4, four Socrata queries named columns that do not exist.**
   - `3usq-5cid` was queried with `street_name`; the column is `street`. This one returned HTTP 400 on every pass. A stop-work order counts toward the violations source, so `dob_violations` never first-synced for any project polled after 2026-10-08. Every violation, stop-work and order alert for 546 waited silently and forever.
   - `xubg-57si` was queried with `house_number`; the column is `house_no`. This also 400'd on every pass.
   - `52dp-yji6` was ordered by `report_filing_date` and `e5aq-a4j2` by `filing_date`. Neither column exists, so both were retried unordered.
   - 3usq-5cid is also a COVID-era (Executive Order 202.6) dataset whose newest row is 2020-05-28. No current stop-work order is in it.
5. **R5, no freshness on any surface.** An empty Complaints tab and the assistant both implied "none", with nothing about what was checked or when.

## Violations, summonses and orders (checked separately)

A complaint is not a violation.

**On the two new complaints, as of 19:48 UTC:**
- No inspection.
- No disposition.
- No violation, ECB/OATH summons or stop-work order linked to either complaint.

**Already standing at the property (not new today):**
- **Partial stop-work order, 2026-07-07:** complaint 3A70077, disposition L1, "STOP ALL EXTERIOR WORK EXP#1 AND #2", inspector badge 3207. The BIS property profile still reads "PARTIAL STOP WORK ORDER EXISTS". LeveLog stores 3A70077 only as a closed complaint, and nothing in LeveLog represents an order in effect.
- **ECB 39556258Y,** Class 2, sidewalk shed / pedestrian protection, $2,400.
- **ECB 39556260N,** Class 2, job site fence, $1,000.
- Both summonses: issued 7/7, ACTIVE. The OATH hearing was rescheduled to 2027-03-12 08:30. Respondent BLUE ELM INC, $3,400 due.
- 3A88492 cites "FENCE CONTRARY", the same condition as the pending fence summons.

## Fixes (branch `fix/dob-complaint-discovery`, not merged, not deployed)

1. **BIS complaint watch** (`lib/bis_complaints.py`, `lib/complaint_watch.py`, `run_bis_complaint_watch_for_project`, job `bis_complaint_watch` every 10 minutes).
   - **Reads:** BIS newest-first for the project's BIN, the lot's other BINs per BIS, and site BINs.
   - **Dedup:** reconciles by complaint number with the Open Data rows, so one complaint is one row and one alert.
   - **Mode:** `BIS_COMPLAINT_WATCH_MODE`, default `off`. `shadow` records decisions only. `live` stores and alerts.
2. **Alert decision** with a readable reason for every non-alert:
   - First sync is a silent baseline, except an open complaint received in the last 48 hours.
   - A late arrival still alerts and is marked late.
   - Closed on arrival does not alert, unless the disposition is a violation or an order.
   - Wrong property never attaches.
   - Duplicates never alert twice.
3. **Lifecycle as distinct linked events:** received, inspected, disposition, order issued, violation issued (ECB number from BIS), hearing scheduled, corrected, closed.
4. **Classifier:** an open, undisposed complaint in a category of MEDIUM risk or higher is "Action". LOW categories are unchanged.
5. **Assistant:** lists open DOB complaints and states freshness.
6. **`GET /api/projects/{id}/dob-freshness`** and a line on the Compliance screen (English and Spanish) giving the last BIS check, the last failure and the last Open Data read.
7. **The four Socrata columns,** corrected against the live schemas (fixture captured 2026-11-10).

## Tests

All shown failing on origin/main first where they pin a server change.

- `tests/test_complaint_watch_546.py`: the exact two complaints, plus first-sync, historical, closed, duplicate, late-arriving, wrong-property, lifecycle, freshness, classifier and assistant cases.
- `tests/test_bis_complaint_watch_flow.py`: the watcher end to end over the real BIS pages.
  - Shadow writes nothing.
  - Live stores and emails once.
  - A second pass is quiet.
  - The next day's Open Data row refreshes the same row.
  - An outage is a recorded failure.
  - Fetch budget is checked; a mutation check confirms it catches broken normalization.
- `tests/test_dob_query_columns_all_datasets.py`: every request names real columns, and a full answer opens every source's first-sync gate.

## The notification 546 should have received

At about 11:30 ET, as an email to admins and the PM, and to the WhatsApp group once one is bound:

> **DOB safety complaint — 546 Saratoga Ave**
> Complaint 3A88489, received by DOB Nov 10, 11:22 AM.
> It says: NO ROOF PROTECTION, NO WINDOW PROTECTION NO DOCS.
> Not inspected yet. A complaint is not a violation: fix this before the inspector comes.
> https://a810-bisweb.nyc.gov/bisweb/OverviewForComplaintServlet?complaintno=3A88489&requestid=0

A second message follows for 3A88492. The Spanish version is rendered by the same function.

## Needs an operator ruling

- **Turn on the watch:** set `BIS_COMPLAINT_WATCH_MODE=shadow` for a day, then `live`.
- **Bind 546's WhatsApp group.** Until then, email is the only channel.
- **Remove `a810-bisweb` from `AKAMAI_BLOCKED_HOSTS`,** or leave it. The watcher uses its own client.

## Not done here

- **Facade `id_field`:** `filing_number` does not exist in xubg-57si, so facade dedupe is keyed on nothing. Changing it renames stored rows.
- **eabe-havv ordering:** `$order date_entered` sorts MM/DD/YYYY text. Paging reads two pages of 250, so it matters only on very busy BINs.
- **3A78809:** emailed as "new" 50 days after filing, so the 2-day gate did not hold on the email path.
