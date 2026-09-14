# Test list — the thirteen-type render migration

**What changed:** every logbook type's PDF is now built by one declarative
engine. The thirteen hand-written renderers are gone, and with them the
email-shell document they produced.

**What did NOT change:** no screen. No editor, no list, no viewer, no kiosk.
The migration is entirely in what the PDF looks like when you download it. Steps
7–9 exist to confirm that.

**Deployed:** `4ab10eab`. Check `api.levelog.com/api/version` reports it before
starting; if it reports something else, you are not testing this.

---

## 1. A filed sheet of every type opens and is the record

**Do:** for each of the thirteen types, open a project that has one, download
the PDF from the logbook.

**See on every one:**
- The dark **LEVELOG** bar is gone. The head is now the contractor's name on the
  left with `PROJECT RECORD` under it, the type and its code on the right.
- **Section numbers run 1, 2, 3 … with no gaps.** This is the one to look at
  hardest — 118 of 317 filed records used to skip a number, and a skipped
  number reads as a section somebody removed.
- The footer says `Page 1 of N` and repeats the job and date at the top of any
  second page.
- **No "Generated on …" line.** That was removed by ruling; its absence is
  correct.

**The seven types with filed records** are: subcontractor orientation (135),
toolbox talk (63), daily jobsite (59), pre-shift sign-in (49), OSHA log (39),
scaffold maintenance (9), superintendent log (6). The other six have no records
in production — the attached mock sheets are what those look like.

---

## 2. The tab title and the saved filename

**Do:** open any of the thirteen PDFs in a browser tab rather than a viewer.

**See:** the tab reads **`<Type> — <Project> — <Date>`**, e.g.
*Daily Jobsite Log — 9 Menahan Street, Brooklyn, NY, USA — 2026-09-11*.

**Why:** 254 filed records went out with that empty. It is the PDF's Title
metadata, which is what a document manager sorts on.

---

## 3. A draft says so, under the letterhead

**Do:** open a logbook that has been started and **not** submitted, and download
its PDF. `hot_work.pdf` in the attached mocks is one.

**See:** immediately under the title block, above everything else —

> **DRAFT** — This record has not been filed.

**And:** it is a line under the letterhead, not a watermark, and it comes
**above** any amendment banner. A reader has to know a record is a draft before
he reads that somebody amended it.

---

## 4. An amended record says who and why

**Do:** open a record that has been amended. `daily_jobsite.pdf` in the mocks is
one.

**See, above section 1:**

> **AMENDED RECORD** — This record was amended by Rosa Delgado on 2026-09-12.
> Reason given: …

**And:** there is **no** "Added after filing" marker on any photograph. That was
dropped by ruling; a timestamp is all a photograph carries now.

---

## 5. A signature says what it is

**Do:** find one filed sheet of each of these three kinds.

| the mark | what you must see under it |
|---|---|
| affirmed | **✓ AFFIRMED for this document**, with a claimed time and a server-received time |
| signed, no affirmation record | **⚠ UNAFFIRMED — no affirmation record for this document** |
| asked for and not given | **UNSIGNED** |

`subcontractor_orientation.pdf` in the mocks carries an unaffirmed worker mark
beside an affirmed CP mark, on the same page — that pairing is the thing to
look at.

**Why it matters:** these two banners were missing from 92 filed orientations
for three days and no comparison caught it.

---

## 6. An unanswered question is not a "No"

This is the class that produced the most defects in this work. Four checks, each
on a different sheet.

**6a — Pre-shift sign-in.** Find a filed roster where a man reported an injury.
**See:** his Injury column reads **Yes**. Every man who reported none reads
**No** — not Yes. *(49 filed records read backwards until this migration.)*

**6b — Any checklist** (hot work precautions, crane pre-operation, scaffold,
orientation topics). **See three distinct states:**
- **☒** — answered yes
- **☐** — answered no
- **— Not recorded** — never asked

A blank box and "not recorded" must not look the same.

**6c — Daily jobsite, Equipment on Site.** Find one where the CP ticked no
equipment. **See:** **None** — not "— Not recorded". *(32 filed records said the
wrong one of those two for three days.)*

**6d — Concrete operations, Slump Tests.** The Result column reads **Pass** or
**Fail** — never Yes or No. See `concrete_operations.pdf`, which has one of
each.

---

## 7. The investor report

**Do:** generate the daily report for a project and date that has records.

**See:**
- **Three pages** (two when the day has no photographs — the evidence page
  collapses rather than printing empty).
- **No draft appears anywhere on it.** A record that has not been filed is not
  on the report; the project-record card shows its **Not filed** state instead.
- The report **indexes** the filed documents — it does not embed them. You
  should not see a full logbook sheet inside the report.

---

## 8. The screens (confirming nothing moved)

Nothing on a screen was changed by this work. These three steps are here to
prove that.

**8a** — Open the CP logbook list and one logbook of each type. Everything
should look exactly as it did yesterday: same fields, same order, same labels.

**8b** — Open the gate/kiosk check-in flow and complete one check-in. Unchanged.

**8c** — Open the in-app logbook viewer for a filed record. Unchanged. *(Note:
the in-app viewer is a different renderer from the PDF and always has been. If
the two disagree about a value, that is worth reporting.)*

---

## 9. A record whose type nothing renders

**Do:** nothing — there is no way to produce one through the product today, and
zero stored records are in this state.

**Know:** if a logbook type is ever retired while records exist under it, its
PDF is now a one-page document headed **PROJECT RECORD — NOT RENDERABLE** that
names the record and says, in bold, *"This page is not the record."* It is not a
server error and it is not a stub pretending to be the filing.

**Report it if you ever see one.** It logs an error server-side, so we should
know first.

---

## What to report back

For anything that looks wrong, the useful three:

1. **The type and the date** of the record.
2. **What the sheet says** and what you expected it to say.
3. **Whether the record itself is right** — i.e. is the document lying, or is
   the data wrong? Those are different defects and they go to different places.

---

## Two things going to you as decisions, not bugs

**The superintendent log's licence sentence.** The BC 3301.13.13 sheet says the
superintendent was matched "by licence number". The DOB card carries a
**registration** number, and `registration_number` exists nowhere in the
product. Nine filed records say it. Changing the words on a filed compliance
record is your call — the fix is one sentence.

**Nine filed orientations print "UNASSIGNED" as the worker's company.** There is
already a formatter that renders that as *"Pending assignment"*, and the daily
log uses it. Switching the orientation to it is one word in one file, and it
changes what nine filed documents say.

Both are in the consolidated defect list as **T1.1** and **T1.2**.
