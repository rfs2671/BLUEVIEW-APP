# D3 groups B and D — the autosave indicator, and where the signature-audit alert goes

_2026-08-19. **Group B is now BUILT** — see the decisions box below; the
recommendation in §B3 was overruled and this document records what shipped
instead. Group D remains report-only. Group A (the silent catches on the submit
path) shipped earlier in the same session._

---

## DECISIONS — 2026-08-19, and what changed because of them

Three rulings landed after this report was first written. Two of them
contradict what it recommended, so the recommendations are struck through
below rather than quietly edited — the reasoning that lost is worth keeping.

**Q1 — no toast on every save; surface it at the SUBMIT GATE.** §B2/§B3 proposed
a four-state sticky indicator in the `autosaveNote` slot. Overruled. A CP
saving every few seconds does not need a message each time, and a message that
fires constantly is one he stops reading — which is worse than silence. But a
lost draft discovered at signature is the same failure one step later, so he
must be told *before he signs*: it surfaces once, at the submit gate, beside
the reasons already rendered there.

> **Built as:** a new `submitWarning` prop on `LogbookStepper`, rendered on the
> submit step above the existing `submitHint`. The ten stepper editors and
> `preshift_signin` (its own footer) pass `finalize.autosaveFailedWarning` when
> the flag is set.
>
> **It WARNS; it does not GATE.** A broken local store does not stop the log
> reaching the server, so disabling Submit would turn a storage fault into an
> inability to file at all. That is one character away from being broken —
> `|| !!submitWarning` in the disabled expression — so it is asserted directly
> in `localSaveVisibility.test.cjs`, and the mutation that adds it is killed.

**Q2 — banner, not a toast.** Group A shipped the submit-time local-save failure
as a `toast.error`. Overruled: he may have walked away, and a toast that
vanished in his truck is the same as no message.

> **Built as:** `recordFinalizeError(handle, 'LOCAL_SAVE_FAILED', key, 'local')`
> at every no-local-copy exit, so `LogbookLockBar` carries it durably to his
> next visit to that exact log — the same mechanism the drain's refusals use.
>
> **A new `'local'` source was required, not just a new code.** §D3 rejected the
> durable banner for group D because its wording would be false; the same
> objection applies here and was answered rather than ignored. `notLockedHint`
> promises a queued retry and `notPushedHint` promises the work is still on the
> device; when the local write is what failed, **both are false**, and either
> would send him away from the only copy there is. Source `'local'` selects
> `notSavedLocalTitle` / `notSavedLocalHint`, which say the true thing: nothing
> is queued, nothing will retry, do not close this log.
>
> **The toast was kept alongside it.** The ruling was read as "a toast is not
> sufficient", not "immediate feedback is wrong" — its stated reason is only
> about durability. This also matches the precedent already in these editors:
> a server refusal does `recordFinalizeError` **and** `toast.error`. If the
> intent was to remove the toast, that is a one-line follow-up.

**Q3 — build both failure modes.** A `false` return and a thrown exception both
mean the write did not happen, and a caller handling one and not the other has
fixed half of it.

> **Built as:** every submit save is now `let localSaved = false; try { ... }
> catch (_e) { localSaved = false; }` (14 sites), and every autosave path moves
> the same flag from both its `.then` and its `.catch`.
>
> `writeDraft` catches its own storage errors, so the throw is unreachable from
> it *as written today*. That is the argument for the branch, not against it:
> the next person to make it throw will not come back and audit fourteen call
> sites. Asserted by PAIRING rather than presence — the count of handled
> writes must equal the count of writes — because a screen with two write sites
> and one handler passes a presence test while half its writes are silent again.

**Q4 — the phone wins.** Already the behaviour on every screen; now pinned
against regression. Separate report: [the phone wins, and what happens to the
server's version](d3-phone-wins-and-the-server-copy.md) — which also answers,
factually and without deciding, whether the server's copy is overwritten
silently (it is) or the divergence is recorded (it is not).

**Q5 — the banner fires on BOTH reasons, worded differently.** The Q2 build only
covered the case where the LOCAL WRITE failed. Overruled as half the problem:
he is signing a legal record, and a phone holding data the server does not is
what he needs to know before he attests — whether the local write failed or the
push did.

> **Built as:** a second code and source, `NOT_ON_SERVER` / `'unsynced'`,
> raised on every exit where the push did not land — the offline fall-through
> AND the 5xx branch, which is the same condition and would otherwise have been
> the half nobody wired. `ON THIS DEVICE ONLY` / "saved here and queued to
> upload … nobody else can see it" against `NOT SAVED ON THIS DEVICE` /
> "nothing is queued and nothing will retry". Opposite advice about whether his
> work is safe, which is why the test asserts the two sentences differ and that
> only one of them uses the word "safe".
>
> **The clear side had to be built with it.** `pushOne` cleared the banner only
> by SERVER ID, and only for a finalized draft — so a banner raised during an
> offline CREATE, recorded against the draft key because no id existed yet,
> would have survived the very sync that made it untrue. A banner that cannot
> come down teaches him to read past all of them. `clearUnsyncedBanner` clears
> both handles on both success paths, and `ssc_daily_safety_log` — which
> imported `clearFinalizeError` and never called it — gained the call.

**Four tests changed shape, and each pinned something the rulings moved.**
`dailyJobsiteFinalizeRefusal` asserted that offline and 5xx record NOTHING,
on the sound reasoning that claiming a refusal the server never made is its own
lie. The reasoning survives; silence was the wrong way to honour it, so the
assertions now check that nothing claims a REFUSAL — distinct code, distinct
source, distinct sentence — rather than that nothing is recorded. Its harness
was also never passing `setRefusedSource`, so the bar's effect threw a
ReferenceError into its own `.catch(() => {})` on every run while every
assertion still passed. `draftSync.finalizeGate` required literal adjacency
between `clearPending` and a return, so inserting a line failed it without
changing the order it checks.

**Coverage.** `frontend/src/utils/localSaveVisibility.test.cjs`, 326
assertions. The first version of these checks used an unanchored lazy
`[\s\S]*?` and matched a *different* catch block hundreds of lines away: it
passed while the branch it claimed to guard was mutated out. 1 of 10 mutations
killed. Rewritten on anchored, non-empty-asserted slices: **10 of 10**.

The Q4/Q5 round repeated the lesson in a smaller way: 10 of 12, because two
assertions tested PRESENCE where each screen now has two exits, so a mutation
silencing one of them passed. Rewritten to assert the expected exit COUNT per
screen — which immediately found a third exit that had never been wired at all
(`subcontractor_orientation`'s create path). **13 of 13** after.

---

## The original report follows

Both questions have the same shape as group A and the same answer-shape: a
promise is printed unconditionally, and the thing that would make it true is
never consulted.

---

# Group B — the autosave indicator

## B1. What is on screen today

There is already an indicator slot, and it is a **static string**.

`LogbookStepper.jsx:209` renders `<Text style={s.autosaveNote}>{autosaveNote}</Text>`,
and all twelve editors pass `autosaveNote={t('savedAutomatically')}` — "Saved
automatically as you go." (`frontend/src/i18n/en.js`, ten namespaces).

It is not driven by anything. It is a constant, rendered at mount, and it says
"Saved" whether the last write succeeded, failed, or never ran. It is the
group-A bug rendered as a label instead of a toast: the debounced autosave was
`writeDraft(...).catch(() => {})` (e.g. `hot_work.jsx:133-137`) and its boolean
return was never read. **Both halves of that are now fixed per Q1/Q3 above;**
the static `autosaveNote` string stays exactly as it was, and the failure is
reported at the submit gate instead of in this slot.

The two daily-log screens are ahead of the twelve editors here: they carry a
real two-state badge — `pendingSync ? "Saved on device" : "Saved"` with distinct
icons (`app/site/daily-logs.jsx:540-549`) — driven by the *pending-push queue*.
That state is real. It is about the SERVER round trip, though, not about
whether the local write landed, so it does not cover this either.

## B2. What the indicator has to be able to say — SUPERSEDED by Q1

> Kept for the reasoning, not as a plan. The four-state indicator below was
> overruled: it puts the message where he is already not reading, and it
> reports on every save. What shipped reports once, at the gate.

Four states, and the fourth is the whole reason to build it.

| State | When | Copy |
|---|---|---|
| `idle` | Nothing typed since the last save landed | "Saved automatically as you go." (today's string, now earned) |
| `saving` | Debounce fired, write in flight | "Saving…" |
| `saved` | `writeDraft` returned **true** | "Saved · 09:14" |
| `failed` | `writeDraft` returned **false** | "NOT SAVED on this device" + the fix |

`failed` is a **sticky** state. It does not decay back to `idle` on the next
keystroke and it is not a toast. A toast is the wrong instrument for this
specific failure: the CP is head-down in a form, and a message that removes
itself after four seconds is indistinguishable from one that was never shown.
It clears on exactly one event — a subsequent `writeDraft` returning true.

## B3. Recommended shape — SUPERSEDED by Q1

> One part of this survived and is worth carrying into any future work here:
> the twelve editors hand-roll the same debounce twelve times, and that
> duplication is exactly why the missing branch was missing twelve times.
> The Q1 build did NOT fix that — it added the same three lines to each of
> them. A `useDraftSaveState(key)` hook would still be the right cleanup.

**A small hook, `useDraftSaveState(key)`, owning the debounce and the state**,
returning `{ state, at, save }`. The twelve editors currently hand-roll the
same `useEffect` + `setTimeout(800)` + `.catch(() => {})` twelve times; that
duplication is why the missing branch is missing twelve times. One hook makes
the failure branch impossible to omit.

Render it in the slot that already exists — `LogbookStepper`'s `autosaveNote`
becomes `saveState` — so no editor gains a new element and the diff per editor
is the import plus the hook call.

**Colour discipline:** `idle`/`saved` stay in muted text, exactly as now. Only
`failed` takes `semantic.critical`. An indicator that draws attention in its
normal state trains the CP to stop reading it, and then it cannot do its one
job.

**Do not make `saving` visible below ~250ms.** A local AsyncStorage write is
usually single-digit milliseconds; flashing "Saving…" on every keystroke is
noise that makes the eventual "NOT SAVED" less visible, not more.

## B4. Explicitly out of scope

- **Retry.** The indicator reports; it does not fix. A storage failure is a
  device condition (quota, corrupt store) and retrying on a loop hides it.
- **Blocking input.** A full store must not stop a CP typing. Group A already
  guarantees his content cannot be silently swallowed at submit; group B is so
  he learns before he gets there.
- **The server round trip.** That is the pending-push queue and the
  `OfflineNotice`. Two different facts; two different indicators. Merging them
  produces one indicator that means neither.

## B5. Sizing

12 editors × (import + hook + one prop) + one hook + one stepper prop + copy in
the `finalize` namespace. The group-A copy keys (`localSaveFailedTitle`,
`localSaveFailed`, `en.js`) already exist and can be reused for the `failed`
sentence.

---

# Group D — where the signature-audit alert goes

## RULED — DO NOT BUILD (2026-08-19)

> No consumer and no rule for what happens when it fires. An alert nobody
> reads is worse than none, because it looks like coverage.

Accepted, and it is the right call on this evidence. §D4b below drafts a rule,
but a rule I wrote is not a consumer: nobody has committed to reading this,
and shipping it would put a number on a dashboard that makes the gap look
handled while nothing changes about it.

**It becomes buildable when these four are answered.** They are the four this
report could not answer from the code:

1. **Who reads it, by name?** Not "an admin" — a role that has agreed to look.
   Absent that, §D4b rule 4's "put it on the exception report" is a place to
   put it, not a consumer.
2. **What do they do about one?** §D4b rule 5 says the honest answer is
   *nothing can be recovered* — the device fingerprint and sign-time hash
   existed only on that phone at that moment. If the only action is "note it",
   say so explicitly, because that determines whether this is an alert or a
   statistic.
3. **At what rate does it stop being one-off and become an incident?** One
   missing event is a dead zone. Ten in a day is a broken endpoint. Nobody has
   set the line, and without it the count in §D4b rule 6 has no meaning.
4. **Is the offline case in scope?** Today an offline-signed log never even
   attempts the audit event — so the gap is not rare, it is systematic and
   invisible. If it is in scope the queue is the bigger half of the work; if
   not, the alert only ever reports online failures and its count means
   something quite different.

Question 4 is the one that should be answered first: it changes the size of
the thing by more than the other three together.

**Unblocked by none of this:** the idempotency question in §D4b. If a retry
queue is ever built, it is a hard precondition — duplicate provenance on a
signed record is worse than absent provenance, because absence is a gap and
duplication is a contradiction.

---

## D1. What happens today

Twelve sites, all identical:

```js
recordSignatureEvent({ ... })
  .catch((e) => console.warn('Signature audit failed (non-blocking):', e?.message));
```

`recordSignatureEvent` itself already swallows (`signatureAudit.js:119-124`:
`console.error`, `return null`), so the `.catch` at the call site is a second
net under a first one. **Nothing reaches a screen, a queue, or a server.** The
call is fire-and-forget, un-awaited, and its failure is invisible.

## D2. What is actually lost

This is the part that decides the destination, so it is worth being exact:
the signature is **not** lost. It is on the document (`cp_signature`), it is
rendered on the PDF, and the log is filed and locked. What is lost is the
`signature_events` row — the independent audit record carrying the device
fingerprint, the acting capacity, and the content snapshot at signing time
(`server.py:12952`, read back at `:13012` and verified at `:13055`).

So the severity is: **the document is fine; its provenance evidence is
missing, and nothing knows.** That is a compliance-evidence gap, discovered
only when someone runs verification against a document and finds no events.

It is also the *most likely* thing to fail of everything on the submit path,
because it is the last network call in a sequence that has already established
the network is unreliable — and on the offline branch it does not even fire
(`preshift_signin.jsx`, `crane_operations.jsx` and the rest gate it on
`landed` / `docId`), so an offline-signed log has no audit event by
construction and no record that it is owed one.

## D3. The candidate destinations

| Destination | Fit | Verdict |
|---|---|---|
| Toast to the CP | He cannot act on it, and it is not his record. Trains him to dismiss | **No** |
| `console.warn` (today) | Reaches nobody | **No** |
| The durable banner (`FINALIZE_ERROR_KEY` → `LogbookLockBar`) | Right *mechanism*, wrong *message*: that banner means "this log is NOT filed", which would be false here | **No** — but reuse its pattern |
| **The pending-push queue** (`logbook_pending_push` → `draftSync`) | Purpose-built: durable, survives app death, drains on reconnect, already retries | **Yes** |
| Server-side detection | Catches what the client can never report (app deleted before reconnect) | **Yes, as the backstop** |

## D4. Recommendation — a two-layer answer

### Layer 1 (primary): a retry queue, mirroring the draft drain

A failed `recordSignatureEvent` writes its payload to a durable AsyncStorage
queue — `signature_events_pending` — and `draftSync`'s existing reconnect
trigger drains it alongside the logbook drafts. It fails into a state that
already exists, invents no new failure mode, and is the same pattern
`markPending` / `pushOne` already prove out.

Three constraints, and the first is not optional:

1. **Idempotency is required before this is built, not after.** A retry queue
   on a non-idempotent endpoint manufactures duplicate audit rows, and
   duplicate provenance on a signed record is worse than absent provenance —
   absence is a gap, duplication is a contradiction. `server.py:12915` already
   does an `existing_count` check on the collection; whether that is sufficient
   as a dedup key for a *replayed* event needs confirming, and a client-minted
   event id is the clean answer if it is not.
2. **It fixes the offline case as a side effect**, and that is most of the
   value. Today an offline-signed log's audit event is never attempted at all.
   Queueing at sign time — rather than only on a caught failure — means the
   event is owed, recorded as owed, and sent when there is signal. This is the
   larger win and it argues for queue-first rather than try-then-queue.
3. **It must not block or delay the signature.** Same rule as everything else
   on this path.

### Layer 2 (backstop): a server-side reconciliation

The client queue cannot cover a device that is wiped, or an app deleted before
reconnect. A periodic job — or a column in the existing admin exception report
that already surfaces unaffirmed signatures (`server.py:17838-17854`) — asking
"which submitted logbooks have a `cp_signature` and **no** `signature_events`
row?" catches the residue.

This is the same instrument that already exists for the adjacent problem, which
is the argument for putting it there rather than building a new surface: an
admin who is already reading a signature-exception report is the right reader,
and "signed but unattested" belongs beside "signed but unaffirmed".

## D4b. THE RULE FOR WHAT HAPPENS WHEN IT FIRES

A destination without a rule is a queue nobody drains. This is the part that
decides whether the alert is worth building at all.

### The state it names

**SIGNED BUT UNATTESTED**: a `logbooks` row with `status: submitted` and a
`cp_signature`, and no `signature_events` row. The document is valid and the
record is filed; what is missing is the independent provenance — device
fingerprint, acting capacity, content hash at sign time.

### Rule 1 — it never blocks anything

Not the submit, not the finalize, not the report, not the PDF. The document is
complete without it. Trading a filed compliance record for a missing metadata
row is a worse outcome than the gap, and a CP who cannot file because an audit
row failed will be taught to work around the app.

### Rule 2 — it retries silently, and only it decides when to stop

Queued, drained on reconnect alongside the drafts, and **not** shown to the CP
while it is retrying. A retrying alert is not an alert; it is a status. It
becomes visible only when it stops retrying.

### Rule 3 — what makes it stop retrying, and what happens then

| Condition | Then |
|---|---|
| The push lands | Dequeue. Nothing is shown. This is the overwhelmingly common case |
| The server REFUSES it (4xx) | Stop retrying. It will keep saying no. Surface on the admin exception report, tagged with the code |
| Still queued after **7 days** | Stop retrying. Surface as above, tagged `stale` |
| The document was deleted meanwhile | Dequeue silently. There is nothing left to attest |

Seven days is a deliberate choice and worth arguing with: it is longer than any
plausible dead-zone rotation and shorter than a monthly compliance review, so a
gap surfaces before anyone is asked to certify a period containing it. What it
must NOT be is unbounded — an entry that retries forever is one nobody ever
learns about.

### Rule 4 — who sees it, and where

The **admin**, on the exception report that already surfaces unaffirmed
signatures (`server.py:17838-17854`) — as an additional column, not a new
screen. "Signed but unattested" belongs beside "signed but unaffirmed": same
reader, same decision, same page.

**Never the CP.** He cannot fix it, it is not his artefact, and telling him
would attach an alarming message to a log he filed correctly.

### Rule 5 — what the admin can actually do

The honest answer, and it constrains the copy: **the provenance cannot be
reconstructed after the fact.** The device fingerprint and the sign-time
content hash existed only on the phone at that moment. Re-recording the event
later would fabricate them, which is worse than the gap.

So the only true actions are:

1. **Note it** — the row is signed and filed, its provenance is absent, and that
   is now a permanent property of that record.
2. **Ask for a re-sign** if the document still matters enough, which produces a
   *new* event with honest values rather than a backdated one.

The report must therefore say "provenance missing, cannot be recovered" and
NOT offer a Retry button. A button that appears to fix an unfixable thing is
how a fabricated audit record gets created by someone being diligent.

### Rule 6 — the count is the metric, not the individual row

One missing event is a dead zone. A rising count is a broken endpoint, a bad
deploy, or a device fleet that cannot reach the API — and that is the thing
worth reacting to. Whatever surfaces this should show the count over time, not
just a list.

## D5. What must not happen

- **Blocking or failing the submit on an audit failure.** The document is
  valid; the evidence is incomplete. Refusing to file it would trade a real
  compliance record for a missing metadata row.
- **Telling the CP.** He cannot fix it and it is not his artefact. The
  destination is the admin surface and the retry queue.
- **A retry queue without idempotency** (D4.1).
- **Reusing the `NOT LOCKED ON THE SERVER` banner.** It asserts something false
  here, and a banner that is sometimes wrong stops being read.
- **A Retry button on the exception report** (D4b rule 5). The provenance is
  unrecoverable; a button that looks like it fixes that is how a fabricated
  audit record gets created by someone being diligent.
- **An unbounded retry** (D4b rule 3). An entry that retries forever is one
  nobody ever learns about — the same silence in a different costume.

---

## Cross-cutting note

Groups A, B and D are three instances of one defect: **an unconditional
promise printed next to a conditional fact.** "Saved on this device" (A),
"Saved automatically as you go" (B), and the audit trail's implicit "this
signature is attested" (D) are each asserted by code that never asks whether
they are true. Group A now asks. B and D are the same question at two other
surfaces, and if a fourth turns up, that phrasing is the thing to grep for.
