# D3 — the phone wins, and what happens to the server's version

_2026-08-19. **The ruling half is built and pinned.** The question this report
answers — silent overwrite, or recorded divergence — is left open by ruling._

---

## FOLLOW-UP PR — strip the selfie base64, gated on head_object

Ruled with D5: **the inline base64 stays for now.** `_upload_to_r2` returning
a URL proves the PUT returned, not that the object is readable, and this
project has produced an unreachable file that way before. Until something
verifies the object, the base64 is the only copy known to exist.

The strip is its own PR and is gated on a `head_object` check confirming the
object is there — the same shape Track P used for the logbook photos, where
`_purge_finalized_photo_base64` materialises its thumbnail **from the bytes R2
really returns** rather than from the bytes it believes it sent. The rule that
work encoded, and the one this PR must reuse: *the writer must not be the thing
that verifies the writer.*

**It must also preserve a distinction that currently rides on the base64.**
Today "took a selfie, upload failed" is a row WITH `selfie_image` and WITHOUT
`selfie_r2_key`; "declined" has neither. Remove the inline copy and both become
the same empty row — which is precisely the two-absences shape the D5 ruling
refused a sentinel for. So the strip PR owns that question: either the
verification makes the failed case impossible to reach, or the distinction has
to be carried some other way before the bytes go.

---

## RULED, 2026-08-19 — Option D, as a SEPARATE PR

**Option D is confirmed. A client push must never clobber server-authored keys.**
Options A, B and C are not taken. Not built here; it is its own PR.

**And the test is half the point of that PR.** From the ruling:

> The all-rungs-gone case is unreachable only because the purge happens at
> finalize and finalize sets the lock. A guarantee arrived at incidentally is one
> a later change removes without anyone noticing.

So §2c/§2d below describe a safety property that **nothing currently asserts**.
Today a photo survives a verbatim client overwrite because
`_logbook_photo_sources` falls back down its ladder, and the case where every
rung is gone — after `_purge_finalized_photo_base64` removes the inline copy —
cannot be reached, because the purge happens at finalize and finalize sets
`is_locked`, which makes `update_logbook` return 423.

Not one line of that chain was written with this in mind. Four independent
decisions happen to compose into a guarantee. Any of them could move:

* the purge could run somewhere other than finalize,
* finalize could stop setting `is_locked` in the same operation,
* the 423 could be narrowed to a subset of fields (plausible — it is exactly
  what a field-level merge invites),
* the fallback ladder could be shortened.

Each is a reasonable-looking change on its own, and any one of them opens a path
to a photo that cannot be served from any copy.

### What the PR must pin, beyond the fix itself

1. **The composition, as one test.** Purge-then-overwrite is unreachable.
   Asserted end to end — finalize purges the inline copy AND sets the lock AND a
   subsequent client `update_logbook` is refused — so that breaking any single
   link in the chain fails it. A test per link would pass while the chain
   parted.
2. **The ladder still has a rung.** For every photo shape the client can push,
   `_logbook_photo_sources` returns at least one source. This is the property
   the fallback exists for and it is currently assumed, not checked.
3. **The fix itself.** Server-authored keys (`enhanced_r2_key`, `thumb_r2_key`,
   `thumb_base64`, `enhance_status`) survive a verbatim client `data` push.
4. **A mutation run over all three.** Same bar as the rest of Part D: remove the
   423, move the purge off finalize, drop a rung, drop the key protection —
   each must turn the suite red. If a mutation survives, the guarantee is still
   incidental and the PR has not done its job.

**Sizing note for whoever picks it up.** §4's query should run first. It sizes
the problem and tells you whether row three of §2d is happening in production at
all; the pinning tests are worth writing either way.

---

**The ruling:** the CP's phone wins. He was on that screen and typed those
words; nothing else has a claim to them.

---

## 1. The rule was already the behaviour

Nothing had to change. Every screen that holds a draft already reads it before
the server and already prefers it, and several say so in as many words:

| Screen(s) | Mechanism | Its own words |
|---|---|---|
| The 9 ported editors + `fall_protection` | `readDraft` → if it has data, hydrate and **`return`** before the server is ever called | "LOCAL-FIRST. A local draft wins over the server copy, so an offline CP reopens to exactly what he filled and unsynced edits are never clobbered" (`hot_work.jsx:184-186`) |
| `daily_jobsite` | same shape | same |
| `preshift_signin` | same shape | "local-first: read the on-device draft first; if present, hydrate from it and skip the server round-trip" (`preshift_signin.jsx:149-150`) |
| `daily-log.jsx` | server IS read (for the list and the id binding) but the form is guarded: `if (!draft) populateFormFromLog(todayLog)` | "The local draft is the NEWER, unsynced copy — it wins. Only hydrate the form from the server when there is nothing on this device" (`:266-267`) |
| `site/daily-logs.jsx` | same, plus `hasDraftData` before any reset | "A draft with no server twin is a log typed offline today — it stays" |

So the build for this ruling was **pinning it, not implementing it**. That is
worth doing on its own: a server-first load is a two-line edit that would read
as a tidy-up in review and would silently overwrite a CP's unsynced work.

`localSaveVisibility.test.cjs` now asserts it on **order**, not presence —
every one of these screens reads the draft *and* calls the server, so "does it
read the draft" passes even on a server-wins screen. It asserts `readDraft`
precedes the server call, and that the draft branch **returns** rather than
falling through into it. Both mutations (drop the `return`; drop the `!draft`
guard) are killed.

The one exception, stated so it is not mistaken for a hole:
`adoptAmendment` deliberately falls **through** to the server when a finalized
local draft has been superseded by an amendment child. That is not the server
winning — it is the local draft being discarded on server confirmation and the
child becoming the thing the phone then holds.

---

## 2. What happens to the server's version — the question, answered factually

### 2a. It is overwritten, verbatim, with no record of what it held

`update_logbook` builds `update["data"] = data.data` and issues
`$set` (`server.py:17256`). The stored `data` is replaced wholesale. There is:

- no read of the prior value,
- no comparison,
- no `updated_from` / `previous_data` / revision entry,
- nothing written anywhere that says the two differed.

`create_logbook`'s upsert branch does the same (`server.py:17061-17067`).

So: **silent overwrite.** Not "silent" as an accusation — it is the only
behaviour consistent with the ruling — but silent as a fact, and it means a
filed record where the two disagreed **cannot currently be reconstructed.**

### 2b. The screen does not even know a divergence happened

This is the sharper half. In the ten editors the local-first branch **returns
before the server is called**, so the phone never sees the server's version at
all. The divergence is not resolved in the phone's favour after being noticed;
it is never noticed. Nothing is in a position to record it, which is why 2a is
a design gap rather than an omission at one call site.

`daily-log.jsx` is the exception: it *does* fetch `todayLog` and then declines
to use it. That screen is the one place where a comparison is available for
free today.

### 2c. What limits the blast radius

Three things, and they should be counted before deciding this needs fixing:

1. **The finalize lock.** `update_logbook` returns **423** on
   `is_locked` (`server.py:17187-17188`), so a filed, frozen record can never
   be overwritten this way. Corrections go through `/amend`, which creates a
   child. **The worst case — overwriting signed, filed evidence — is already
   closed.**
2. **`writeDraft`'s own finalize lock** refuses local content edits on a
   finalized draft, so the phone will not accumulate changes to push over one.
3. **The empty-draft guard** in `pushOne` refuses to push `{}` over an existing
   document (`draftSync.js:229-231`) — the one divergence case that was
   noticed and handled, because it destroys rather than replaces.

### 2d. How a divergence actually arises

The phone can only overwrite something another writer put there. Enumerated
from `db.logbooks.update_one` call sites:

| Writer | Writes | Reachable divergence? |
|---|---|---|
| Another device / CP editing the same (project, type, date) | whole `data` | Yes, if two devices hold the same log |
| Admin edit via the same endpoint | whole `data` | Yes |
| **The photo-enhance pass** (`server.py:448`) | `data.activities.N.photos.M.{enhanced_r2_key, thumb_r2_key, enhance_status, …}` | **Yes, and routinely** |
| The thumbnail retention write (`:17347`) | `data.activities.N.photos.M.thumb_base64` | Yes |
| `/finalize` (`:17411`) | `is_locked` only | No — not inside `data` |
| Soft delete (`:17755`) | `is_deleted` | No |

The third row is the concrete, non-hypothetical one and it is worth stating
plainly: **the server writes fields inside `data` that the phone has never
seen.** The enhance pass runs after upload and stores its output on the photo
row. A phone that later pushes `data` verbatim — built from a draft that
predates those keys — drops them.

The consequence is bounded: `_logbook_photo_sources` (`server.py:274-305`) is
an explicit fallback ladder, so a photo missing `enhanced_r2_key` still serves
from `thumb_r2_key`, `original_r2_key` or the inline base64. The symptom is a
photo served at lower quality, not a missing photo. And the case where *every*
rung is gone — after the finalize purge removes the inline copy — is
unreachable, because the purge happens at finalize and finalize sets
`is_locked`, which makes the overwrite 423.

That is a real guarantee arrived at incidentally. It holds because of the lock,
not because anything reasoned about photo keys.

---

## 3. The options, not a decision

Left open by ruling. Sketched with costs so the decision has something to price.

**A. Leave it. Document that the phone is authoritative and the server's prior
`data` is not retained.** Zero cost. Honest, given 2c: the only records where
the divergence would matter legally are locked, and locked records cannot be
overwritten. The cost is that a "why does the filed log not match what I saw"
question has no answer.

**B. Record the divergence without changing who wins.** On update, if the
stored `data` differs from the incoming `data`, write the prior value to a
side collection (`logbook_overwrites`) with `{logbook_id, at, by, prior_data}`.
The phone still wins; the loser is kept. Costs one extra read per update and
storage proportional to real conflicts, which 2d suggests is small. This is the
option that makes "a filed record where the two disagreed" reconstructable,
which is the phrasing the ruling used.

**C. Detect and tell the CP.** Requires the ten editors to fetch the server
copy even when a draft exists — i.e. giving up the local-first early return
that makes them work offline. **Recommend against.** It buys a prompt at a
turnstile at 6:40am and costs the offline guarantee.

**D. Field-level merge.** Server-authored keys (`enhanced_r2_key`,
`thumb_r2_key`, `thumb_base64`) are never overwritten by a client push; the
rest is verbatim. Narrower than B and fixes only 2d's third row. Worth doing
**regardless** of B — those three fields have no business being clobbered by a
client that has never seen them, and the current safety is incidental.

**Sequencing note.** B and D are independent. D is small, has a named
beneficiary, and does not touch the who-wins rule at all. If only one gets
built, it should be D.

---

## 4. Open question worth one query

How often do two writers actually touch one logbook? `db.logbooks` has
`updated_at`; the enhance pass and the client push both bump it. A count of
documents whose `data.activities.*.photos.*.enhanced_r2_key` is absent while
`enhance_status` is `"done"` would show whether 2d's third row is happening in
production, and would size B and D against real numbers rather than against
this reasoning. Read-only, one aggregation.
