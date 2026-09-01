# Two ways a signature loses its signer, and what fixes each

Report only. No code changed in this pass. Companion to
`docs/compliance/esra-consent-retrospective-exposure.md`, which states the
compliance facts; this states the **causes** and what fixing them costs.

Both are live. One is still producing records today.

---

## 1. Gate-created orientations never record who signed them

**50 signed documents. All `subcontractor_orientation`. Ongoing — 6 in July, 42
in August, 2 in September.**

### The path

`subcontractor_orientation` has two creation routes:

| route | endpoint | authenticated | sets `created_by` |
|---|---|---|---|
| the worker at the gate | `POST /api/checkin/register-and-checkin` (`server.py:12838`) | **no** | **no** |
| a CP in the app | `POST /api/logbooks` | yes | yes |

The gate route is `async def register_and_checkin(data: dict, request: Request)`
— **no `current_user` parameter at all.** A worker taps an NFC tag and registers
himself; there is no principal in the request. The orientation it inserts
(`server.py:13153`) therefore cannot carry an authenticated identity, and
correctly does not invent one.

That produced 50 of the 79 orientations. The other 29 came through the CP route
and carry `created_by` normally.

### Why it is not fixed by filling in `created_by`

**`created_by` is not wrong.** The record WAS created by a gate registration.
Writing a CP's id into it would assert he created a document he did not create,
and would then be indistinguishable from the 29 where it is true.

**The missing fact is a different one: who was authenticated when the signature
was applied.** No field holds it. `PUT /api/logbooks/{id}` — the authenticated
request through which a CP signs — writes `cp_signature` and the typed `cp_name`
and nothing else about the signer (`server.py:21066-21073`).

So the identity is in hand at the moment it matters and is discarded.

### The fix

Add `signed_by` and `signed_by_name`, server-set, stamped in `update_logbook`
**at the same moment `cp_signature` is written**:

```python
if data.cp_signature is not None:
    update["cp_signature"] = _finalize_cp_signature(...)
    update["signed_by"] = str(current_user.get("id") or "") or None
    update["signed_by_name"] = current_user.get("full_name") or current_user.get("name")
```

**There is already a precedent for exactly this shape in the codebase.**
Assigning a trade to a flagged worker stamps `trade_assigned_by` and
`trade_assigned_by_name` from the authenticated session at the moment of the
act (`server.py:15280`, `15315`) — separately from whoever created the worker
record. The same distinction, already drawn, on a far less consequential act
than applying a signature to a compliance document.

**Why this and not something narrower:**

- It fixes every log type, not orientations. `cp_name` is self-typed on all 13
  signing screens; today the document's only server-set identity is
  `created_by`, which for eleven of them happens to be the same person by
  accident of workflow rather than by design.
- It is stamped where the signature is stamped, so the two cannot diverge.
- It is additive. Nothing reads `signed_by` yet, so nothing changes behaviour.

**What it does NOT do, deliberately: it does not reach backwards.** The 50
existing documents stay as they are. An identity inferred now and written into a
field reserved for an authenticated one is a stronger claim than the record
supports, and would be indistinguishable from a real one afterwards — the same
objection as backfilling consent.

**Cost:** three lines in one handler, plus a test that a signed document carries
`signed_by`, plus the same stamp on the finalize path if a signature can first
appear there. Small. The value is that it stops the count growing.

---

## 2. The audit ledger drops rows, silently, with no queue

**41 signed documents have no ledger row despite the ledger being live. 33 are
on the live customer project.**

(A further 16 predate the ledger entirely and are not loss — nothing was
attempted.)

### The two mechanisms, both in the same six lines

Every signing editor ends its submit like this. From `toolbox_talk.jsx`, which
accounts for 17 of the 41:

```js
const docId = existingLogId || created?.id || created?._id;
if (docId) {
  recordSignatureEvent({ ... })
    .catch((e) => console.warn('Signature audit failed (non-blocking):', e?.message));
}
```

**(a) `if (docId)` — never attempted.** When the push to the server failed there
is no server id, so no ledger write is even tried. The signature is still applied
and the log is still saved locally and will be pushed later by the drain.

**(b) `.catch(...)` — attempted and dropped.** When an id exists but the POST
fails, the failure becomes a console warning. `recordSignatureEvent`
(`signatureAudit.js:119`) swallows it too and returns `null`. There is no queue
and no retry anywhere.

**And the drain does not close either gap.** `draftSync` re-sends the document
and re-applies the freeze on reconnect. It has no reference to
`recordSignatureEvent` at all.

Eleven of the twelve pre-existing signing screens are local-first **by design** —
a CP signs below grade and syncs later. So the system is built to sign without a
connection and built to lose the audit row when it does.

### Why nobody noticed for four months

The ledger's code shipped **2026-03-26**, both halves the same day. Its first row
is **2026-07-29**. Signatures were applied throughout the gap — 15 documents in
March, 15 in July.

Nothing reported it, because every failure on that path is swallowed. **A
recorder that is live and writing nothing is indistinguishable, at every
observation point an operator has, from one that is working.** Why it wrote
nothing for those four months is not established and cannot be determined from
the source.

### The fix

**Queue the event with the draft, and drain it with the draft.** The machinery
exists: `draftSync.applyRemoteFreeze` already re-applies `/finalize` on
reconnect, keyed off the draft, with refusals recorded and surfaced. A signature
event is the same shape of problem.

1. On submit, write the event payload into the draft alongside `cp_signature`
   rather than firing it and hoping.
2. In the drain, after the document push yields an id, POST the queued event and
   clear it on success. **Keyed on the document id the push returns**, which is
   what mechanism (a) lacks.
3. Stop swallowing. A failed event should leave the key pending so the next drain
   retries it — the same treatment `applyRemoteFreeze` already gets, and for the
   reason recorded there: *"a refusal now fails the push, which leaves the key
   PENDING."*

**Cost:** larger than fix 1. It touches `draftSync`, `logbookDrafts` and the
submit path of all 13 editors, and it needs its own control run — the failure
mode being fixed is silent, so a test that only proves the happy path proves
nothing. Worth scoping separately.

**Interim, if the full fix is deferred:** removing the `if (docId)` guard is
worse than useless — it would attempt a write with no document to attach it to.
The minimum honest interim is to record the failure where the CP can see it,
using the mechanism `recordFinalizeError` already provides, so an unledgered
signature is at least visible rather than silent.

---

## 3. What neither fix does

**Neither reaches backwards, and neither should.** The 50 documents without a
signer and the 41 without a ledger row stay as they are. Both fixes stop the
counts growing; nothing repairs the existing records, because repairing them
means asserting facts the system did not record at the time.

That is the same rule already applied to consent, for the same reason: a record
reconstructed after the fact is indistinguishable from a real one, which is
precisely what makes it unusable as evidence.

---

## 4. Priority

| | ongoing? | records affected | cost |
|---|---|---|---|
| 1. `signed_by` at signature time | **yes — 2 in September** | 50 and growing | small |
| 2. queue the ledger event | **yes** | 41, growing with every offline signature | medium |

Fix 1 first: it is small, additive, stops an actively growing count, and closes
the attribution question for every log type rather than for orientations.
