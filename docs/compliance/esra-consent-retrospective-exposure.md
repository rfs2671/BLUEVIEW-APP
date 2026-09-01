# Electronic signatures applied before consent was recorded

**For legal review.** Companion to `docs/compliance/esra-bb2024-007-compliance.md`.
Written against `main` at `7af62b8`, 2026-09-01.

---

## 1. The question the client is asking

Between 2026-02-26 and 2026-09-01, users of this application applied electronic
signatures to construction site safety records. During that period the
application never asked them to agree to sign electronically, and no such
agreement was recorded for anyone.

From 2026-09-01 the application asks, and records the agreement before it
permits a signature.

**The client's position, for assessment — not argued here:**

> The person who signed those records is the same person who is now being asked
> to consent. What he agrees to is a statement about **his own electronic
> signature generally** — it names no document, no log type and no date. The
> client asks whether an agreement in those terms, given now, has any bearing
> on signatures that person applied earlier.

**The client is not asking to have consent backdated, and has instructed that
it must not be.** See §6.

This document supplies the facts that question turns on. It reaches no legal
conclusion and none should be inferred from it.

---

## 2. What the person agrees to

The full wording, verbatim, as version `2026-08-30.1` — the only version that
has ever existed:

> I agree to do business electronically with LeveLog and with the company that
> gave me this account.
>
> I agree that the signature I draw or apply in this application is my
> signature, and I intend it to have the same effect as a signature I write by
> hand on paper.
>
> I understand that the records I sign here are kept as the record of the work
> they describe, that I cannot edit a record after I have signed it, and that I
> can be given a copy of anything I have signed.
>
> I can withdraw this agreement at any time by telling my company
> administrator. If I withdraw it, I will be asked to sign on paper instead.

Three properties of this text are facts about the record, not interpretation:

- It **names no document, log type, capacity or date.** Every subject is
  generic: "the signature I draw or apply in this application", "the records I
  sign here", "anything I have signed".
- It is stored **verbatim on each consent row**, not as a pointer to a version.
  A stored consent can be reconstructed exactly as the person read it, and
  checked against the registry of every version ever shown.
- It is **keyed on the person**, not on anything he signs. The stored row
  carries `user_id`, email, name, role at the time, company and timestamp. It
  carries no log type and no document reference. One row per person covers
  everything that person signs.

---

## 3. The facts, with numbers

**The counts below are produced by the queries in §5, run against production.
They are not filled in here: the author has no database access and has not
estimated them.**

### 3a. Documents signed with no recorded consent, by log type

| log type | documents signed | first | last | distinct signers |
|---|---|---|---|---|
| _(query 2)_ | | | | |

### 3b. Who signed

| user id | name | company | documents | log types | first | last |
|---|---|---|---|---|---|---|
| _(query 4)_ | | | | | | |

**Two precision notes on this table, so it is not read as more than it says:**

- **`created_by` is who created the document; `cp_name` is the printed name of
  who signed it.** In practice these are the same person — the CP opens the log
  and signs it — but the schema does not enforce that, so query 4 returns both
  and any row where they diverge should be looked at rather than assumed.
- **An amended log counts twice.** A correction is a new child document
  (`is_amendment: true`) that is signed in its own right; the original stays
  signed and intact. So "documents signed" is a count of *signatures applied*,
  not of *distinct matters recorded*. Query 4 splits by `is_amendment` so both
  numbers are visible.

### 3c. Consents on file before 2026-09-01

Expected: **none.** The endpoint existed from 2026-08-30 and nothing called it.
Query 5 confirms or refutes.

| user id | version | agreed at |
|---|---|---|
| _(query 5)_ | | |

### 3d. The date range

- **Earliest possible signature: 2026-02-26** — the first commit storing
  `cp_signature` on a logbook (`fb9cdce`). The actual earliest is query 2's
  `first`.
- **Consent first askable: 2026-09-01** — deployed at `7af62b8`.
- **Superintendent log:** gated from 2026-09-01.
- **Ten CP log types and the SSC log:** not yet gated. Signatures applied on
  those paths after 2026-09-01 also carry no recorded consent, until the gate
  is extended.

---

## 4. What the records do and do not contain

**They are not bare marks.** Each signature carries, on the document itself, the
drawn signature and the signer's printed name. Where an audit row exists it
additionally carries the authenticated user id, the role the server verified,
the acting capacity, a device fingerprint, an IP address, a hash of the content
signed, and a timestamp.

**The audit ledger is incomplete, for two independent reasons, and the size of
the shortfall is unknown:**

1. **It did not exist until 2026-03-26.** Signatures applied between 2026-02-26
   and 2026-03-26 are on the documents with no ledger row at all.
2. **It drops rows on a failed write, by design and to this day.**
   `recordSignatureEvent` catches every failure, returns null, and neither
   queues nor retries; its own comment states the audit entry will be missing
   and the app will not break. Eleven of the twelve signing screens are
   local-first, so a signature applied with no signal persists on the document
   and loses its ledger row permanently.

**Therefore: count documents, not ledger rows.** Query 2 is the authoritative
count and query 1 is not. Query 3 measures the gap between them.

**Not in scope: the worker gate affirmation.** Its text authorises "use on
today's Pre-Shift Sign-In Log for this jobsite" — one signature, one day, one
named document. It is not a general agreement to conduct business
electronically and has never been presented as one. Whether § V.5 reaches it is
a separate question this document does not prejudge.

---

## 5. The queries

Read-only. **Not run by the author.**

```js
// 2. AUTHORITATIVE — documents signed, by log type. Fills table 3a.
db.logbooks.aggregate([
  { $match: { cp_signature: { $exists: true, $ne: null },
              created_at: { $lt: ISODate("2026-09-01T00:00:00Z") } } },
  { $group: { _id: "$log_type", documents: { $sum: 1 },
              first: { $min: "$created_at" }, last: { $max: "$created_at" },
              signers: { $addToSet: "$created_by" } } },
  { $project: { documents: 1, first: 1, last: 1,
                distinct_signers: { $size: "$signers" } } },
  { $sort: { documents: -1 } },
])

// 4. WHO. Fills table 3b. Splits amendments out — a corrected log is a second
//    signed document, so the totals are signatures applied, not matters
//    recorded. Returns cp_name alongside created_by: normally the same person,
//    not guaranteed by the schema.
db.logbooks.aggregate([
  { $match: { cp_signature: { $exists: true, $ne: null },
              created_at: { $lt: ISODate("2026-09-01T00:00:00Z") } } },
  { $group: { _id: { user: "$created_by", amendment: { $eq: ["$is_amendment", true] } },
              documents: { $sum: 1 },
              signer_names: { $addToSet: "$cp_name" },
              creator_names: { $addToSet: "$created_by_name" },
              companies: { $addToSet: "$company_id" },
              log_types: { $addToSet: "$log_type" },
              first: { $min: "$created_at" }, last: { $max: "$created_at" } } },
  { $sort: { documents: -1 } },
])

// 5. CONSENTS ON FILE. Fills table 3c. Expected empty before 2026-09-01.
db.esra_consents.find({}, { user_id: 1, consent_version: 1, agreed_at: 1 })
db.esra_consent_declines.find({}, { user_id: 1, consent_version: 1, declined_at: 1 })

// 1. THE LEDGER, for comparison only. NOT the count for table 3a — see §4.
db.signature_events.aggregate([
  { $match: { timestamp: { $lt: ISODate("2026-09-01T00:00:00Z") } } },
  { $group: { _id: "$event_type", rows: { $sum: 1 },
              first: { $min: "$timestamp" }, last: { $max: "$timestamp" } } },
])

// 3. THE SHORTFALL — signed documents with no ledger row.
//    THE $toString IS LOAD-BEARING: signature_events.document_id is a string
//    (server.py:4264) and logbooks._id is an ObjectId. Joining them directly
//    matches nothing and reports every signed document as unledgered.
db.logbooks.aggregate([
  { $match: { cp_signature: { $exists: true, $ne: null } } },
  { $addFields: { idStr: { $toString: "$_id" } } },
  { $lookup: { from: "signature_events", localField: "idStr",
               foreignField: "document_id", as: "ev" } },
  { $match: { ev: { $size: 0 } } },
  { $group: { _id: "$log_type", unledgered: { $sum: 1 },
              first: { $min: "$created_at" } } },
])

// 3b. CONTROL ON QUERY 3. If this returns 0, query 3's join is broken and its
//     output is meaningless rather than alarming. Run it first.
db.logbooks.aggregate([
  { $match: { cp_signature: { $exists: true, $ne: null } } },
  { $addFields: { idStr: { $toString: "$_id" } } },
  { $lookup: { from: "signature_events", localField: "idStr",
               foreignField: "document_id", as: "ev" } },
  { $match: { "ev.0": { $exists: true } } },
  { $count: "documents_with_a_ledger_row" },
])

// 6. LEGACY. Whether daily_logs holds signatures could not be established from
//    the source; no signature field is written to it anywhere in server.py.
db.daily_logs.findOne()
db.daily_logs.countDocuments({ cp_signature: { $exists: true, $ne: null } })
```

---

## 6. Constraint the client has imposed

**No consent may be backfilled.** A consent row written now, dated now,
describing an agreement nobody made, attached to a signature applied in March,
would be a fabricated record in a compliance system — and undetectable
afterwards, because the schema cannot distinguish a backfilled row from a real
one.

If a person is asked today and agrees today, that is a consent dated today. It
says nothing about a signature from March, and this document does not suggest
otherwise. Whether it nonetheless bears on that signature is the question in
§1.

---

## 7. Open, and relevant to the assessment

- `docs/compliance/esra-bb2024-007-compliance.md` is **stale**: dated
  2026-08-30 and still states the superintendent log is "NOT YET BUILT". It
  shipped 2026-09-01. It should be brought current before both documents go
  out together.
- The ledger's silent row-dropping (§4.2) is a live defect in the audit trail,
  independent of consent, and is not yet scheduled.
