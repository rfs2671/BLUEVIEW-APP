# Electronic signatures applied before consent was recorded

**For legal review.** Companion to `docs/compliance/esra-bb2024-007-compliance.md`.
Written against `main` at `4f68b46`. Figures from production, 2026-09-01.

---

## 1. The question the client is asking

Between 2026-03-10 and 2026-09-01, users of this application applied **248
electronic signatures** to construction site safety records. During that period
the application never asked anyone to agree to sign electronically, and **no
such agreement is on file for any user**.

From 2026-09-01 the application asks, and records the agreement before it
permits a signature on the construction superintendent log.

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
- It is stored **verbatim on each consent row**, not as a pointer to a version,
  so a stored consent can be reconstructed exactly as the person read it.
- It is **keyed on the person**, not on anything he signs. The row carries
  `user_id`, email, name, role at the time, company and timestamp; it carries
  no log type and no document reference. One row per person covers everything
  that person signs.

---

## 3. The facts

### 3a. Scope

| | |
|---|---|
| Signed documents with no recorded consent | **248** |
| Consents on file | **0** — the collection is empty |
| Declines on file | **0** |
| First signature | **2026-03-10 22:31:19 UTC** |
| Last signature | **2026-09-01 17:19:15 UTC** |
| Distinct log types | **6** |

**The set is closed at 248.** The last signature (17:19:15 UTC) predates the
deployment of the consent gate that same day (merged 18:47:27 UTC). No
signature has yet been applied under the gate, and none has been applied by a
consenting user, because nobody has consented.

### 3b. By log type

| log type | documents |
|---|---|
| subcontractor_orientation | 79 |
| toolbox_talk | 53 |
| daily_jobsite | 44 |
| preshift_signin | 40 |
| osha_log | 31 |
| scaffold_maintenance | 1 |
| **total** | **248** |

The BC 3301.13.13 **construction superintendent log does not appear**: it has
never been filed. It is the one log type now gated.

### 3c. By signer

Grouped on `cp_name`, the printed name **typed by the signer**. See §3e — this
is a self-entered label, not the authenticated account identity.

| cp_name | original | amendment | total |
|---|---|---|---|
| michael | 150 | 50 | 200 |
| `"2"` | 24 | 1 | 25 |
| Roy Fishman | 15 | — | 15 |
| Test CP | 8 | — | 8 |
| **total** | **197** | **51** | **248** |

**51 of the 248 are amendments.** A correction is a new child document signed
in its own right while the original stays signed, so 248 counts *signatures
applied*, not *distinct matters recorded*. The number of matters is 197.

### 3d. By month

| month | documents |
|---|---|
| 2026-03 | 15 |
| 2026-07 | 15 |
| 2026-08 | 209 |
| 2026-09 | 9 |

84% of all signatures fall in the final month.

### 3e. Two data-quality findings, reported rather than averaged into the tables

Neither changes the legal question. Both change what the tables mean.

**(i) `cp_name` is `"2"` on 25 signed documents.**

`cp_name` is **free text typed by the signer** on the signature pad
(`onNameChange`), then **persisted to that user's profile and pre-filled into
every subsequent log**. There is no validation on either side: the client
requires only that the field be non-blank (`signerName?.trim()`), and the
server declares `cp_name: Optional[str] = None` with no validator, no minimum
length and no pattern.

So one person typing `2` once produced that label on 25 records, across
however many log types, without anything objecting.

**This does not mean 25 records have an unknown signer.** The account identity
is recorded separately and is server-set, not typed:

| field | source | trustworthy as identity |
|---|---|---|
| `cp_name` | typed by the signer | **no** — a self-entered label |
| `created_by` | authenticated user id, server-set | **yes** |
| `created_by_name` | account name, server-set | yes |

Query A below resolves the 25 to an authenticated user id. Until it is run, who
signed them is *recorded but not yet read* — which is different from unknown,
and different again from unattributable.

The same caveat applies to every row of table 3c, including "michael": that is
a typed label too, and the authoritative identity is `created_by`.

**(ii) `"Test CP"` on 8 signed documents.**

Test data in the same collection as live compliance records. Whether those 8
sit on a real project cannot be determined from the source; query B answers it.
They are included in the 248 above and **should be excluded from any figure
presented as production activity** if query B shows they are not on a real
project. No row has been removed from this document on an assumption.

---

## 4. What the records do and do not contain

**They are not bare marks.** Each carries, on the document, the drawn signature
and the typed printed name. Where an audit row exists it adds the authenticated
user id, the verified role, the acting capacity, a device fingerprint, an IP
address, a hash of the content signed, and a timestamp.

**The audit ledger is incomplete, for two independent reasons:**

1. **It did not exist until 2026-03-26**, sixteen days after the first
   signature. The 15 documents signed in March 2026 straddle that date.
2. **It drops rows on a failed write, by design and to this day.**
   `recordSignatureEvent` catches every failure, returns null, and neither
   queues nor retries; its own comment states the audit entry will be missing
   and the app will not break. Eleven of the twelve signing screens are
   local-first, so a signature applied with no signal persists on the document
   and loses its ledger row permanently.

**The ledger holds 245 rows, and that number must not be subtracted from 248.**
The ledger spans **all** document types — `logbook`, `daily_log` and
`worker_registration` — so 245 is not a count of logbook signatures. The
shortfall is genuinely unknown; query C measures it, and query D checks that
query C is working before its output is believed.

**Count documents, not ledger rows.** The 248 is authoritative.

**Not in scope: the worker gate affirmation.** Its text authorises "use on
today's Pre-Shift Sign-In Log for this jobsite" — one signature, one day, one
named document. It is not a general agreement to conduct business
electronically and has never been presented as one. Whether § V.5 reaches it is
a separate question this document does not prejudge.

---

## 5. Queries still outstanding

Read-only.

```js
// A. WHO the 25 "2" documents belong to. Resolves a typed label to an
//    authenticated account.
db.logbooks.aggregate([
  { $match: { cp_name: "2", cp_signature: { $exists: true, $ne: null } } },
  { $group: { _id: "$created_by", n: { $sum: 1 },
              account_name: { $addToSet: "$created_by_name" },
              log_types: { $addToSet: "$log_type" },
              projects: { $addToSet: "$project_id" },
              first: { $min: "$created_at" }, last: { $max: "$created_at" } } },
])

// B. Are the 8 "Test CP" documents on a real project?
db.logbooks.aggregate([
  { $match: { cp_name: "Test CP", cp_signature: { $exists: true, $ne: null } } },
  { $group: { _id: "$project_id", n: { $sum: 1 },
              project_name: { $addToSet: "$project_name" },
              company: { $addToSet: "$company_id" } } },
])
// then, for each project_id returned:
db.projects.find({ _id: ObjectId("<id>") }, { name: 1, address: 1, company_id: 1, status: 1 })

// D. RUN THIS BEFORE C. If it returns 0, C's join is broken and C's output is
//    meaningless rather than alarming.
db.logbooks.aggregate([
  { $match: { cp_signature: { $exists: true, $ne: null } } },
  { $addFields: { idStr: { $toString: "$_id" } } },
  { $lookup: { from: "signature_events", localField: "idStr",
               foreignField: "document_id", as: "ev" } },
  { $match: { "ev.0": { $exists: true } } },
  { $count: "documents_with_a_ledger_row" },
])

// C. THE SHORTFALL — signed documents with no ledger row.
//    signature_events.document_id is a STRING (server.py:4264) and
//    logbooks._id is an ObjectId. Joining them directly matches nothing.
db.logbooks.aggregate([
  { $match: { cp_signature: { $exists: true, $ne: null } } },
  { $addFields: { idStr: { $toString: "$_id" } } },
  { $lookup: { from: "signature_events", localField: "idStr",
               foreignField: "document_id", as: "ev" } },
  { $match: { ev: { $size: 0 } } },
  { $group: { _id: "$log_type", unledgered: { $sum: 1 },
              first: { $min: "$created_at" }, last: { $max: "$created_at" } } },
])

// E. THE LEDGER'S OWN DATE RANGE. The field is `timestamp`. There is no
//    top-level `signed_at` on this collection — `signed_at` exists only INSIDE
//    logbooks.cp_signature, as a string.
//
//    A MATCH ON A FIELD THAT DOES NOT EXIST SILENTLY MATCHES EVERYTHING: a
//    missing field reads as null, and null sorts before Date in BSON, so
//    `{signed_at: {$lt: ISODate(...)}}` is true for every row. That is why an
//    earlier run returned 245 rows with null first/last — the filter matched
//    all of them and the min/max of an absent field is null. There is no date
//    filter here at all; the range is what is being asked for.
db.signature_events.aggregate([
  { $group: { _id: { type: "$document_type", event: "$event_type" },
              rows: { $sum: 1 },
              first: { $min: "$timestamp" }, last: { $max: "$timestamp" } } },
  { $sort: { rows: -1 } },
])

// F. LEGACY. Whether daily_logs holds signatures could not be established from
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

- **Queries A–F above are unrun.** §3e's two findings and the ledger's date
  range and shortfall are not yet resolved.
- **Eleven of the twelve signing paths are not yet gated.** Only the
  superintendent log checks for consent today. Signatures applied on the other
  eleven after 2026-09-01 will carry no recorded consent until the gate is
  extended, which is scheduled.
- `docs/compliance/esra-bb2024-007-compliance.md` is **stale**: dated
  2026-08-30 and still states the superintendent log is "NOT YET BUILT". It
  shipped 2026-09-01. It should be brought current before both documents go out
  together.
- The ledger's silent row-dropping (§4.2) is a live defect in the audit trail,
  independent of consent, and is not yet scheduled.
- **`cp_name` accepts any non-blank string** (§3e). Unfixed. It is the field a
  reader would take for the signer's name on a filed compliance record.
