# Electronic signatures applied before consent was recorded

**For legal review.** Companion to `docs/compliance/esra-bb2024-007-compliance.md`.
Written against `main` at `b1f1ec5`. Figures from production, 2026-09-01.

---

## 1. The question the client is asking

Between 2026-03-10 and 2026-09-01, users of this application applied **248
electronic signatures** to construction site safety records — **240 of them on
customer projects**. During that period the application never asked anyone to
agree to sign electronically, and **no such agreement is on file for any user**.

From 2026-09-01 the application asks, and records the agreement before it
permits a signature.

**The client's position, for assessment — not argued here:**

> The person who signed those records is the same person who is now being asked
> to consent. What he agrees to is a statement about **his own electronic
> signature generally** — it names no document, no log type and no date. The
> client asks whether an agreement in those terms, given now, has any bearing
> on signatures that person applied earlier.

**The client is not asking to have consent backdated, and has instructed that
it must not be.** See §7.

There is a second question the facts raise on their own, and the client asserts
no position on it: **for some of these documents the signer cannot be identified
from the record at all.** See §4.

This document supplies facts. It reaches no legal conclusion and none should be
inferred from it.

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

- It **names no document, log type, capacity or date.**
- It is stored **verbatim on each consent row**, not as a version pointer, so a
  stored consent can be reconstructed as the person read it.
- It is **keyed on the person**, not on anything he signs. One row per person
  covers everything that person signs.

---

## 3. Scope

| | |
|---|---|
| Signed documents with no recorded consent | **248** |
| — of which on a **test** project (§6) | **8** |
| — **on customer projects** | **240** |
| Consents on file | **0** — the collection is empty |
| Declines on file | **0** |
| First signature | **2026-03-10 22:31:19 UTC** |
| Last signature | **2026-09-01 17:19:15 UTC** |
| Distinct log types | **6** |

**The set is closed at 248.** The last signature (17:19:15 UTC) predates the
deployment of the consent gate that same day (18:47:27 UTC). No signature has
been applied under the gate, and none by a consenting user, because nobody has
consented.

### 3a. By log type

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
never been filed. It is the log the consent gate was built for.

### 3b. By month

| month | documents |
|---|---|
| 2026-03 | 15 |
| 2026-07 | 15 |
| 2026-08 | 209 |
| 2026-09 | 9 |

### 3c. By signer

Grouped on `cp_name`, the printed name **typed by the signer**.

| cp_name | original | amendment | total |
|---|---|---|---|
| michael | 150 | 50 | 200 |
| `"2"` | 24 | 1 | 25 |
| Roy Fishman | 15 | — | 15 |
| Test CP | 8 | — | 8 |
| **total** | **197** | **51** | **248** |

**51 of the 248 are amendments.** A correction is a new child document signed in
its own right while the original stays signed. So 248 counts *signatures
applied*; **197** is the number of distinct matters recorded.

---

## 4. Can the signer be identified?

This section replaces an earlier draft that was **wrong**. That draft said
`created_by` is server-set and authenticated and therefore resolves any typed
name to an account. That holds where the field is present. **It is absent on
some of these documents**, which the earlier draft did not check.

### 4a. Three fields, and what each is worth

| field | source | identifies the signer? |
|---|---|---|
| `cp_name` | typed by the signer, free text | **no** — a self-entered label |
| `created_by` | server-set from the authenticated session | yes, **when present** |
| `signature_events.signer.user_id` | server-set on the audit row | yes, **when a row exists** |

`cp_name` has no validation on either side: the client requires only a non-blank
string, and the server declares `cp_name: Optional[str] = None` with no
validator, minimum length or pattern. It is also **persisted to the signer's
profile and pre-filled into every later log**, so one person typing `2` once
produced that label on 25 records.

### 4b. `created_by` is absent on 50 signed documents, and still is

An earlier count of 13 was **only those that also carried `cp_name: "2"`**. The
true figure across all signed documents is **50**, and every one is a
`subcontractor_orientation` — 50 of the 79 orientations in the corpus. The other
29 orientations do carry it.

| month | documents |
|---|---|
| 2026-07 | 6 |
| 2026-08 | 42 |
| 2026-09 | 2 |

**It is ongoing.** The two September documents were created after the consent
gate shipped. Nothing about this has been fixed.

**Why the field is empty, and why it is not an oversight.** Orientations have
two creation paths, and only one of them has anybody to record:

1. **At the gate** — `POST /api/checkin/register-and-checkin`
   (`backend/server.py:12838`). This is a **public, unauthenticated endpoint**:
   the worker taps an NFC tag and registers himself. Its handler signature takes
   no `current_user` and there is no principal in the request at all. The
   orientation document it inserts (`server.py:13153`) therefore has no
   authenticated identity available to write. This is the path that produced all
   50.
2. **By a CP in the app** — `POST /api/logbooks`, authenticated, which sets
   `created_by` from the session. This produced the other 29.

**The identity does exist at the moment of signing, and is discarded.** A CP
signs a gate-created orientation through `PUT /api/logbooks/{id}` — an
authenticated request that knows exactly who he is. That handler writes
`cp_signature` and the typed `cp_name` and **nothing else about the signer**.
There is no `signed_by` field on the collection.

So the document records *who typed a name* and not *who was authenticated when
the signature was applied*, on the log type with the most records, and the
information needed to record it was in hand each time.

*(A second, unrelated inconsistency found while tracing this: `create_logbook`
writes `str(current_user.get("id"))` while `amend_logbook` writes
`current_user.get("id")` raw — the first would store the string `"None"` where
the second stores a null. Neither is the cause here and neither is a live
defect, but they are not the same field on the same collection.)*

### 4c. Where the ledger can still answer

A missing `created_by` is only fatal to attribution if **no audit row exists
either**. Where a `signature_events` row exists it carries `signer.user_id`,
server-set from the authenticated session, and the signer is recoverable.

**The intersection is the number that matters** — documents with neither — and
it is **not yet established**. It cannot be derived from the figures above: the
50 without `created_by` and the 57 without a ledger row are different sets that
overlap by an unknown amount. Query **K** measures it.

---

## 5. The audit ledger — smaller and later than expected

| document_type | rows | first | last |
|---|---|---|---|
| `logbook` | 233 | 2026-07-29 | 2026-09-01 |
| `preshift_signature_affirmation` | 12 | 2026-08-31 | 2026-09-01 |

233 rows cover **191** of the 248 signed documents. A document may carry more
than one event, so 233 rows over 191 documents is consistent and not a
discrepancy.

**57 signed documents have no ledger row.**

### 5a. The ledger began 2026-07-29, not when it was built

The recorder shipped on **2026-03-26** — the frontend call sites and the backend
endpoint landed the same day. **The earliest row is 2026-07-29**, four months
later, and signatures were applied throughout: 15 documents in March, 15 in
July.

**Nothing reported the gap.** `recordSignatureEvent` catches every failure, logs
to the console and returns null; its own comment states the audit entry will be
missing and the app will not break. A recorder that is live and writing nothing
is indistinguishable, at every observation point available to an operator, from
one that is working.

Why it wrote nothing for those four months is **not established** and cannot be
determined from the source.

### 5b. Two different absences inside the 57, and only one is a defect

| | documents |
|---|---|
| Signed **before** 2026-07-29 — structural, no ledger existed | **16** |
| Signed **after** 2026-07-29 — the ledger was live and no row exists | **41** |

The first 16 are not a loss: nothing was attempted, because there was nothing to
attempt it against.

**The 41 are.** By log type and project:

| log type | project | documents |
|---|---|---|
| toolbox_talk | 588 Thomas | 17 |
| daily_jobsite | **857 Prescott (test)** | 8 |
| subcontractor_orientation | 588 Thomas | 7 |
| osha_log | 588 Thomas | 6 |
| daily_jobsite | 588 Thomas | 2 |
| preshift_signin | 588 Thomas | 1 |
| **total** | | **41** |

**33 of those are on the live customer project.** Thirty-three signatures were
applied to customer compliance records after the audit ledger existed, and no
audit row was written for any of them.

### 5c. How a row is lost, exactly

There are two mechanisms and both are in the same six lines of every signing
editor. Taken from `toolbox_talk.jsx`, which accounts for 17 of the 41:

    const docId = existingLogId || created?.id || created?._id;
    if (docId) {
      recordSignatureEvent({ ... })
        .catch((e) => console.warn('Signature audit failed (non-blocking):', ...));
    }

- **`if (docId)`** — when the push to the server failed, there is no server id,
  so the ledger write is **never attempted**. The signature is still applied and
  the log is still saved locally.
- **`.catch(...)`** — when an id does exist but the ledger POST itself fails, the
  failure is swallowed to a console warning. There is no queue and no retry.

Eleven of the twelve signing screens are local-first by design: a CP signs with
no signal and the reconnect drain later pushes the document and re-applies the
freeze. **The drain does not re-send the signature event.** So a signature
applied without a connection loses its ledger row by the first mechanism, and
one applied on a failing connection loses it by the second, and in neither case
does anything report that it happened.

This is not a design gap in the ledger. It is loss, and the mechanism is known.

### 5c. `daily_logs` holds no signatures

Confirmed zero. That legacy collection is not part of this exposure.

---

## 6. The 8 test documents

All 8 `Test CP` documents are on project `6a7a145e9271db492b9a46ce` — **857
Prescott Pl**, a throwaway test project seeded by
`backend/scripts/seed_857_prescott.py`.

**They are not customer records** and should be excluded from any figure
presented as production activity. They are retained inside the 248 so the total
reconciles with the raw queries; **240** is the customer figure.

---

## 7. Constraints the client has imposed

**No consent may be backfilled.** A consent row written now, dated now,
describing an agreement nobody made, attached to a signature applied in March,
would be a fabricated record — and undetectable afterwards, because the schema
cannot distinguish a backfilled row from a real one.

If a person is asked today and agrees today, that is a consent dated today. It
says nothing about a signature from March. Whether it nonetheless bears on that
signature is the question in §1.

**The same applies to `created_by`.** It must not be inferred and written onto
the documents that lack it. An identity reconstructed after the fact, stored in
the field reserved for an authenticated one, is a stronger claim than the record
can support and would be indistinguishable from a real one thereafter.

---

## 8. The one query outstanding

Read-only. **Not run by the author.** G, H, I and J are answered above; **K** is
the remaining one, and it is the one that decides how many documents have no
recoverable signer at all.

db.logbooks.aggregate([{$match:{cp_signature:{$exists:true,$ne:null},created_by:null}},{$addFields:{idStr:{$toString:"$_id"}}},{$lookup:{from:"signature_events",localField:"idStr",foreignField:"document_id",as:"ev"}},{$match:{ev:{$size:0}}},{$group:{_id:{log_type:"$log_type",project:"$project_name"},unattributable:{$sum:1},names:{$addToSet:"$cp_name"},first:{$min:"$created_at"},last:{$max:"$created_at"}}}])  // K - no created_by AND no ledger row

**Note on K.** `created_by: null` matches both an explicit null and a missing
field, which is what is wanted: §4b's 50 are missing rather than null.

K returns the documents for which **the signer is not recoverable from the
record by any means the system provides** — no authenticated identity on the
document, and no audit row carrying one. It cannot be derived from the numbers
above: the 50 and the 57 are different sets whose overlap is unknown.

---

## 9. Open

- **Queries G, H and I are unrun.** §4b's extent, §5b's split and the
  unattributable count are not yet stated.
- **Why the ledger wrote nothing between 2026-03-26 and 2026-07-29** is not
  established.
- `docs/compliance/esra-bb2024-007-compliance.md` is **stale**: dated 2026-08-30
  and still states the superintendent log is "NOT YET BUILT". It shipped
  2026-09-01. It should be brought current before both documents go out.
- **All thirteen signing screens carry the consent gate** as of `b1f1ec5`. The
  exposure is closed going forward.
- Three defects surfaced by this exercise are live and unscheduled: the ledger
  drops rows silently on a failed write; `cp_name` accepts any non-blank string;
  gate-created orientations never receive a `created_by`.
