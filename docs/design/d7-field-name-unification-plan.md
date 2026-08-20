# D7 — the field-name unification plan

_2026-08-19. **The reader-side unification is BUILT** (see RULED below). The rest is plan._

---

## 0. The thesis

A duplicated name is not a tidiness problem. It has two costs, and this repo has
paid both:

1. **A split enforcement boundary.** Every rule written afterwards attaches to
   one name and silently exempts everything stored under the other.
2. **A reconciliation layer.** When two names must be compared, something has to
   translate — and the translation becomes load-bearing code with its own bugs,
   its own tests, and its own production defects.

Ordered by damage done, not by occurrence count.

---

## RULED (2026-08-19)

**The reader-side unification is BUILT** — `_worker_company` and
`_roster_pairs`/`_has_roster` in `backend/server.py`, pinned by
`backend/tests/test_d7_reader_unification.py`. See §6 for what it did and did
not touch.

**The mandatory gate is TRADE ONLY, and is its own PR.** Ruled: trade is
sufficient; company follows from the roster once the trade is picked. Recorded
here because it changes the shape of that PR — it is a gate on ONE field, and
the (trade, company) pair that `_roster_pairs` returns is a matching key, not
the thing to gate on. Nothing in the reader pass assumes either way.

---

## 1. The inventory

### Item 1 — `company` / `worker_company` / `sub_name` — **HIGHEST**

**Three names for one fact: which subcontractor this man works for.**

| Name | Where it lives | Written by |
|---|---|---|
| `company` | `project.trade_assignments[]` (`server.py:10060-10062`), `worker_project_trades` (`:10304-10333`) | admin roster; per-project trade assignment |
| `worker_company` | `checkins` rows (`server.py:2443` — `"worker_company": worker.get("company", "")`) | the check-in write |
| `sub_name` | `worker_enrollments` (`card_audit.py:278`, "denormalized from project trade_assignments") | the NFC gate |

Three collections, three spellings, one fact — and they meet. `checkins_today`
performs a **three-pass merge** across all three
(`server.py:18323-18430`), because the pre-shift sheet has to show one row per
man regardless of which door he came through.

**What that merge has cost, in the code's own words.** The comment at
`server.py:18324-18331` explains why `_norm_key` exists:

> The passes read the company from different places — the gate pass from the
> enrollment's `sub_name`, the legacy pass from the check-in's `worker_company`
> (or the worker doc) — so a trailing or doubled space on either side made the
> raw lowercased pair miss and emitted the SAME MAN twice: once from the gate
> WITH his card id, once from legacy WITHOUT one. That is the duplicate row
> found on a production pre-shift sheet.

And immediately after (`:18336-18338`):

> THE ONLY RELIABLE IDENTITY IN THIS MERGE. A worker_id is an id; the
> (name, company) pair below is a STRING STANDING IN for one, and it has now
> produced **four separate defects on this project**.

That is the whole argument for this item, written by the people who paid for it.
A man's identity in the most safety-critical merge in the app is a pair of
strings, one of which is spelled three different ways depending on which
collection it came from. `_norm_key` is not a bug fix; it is a **standing tax**
on the divergence.

**Note the direction of the fix.** Unifying the spelling does NOT fix this on its
own — a single name for a string-keyed identity is still a string-keyed
identity. The name unification is what makes the real fix (key the merge on
`worker_id`) expressible without a translation layer in the middle. Item 1 is a
prerequisite, not the cure.

### Item 2 — roster-emptiness, computed five ways — **HIGH**

"Is this roster empty?" is asked at five points in one document's life, and no
two ask it the same way.

| # | Where | Predicate | A row with a blank name is… |
|---|---|---|---|
| 1 | `preshift_signin.jsx:247` | `d.workers && d.workers.length > 0` → reconcile vs rebuild | **content** |
| 2 | `toolbox_talk.jsx:250` | `storedRoster.length > 0` → same fork, attendees | **content** |
| 3 | `preshift_signin.jsx:449` | `workers.filter(w => w.name.trim())` → `total_count`, and the submit gate | **empty** |
| 4 | `draftSync.js:290-293` | rows where `String(w.name||'').trim()` is non-blank → the injury/PPE drain gate | **empty** |
| 5 | `server.py _row_has` (`:16725`) → `SUBMIT_NO_CONTENT` | any listed field present; **a bool counts, because `False` is an answer** | **content, if any field is set** |

Predicate 5 has a sixth copy. Its own docstring:

> A MIRROR of the `has()` helper inside `render_logbook_html`, which is nested
> there and not importable. Kept semantically identical on purpose … so a field
> added to a rule below behaves exactly as the renderer would treat it.
> `test_submit_no_content_gate.py` checks the two against each other case by
> case.

So the same question is answered by two deliberately-duplicated
implementations, held together by a test that compares them case by case —
because one of them cannot be imported. That test is the correct response to
the situation and is also the clearest possible statement of the problem: the
cost of the duplication is now a permanent test whose only job is to stop two
copies drifting.

**Why this matters more than it looks.** These predicates disagree about
exactly one input — the blank spare row, which every one of these sheets carries
by construction. A sheet holding only blank rows is:

- **content** to #1, so the editor RECONCILES against it instead of rebuilding
  from today's check-ins,
- **empty** to #3 and #4, so `total_count` is 0 and the drain gate passes it,
- **content** to #5 if any field on any row is set.

The #1 disagreement is the live one: reconcile-not-rebuild against an all-blank
stored roster is how a sheet fails to pick up the men who actually checked in.
`toolbox_talk` had exactly this defect and the fix is commented at
`toolbox_talk.jsx:250-257`; `preshift_signin.jsx:247` still uses the raw
`length > 0` form.

> **Logged, not actioned** (Part D is closed to additions): `preshift_signin.jsx:247`
> looks like the same defect `toolbox_talk` fixed. It is guarded in practice by
> `_reconcileWorkers` re-checking against today's check-ins, so it may be inert
> — but it is inert by a second mechanism, not by the predicate being right.
> Worth a look on its own.

### Item 3 — `cp_signature` vs `competent_person_signature` — **HIGH**

One human, one act, two names, two shapes, two rule sets.

| | `logbooks` | `daily_logs` |
|---|---|---|
| Signature | `cp_signature` | `competent_person_signature` |
| Signer name | `cp_name`, a **sibling** | `.signer_name`, **nested inside the signature** |
| Affirmation | `cp_signature.affirmed === true`, enforced | **no `affirmed` concept at all** |
| Client guard | `isAffirmedSignature()` in all 12 editors | **zero** uses in either daily-log screen |
| Server stamp | `_finalize_cp_signature` (`server.py:16652`) | none |
| PDF renderer | refuses/marks unaffirmed (`server.py:3312`) | renders whatever is there (`:20274-20290`) |
| Admin exception report | `db.logbooks.find({"cp_signature.affirmed": {"$ne": True}})` (`:17844`) | **structurally invisible** |

The exception report queries by field name. A `daily_logs` row cannot appear in
it — not because its signature is affirmed, but because the query does not name
its field. Silence reads as clean.

And `daily-log.jsx` holds both at once: `competent_person_signature` to the
server (`:406`), the same value as `cp_signature` into the draft (`:418-419`),
with `cp_name` reconstructed from the nested `signer_name` on load (`:307`).
That hand-written translation on every save and load is where the affirmation
was dropped — there was never an `affirmed` on the other side to carry.

### Item 4 — the SST class vocabulary, four lists — **MEDIUM**

`SST_CLASS_TYPES` (`server.py:2097`) has four members including
`SST_TEMPORARY`. `CertificationType` (`:2048-2050`), `ll196._SST_CERT_TYPES`
(`ll196.py:47`) and the scoring list (`score.py:475`) have three. A temporary
card is a legible, gate-valid class in one place and unrecognised in the other
three. `ll196.py:46` says its list "Mirrors server.py::validate_worker_certifications"
— a comment asserting a synchronisation nothing enforces. See
[D6 §4c](d6-card-class-confidence-model.md).

### Items 5–6 — distinctions, not duplications — **DOCUMENT, DO NOT MERGE**

- `is_locked` (server) vs `finalized` (draft). They **can** disagree, and the
  disagreement is meaningful: "frozen on this device, not yet locked on the
  server" is a real state the UI names.
- `_id` / `id` / `backend_id` / `_local_id`. Four genuinely different things:
  server identity, wire identity, binding record, provisional client identity.
  Reads like `orient._id || orient.id || orient._local_id` are the tell.

Both need **a sentence saying they are deliberate**, not a merge. Collapsing
either would destroy information.

### Item 7 — `selfie_image` vs `selfie_r2_key`/`selfie_r2_url` — **LOW, decided**

Introduced by D5. Old rows keep inline base64; new check-ins write the key. Both
coexist by ruling, no backfill. Listed so it stays a *dated, decided*
duplication rather than being rediscovered later as an accident.

---

## 2. Why the obvious approach fails

1. **The shapes differ, so it is not a rename.** `cp_name` is a sibling;
   `signer_name` is nested. A reshape has no inverse if it is wrong.
2. **Offline clients hold the old name for an unbounded window.** A draft
   written on an old build sits in AsyncStorage for days in the field, and
   `draftSync.pushOne` replays it verbatim. A server that has stopped
   understanding the old name silently discards a signed compliance record.
3. **These are signed legal records.** A migration that rewrites the field a
   signature lives in is rewriting filed evidence.

## 3. The plan

Five phases. **Readers change before writers; writers before data; data before
the alias is dropped.** Each phase ends green on its own and is reversible by
construction.

- **Phase 0 — measure, and freeze the surface.** Count affected rows split by
  `is_locked` (locked rows constrain phase 4). Then add the test that
  **enumerates the aliases and fails when a new one appears.** Without it the
  cleanup races new divergence. Model it on `assertionsCanFail.test.cjs`:
  anchored slices, non-empty asserted before contents.
- **Phase 1 — pick the canonical name, and record why.**
  For item 3: **`cp_signature` / `cp_name`** — it is what the affirmation rule,
  the server stamp, the PDF refusal and the exception report already key on, so
  it moves *data* toward the rules rather than rewriting four enforcement
  points; it is what the draft store and drain already speak, putting the
  unbounded-offline risk on the smaller side; and 12 editors already use it
  against 2 screens that do not. Cost, recorded honestly: it is the less
  legible name to someone reading the database cold.
  For item 1: **`company`**, being the name the roster and the per-project trade
  record already use, and the one an admin sees.
- **Phase 2 — readers accept both.** One accessor per concept, used everywhere.
  **At the end of this phase the affirmation rule reaches `daily_logs` rows for
  the first time** — which is the actual objective. Expect the unaffirmed
  exception report to jump; that is the pre-existing gap becoming visible, and
  whoever runs it must be told in advance or the jump reads as a new bug.
- **Phase 3 — writers emit canonical, and keep writing the alias.** Duration set
  by the oldest plausible offline draft, measured, not guessed.
- **Phase 4 — backfill unlocked rows only.** **Locked rows are never rewritten** —
  the same rule `writeDraft`'s finalize lock and `update_logbook`'s 423 already
  encode. They keep the alias forever, served through the phase-2 accessor.
  That is the correct outcome, not a shortfall.
- **Phase 5 — drop the alias write; keep the alias read.** Permanently, because
  of phase 4. The phase-0 test flips from "these aliases exist" to "no NEW alias
  may be introduced."

## 4. Sequencing

1. **Item 4 (SST vocabulary) first.** Four constant lists, no data migration, no
   offline window. Cheapest possible proof of the phase-0 guard test, and it
   unblocks [D6](d6-card-class-confidence-model.md) step 3.
2. **Item 2 (roster-emptiness) next.** Also no migration — it is one shared
   predicate replacing five, plus deleting the mirror-and-compare test once
   `has()` is importable. Highest ratio of risk removed to work done.
3. **Item 1 (the company triple)** — the largest, and the one with production
   defects behind it. Do not start it until D6 step 1 has been measured; both
   touch the worker/cert read path and two concurrent migrations there make any
   regression un-attributable.
4. **Item 3 (the signature names)** after item 1, same read-path reasoning.
5. **Items 5–6 are documentation.** Any time, and **not** bundled into a
   migration — that is how a migration's diff stops being reviewable.

## 5. What must not happen

- A big-bang `$rename`. Phases 2–3 exist because of the offline window; skipping
  them silently discards signed records.
- Rewriting locked rows. Ever.
- Dropping the alias *read* at phase 5.
- Starting item 1 or 3 without phase 0's guard test.
- Treating items 5–6 as duplication to eliminate.
- Unifying item 1's spelling and calling the identity problem solved. It is a
  prerequisite for keying the merge on `worker_id`, not a substitute for it.
