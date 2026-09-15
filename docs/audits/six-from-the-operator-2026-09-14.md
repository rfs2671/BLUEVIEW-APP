# SIX FROM THE OPERATOR — 2026-09-14

Report only. Nothing fixed. Measured against production (`api.levelog.com`,
deploy `3622a9b3`) unless stated.

Two of the six reach a FILED DOCUMENT: **item 2** (302 roster rows assert a
deficiency that cannot exist) and **item 1** (the roster flags named men a CP
cleared). Item 5 reaches a man who cannot file a log with a statutory deadline.

---

## 6. AN INVESTOR CLICKS A LOGBOOK CARD AND NOTHING OPENS

**The token lifetime is not the defect.** There are two different tokens and
the question conflated them.

| | minted | lifetime | used for |
|---|---|---|---|
| `logbook_share_tokens` | at report render | `SHARED_LOGBOOK_TTL_SECONDS` = **90 days** | the CARD LINK |
| `_mint_temp_media_token` | at report render | 3600s = 1 hour | the THUMBNAIL IMAGE |

The one-hour grant is the thumbnail, and the report is delivered as a **PDF
attachment**, so thumbnails are rasterised into the file at render time. They
never need the token to survive. The card LINK is the 90-day token.

**777 share tokens live, 0 expired.**

**The link works.** Page 3 of a re-rendered report carries 18 PDF link
annotations; each card points at its own correct document (checked per card —
`daily_jobsite` to the daily jobsite log, `toolbox_talk` to the toolbox talk,
and so on). Fetched one from outside any session, no cookie, no header:

```
status=200  size=14579  type=application/pdf
```

Access log on that route: **4 requests, all 200. No 4xx of any kind.**

**But one of the three reports he may be holding had no links at all.**

| report | data date | sent | tokens minted at send | cards were |
|---|---|---|---|---|
| **#29** | 2026-09-10 | 2026-09-11 00:00:00 | **0** | **NOT LINKS** |
| #30 | 2026-09-11 | 2026-09-12 | 7 | links |
| #31 | 2026-09-14 | 2026-09-15 | 6 | links |

#29's send **preceded the first share token in the database by 73 seconds**.
Its cards were flat text. Recipients on all three: `rfs2671@gmail.com`,
`michael@blueviewbuilders.com`.

On email-client rewriting: a SafeLinks-style rewrite still resolves to the same
origin and would appear in the access log. There is no 4xx and no request that
failed, so nothing supports a rewrite failure.

**THE ONE THING THE LOGS CANNOT SAY: which report he has.** If it is #29, that
is the answer and it is already closed going forward. If it is #30 or #31, the
link is live from outside a session and the failure is on his side — which is
why what he actually SEES (404 / login wall / blank page / nothing at all) is
worth one question.

---

## 1. SST STILL UNAFFIRMED THE DAY AFTER THE CP APPROVED

**Neither piece shipped. The approval writes to a different collection from the
one the roster reads.**

- The CP's approve writes `review_decision: 'approved'` onto **`db.checkins`**.
- The sheet reads `needs_review` on a certification inside **`db.workers`**.
- **Nothing in `main` lowers it.**

`card_check_covers()` and `POST /checkins/{id}/card-check` exist only on branch
`sst/card-check-clears-review-and-four-states`, one commit **`41e87c92`
(2026-09-03)**. `git cherry` reports `+` — absent from main. **No PR was ever
opened.** `card_check_covers` appears **0 times** anywhere in `backend/`. The
needs_review-clearing work is in the same state.

**Named, measured:**

| worker | card | CP approved | cert flag today |
|---|---|---|---|
| **Angel Lopez** | — | **2026-09-14 11:00:33** | `needs_review=True` |
| Jose David Hernandez Pena | XCAS2DYB8G | 2026-09-02 11:32:18 | `needs_review=True` |
| WILMER CARRILLO | 4YU1RY8KKM | 2026-09-02 11:35:26 | `needs_review=True` |
| Hector Ramirez | SST7F6308A7 | 2026-08-16 12:43:26 | `needs_review=True` |
| Dmitri Volkov | SST072F2336 | 2026-08-16 12:43:26 | `needs_review=True` |

Angel Lopez was approved this morning and the sheet still flags him.

---

## 2. EVERY WORKER UNAFFIRMED ON PRE-SHIFT

**Confirmed, and it is worse than described: a worker's mark cannot be affirmed
at all. The state does not exist for him.**

Across filed pre-shift rosters:

```
worker rows                        400
  has a mark                       302
  mark type str                    302      <- every one
  mark type dict                     0
  AFFIRMED                           0
```

`_is_affirmed_signature(sig)` is `isinstance(sig, dict) and
sig.get("affirmed") is True`. A string can never satisfy it. And nothing
anywhere writes `affirmed` onto a worker's roster mark — the only writers in
`server.py` are `update_logbook` and `withdraw_amendment`, both for the
**document-level CP signature**.

So **302 of 302 signed worker rows render**:

> ⚠ UNAFFIRMED — no affirmation record for this document

against a man who did sign, with no action on site that can clear it.

**This is a RE-INTRODUCED defect.** `_preshift_signature_cell`
(`backend/server.py:30102`) carries this in its docstring:

> IT MUST NOT PRINT "NOT AFFIRMED" AGAIN, in any form: that was a finding
> against a named man from a field nobody wrote.

The declarative engine's `ink()` appends the affirmation banner to **every**
mark, which puts the overlay straight back.

**And my own test now pins the defect as correct.** During the migration I
restated `test_preshift_affirmation_record.py` so it asserts
`assertIn("UNAFFIRMED", signed)`. That assertion is mine, it is wrong, and it
would have stopped anyone else from fixing this.

---

## 3 AND 4. TOOLBOX AND ORIENTATION SHOWING DAILY

**Right about the cards. Wrong about the ratio — they are two different lists,
and the shortfall has a different cause.**

The registry is correct:

```
toolbox_talk                weekly
subcontractor_orientation   as_needed
```

`due = [t for t in required if frequency.get(t) in (None, "daily")]` excludes
both, on all 5 projects that hold logs. `RequiredLogsState.ratio` is
`f"{due_filed} of {len(due)}"`. **Neither type has ever been in the
denominator.** The compliance ratio is not wrong.

**The cards iterate `required`, not `due`** — so a weekly or as-needed type
gets a card every single day. On 2026-09-14: `toolbox_talk` FILED,
`subcontractor_orientation` NOT_DUE. That is the "showing daily" he sees, and
it is a presentation question, not a counting one.

**The shortfall is real. 44 of 52 project-days are short** (matching his
38-of-44):

| missing type | days | frequency |
|---|---|---|
| `site_superintendent_log` | 26 | daily |
| `scaffold_maintenance` | 24 | daily |
| `osha_log` | 21 | daily |
| `preshift_signin` | 16 | daily |
| `daily_jobsite` | 6 | daily |
| `ssc_daily_safety_log` | 2 | daily |
| `concrete_operations` | 2 | daily |

**Toolbox and orientation appear nowhere in it.** The top driver is item 5's
log.

---

## 5. THE CP SEES THE SUPERINTENDENT LOG

**Two different reads, answering two different questions.**

| | reads | asks |
|---|---|---|
| **THE TILE** | `getVisibleLogTypes()` in `frontend/app/logbooks/index.jsx` renders the server's `required_logbooks` verbatim; `site_superintendent_log` enters that list when `project.superintendent_log_active` is true | *is this log ON for this project* |
| **THE GATE** | `_refuse_if_not_the_superintendent` (`backend/server.py:24873`) reads `db.cs_registrations` and compares the signer through `attribute_signer` / `cs_filing_refused` | *is this PERSON the registered CS* |

**The tile never asks who the user is.** No frontend file reads
`cs_registrations` at all.

Measured on 588 Thomas S Boyland Street — the one project with the flag on.
Registered CS: **Michael Cespedes**.

```
accounts that see the tile: 9
   Roy Fishman        owner    REFUSED AT SUBMIT
   TEST               admin    REFUSED AT SUBMIT
   Meilich Friedman   admin    REFUSED AT SUBMIT
   Michael Cespedes   cp
   test               admin    REFUSED AT SUBMIT
   Test               admin    REFUSED AT SUBMIT
   test               owner    REFUSED AT SUBMIT
   wilson peleaz      cp       REFUSED AT SUBMIT
   wilson@cp.comm     owner    REFUSED AT SUBMIT
```

**8 of 9 see a tile they cannot file**, including `wilson peleaz`, a real CP
assigned to the project.

**And it is worse than "open and cannot file", in two ways.**

1. **The refusal lands at the last possible moment.** The gate runs on
   `POST /logbooks` and on `PUT` **only when the status is submit** — drafts
   save clean, by design. So he fills the whole log, every autosave succeeds,
   and the refusal arrives the instant he presses Submit, on the one log whose
   deadline is *before he leaves the site*.

2. **The refusal's message never reaches him.** The server deliberately names
   who may file (`registered_name` in the detail — the helper's docstring says
   why). The screen routes every 4xx through `gateCopy(code)`, which looks up
   `code_NOT_THE_REGISTERED_SUPERINTENDENT` in i18n. **That key does not
   exist.** He gets the fallback:

   > *"That could not be recorded just now. Your entry is kept — try again."*

   Telling him to retry a refusal that will never succeed, with no name and no
   remedy.

7 superintendent logs are filed, all by Michael Cespedes' account —
2026-09-04, 09-07, 09-08, 09-09, 09-10, 09-11, 09-14.
