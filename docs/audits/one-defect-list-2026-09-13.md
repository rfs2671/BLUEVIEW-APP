# Every known defect, one list — 2026-09-13

Everything from the 2026-09-11 handoff (`open-defects-2026-09-11.md`, its
fourteen live entries and its fifty routes) plus every finding of the
thirteen-type render migration, in one place.

**Ordered by two questions, in this order:**

1. **Does a filed document say something that is not true?** A compliance record
   is the product. A wrong statement on one outranks everything, because it is
   the thing an inspector, a lender or a court reads and there is no other copy.
2. **Can anyone reach it?** Within a tier, a defect on 135 filed records outranks
   one on 4; a route anybody can call outranks a screen only an admin sees.

Cost, latency and code hygiene come last. They are real and none of them is a
lie on paper.

---

## How to read this

**Every row says LIVE or FIXED.** FIXED means merged, deployed, and re-measured
in production — not "a PR exists".

**The counts were re-measured on 2026-09-13, not copied.** The source document's
own first warning is that a verdict is only as fresh as the tree it was checked
against, and main has moved seventeen merges. Four verdicts changed when
re-run:

| entry | was | is |
|---|---|---|
| A15 "Areas Visited: N/A" on every daily log | live, 59 records | **0 records — FIXED** |
| A10 a role label where a name goes | partially closed | **0 sheets — FIXED** |
| A19 helpers with no caller | six | **eight** |
| A16 "corrected immediately" never printed | live | **live, and it is 4 records, not all of them** |

**Where a count and a sentence disagree, trust the count.** Each one below names
how it was measured.

---

## TIER 1 — A filed document says something untrue

### LIVE

#### T1.1 — A filed compliance log asserts a licence the superintendent does not hold *(was A2)*
**9 filed records.** The BC 3301.13.13 sheet's attribution sentence describes
how the superintendent was matched to the filing "by licence number". The DOB
card does not use that term — it carries a **registration** number — and
`registration_number` appears nowhere in this repository. The sheet is
describing a match against a field that does not exist under a name the
regulator does not use.

*Carried verbatim through the conversion deliberately: changing the words on a
filed compliance record is a decision with the operator's name on it.*
**One sentence to fix, in `attribution_sentence`.**

#### T1.2 — Nine filed orientations print "UNASSIGNED" as the worker's company *(was A4)*
**9 of 135 orientations store `worker_company: "UNASSIGNED"`, and all 9 print it
raw.** On a signed orientation record that reads as the name of a firm.

`sub_company` already exists for exactly this and renders "Pending assignment";
the daily jobsite crew table uses it. The orientation declaration binds `name`.
**One formatter name in `schema.py`** — but it changes what 9 filed documents
say, so it is the operator's call, not a restyle's.

#### T1.3 — Nine filed records name a project that is not in the collection *(was A18)*
**9 records, unchanged since the census.** The sheet prints *"The project this
record names is not on file, so the site could not be identified"* — which is
the honest rendering and is not the defect. The defect is that a filed
compliance record exists for a site the product cannot identify, and nothing
stops another one being created tomorrow.

*The mechanism matters more than the count: nothing enforces referential
integrity between `logbooks.project_id` and `projects`.*

#### T1.4 — "Corrected immediately" is recorded and never printed *(was A16)*
**4 filed daily jobsite records store it; 0 print it.** A safety observation
that says the condition was fixed on the spot reads, on the sheet, as an
observation with no remedy. The record carries the better fact and the document
withholds it.

*Smaller than it looked in the original write-up — measured at four records,
not at every daily log.*

#### T1.5 — No filed PDF declares its language, and no table declares its headers *(was A22)*
Absent on **both** renderers and on all 317 filed records. A PDF with no `lang`
is one a screen reader guesses the language of, from the reader's locale rather
than the document's. A `<table>` with no `scope` cannot be navigated by column:
a §3301.12.3 attendance roster reads as a flat run of cells.

*Not a regression — it was never there, which is why no comparison ever
reported it. It is the rest of the category A21 belonged to.*

### FIXED

| # | what a filed document said | records | closed by |
|---|---|---|---|
| T1.6 | **32 daily logs said "Equipment: None", then "— Not recorded"** — `toggle_list` tested `if v else` and `{}` is falsy, so the seeded map fell in with the absent one *(A20)* | 32 of 59 | #517 |
| T1.7 | **118 of 317 sheets skipped a section number** — 1, 2, 4 says a section was removed, and a reader cannot tell that from a redaction *(A23)* | 118 of 317 | #521 |
| T1.8 | **254 sheets filed with no document title** — the engine's head had a charset and a stylesheet; WeasyPrint copies `<title>` into PDF metadata *(A21)* | 254 | #517 |
| T1.9 | **A draft did not say it was a draft** — the filing-state line under the letterhead *(A17)* | all drafts | #513 |
| T1.10 | **Every daily log said "Areas Visited: N/A"** — a field nothing had written since the picker work *(A15)* | 59 → **0** | #514 |
| T1.11 | **A signer's name slot printed the role label** *(A10)* | → **0** | measured 0 on 2026-09-13 |
| T1.12 | **`yes_no` printed Yes for a stored "no"** — Injury: **Yes** for every man reporting none | 49 | #512 |
| T1.13 | **Both banners missing from 92 filed orientations** — affirmation and amendment, composed below the line that returns | 92 | #512 |
| T1.14 | **291 pre-shift signature images lost** — the cell returned a sentence and drew nothing | 49 records | pre-shift conversion |
| T1.15 | **The statutory register drew nothing on all 6 superintendent sheets** — `register` took its subject as the rows | 6 | superintendent conversion |
| T1.16 | **Doubled base64 prefix — every worker acknowledgment a broken image** | 72 | #497 |
| T1.17 | **"Site Superintendent Log" section rendering from a collection last written in April** | — | #505 |
| T1.18 | **A failed slump test would have vanished off a pour register** — caught before it shipped: `row_requires` is a value test and `str(False or "")` is empty | 0 (pre-emptive) | #519 |
| T1.19 | **A site with zero men recorded lost its address, safety-plan number and weather** — `requires` is a value test and `str(0 or "")` is empty | 0 (pre-emptive) | #519 |

---

## TIER 2 — Data loss and exposure

### LIVE

#### T2.1 — Dropbox R2 keys collide on basename *(was A1)*
`{company}/{project}/{filename}` built from a **recursive** listing: `A/plan.pdf`
and `B/plan.pdf` are two rows and one object. The second upload silently
replaces the first, and both rows then point at it. **Wrong document, right-
looking.** Top of the Dropbox redesign.

#### T2.2 — A delete path that promises to keep the bytes deletes them *(was A3)*
The path documents a soft delete and removes the object.

#### T2.3 — Photographs vanish from a row that is no longer "camera ready" *(was A8)*
The condition that hides the camera also hides photographs already taken.

#### T2.4 — Fifty project-id routes reference no tenancy guard *(was section C)*
Ninety-four backend routes take `{project_id}`; 44 carry
`Depends(require_project_access)`; **50 reference neither that nor
`project_access_ok`/`_assert_project_access`.**

**This is a population, not fifty holes.** Two spot-checks disagreed in both
directions — `get_checkin_info` is a documented public endpoint,
`get_logbook_audit` takes the project id straight into a query with no company
term. The number says how much reading is left.

**Named as having no guard at the census (21 of them):** `get_logbook_audit`,
`get_logbook_missing`, `get_logbook_deficiencies`, `get_logbook_attestations`,
`export_logbook`, and the rest listed in `open-defects-2026-09-11.md` §C.

*The one question per route: can a caller from another company reach another
company's data through it. That needs reading, not scanning.*

#### T2.5 — `upload-osha` is a public endpoint calling a paid vision API with no limit
Unmetered since PR #240. Meter on device fingerprint or global spend, never
per-IP.

### FIXED

| # | what | closed by |
|---|---|---|
| T2.6 | Three report routes gated tenancy on `role == "admin"`, which an owner never reaches — and registration sets owner on every self-serve signup | #499 |
| T2.7 | File stream had no project-access dependency; the document index and the Dropbox link route ignored the folder allow-list; the link route sent a caller-supplied path to the company's Dropbox token | #501 |
| T2.8 | A 720-hour session JWT in document URLs, logged verbatim | #502 |

---

## TIER 3 — A capability the product advertises and does not deliver

### LIVE

| # | what | note |
|---|---|---|
| T3.1 | **Every notification in the app is a dead card** *(A11)* | nothing routes anywhere |
| T3.2 | **An SST review flag nothing can clear, and a status never shown** *(A5)* | |
| T3.3 | **Inspector mode confines the gate tablet to half its own scope** *(A6)* | |
| T3.4 | **The gate tablet boots dark and cannot leave** *(A7)* | |
| T3.5 | **An empty site-device allow-list is closed, not open** | 3 of 5 provisioned devices sync nothing; the default is right, the silence is not |
| T3.6 | **The OSHA sheet's name** | the register is titled for OSHA and carries SST cards, which are a NYC DOB credential. A product question, parked deliberately — it is the operator's word, not a defect |

### FIXED

| # | what | closed by |
|---|---|---|
| T3.7 | Offline daily log promised a sync the drain refuses for that type | #504 |

---

## TIER 4 — Cost, latency, hygiene, latent

| # | what | state |
|---|---|---|
| T4.1 | **Eight multi-worker reads fetch an inline base64 photograph each** *(A9)* | LIVE — cost and latency |
| T4.2 | **Eight helpers have no caller and still read as renderers** *(A19, was six)* | LIVE — `_headcount_cell`, `_display_inspections`, `_display_sub_company`, `_appended_photo_notice`, `_display_weather`, `_superintendent_log_html`, `_osha_type_cell`, `_preshift_signature_cell`. Every rule they hold now lives in `lib/legal_render`. Removing them takes ~45 tests with it — a deliberate change, not a rider |
| T4.3 | **Two writers do not stamp `updated_at`** *(A12)* | LIVE — latent |
| T4.4 | **Cache hydration waits on auth** *(A13)* | LIVE — availability, low |
| T4.5 | **No client version floor** *(A14)* | by design, recorded |
| T4.6 | **`get_single_logbook_pdf` still declares a `token` query parameter** | recorded, **not verified** — nobody has checked what passes it |
| T4.7 | **The geofence is dead code** | the check-in geofence never runs; never cite it as a presence control |
| T4.8 | **Three cosmetic items on the investor report** | ragged card bottoms; the "Not due today" placeholder about a third the width of a real thumbnail; the cover's date and address columns reading as one line. Appearance, no data |
| T4.9 | **Report #29 went out without page 4** | the send fired 44 minutes before the project-record page deployed. Recorded, not actionable |

---

## The instrument itself

Not defects in the product — defects in what was checking the product, and the
reason several of the entries above went unnoticed for so long. Written up in
`check-harness.md`.

| what it could not see | found by |
|---|---|
| images and ink — `src=` tokenised, then the tag stripped | a signature count |
| **case** — `words()` lowercases both sides, so "Foreman" → "foreman" on 393 rows reported nothing | a unit test naming the literal |
| **anything not on the page** — `<title>` is in the document and not on it | luck: one project's name differs from its address |
| an **invented project** for records whose project is not on file | reading the orphan count |
| **order** — a set difference reports *nothing* when every man's Injury answer is swapped with his PPE answer | a deliberate demonstration |

**Four repairs, and each was found by something other than the instrument.**
The standing rule is now: every comparison states what it cannot see, and every
conversion carries at least one check that does not go through it.

**And one class, §17:** *a truthiness test standing in for a presence test.*
Four measured instances — `bool("no")`, `{}`, `str(0 or "")`, `str(False or "")`
— and **every one failed toward the document looking better than the site**.
That direction is not chance: the falsy value is what a blank looks like, so
collapsing them always erases the negative answer and never the positive one.

---

## What this document is not

It is not a plan, and nothing here is prioritised for anybody's week. The
ordering is an argument about severity, not a schedule.

**It is not a claim of completeness.** It is everything *known* on 2026-09-13.
The fifty routes are the honest edge of that: nobody has read them.

**Nothing in Tier 1 LIVE is being worked from here.** Each of T1.1 and T1.2 is a
one-line change that alters what a filed compliance record says, and that is a
decision, not a repair.
