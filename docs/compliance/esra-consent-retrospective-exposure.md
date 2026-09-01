# Electronic signatures applied before consent was recorded — retrospective exposure

**Prepared for legal review**, as a companion to
`docs/compliance/esra-bb2024-007-compliance.md`. Written against `main` at
`7af62b8` (2026-09-01).

## What this document is, and is not

This is an engineering statement of **what happened and over what period**,
written so that a reviewing attorney can decide what, if anything, follows from
it. It names the records affected, the dates that bound the exposure, and the
queries that will quantify it against production.

**It does not certify compliance and contains no legal conclusion.** Whether an
electronic signature applied without a separately recorded agreement to sign
electronically is valid, invalid, curable, or immaterial is a legal judgment
that has not been made here and is not made anywhere in this codebase.

**No numbers in this document are asserted.** The author has no access to the
production database. Section 5 gives the exact queries; the counts they return
are the facts, and this document deliberately contains none of them rather than
estimating.

**Nothing has been remediated, and nothing should be.** See section 6.

---

## 1. What the requirement is

Buildings Bulletin 2024-007 § V.5 requires that all involved parties "clearly
intend to sign electronically and agree to conduct transactions
electronically". That is a general agreement about the *medium*, made once, and
it is distinct from the act of signing any particular document.

The bulletin does not distinguish the BC 3301.13.13 construction superintendent
log from the other site safety documents it names. Whatever § V.5 requires of
one, it requires of all of them.

## 2. What the software did

**It recorded signatures. It never asked for the agreement.**

The consent machinery — `backend/lib/esra_consent.py`, `GET`/`POST
/api/esra-consent`, the `esra_consents` collection — landed on **2026-08-30**
in #308. It was complete and correct: it stores the wording verbatim against a
dated version, denormalises who agreed, and keeps every historical version so a
stored row can be checked against what it claims to have said.

**Nothing ever called it.** `has_current_esra_consent` had no callers outside
its own unit tests, and no screen in the shipped bundle mentioned consent. The
agreement existed as a facility and was never put in front of a person.

That was closed on **2026-09-01** by #347, which gates the superintendent log's
signature on a recorded current consent. **The eleven other signing paths are
not yet gated** — see section 4.

## 3. What was signed, and where it lives

Two independent stores, and both matter:

| store | what it holds | since |
|---|---|---|
| `logbooks.cp_signature` | the signature itself, on the document | **2026-02-26** (`fb9cdce`) |
| `signature_events` | the audit ledger: signer, capacity, device, content hash, timestamp | **2026-03-26** (`15e2ca8`) |

The one-month gap is material: **signatures applied between 2026-02-26 and
2026-03-26 exist on the documents but have no ledger entry at all.** A query
that counts only `signature_events` will understate the exposure, and any
characterisation drawn from the ledger alone will be wrong about that first
month.

There is a third, older collection, `daily_logs`, which predates `logbooks`.
**Whether it carries signatures could not be established from the source** — no
signature field is written to it anywhere in `server.py` that the author could
find. It is listed in query 6 so the question is answered from the data rather
than left to an assumption in either direction.

### Log types with a CP or SSC signing path

All thirteen registry types except those never signed by a CP. As of `7af62b8`
the app sends three signature event types:

- `cp_sign` — eleven call sites across ten logbook editors
- `ssc_sign` — one, the SSC/SSM daily safety log
- `superintendent_sign` — the BC 3301.13.13 log (**now gated**)

## 4. The exposure, stated plainly

**Every electronic signature applied in this product before 2026-09-01 was
applied without a recorded agreement to sign electronically.** That is the
whole of the claim, and it is not qualified by log type, project, or company.

**And it continues, narrowly, after 2026-09-01.** #347 gates one document. Until
the CP and SSC paths are gated, every `cp_sign` and `ssc_sign` signature applied
carries the same absence. This is scheduled and not yet built.

### What is NOT part of this exposure

**The worker gate affirmation is a different thing and should not be swept in.**
Its text authorises "use on today's Pre-Shift Sign-In Log for this jobsite" —
one signature, one day, one named document. It is not a general agreement to
conduct business electronically and was never presented as one. Whether § V.5
reaches it is a legal question; this document does not assume it does, and the
product has not treated it as consent.

### What the records DO carry

The absence is of the *general* agreement. The signatures themselves are not
bare marks. Each `signature_events` row carries the signer's authenticated user
id, the role the server verified, the acting capacity, a device fingerprint, an
IP address, a content hash of what was signed, and a timestamp. From 2026-08-31
the CP-facing editors also record a per-document attestation with its wording
stored verbatim.

Whether any of that bears on what § V.5 requires is for the attorney. It is set
out here because a characterisation of "signed with nothing recorded" would be
inaccurate, and so would "signed with consent recorded".

## 5. How to quantify it

Run against production. **These have not been run by the author.**

```js
// 1. THE LEDGER. Signatures with an audit row, by type, before the gate.
db.signature_events.aggregate([
  { $match: { timestamp: { $lt: ISODate("2026-09-01T00:00:00Z") } } },
  { $group: { _id: "$event_type", n: { $sum: 1 },
              first: { $min: "$timestamp" }, last: { $max: "$timestamp" },
              signers: { $addToSet: "$signer.user_id" } } },
])

// 2. THE DOCUMENTS. Signed logbooks, by log type — INCLUDING the month before
//    the ledger existed, which query 1 cannot see.
db.logbooks.aggregate([
  { $match: { cp_signature: { $exists: true, $ne: null },
              created_at: { $lt: ISODate("2026-09-01T00:00:00Z") } } },
  { $group: { _id: "$log_type", n: { $sum: 1 },
              first: { $min: "$created_at" }, last: { $max: "$created_at" } } },
])

// 3. THE GAP. Signed documents with NO ledger row — the Feb–Mar window.
//
//    THE $toString IS LOAD-BEARING, NOT TIDINESS. `signature_events.document_id`
//    is declared `str` (server.py:4264) while `logbooks._id` is an ObjectId, so
//    a lookup joining them directly matches NOTHING and reports every signed
//    logbook as unledgered. That would overstate this exposure by the entire
//    corpus. Verify the join returns a non-empty `ev` for at least one recent
//    logbook before trusting the zero-match set.
db.logbooks.aggregate([
  { $match: { cp_signature: { $exists: true, $ne: null } } },
  { $addFields: { idStr: { $toString: "$_id" } } },
  { $lookup: { from: "signature_events", localField: "idStr",
               foreignField: "document_id", as: "ev" } },
  { $match: { ev: { $size: 0 } } },
  { $group: { _id: "$log_type", n: { $sum: 1 },
              first: { $min: "$created_at" } } },
])

// 3b. THE CONTROL ON QUERY 3. If this returns 0, query 3's join is broken and
//     its output is meaningless rather than alarming.
db.logbooks.aggregate([
  { $match: { cp_signature: { $exists: true, $ne: null } } },
  { $addFields: { idStr: { $toString: "$_id" } } },
  { $lookup: { from: "signature_events", localField: "idStr",
               foreignField: "document_id", as: "ev" } },
  { $match: { "ev.0": { $exists: true } } },
  { $count: "logbooks_with_a_ledger_row" },
])

// 4. WHO. Distinct signers, for the population the answer concerns.
db.signature_events.distinct("signer.user_id",
  { timestamp: { $lt: ISODate("2026-09-01T00:00:00Z") } })

// 5. CONSENTS ACTUALLY ON FILE. Expected to be empty or near-empty before
//    2026-09-01: the endpoint existed from 2026-08-30 and nothing called it.
db.esra_consents.find({}, { user_id: 1, consent_version: 1, agreed_at: 1 })

// 6. LEGACY SURFACE. Does daily_logs hold signatures at all? The source does
//    not say it does. Answer it from the data rather than assuming either way.
db.daily_logs.findOne()   // inspect the shape first
db.daily_logs.countDocuments({ cp_signature: { $exists: true, $ne: null } })
db.daily_logs.countDocuments({ worker_signature: { $exists: true, $ne: null } })
```

Query 3 is the one most likely to be forgotten and is the one that establishes
the true start date.

## 6. What must NOT be done

**Do not backfill consent.** A consent row written now, dated now, describing an
agreement nobody made, attached to a signature applied in March, would be a
fabricated record in a compliance system. It would also be undetectable later:
the schema cannot distinguish a backfilled row from a real one.

A consent recorded after the fact is not consent. The exposure is a fact about
the past and the past is not editable — which is the same principle the product
enforces on every filed logbook, where a correction is an amendment and never an
edit.

**Do not date a consent to anything but the moment it was given.** If a person
is asked today and agrees today, that is a consent from today, and it says
nothing about a signature from March.

**Do not treat the gate as retrospective.** #347 changes what happens next. It
makes no statement about what happened before, and no report should imply that
it does.

## 7. Related and outstanding

- `docs/compliance/esra-bb2024-007-compliance.md` is **stale**. It is dated
  2026-08-30 against `448410f` and states "Status of the log itself: NOT YET
  BUILT". The log shipped in #339 and the consent gate in #347. It should be
  updated before it goes to the attorney alongside this document.
- The CP and SSC signing paths are not gated. Scheduled; shape to be reported
  before it is built.
- The superintendent log's editor is online-only, which is what makes the
  gate's fail-closed behaviour safe. If the log becomes local-first, the gate
  needs a cached consent state and that decision must be re-taken.
