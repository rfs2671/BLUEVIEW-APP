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

## Update: ten ECB/OATH summonses issued the afternoon of 2026-11-10

The operator reported nine violations. The numbers supplied were ten: 039561781P, 782R, 783Z, 786Y, 787X, 788H, 789J, 790R, 791Z, 792K. These are OATH ticket numbers; drop the leading 0 to get the DOB ECB number.

**Where each source stood, checked 21:42–21:55 UTC.** The same answer holds for all ten.

| Source | Contains them? | Evidence |
|---|---|---|
| BIS ECB by number (`ECBQueryByNumberServlet`) | **No.** "NOT FOUND" | Control: the same query returns 39556258Y |
| BIS ECB list, BIN 3255205 | **No.** 19 issued, newest 07/07/2026 | Page count equals rows read |
| BIS ECB list, BIN 3423445 (rear) | **No.** 1 issued, from 2025 | |
| BIS DOB violations, both BINs | **No** | Two closed 1986–87 items |
| BIS complaints 3A88489 / 3A88492 | **No disposition, no ECB number yet** | |
| Open Data 6bgk-3dad (ECB) | **No** | Refreshed 18:09 UTC |
| Open Data 3h2n-5cm9 / 855j-jady | **No** | Refreshed 18:38 / 19:07 UTC |
| OATH hearings jz4z-kudi | **No** | Refreshed 05:59 UTC |
| DOB NOW public portal | **Unknown: the portal itself was down** ("DOB NOW is unavailable") | |
| LeveLog production (`dob_logs`, `dot_logs`) | **No** | Read-only probe |

**Why LeveLog has not shown them.** No source LeveLog can read had published any of the ten. The summonses were issued on site, and DOB had not yet entered them into BIS or ECB/OATH.

**Why no notification would have fired once they were published,** under the code on main:
- **WhatsApp group:** violation alerts for 546 wait on the first sync of `dob_violations`. That sync never happens, because 3usq-5cid fails on every pass. Violations also share their baseline with permits, so permit alerts to the group were blocked too.
- **Email:** it would fire only after Open Data publishes, the next day or later. An ECB row from 6bgk-3dad that is active scores "Action", and the 2-day gate counts from the issue date.

**When each source learns of them:** being measured. `track_10_summonses.py` polls every source above every 10 minutes, read-only, and logs the first time each number appears (`track_10_summonses.jsonl`). It also saves the real BIS page the moment the numbers appear.

## Architecture fix: per-dataset sync

- **Per-dataset answers.** `_query_dob_apis` records whether each dataset answered (`ds:<id>`), alongside each record type.
- **Per-dataset state.** `source_sync_state.datasets.<id>` holds `synced_at`, `first_synced_at` and `last_error_at`. A dataset's first sync inherits its source's first sync, so nothing that was already baselined gets re-dated.
- **A source opens when any of its datasets answers in full.** A storage failure still closes it.
- **The group alert gate works per row** (`source_sync.dataset_gate`):
  - A row from a failing dataset that has never synced waits, and only that dataset's rows wait.
  - A row stored by its dataset's first sync is claimed as baseline.
  - A later row posts.
- **Freshness shows each violation dataset on its own line,** so a dead dataset is visible as itself.

## Same-day summons discovery

- **What it reads:** the BIS ECB list for every BIN of the project, in `lib/bis_violations.py` (it parses the page's own structured record, including the issued count).
- **Dedup:** new numbers are reconciled with stored rows by ECB number. The Open Data row arriving the next day refreshes the same row instead of adding one.
- **Alert priority:** Class 1 is critical, Class 2 is high. The email text gives the summons number, class, unit, hearing and the BIS link.
- **Separate state:** it has its own state (`watch.bis_ecb`), so an ECB-page failure never fails the complaint watch, and the reverse.
- **Rollout:** same mode switch, `BIS_COMPLAINT_WATCH_MODE`, still off.

## Tests (`tests/test_violation_sources_546.py`, `tests/test_bis_complaint_watch_flow.py`)

- **Parsing:** the real ECB pages for both BINs parse completely. The ten numbers normalize to their ECB form, and none appears on the 21:4x pages.
- **Dead dataset:** a real `_query_dob_apis` pass with 3usq-5cid returning 400 still syncs violations.
- **Group alert:** the tick, with 3usq-5cid failing on every pass, posts a later ECB violation and keeps the history silent. It failed on origin/main (0 posts).
- **Discovery:** on the real page, a summons BIS lists that LeveLog lacks is found, stored and emailed once.
- **First sync and outages:** a first pass stores the history silently, and an ECB outage does not fail the complaint watch.
- **The ten end to end: SKIPPED until BIS lists them.** It runs on the real page the tracker captures. No synthetic records stand in for them.

## Independent review and fixes

An independent reviewer read the branch at aea671ee and found five confirmed defects, plus two lower-severity ones. Each fix has a test that failed on aea671ee:

1. A stored `detected_at` comes back from Mongo without a timezone, and BIS's received time has one. Subtracting them raised `TypeError`, which aborted the whole pass for the project (ECB included) every tick.
2. A stop-work disposition on a stored complaint that stays ACTIVE was skipped, and never alerted. Updates now:
   - write `disposition_code`, status and `status_history` onto the row;
   - email only under the Open Data path's own rule (`dob_alert_gate.update_issues_order`).

   So the next day's Open Data refresh does not email the same order again.
3. That same fix removes the duplicate stop-work email (BIS first, Open Data about 26 hours later).
4. Shadow saved `lot_bins`, which made the Open Data scan store and post the rear BIN's records. `lot_bins` is now saved only in live mode.
5. A failed property page dropped the rear BIN while still reporting "fresh". It is now recorded as an error, the saved BINs stand in, and the page's BIN is checked.
6. Lower severity:
   - The cross-path email check could never match the throttle keys; it now matches them.
   - Soft-deleted rows were re-inserted; they are now left alone.
   - A ledger row written before a failed insert stuck forever; it is now removed.

Found while testing the screen and in the full suite:

- Shadow mode reported "Checked DOB BIS directly" next to an empty list. Freshness now claims live coverage only in live mode.
- Complaint cards inserted from BIS were blank. They now show DOB's own text.
- `complaint_status` now follows updates, so `/dob-summary` counts a resolved complaint as closed.
- The new lot-BIN step could discard the site-BIN records already found if its state read failed. It now has its own guard.

**Mount smoke.** The Compliance screen is served the real `/dob-logs` output for 3A88489 and 3A88492, generated by the backend endpoint. It must show both numbers, DOB's text and the freshness line, in light and dark: 84/84 routes pass.

## Second and third review: fixes, and proof on a real database

**Second review (bd4355d1), fixed in 4b7bbe9f:**
- Switching shadow to live skipped what shadow had seen.
- A watch-stored summons or complaint could email a false stop-work order on the next Open Data refresh.
- The brief could not name a watch-stored summons.
- The assistant judged complaints by any row, and read only 80 rows.
- The report's `dob_complete` ignored a failing dataset.

**Third pass (4b7bbe9f).** Three defects, and one unproven claim.

1. **Shadow to live replayed history.**
   - **Cause:** shadow wrote its first-sync baseline into the same field live reads. Live's first pass was therefore not a first sync, and every open complaint or active summons it had not stored alerted as new.
   - **Effect on the real 546 pages:** live-after-shadow emailed:
     - 3A32841: closed 2025-10, disposition A8;
     - 39556258Y and 39556260N: July summonses, already in BIS and OATH.

     All three were emailed alongside the two genuinely new complaints.
   - **Fix:** each mode keeps its own baseline (`bins_first_synced` for live, `shadow_bins_first_synced` for shadow). Live's first pass promotes only what shadow recorded as `would_alert`. A complaint resolved in between is not emailed. A complaint shadow saw days earlier is emailed and marked late.
2. **ECB summonses were typed as stop-work orders.**
   - **Cause:** the Open Data scan retyped any violation whose text cites a stop-work order as `swo`.
   - **In production:** both `swo` rows are such summonses, 39550534Y and 39543624M (BLUEVIEW). The BIS watch stores the same summons as a violation, so its type depended on which path saw it first.
   - **Fix:** an ECB/OATH summons is never itself an order, at every step:
     - ingestion (no retype);
     - classification (subtype `ECB`);
     - the order gate (`order_in_force`);
     - the Shabbos-critical rule (`is_critical`).

     Orders from 3usq-5cid, and complaints DOB disposed with an order code (e.g. 3A70077, L1), are still orders.
3. **A complaint's alert headline followed its priority.** A complaint whose text mentions an SWO was headed "STOP-WORK ORDER". The headline now follows DOB's disposition: "Urgent DOB complaint" unless DOB issued the order.
4. **The 311 limit case was not proven.**
   - **Why the fake could not prove it:** it ignores sort and row limits, so the 4b7bbe9f test could not fail.
   - **Fix:** the assistant now excludes 311 rows in the database query (`complaint_source`) and reads without a row limit.
   - **Proof:** `tests/test_dob_status_real_mongo.py` runs on a real mongod (local `mongo:7.0` container):
     - **Limit:** an open complaint older than 2,500 newer 311 rows is listed. The database hands back 4 rows, not 2,504.
     - **Closed complaints:** a complaint whose newest row is CLOSED is not listed. The older ACTIVE row is inserted first, so only a real sort gets this right.

**Control runs on the real database:**
- **4b7bbe9f:** 4 of 7 fail. The assistant answered "No open DOB complaints on file" while 3A88489 was open behind the 311 rows. Shadow-to-live replayed history.
- **bd4355d1:** both 311 assistant tests fail.

**Needs an operator ruling:** the two production `swo` rows (39550534Y, 39543624M) keep their type, because the refresh preserves `record_type`. Correcting them is a production write: `record_type` `swo` → `violation` on those two `dob_logs` rows.

## Final independent review (892e350d)

The reviewer found **no way for off or shadow mode to write records, send email, post to WhatsApp, or change state another job reads.** It found nine live-mode defects. Seven are fixed here, each with a test that fails on 892e350d (`tests/test_bis_watch_review4.py`, plus the summary count on a real database):

| # | Defect | Fix |
|---|---|---|
| D1 | Rows the watch inserted counted closed items as open: no `resolution_state` on summonses, and BIS's "RESOLVED" where `/dob-summary` looks for "closed". After one live pass, the summary would have shown 20 open summonses for 546 and 10 open complaints. | Rows are stored in Open Data's own words. On a real database the summary counts **2 open complaints and 2 open violations**. |
| D2 | A stop-work order lifted in full was never alerted once BIS saw the lift first. | The watch's update path applies `update_lifts_order` and emails the lift once. |
| D3 | A complaint's text ("work contrary to stop work order") counted as an order in force, so DOB's later A3 was never alerted. The text also made the complaint "critical". | A complaint is under an order only by DOB's disposition. |
| D4 | H3, H4 and V3 (violations for disobeying an SWO) read as new orders. A4 read as a lift. L2 and Y2 were missing. A vacate order was emailed as a stop-work order. | Sets follow DOB's own code labels. Vacate is its own event. Padlock and emergency declarations are urgent, but not stop-work orders. |
| D5 | The two production rows an older scan typed `swo` still read as stop-work orders. | A row from a summons dataset is a summons everywhere it is read. A 3usq-5cid row is still an order. |
| D6 | A watch-stored summons dropped out of `/dob-summary` on Open Data's first refresh (treated as a seed transition). | Rows carry a status history in Open Data's vocabulary, so the refresh sees no change. |
| D7 | A summons shadow judged new, which Open Data then stored silently, was never alerted. | Live's first pass sends what is owed from shadow, once, unless another path already sent it. |
| D9 | "Open DOB complaints (5)" was printed for any count over 5. | The real count is printed. |
| — | A malformed BIS issue date aborted the pass. | It is decided as undated. |

**Left as found, with reasons:**
- **D8.** A recovering dataset's history posts rather than baselines; the 2-day age rule still refuses it downstream, and no wrong post was observed.
- **Two emails for one served violation.** A brand-new complaint closed on arrival with A8 is emailed once as the complaint and once as the summons it produced. This is low severity.
- **The two legacy `swo` rows keep `record_type` `swo` in the database.** Every reader now treats them as summonses. Correcting the stored type is a production write that needs a ruling.

**Second reviewer, on the fixes (1a79ba4b).** It confirmed that off and shadow still cannot write or send. Four tests fail on 1a79ba4b:
- **A duplicate stop-work email.** An owed complaint alert recorded BIS's state, which kept the update path from writing an order onto the row. Open Data could then re-email the same stop-work order once the 24 h throttle expired. Now:
  - an owed alert is never an order;
  - the update path writes and stamps the order.
- **V3.** DOB's action for it reads "Stop all work", so it stays an order. **This needs an operator ruling.**
- **Partial rescinds.** A partial rescind (L3, Y4) leaves the order in force, so the later full lift alerts.
- **Old summonses in the morning brief.** The brief no longer calls a summons an older scan typed `swo` a "Stop-work order".

## Operator ruling 2026-11-11: an order is issued, not worded

An officially issued stop-work order is distinct from a violation that references or alleges stop-work conditions. **Wording never makes an order.**

**What counts as an order:**
- a record of the stop-work dataset (3usq-5cid);
- a complaint DOB **disposed** with an order code: A3 full, L1 partial, H5, K4, K6, and vacate Y1/Y3.

**What changed:**
- **V3** ("Stop Work Order Violation Served for Non-Compliant After Hours Work") is a violation served, as DOB labels it. It is alerted at high priority, never headed "STOP-WORK ORDER". This reverses the earlier conservative choice.
- **Open Data ingestion** no longer retypes a violation as `swo` from its words. Measured in production, that rule had typed 3 rows as stop-work orders, and none came from the stop-work dataset:
  - ECB summonses 39550534Y and 39543624M;
  - DOB violation 2820774, a "V-DOB VIOLATION - ACTIVE" whose text reads "BOROUGH COMMISSIONER HAS ORDERED ALL WORK STOPPED". It was given subtype SWO_FULL. It is now COMM_ORDER, still open and on the open-violations list, with DOB's words intact. Its stored subtype is recomputed on the next Open Data refresh.
- **The order gate and the Shabbos-critical rule** no longer read stop-work wording on a violation. Vacate wording is unchanged.
- **DOB's exact disposition words and their source** are kept on BIS rows (`disposition_label`, `disposition_source: "DOB BIS"`). They also appear in the complaint alert (EN/ES) and on the Compliance card: "DOB disposition (BIS): V3 - STOP WORK ORDER VIOLATION SERVED FOR NON-COMPLIANT AFTER HOURS WORK."

**Final review of the ruling change (995dc5d7).**
- **Wording paths:** every remaining stop-work match on an alert path is keyed on the stop-work dataset or a complaint's order disposition.
- **Issued orders:** they and their lifts still alert once.
- **One real defect:** Open Data's midnight extract wrote yesterday's state and LeveLog's own label over what BIS had printed, while the source tag still said "DOB BIS". For example, ACTIVE with no disposition over CLOSED with "L1 - PARTIAL STOP WORK ORDER". It flipped the row and the counts until the next pass.
  - **Fix:** while the watch is live and read the project within the hour, BIS owns a complaint's status and disposition fields. Off, shadow or a stale watch leaves Open Data as before.
  - **Source tag:** it now says where the words came from: BIS's printed words, or BIS's code with DOB's code-table label.
- **Also fixed:**
  - A violation's type wording no longer yields "STOP ALL WORK" advice.
  - A complaint's stop-work text is recorded as an allegation, not as "names a stop-work order".
- **Left as found:**
  - A complaint disposed A3 → V3 → L2 does not alert the final lift. V3 is not an order, and the same gap already existed for H3/H4.
  - An analytics counter (`statistical_engine/triggers.py`) counts neighbours' stop-work orders by wording. It is not an alert path.
