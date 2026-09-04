# Audit follow-ups

Running log of deferred fixes surfaced during audits. Newest first.

---

## PRACTICE — 2026-09-04 — a LOCATION standing in for a STRUCTURE, which is most of this week

Three checks broke in one day, none of them because the thing they protect
changed. Each had substituted a position in a file for the shape it cared about.

| check | what it pinned | what it meant |
|---|---|---|
| `test_signature_ink_predicate` | the affirmed/ink predicates within 4000 CHARACTERS of each other | "the two halves of one rule are read together" |
| `test_startup_seed_guard`, and a SECOND COPY in `test_worker_response_model` | 900 CHARACTERS from a marker comment | "these keys are in the seeded document" |
| `test_assigned_projects_grant` | the LITERAL `sub_dict["assigned_projects"] = []` | "every creation handler forces the list" |

The first fired because a new module-level function was inserted between them.
The second and third fired because a COMMENT was added inside the seed call and
the byte budget ran out mid-comment — both files then reported a document that
carries `contact_name` as omitting it. The third fired because the handler it
named was deleted as dead code.

**In every case the invariant was intact and the check was measuring
somewhere.** That is the same defect as a leftmost `re.search` with `(.*?)` over
a 41k-line file, which this project hit four times in a week and twice more
from two directions at once; as a ratchet whose scan root was
`Path(__file__).parent`; and as a source pin that greps a location when the
thing worth protecting is a behaviour.

### The rule

**If the assertion is about a STRUCTURE — a dict's keys, a function's calls, a
projection's shape — read the structure.** `ast.parse` is three lines and it
cannot be pushed out of range by a comment. A character window, a line number
and a bare literal are all the same bet: that nothing above the subject will
ever move.

Where a positional check is genuinely the point — "these two predicates must
stay adjacent" IS a claim about position — keep it, and say in the failure
message that the fix may be to move the new code rather than to widen the
bound. `test_signature_ink_predicate` was RIGHT to fail on 2026-09-04, and the
correct response was relocating two helpers, not raising 4000 to 6000.

### And the corollary that cost the most

**A grep for a route string cannot find every reference to a route.** Removing
five dead `/admin/subcontractors` handlers was preceded by a full-repo search
for the path, which returned seven references and was reported as complete. Two
more existed: one naming a handler by SYMBOL through `hasattr`-shaped source
text, one pinning a line from inside its body. Neither contains the path.

The suite found them. **Treat a reference grep as necessary and never
sufficient before a removal; the full suite is the check.**

### Where the two repairs landed

The window is gone. `tests/source_text.inserted_doc_keys(collection)` reads the
document from the AST, is used by both files that had a copy of the window, and
RAISES rather than returning an empty set when it finds no matching call —
every "is field X present" assertion downstream is vacuously satisfied by an
empty result, which is exactly how a check that stopped reaching its subject
reports success. See the empty-set entry.

The injection guard was made CONDITIONAL rather than deleted: it re-arms if
`create_subcontractor` ever comes back, which matters because the models were
kept deliberately and re-adding a handler is a plausible afternoon's work.

---

## RULED — 2026-09-04 — five dead subcontractor routes removed; the COLLECTION is kept, deliberately

`GET/POST /admin/subcontractors`, `GET/PUT/DELETE /admin/subcontractors/{id}`
are gone. Nothing had ever called them: no wrapper in
`frontend/src/utils/api.js`, zero references anywhere under `frontend/`,
nothing in `checkin.html`, `scripts/` or `lib/`.

**Removed rather than fixed, because the list handler was not merely dead.** It
sorted `company_name` under `{"password": 0}` — an EXCLUSION projection, the
shape that returned 500 twice this week on collections carrying inline base64.
It was rated slow-only for exactly one reason: nothing stores base64 on
`subcontractors` *yet*. An unreachable endpoint carrying a broken projection is
a defect waiting for a future caller who assumes it works, and deleting it is a
smaller change than repairing it.

### What is KEPT, and why that is not an oversight

`db.subcontractors` and every document in it. `SubcontractorCreate` /
`SubcontractorResponse`. The `email_1` unique index. The startup seed row, and
`backend/tests/test_startup_seed_guard.py` — the seed still runs at boot and the
guard still describes real behaviour, so removing the routes does not orphan it.

**Retiring a collection is a DATA decision, not a routing one.** Subcontractors
sit beside the Subcontractor Compliance Graph on the future feature list, and
deleting the schema now means rebuilding it from memory later. The routes were
the liability; the shape was not.

**If these routes are ever re-added, the list handler gets an INCLUSION
projection from the start.** The exclusion is what turned dead code into a
defect.

### The PRD claimed a page that has never existed

`memory/PRD.md` listed `/admin/subcontractors` under **Pages Implemented** as
"Admin Subcontractors — ✅ Full CRUD". There is no such screen in
`frontend/app/admin/` and there never has been. That line was false before this
change, not because of it, and it is the most likely source of the future
caller this removal exists to protect against: a spec asserting a working
feature is stronger evidence to a reader than an endpoint's absence is.

**The rule.** A status table that is written by hand and read as truth needs the
same treatment as a comment asserting a rule the code does not implement —
recorded here more than once this week. When a row says ✅, something has to
have checked.

---

## PRACTICE — 2026-09-04 — the build card's verdict line is a COMPARISON, not a health check

`app/settings.jsx` prints "MISMATCH — the app and the backend are on different
commits" whenever `jsCommit[:7] != backendCommit[:7]`. That sentence has one
reading in the field — *something is wrong, the app is stale* — and it is
correct for the case it was built for: a bundle that failed to publish.

**It is also what a BACKEND-ONLY change legitimately produces.** #401 and #402
touched `backend/server.py` and nothing under `frontend/`, so the OTA workflow
did not run — correctly, its paths filter is frontend-only. The phone keeps the
bundle it has, the backend moves, and the card says MISMATCH about a system
that is exactly right.

**The cost is concrete and was nearly paid.** The acceptance test for #401 was
first written as "wait for the OTA, confirm the version line reads the new
SHA." That would never have happened, and the CP would have concluded a landed
fix had not shipped — the same wrong conclusion the stale-bundle case produces,
from the opposite cause.

### What the card can and cannot distinguish today

It cannot. It compares two commit strings for equality and has no notion of
ANCESTRY, so "the app is behind the backend", "the backend is behind the app"
and "they differ because the change was one-sided" are one output.

Everything needed to tell them apart is already on the card: `Bundle built`
carries `Updates.createdAt`, and `/api/version` could carry the backend's
commit date. **Backend newer than the bundle, with the bundle's own age small,
is the one-sided case; a bundle weeks older than the backend is the stale one.**
That is a comparison of two timestamps, not a graph walk, and it needs one
field added to `/api/version`.

Recorded rather than built: the card is honest today, and a wrong explanation
would be worse than a bare fact. But an unexplained MISMATCH is read as a
fault, and this week it was.

---

## OPEN — 2026-09-03 — a tradeoff paying full price for a guarantee its other half stopped delivering

The PDF viewer rasterises pages at up to 16 megapixels, oversampled ~3x on a
dpr-2 device, across a window spanning four viewport heights. On a 25-31 MB
architectural set that is 20-30 seconds to open.

The cost is deliberate and the reason is written down in `pdfjsViewer.js`:
*"Render above CSS size so pinch-zoom stays legible without a re-render."* Nine
times the pixels, bought to make zoom free.

**Zoom is not free. It reloads the WebView and drops the reader back to page
one.** So the product pays the whole cost of the tradeoff and receives none of
the benefit. Not a slow feature and a separate bug — one bargain, half of which
stopped being honoured, with the payment still going out.

### Why nothing surfaced it

Both halves still "work" in the sense each was written to. The oversample
renders exactly as designed. The reload is a correct consequence of a
dependency array. **Neither is a defect on its own terms, and no test relates
them,** because the relationship is an intention that lives in a comment. A
comment cannot fail.

There is even a memo guarding part of it — `webViewSource` is memoised
specifically so unrelated state updates do not force a reload, and that memo
works. It protects against changes INSIDE the component and not against a new
`file` prop from the parent, so the guarantee holds in the cases somebody
thought of and silently lapses in the one that matters.

### The shape

When a cost is paid to buy a property, **the property is the thing to test, not
the mechanism that pays for it.** Here the assertion worth having is "zoom does
not reload", which is cheap to state and would have failed the day it broke.
Instead there is an oversample multiplier nobody can evaluate without knowing
what it was for, and a reader who finds it later sees only an expensive constant.

Same family as the rest of this log — something ran, did exactly what it was
written to do, and the answer meant nothing because the thing it was for had
moved. Here the thing it was for was another part of the same feature.

### The rule

A performance constant bought to guarantee a behaviour should name the
behaviour in a test, not only in a comment. And when a screen is slow, ask what
the slowness was purchasing before optimising it — removing the cost is right
only if the benefit is genuinely gone, and here the correct order is to restore
the benefit first and then re-measure whether the cost is still worth paying.
Measuring the oversample while reloads are still happening would confound the
two and produce a number that argues for the wrong change.

---

## RULED — 2026-09-03 — the two dead plan-page indexes: do NOT build, decide later against real numbers

Operator ruling. Neither is a correctness problem and both are cheap to add
later against measured queries, so nothing is being built now. Recorded so the
next person does not rediscover them and "fix" them blind.

### `document_page_by_sheet_number` — what it would serve

The sheet lookup in `server.py`: a CP asks for a drawing by number ("A-301",
"ME-401"), `_is_sheet_number_query` recognises the token, and the search runs

    fq["sheet_number"] = {"$regex": pattern, "$options": "i"}
    hits = await db.document_page_index.find(fq).to_list(10)

against a `project_id` base filter. The pattern is anchored
(`^(PFX1|PFX2)(\.\d+)?$`), so it WOULD be indexable — except `$options: "i"`
defeats it. A case-insensitive regex cannot use a case-sensitively ordered
index, so Mongo takes the `project_id` prefix and scans within it.

**Building the index alone changes nothing.** The fix is either a collation on
the index or normalising `sheet_number` on write and dropping the `i` — and the
second is the one worth measuring, because it also makes the query cheaper for
every project regardless of index.

### `document_page_by_floor` — what it would serve

Nothing, as the code stands. `floor` is READ (the scheduling aggregator's
`p.get("floor")`, the engine's grouping) but is never a query key. The
aggregator loads every row for a project with `find({"project_id": project_id})`
and groups in Python. An index on `(project_id, floor)` serves a filter no
caller applies.

It becomes worth having the day someone queries by floor rather than grouping
after a full load — which is a different change, and would be the thing to
measure first.

### Why this is a ruling and not a TODO

Both indexes exist in the code and are created on every boot. Neither is
absent, broken, or blocking. What they lack is a caller that benefits, and that
is a measurement question rather than a build question. **Adding an index to
make a report look tidy is how a collection acquires write cost nobody can
attribute later.**

Contrast `document_page_unique`, which is NOT in this ruling: it is a
correctness constraint, not a performance one, and its absence would let
duplicate `(file_id, page_number)` rows accumulate to the point where it can
never be built.

### One thing checked and found NOT to be a defect

`dob_logs_summary_dedup` was suspected of having been created by hand rather
than by the code that intended it — a divergence between what the code declares
and what production runs. It is not. `server.py:42989` creates it at indent 4
inside `startup_event`, unconditionally, on every boot. Recorded because the
suspicion was reasonable and the answer is worth not re-deriving: an index
present in production AND declared unconditionally in startup code is the system
working, not a hand-made stand-in.

---

## OPEN — 2026-09-03 — an index that cannot serve its query looks identical, from inside, to one that works

`run_whatsapp_startup_migrations` creates four indexes on `document_page_index`
— the plan-page search collection, which has nothing to do with WhatsApp. Asked
what each one buys, the answers were not what the names suggest.

**`document_page_by_floor` serves no query.** `floor` is READ — the scheduling
aggregator does `p.get("floor")` and the engine groups by it — but it is never a
query key. The aggregator loads every row for a project with
`find({"project_id": project_id})` and groups in Python. The index exists for a
filter nobody applies.

**`document_page_by_sheet_number` cannot serve the query it was built for.** The
lookup is `{"$regex": pattern, "$options": "i"}`. The pattern IS anchored, which
would normally be indexable — but the case-insensitive option defeats it,
because the index stores keys in case-sensitive order. Mongo uses the
`project_id` prefix and scans the rest. The index was created for a query shape
that cannot use it.

**`document_page_unique` is correctness, not performance,** and was described as
performance. Unique on `(file_id, page_number)`, it stops one page of one file
being indexed twice. It is also the one with a trap: absent, duplicates
accumulate, and then it can never be built without cleaning them first.

### The shape

**Nothing in this system can tell a working index from a useless one.**
`getIndexes()` shows all four. They build, they occupy space, they are
maintained on every write, and two of them do nothing. There is no measurement
anywhere of whether an index is USED — no `$indexStats` check, no test, no
alert. An index is assumed to be doing its job because it exists.

That is the same family this log keeps recording: the sweep whose keep-set could
see one of two shapes, the grep whose pattern could not match its own output,
the CofO query that 400'd 96 times a day for months, the mutation control that
patched the wrong occurrence. **Something ran, produced a well-formed result,
and never reached its subject** — and the well-formed result is exactly what
made it invisible.

### The rule

An index is a claim that a specific query will use it. Write the query beside
it, or the index is decoration with a maintenance cost. Before adding one, name
the query; after adding one, prove the query uses it — `$indexStats` or an
`explain()` assertion, not the fact that `create_index` returned.

**And case-insensitive matching needs a collation, not an index and a hope.**
`$options: "i"` and a plain index are mutually exclusive; either the field is
normalised on write or the index carries the collation.

### Related, and not the same

These four sit inside a single `try`/`except` covering six unrelated migrations,
so a failure in an earlier one strands the later ones into one `logger.warning`.
That is a separate defect, recorded in the entry above on `startup_event`'s two
failure contracts, and it was already half-fixed once — `ensure_dropbox_sync_indexes`
was extracted from this very function for exactly that reason, and
`document_page_index` was left behind.

Note for anyone reading a claim that these never ran: the call is
`await run_whatsapp_startup_migrations()` at the top level of `startup_event`,
indent 4, **with no conditional above it**. It executes on every boot whether or
not WhatsApp is configured. They are not gated and not pending.

---

## OPEN — 2026-09-03 — startup_event has two eras of failure semantics and nothing marks the boundary

`startup_event` is **1,589 lines** and performs **77 index creations**. It is
registered `@app.on_event("startup")`, so an exception there does not skip a
step -- it stops the service from booting at all.

The first block is BARE sequential awaits with no guard, and seven of them are
UNIQUE builds:

    await db.users.create_index("email", unique=True)
    await db.workers.create_index("phone", unique=True, sparse=True)
    await db.nfc_tags.create_index("tag_id", unique=True)
    await db.subcontractors.create_index("email", unique=True)
    await db.companies.create_index("name", unique=True)
    await db.daily_logs.create_index([...], unique=True)
    await db.whatsapp_contacts.create_index([...], unique=True)

A unique build is rejected when the collection already holds duplicates. So the
day any of those seven meets duplicate data -- one repeated company name, one
worker phone entered twice -- **the API does not start.** Not a degraded
feature: a total outage, on a data condition, at the next restart, with no
deploy having changed anything.

Later blocks in the same function use `_ensure_index_resilient`, which catches a
non-conflict `OperationFailure`, logs a warning and returns. Those cannot take
the service down. That is the right behaviour and it is deliberate -- the
partial unique index added for open amendments is documented as legitimately
unable to build today, because production holds the duplicates it forbids, and
it must not block startup.

**So one function contains two opposite contracts, and nothing in it says
where the boundary is.** A developer adding an index copies whichever line is
nearest. Adding a unique one to the bare block is a latent outage; adding a
critical one to the resilient block is an index that may silently never exist.

### The rule

Every index creation in `startup_event` should go through
`_ensure_index_resilient`, and any that genuinely must exist before the app
serves should say so explicitly rather than by being an unguarded `await` in
the older half of a 1,589-line function.

**And the general shape, which is worth more than the instance:** a destructive
or blocking operation that has never fired is not thereby proven safe. It may
be deferred behind a condition nobody has met yet. "It has never happened" and
"it cannot happen" are different claims, and only the second is a guarantee.
Nothing in this system distinguishes them -- which is why the seven unique
builds above have looked fine for as long as the data happened to be clean.

### How this was found, which is also worth recording

By pulling on a claim that turned out to be false. A runbook asserted two TTL
indexes still existed in production; the operator checked and they did not.
Establishing why led through `startup_event`, and the real finding was standing
next to the imagined one. **A wrong hypothesis investigated properly is not a
wasted investigation** -- but the answer has to come from running the check, not
from the document that prompted it.

---

## PRACTICE — 2026-09-02 — `git stash` is ONE ref shared by every worktree, and two agents traded trees through it

Roughly forty-five agent worktrees hang off this repository. `refs/stash` lives
in the common git dir, so every one of them pushes and pops the SAME stack.

Two agents ran `git stash` inside the same window. The second one's `pop`
restored the FIRST one's work into its tree, and its own changes went to the
top of a stack it did not own. One agent found conflict markers in server.py
that no merge it performed had produced; the other found its working tree
emptied mid-run. Both recovered in full, but only because each noticed and
neither assumed the tree it was looking at was its own.

**`stash@{n}` is a POSITION, not an identity.** A concurrent push shifts every
index, so even an agent that recorded "mine is stash@{0}" pops somebody else's a
minute later. This is the same defect class as an index-keyed anything under
concurrency, and it destroys uncommitted work rather than merely confusing a
read.

**The rule: no agent uses `git stash` in this repository.** To set work aside,
make a temporary WIP commit and reset it afterwards, or copy the file to the
scratchpad and copy it back. Both are private to the worktree.

If a stash is genuinely unavoidable, it must be `git stash push -u -m
"<unique-tag>"`, its SHA captured immediately from `git stash list
--format='%H %gs'`, restored with `git stash apply <sha>` and NEVER `pop`, and
dropped only after re-finding its current index by tag. That is four rules to
remember correctly under concurrency, which is why the answer is simply not to.

**The wider point.** Worktrees isolate the working tree and the index. They do
NOT isolate the stash, the reflog, refs, hooks, or config. An agent reasoning
"my worktree is mine" is right about files and wrong about everything that
lives in the common git dir, and the failure is silent until it is destructive.

---

## PRACTICE — 2026-09-02 — a mutation control that patches the wrong occurrence reports a pass and means nothing

A control broke `except DuplicateKeyError:` to prove the tests could see it
missing. **106 tests passed against the supposedly broken code.** The string
appears twice in server.py; the patch hit the first, six thousand lines away in
an unrelated function, and never touched the code under test.

The test suite was fine. The CONTROL was broken, and a broken control reports
exactly what a well-covered change reports.

This is the second instance recorded here. The first was a mutation whose anchor
did not match because the file was CRLF and the patch was LF: it applied to
nothing, the suite passed, and the pass was read as coverage.

**A mutation control has TWO claims, and only one is usually checked.** The
loud one is "the tests fail when the code is broken." The silent one is "the
code was actually broken." A control that skips the second measures nothing, and
it fails in the reassuring direction — toward a green suite and a confident
report.

**The rule: verify the mutation LANDED before believing the result.** Diff the
file, or print the patched line, or assert the occurrence count changed. Where
a symbol appears more than once, target it by enclosing function and not by
first match. When a mutation produces NO failures, the first hypothesis is a
control that did not apply — not a gap in coverage — because the former is far
more common and is invisible in the output.

Related: the tab-blind grep and the empty-set `executionSuccess`. Same family
throughout — a check ran, produced a well-formed answer, and never reached its
subject. Here the subject was the mutation itself.

---

## PRACTICE — 2026-09-02 — squashing the base of a stack breaks every branch above it

Three PRs were verified to merge clean, then all three went CONFLICTING without
anyone touching them. The cause was the merge of their own base.

The four commits of the manifest work were squash-merged as one new commit. The
three branches stacked on top still carried the ORIGINALS. Git then saw the same
changes arriving twice by two different routes and refused every one of them --
not because the content disagreed, but because the identical content had two
identities.

Nothing was wrong with the branches. The tell is that the conflicts appeared at
the moment of an unrelated-looking merge and appeared in ALL of them at once; a
real conflict arrives one branch at a time and names a line somebody edited.

**The rule.** Squash-merging is a rewrite. Do not squash the base of a stack and
then expect the stack. Either merge the whole stack in one PR, or after squashing
the base, replay the rest:

    git rebase --onto origin/main <last-commit-of-the-squashed-base> <tip>

That replays only the commits the squash did not absorb. It is not a conflict
resolution and should produce no conflicts -- if it does, that is a real one and
worth reading.

**The wider point.** The stack was created to make review granular, and the
squash policy that makes history readable is the same policy that destroys the
stack. Those two are in tension by construction, and the tension surfaces at
merge time, which is the worst moment to discover it. Decide at BRANCH time: a
stack whose base will be squashed is a single PR wearing three hats.

---

## PRACTICE — 2026-09-02 — a source pin greps a LOCATION; the thing worth protecting is a BEHAVIOUR

A backend test read `frontend/app/site/logbooks.jsx` and asserted the string
`stripPhotoBlobs` appeared in it. Moving the day detail off AsyncStorage removed
that function, and the test went red -- for a MOVE, not for a regression.

The screen had stopped being the owner. Storage now lives in
`siteLogbookHistory` as identity rows, and the pin was still watching the
previous owner, from a different language, in a different test suite.

**The concern outlived the function, so it moved rather than died** -- and it
moved somewhere it can be EXECUTED. The frontend suite now feeds `identityRow` a
log carrying `base64`, `thumb_base64`, a `photos[]` array and a `data` blob and
asserts none of those byte-strings appear in the stored row, then asserts the row
is exactly its four fields.

That is a STRONGER claim than the pin made, and the difference is the general
lesson. `stripPhotoBlobs` was a blacklist that removed `base64`; its own
docstring conceded it had become a permanent no-op and would need editing again
for `thumb_base64`. `identityRow` is an allow-list, so a photo field invented
tomorrow is excluded without anyone remembering to exclude it.

**The rule.** A source grep pins a location. Locations move; behaviours are what
the compliance record depends on. When a pin fails, the first question is not
"how do I make it pass" but "did the subject move" -- and if it moved, the pin
follows it into a suite that can run it. A pin that cannot be converted into an
execution is a note, and should be written as a comment rather than as a test
that will one day fail for the wrong reason.

Filed alongside the other members of this family: the sweep blind to .cjs, the
glob that ran 85 of 93, the sort() that did nothing.

---

## PRACTICE — 2026-09-02 — a test double thinner than the real module tests the double

Two branches were built in parallel and each was green alone. One wrote a
file-system double with `deleteAsync`, `getInfoAsync` and `downloadAsync`. The
other changed the downloader to write to a `.part` path and rename on success.

Merged, seven tests failed. Not because the atomic download was wrong -- because
the double had no `moveAsync`, which the real `expo-file-system/legacy` has.
Calling an absent method threw, the retry threw, the outer catch swallowed it,
and every download returned null.

**A double is a claim about the real module.** Every method the subject may call
is part of that claim, including the ones it does not call YET. The gap does not
appear when the double is written; it appears the first time the subject reaches
for something the double never modelled, which is exactly when a change is being
made and confidence matters most.

The fix models the rename properly: `moveAsync` deletes the source name, adds the
destination, and throws ENOENT if the source is absent -- so a promotion of a
file that was never written cannot silently pass. Verified by mutation: deleting
the `moveAsync` call from the product fails 2 of 52.

**The cheap tell.** When a merge of two independently-green branches goes red in
the TEST layer rather than the product layer, suspect the double before
suspecting either change. And when writing a double for a module you did not
write, enumerate its exported surface once rather than implementing the three
methods today's subject happens to call.

This one failed loudly, which is the good version. The same gap in a double whose
absent method returns undefined instead of throwing is the silent version, and
that is the one that ships.

---

## PRACTICE — 2026-09-02 — a grep whose pattern did not match its own output reported a red PR as green

Seven PRs were checked for CI status with a pattern matching a check name
followed by whitespace and `fail` or `pending`. `gh pr checks` emits
TAB-separated fields. The pattern matched nothing, the count came back 0, and 0
was read as "no failing checks".

One of those PRs had a hard failure. It was reported to the operator as green.

**A count of zero from a search is not a finding. It is either a finding or a
broken search, and the two are indistinguishable without a positive control.**
This is the same shape as the empty-set `executionSuccess` and the keep-set that
skipped a whole file format: the check ran, produced a well-formed answer, and
its REACH was wrong.

**The rule, for any check whose passing condition is an absence.** Before
trusting a zero, make the pattern match something known-present. Here that was
one character of work -- printing the second field of every row would have shown
`pass` values and proved the field split was right. A zero that has never been
shown capable of being non-zero is not evidence.

**And the correction that matters more:** when the answer is later shown to be
wrong, say which part was wrong. The failure here was not "CI was flaky" or "the
state was UNKNOWN at the time"; it was a pattern that could not match the output
format. Naming the mechanism is what stops the same grep being written again an
hour later.

---

## PRACTICE — 2026-09-02 — `railway logs --since` is silently ineffective when the line cap binds first

Hunting a lost logbook write, `railway logs --since 20h` was run and returned a
window of 500 lines covering 47 minutes. The same command with a larger `--since`
returned the IDENTICAL window. A grep for the POST across "the last 20 hours"
came back empty, and that empty result was very nearly reported as evidence the
request never arrived.

The flag does not widen what the line cap already bound. Whichever limit binds
first wins, and the tool says nothing about which one did.

**An empty grep over the wrong window is indistinguishable from an empty grep
over the right one.** The only defence is to establish the window's real extent
before searching it: print the first and last timestamps of what came back, and
compare them against what was asked for. That takes one command and converts a
silent truncation into a visible one.

**The rule.** For any log query used as NEGATIVE evidence -- "the request never
arrived", "the error never fired" -- the coverage of the query is part of the
claim and has to be stated with it. "No POST in the log" is worthless; "no POST
between 03:14 and 04:01, which is the whole window the tool returned" is a fact,
and it visibly does not reach back to the event in question.

Same family as the empty-set control and the tab-blind grep: a search that ran,
returned a well-formed answer, and did not reach its subject.

---

## PRACTICE — 2026-09-02 — code that existed, was correct, and was never called

`sendPendingSignatures` was present, well-written, and covered by tests. Nothing
invoked it. Signatures queued on a device with no signal stayed queued.

No sweep catches this. The function parses, its identifiers bind, its tests pass
because tests call it directly, and every static check reads it as live code. The
only thing missing is a caller, and absence of a caller is not a property any of
those checks look at.

The same shape appeared twice more in the same period: a drain that existed but
was not wired to reconnect, and a guard whose call site had been removed.

**The rule.** For any function whose job is to fire on an EVENT -- reconnect,
foreground, boot, retry -- the test that matters is not "does it do the right
thing when called" but "is it called". Those are different assertions and the
first one passing says nothing about the second.

Assert the wiring where the wiring lives: that the effect subscribes, that the
listener list contains it, that teardown removes it. A test that imports the
function and calls it has verified the body and left the entire question open.

**The cheap sweep**, worth having: for each exported function, count call sites
outside its own test file. Zero is not automatically wrong -- public API, dead
code pending removal -- but zero on something named `send*`, `drain*`, `flush*`
or `sync*` is a defect until someone explains it.

---

## PRACTICE — 2026-09-02 — a reader naming a field no writer produces, and the inverse

Two readers consulted a field name that nothing in the codebase ever writes. The
read returns undefined, the caller treats undefined as "not set", and the screen
renders a plausible default. Nothing errors, nothing logs, and the feature is
simply inert.

The operator hit the mirror image of this from the other side: three field names
were queried against production, all returned null, and the null was read as
evidence about the data. The fields were never written by any code path, so the
null was evidence about the QUERY.

**Both directions are the same defect: a name that exists on one side of the
read/write boundary and not the other.** Neither side can detect it alone. A
reader cannot tell "written and empty" from "never written"; a writer has no idea
whether anyone reads it.

A checker exists (`backend/scripts/find_reads_without_writers.py`) and its own
header records FOUR INSTANCES IN ONE DAY. Note its real limitation before relying
on it: the backend half parses the AST, the frontend half is a TEXT search that
cannot distinguish a read from a write. So it is strong on Python and weak
exactly where the two readers above lived.

**The rule.** A field name is an interface between two files that never import
each other, and it is checked by nobody. When adding one, add both sides in the
same commit -- and when a query returns null, establish that the field is written
somewhere before drawing any conclusion from the null.

---

## PRACTICE — 2026-09-02 — the fix changed the guard rather than the field, which is the inverse defect

A check was failing. The change made the check accept the value it was seeing.

That is the correct fix when the check was too strict, and a defect-preserving
one when the value was wrong -- and the two look identical in a diff. Both are a
one-line edit to a conditional, both make the suite green, and neither leaves any
trace of which situation it was.

**The question that separates them is never asked by the tooling: is the guard
wrong, or is the thing it is guarding wrong?** A guard loosened to admit bad data
is worse than no guard, because it now certifies the bad data.

**The rule.** When relaxing a check, say in the commit message what the check was
protecting and why that protection is no longer owed. If that sentence cannot be
written, the guard was probably right and the value is the bug. Where the guard
is loosened for a real reason, the value that provoked it should get its own
assertion so the newly-admitted case is pinned rather than merely tolerated.

**The corollary for absence-ceilings and census tests**, which came up three times
in one night: raising a ceiling to accommodate new code is the same move. The
honest version is to make the new code satisfy what the guard is asking for --
classified, anchored assertions -- rather than to move the number. Twice the
workers did the honest version and said so; recording it here so it stays the
default.

---

## OPEN — 2026-09-02 — the superintendent log that does not exist, and what has been RULED OUT

A site superintendent signed and filed a log. The query returns []. The document
is not in the collection.

**What was ruled out, with the reason, because the ruling-out is the durable part:**

The endpoint works. It was exercised directly and writes the row.

**The null-body path cannot be what happened.** `create_logbook` ends by reading
back the document it just inserted and returning `serialize_id(created)`. If that
read-back misses, the response is a 200 whose body is `null` -- but the INSERT
already happened. That path produces a confusing client and a present document,
which is the opposite of the symptom. It is a real defect and it is not this one.

**The Railway log does not reach back far enough** to say whether the POST
arrived (see the `--since` entry above). That is an absence of evidence and was
very nearly reported as evidence of absence.

**So the mechanism is still unknown.** Recorded because the temptation, at the
end of a long night, is to accept the most available explanation -- and the most
available explanation here was disproved by reading what the code does after the
insert.

**Two fixes shipped that make it survivable regardless of cause**, which is the
right response to an unexplained loss of a statutory record: the editor now keeps
the CP's work on screen and refuses to claim a filing that did not happen, and a
create that returns no id is reported as a failure rather than toasted as
success. Neither is a diagnosis. The cause is still open.

Do not close this on the strength of the fixes.

---

## PRACTICE — 2026-09-01 — a sweep whose keep-set could see one of the two shapes it protected deleted the other

`sweepDocCache` deletes from a flat shared `documents/` directory. What it keeps
is whatever `collectKeepNames` can name, built by walking every `bv_doclist:` key
and reading `id` / `cache_version` off each element.

**Two screens write into that one directory and store their lists differently.**
The plans screen stores `[{id, cache_version, ...}]`, exactly the expected shape.
`app/site/logbooks.jsx` stored `[{date, logs:[...]}]`, where no top-level element
carries an id at all -- while writing real PDFs that matched the sweep pattern.

An element with no id was SKIPPED, silently. So the logbook PDFs were named by
nothing in the keep-set and every sweep deleted them. And the sweep fires from
the PLANS screen on every successful list load, so **opening Plans deleted the
offline logbooks.** The day-report half was worse: its id is invented at render
time and appears in no record, so nothing could ever have named it.

The keep-set ran, returned a well-formed answer, and could not see half its
subject -- reporting "nothing to keep", which at the call site is
indistinguishable from "genuinely orphaned". A deletion pass cannot tell those
apart and has no reason to ask.

Its own test could not catch it: every fixture it built was plans-shaped. **A
test that constructs only the shape the code already handles proves the code
handles that shape.**

**The rule, for anything that deletes by exclusion.** A keep-set is a claim about
EVERY writer into the swept space, not about the caller. Enumerate the writers --
grep for what puts files there, not for what reads them -- and assert one fixture
per writer. Where an identity is invented at render time it cannot be recovered
by a reader, so the writer must declare it.

**The cheap tell:** a `continue` on malformed input inside a keep-set builder is
where a whole class of files goes to be deleted. Count what it skips and log it.

---

## PRACTICE — 2026-09-01 — file ownership has to follow the change, not the ticket

Six workers ran in parallel, each in its own worktree, partitioned by INTENT: one
owned the token leak, one the viewer, one offline plans. The boundaries came from
the defect list.

**The work did not respect them, because the defects did not.** Fixing the token
leak required changing how Android resolves a document, which meant editing the
three screens that open one -- files another worker owned -- and a viewer a third
owned. Three conflicts.

They resolved cleanly and both sides agreed on intent. **That was luck.** A worker
reasoning from a different premise about the same line would have produced a
merge that applied cleanly and was wrong, which is the failure mode this file has
already recorded more than once.

**The rule.** Partition by FILE, decided after reading the code, not by ticket. If
two items touch one file they are one work item or they are strictly ordered --
never two parallel workers. The question before splitting is not "are these
different defects" but "can these be changed without meeting", and that is
answered by reading, not by the list.

Where an overlap is found mid-flight, stop the second worker rather than merge two
independent readings of one line afterwards. **And where a clean merge does cross a
shared file, READ the resolved file** -- three times in one night a merge applied
with no markers and was wrong or misplaced, each caught by looking rather than by
the absence of conflict.

---

## OPEN — 2026-09-01 — a BLANK `cp_name` prints on the same filed PDFs, and nothing prevents it

Deliberately left open by #353, which gated the OTHER half. Recorded so the
narrowing reads as a decision rather than as the part somebody forgot.

**What #353 closed:** a `cp_name` that is PRESENT must look like a name. `"2"`
had reached 25 signed documents and printed as the named Competent Person.

**What it did not close:** an ABSENT `cp_name` is still accepted at submit, and
prints as a blank Competent Person on exactly the same documents — the
per-logbook DOB PDF, the combined daily report, the emailed compliance report,
and the CS-attribution fallback on the superintendent log. A blank signer on a
filed §3301-02 record is no more usable than `"2"`; it is only quieter.

**Why it was not closed in the same change, and this is the whole of the
reasoning:** refusing absence at submit would refuse a CP standing on a site
trying to file a draft that was created before the gate existed. The two
defects look alike and behave differently — one refuses a bad value nobody
meant to enter, the other refuses a man at the moment he is trying to sign.
Riding the second in on the first's coat-tails would have shipped a field
refusal nobody decided to ship.

**What has to be known before closing it:**

  * How many drafts currently hold no `cp_name`. `db.logbooks.count_documents(
    {"status": {"$ne": "submitted"}, "is_deleted": {"$ne": True},
     "$or": [{"cp_name": None}, {"cp_name": ""}]})` — if that is near zero the
    refusal costs nothing and can simply be turned on.
  * Whether the client can always supply one. `SignaturePad` requires
    `signerName?.trim()` before it will confirm, and embeds it as
    `cp_signature.signerName` — so on any signature captured by the pad the
    name exists somewhere on the request even when `cp_name` is absent. The
    cheapest honest fix may be to FALL BACK to that rather than to refuse:
    the man typed his name, the field just did not carry it.
  * Whether any server-side path files without a pad signature at all — the
    offline drain replays `cp_signature` + `status: "submitted"` from a stored
    draft, so it inherits whatever the draft holds.

**Related, and the better long fix:** the C1 proposal to stamp server-set
`signed_by` / `signed_by_name` at the moment the signature is applied. A
hand-typed field is evidence of intent; it should never be the only thing
naming the signer on a filed document. With that in place, `cp_name` becomes
the printed attestation beside an authenticated name rather than the record's
sole identity claim, and a blank one stops being load-bearing.

---

## PRACTICE — 2026-09-01 — three tests pinned a literal while their own docstrings named the invariant

All three failed on a CORRECT change in #353, and each was repaired to assert
what it already claimed to assert. Recorded because the family is the same one
this file keeps returning to.

| test | what its docstring claimed | what it actually asserted |
|---|---|---|
| `TheDuplicateStaysAndSaysWhy` | the duplicated gate stays because it produces the SPECIFIC message | the exact string `current_user.get("role") == "cp"` |
| `requiredLogbooksWiring` | ownership is read off the server's answer, NEVER a client-side list of types | the whole `const mine = ...` line, verbatim |
| `submitSignatureGate` | "server.py returns exactly the 4 submit codes" | five codes, with the count typed into the label |

In every case the claimed invariant SURVIVED the change and the literal did
not. The specific message was untouched; no list of log types appeared; the
codes were still exhaustively enumerated. What moved was the spelling.

**A CHECK THAT PASSES FOR THE WRONG REASON IS INDISTINGUISHABLE FROM ONE THAT
PASSES FOR THE RIGHT ONE UNTIL THE CODE MOVES.** That is why all three surfaced
in the same hour: nothing had touched those lines since they were written, so
nothing had ever asked whether the assertion and the sentence above it agreed.

Same family as the `sort()` that did nothing and still satisfied a determinism
assertion, the `--include=*.js` sweep blind to 96 `.cjs` files, the local glob
that ran 85 of CI's 93, and the CORS middleware that was correct in every
particular and could not reach a 429. In each, the thing that failed was not
the logic but its GRIP on the subject.

**The rule, and it is cheap:** when an assertion's message states a principle,
assert the principle. `assertIn("ROLES_SCOPED_TO_ASSIGNED_PROJECTS", body)`
survives a rename that `assertIn('role == "cp"', body)` does not, and it is the
thing the docstring was talking about. A literal is the right assertion only
when the literal IS the requirement — a wire-format string, a machine code, a
published label that must never be re-spelled.

**The tell, in review:** if the assertion would still pass after someone
deleted the behaviour and left the spelling, or fail after someone preserved
the behaviour and changed the spelling, it is pinned to the wrong thing.

---

## PRACTICE — 2026-08-28 — a correctly configured control that could not reach the responses that needed it

Fixed in #341 (`da74996`). Recorded because the SHAPE is the point, and because
it is the third instance this week of one family: a check that runs, is
correct, and cannot act on the case that matters.

### The control was right in every particular

`CORSMiddleware` had the right origins — both hosts we own, exact-match, no
wildcard and no `allow_origin_regex` — the right methods, the right
credentials flag. Nothing about its configuration was wrong, then or now.

It was registered BEFORE the rate limiter. Starlette's `add_middleware`
PREPENDS, so the last registration is the outermost layer: registering CORS
first put the limiter OUTSIDE it. A limiter that short-circuits returns its own
response without passing back through CORS, so a 429 left the server with **no
`Access-Control-Allow-Origin` header at all** — and a 429 to a preflight is
precisely the response most in need of one.

The browser cannot tell that from a misconfiguration. It says:

    Response to preflight request doesn't pass access control check:
    It does not have HTTP ok status.

which sends you to audit the origin list, where every entry is present and
correct, and where a hand-run preflight returns 200 with the right header —
because one cold request is never rate limited. **Every direct test of the
control passed. The control was never reached.**

Same family as the double whose `sort()` did nothing and still satisfied a
determinism assertion, and the `--include=*.js` sweep blind to 96 `.cjs` files,
and the local test glob that ran 85 of CI's 93. In each, the thing that failed
was not the logic but its REACH, and reach is what a direct test of the logic
cannot see. **A control that cannot match is indistinguishable, at every
observation point, from one that matches everything — until someone reads the
order.**

Hence the fix's test asserts on `app.user_middleware` rather than on the
source: what broke was the ORDER of a list whose entries were all correct, and
a source-text check would have passed throughout.

### THE ASYMMETRY THAT HID IT — a shared limit is not a shared budget

The cap was one rule: `("ANY", "/api/admin/{rest:path}", "60/1 minute", "ip")`.
One rule, one number, applied identically to every client. It broke exactly one
of them.

A browser sends an `Origin`, so it gets a **preflight** — and `evaluate()`
counted `OPTIONS`. So the web spent **two requests of the allowance per call**.
The native app sends no `Origin`, gets no preflight, spends **one**, and has no
CORS layer to be bypassed: a 429 there arrives as a 429 and is handled.

Same limit, half the budget, and a refusal that surfaces as a different error
class. An admin page fanning out several calls at once crossed 60/min on the
laptop while the phone stayed comfortably inside it — which is why this read as
"web is broken" rather than "we are rate limiting ourselves", and why it was
invisible to the client the team uses most.

**The general rule: a per-identity limit is only equal if every client spends
it at the same rate.** Before setting a cap, ask what one user ACTION costs on
each surface. Preflights, retries, polling and cache-miss fan-out all mean two
clients under one number are not under one budget.

### AND THE SAME SHAPE ONE LEVEL UP, IN HOW THIS WAS DIAGNOSED

Recorded at the operator's instruction, because it is the same failure in the
conversation rather than in the code.

An uncertain finding was reported with its uncertainty attached — a suspected
mechanism, explicitly flagged as unconfirmed. It was then restated back as
settled, and the next several questions PRESUMED it: a regex that does not
exist in this codebase, a commit SHA that is not in this repository, and a
"has this ever worked" question built on both. The correction was made, flagged
again, and passed back a second time as accepted fact.

**A correction that is issued and not read is worse than one never made,
because repetition confers authority.** Each restatement made the false premise
sound more established, and the questions built on it were well-formed, which
made them harder to refuse than the original claim had been.

The countermeasure is cheap and it is the same one the code uses: **check the
claim against the artifact, not against the last person who said it.** Three
commands settled all of it — `grep allow_origin_regex`, `git cat-file -t
<sha>`, `git log -S'ALLOWED_ORIGINS'`. Any of them, run once, at any point,
would have stopped the framing before it acquired weight.

Both sides of that exchange are worth recording. The finding was flagged as
uncertain and it was still restated as fact; and the restatement was accepted
far enough to shape three rounds of questions before it was checked.

---

## PARKED — 2026-08-28 — PR #90's worker_project_trades backfill: do not run it as written, and find out whether it already ran

`chore/production-mongosh-scripts` (PR #90) has been open since 2026-08-08 and
is ~292 commits behind. Its three files exist NOWHERE on main:

    backend/scripts/WORKER_PROJECT_TRADES_BACKFILL.md
    backend/scripts/audit_company_values.js
    backend/scripts/backfill_worker_project_trades.js

Its own runbook gives the reason it should not have stayed on a branch: "a
script that runs against production must outlive the session that wrote it."

PARKED, not closed. Two separate questions, and the second matters more:
whether the script is safe to run, and whether it ALREADY RAN from a copy that
exists nowhere in this repository.

### What it writes

Collection `worker_project_trades`, keyed `(worker_id, project_id)` — the same
unique index the live path uses. Fields `worker_id`, `project_id`, `trade`,
`company`, `updated_at`: exactly the set `_store_worker_project_trade` writes,
so the row SHAPE is still correct. Source is an aggregation over `checkins`
grouped per worker+project, `$setOnInsert` + `upsert`, `EXECUTE = false` by
default.

### THE DEFECT — the sentinel is filtered on trade and not on company

The aggregation excludes `worker_trade` in `[null, '', 'UNASSIGNED']`. The
company handling is only:

    const companies = (r.companies || []).filter(c => String(c || '').trim() !== '');
    const company = companies.length === 1 ? companies[0] : '';

A blank filter, and nothing else. But `register_and_checkin` stamps the two
INDEPENDENTLY (server.py, the `no_roster` and `not_listed` branches):

    trade   = trade   or "UNASSIGNED"
    company = company or "UNASSIGNED"

so a worker who picks a real trade while his sub is off the roster produces a
row with a valid `worker_trade` and `worker_company: "UNASSIGNED"`. The script
would write the literal string "UNASSIGNED" into `worker_project_trades.company`
as though it were a company name.

**This is not drift.** `git log -S` puts the company stamp at `d69e07c`,
2026-07-29 — TEN DAYS BEFORE the script was written on 2026-08-08. It was wrong
on day one. It has simply never been run, which is the only reason it has not
already cost anything.

### The blast radius grew while it sat on the branch

When the script was authored, `worker_project_trades` was read at the gate.
Since then:

  * **#246** (`fe6805c`, 2026-08-27) — the daily-jobsite roster resolves the
    pairing when the frozen check-in recorded none.
  * **#248** (`e731d13`, 2026-08-27) — five check-in read paths carried
    `s["worker_trade"] or worker.get("trade")`; FOUR of them now resolve the
    pairing instead. Named in that commit: `GET /checkins`, and the `flagged`,
    plain, `active` and `today` project variants.

So rows this script INFERS from history are now rendered as the trade on the
roster and across those read paths, for check-ins that recorded nothing
themselves. That may be exactly what the backfill is for — but it is a much
larger surface than the contract it was written against, and it should be
re-reviewed against the current one rather than the 2026-08-08 one.

### DID IT ALREADY RUN — four read-only queries

**READ THE LIMITATION FIRST.** `_store_worker_project_trade` uses `$set`, not
`$setOnInsert`. So ANY real check-in after a backfill overwrites `trade`,
`company` and `updated_at` on that row and erases every signature below.

**A zero across all four means no SURVIVING row carries the mark. It does not
mean the script never ran.** Pairs that were backfilled and have since seen a
real check-in are invisible to all of it.

0. Denominator:

       db.worker_project_trades.countDocuments({})

1. **The signature.** The script writes `updated_at: r.last_seen` — a `$max` of
   `check_in_time`, copied verbatim. The live writer calls
   `datetime.now(timezone.utc)` INSIDE `_store_worker_project_trade`, separately
   from the `now` that stamps `check_in_time`, so a live row's `updated_at` is
   always some milliseconds later. Exact equality is unreachable from the live
   path. Uses the `checkin_dedup_compound` index.

       var sig = []
       db.worker_project_trades.find({},{worker_id:1,project_id:1,trade:1,company:1,updated_at:1}).forEach(r => { if (db.checkins.countDocuments({worker_id:r.worker_id, project_id:r.project_id, check_in_time:r.updated_at},{limit:1})) sig.push(r) })
       sig.length
       printjson(sig.slice(0,20))

2. **Wider net — rows older than the collection itself.** `bd66de9`
   (2026-08-07 12:17:52Z) introduced `worker_project_trades`; nothing live can
   predate it. Catches backfilled pairs whose millisecond did not line up.

       db.worker_project_trades.countDocuments({updated_at:{$lt:ISODate("2026-08-07T12:17:52Z")}})
       db.worker_project_trades.find({updated_at:{$lt:ISODate("2026-08-07T12:17:52Z")}}).limit(20).toArray()

3. **Strongest positive — the sentinel as a company.** `_store_worker_project_trade`
   refuses `UNASSIGNED` for trade and stores blanks as `""`. A pairing row
   carrying it as a COMPANY is not reachable from the live path at all.

       db.worker_project_trades.countDocuments({company:"UNASSIGNED"})
       db.worker_project_trades.find({company:"UNASSIGNED"}).limit(20).toArray()

4. **Blank company where the source check-ins disagree** — replicates the
   script's own ambiguity rule verbatim (filter blanks only; more than one
   survivor stores `""`).

       var amb = []
       db.worker_project_trades.find({company:""},{worker_id:1,project_id:1,trade:1,updated_at:1}).forEach(r => { var c = db.checkins.distinct("worker_company",{worker_id:r.worker_id, project_id:r.project_id, is_deleted:{$ne:true}}).filter(x => String(x||"").trim() !== ""); if (c.length > 1) amb.push({row:r, companies:c}) })
       amb.length
       printjson(amb.slice(0,20))

If any of these come back non-zero, the question is no longer whether to fix
the script — it is what those rows are currently driving on the roster and the
four #248 read paths.

### If it is ever revived

**The sentinel filter goes through `_recorded_trade`, not a reimplementation.**
That helper is the single place that knows `UNASSIGNED` is not a real value,
and its own docstring states the rule: "Anything that reads a frozen trade to
decide whether one exists has to ask through here, or the sentinel reads as a
real answer." The script predates the helper and asks nowhere — a mongosh
script cannot import Python, so reviving this means either porting the rule
with a comment naming `_recorded_trade` as its source, or moving the backfill
into Python where the helper is callable. The second is better; a second
implementation of the sentinel rule is exactly the drift this codebase keeps
closing.

### The audit script is READ-ONLY and safe, but would misframe two things

`audit_company_values.js` writes nothing. It would still mislead:

  * It prints `workers.company` beside `checkins.worker_company` as comparable
    sources. `workers.company` is now DELIBERATELY unpopulated — a worker
    document created at check-in carries neither trade nor company, "a
    worker-level copy is what bled across jobs". That row reads as data loss
    when it is the design.
  * It does not filter `is_deleted` on the collision scan or the blank count,
    while the backfill does — so it describes a different population than the
    one it exists to measure.
  * `"UNASSIGNED"` counts as a distinct company spelling in the collision
    groups, inflating the count with a sentinel.

---

## INFRA — 2026-08-28 — no Vercel preview deployment can log in, and none ever could

**THE GENERAL FINDING FIRST, because it was found through one screen and is not
about that screen.** Every login-requiring screen on every Vercel preview
deployment fails at the login call, today and for as long as previews have
existed. Nothing about the Dropbox redesign caused it; that work is only where
it was noticed, when a preview was handed to the operator to test #279 and he
got "network failed" at the login screen.

### Why

`server.py` builds an EXACT-MATCH CORS allowlist — no wildcard, no
`allow_origin_regex`:

    https://levelog.com
    https://www.levelog.com
    https://api.levelog.com
    https://mozilla.github.io      (pdf.js in the native WebView)
    http://localhost:8081
    http://localhost:19006
    http://localhost:3000

applied with `allow_origins=ALLOWED_ORIGINS, allow_credentials=True`.

A Vercel preview gets a per-branch domain — e.g.
`blueview-git-<branch>-<team>.vercel.app` — which by construction can never
appear in a list written ahead of time. Confirmed against the LIVE api, not
just the source, by preflighting `POST /api/auth/login`:

| Origin | Result |
|---|---|
| `blueview-git-dropbox-one-screen-…vercel.app` | 400, no `access-control-allow-origin` |
| `https://levelog.com` | 200, `access-control-allow-origin: https://levelog.com` |
| `https://blueview.vercel.app` | 400 |

So the deployed `ALLOWED_ORIGINS` matches the code default, and the browser is
reporting a refused preflight as a network failure.

### The fix, and it is not a CORS exception

`frontend/vercel.json` ALREADY carries a server-side rewrite:

    /api/:path*  ->  https://api.levelog.com/api/:path*

The app never uses it, because `src/utils/api.js` sets an ABSOLUTE base:

    const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL
      || process.env.NEXT_PUBLIC_API_URL
      || 'https://api.levelog.com';

so the browser goes cross-origin directly and hits CORS. Production works by
being IN the allowlist, not by the rewrite.

**Set `EXPO_PUBLIC_API_URL` to `/` on Vercel's PREVIEW environment only.**
Requests become same-origin, Vercel proxies them server-side, and no preflight
is ever issued. No backend change. No allowlist edit. Production untouched —
its own environment keeps the absolute URL, and the env var is scoped per
environment in Vercel.

It is worth being clear about what this is NOT, because it was nearly rejected
as one: it is not a CORS exception carved for a single PR. It is a settings
change that makes every future preview deployment testable, permanently, and it
touches no code the app ships.

The rejected alternative, for the record: adding preview domains to
`ALLOWED_ORIGINS`. The env var REPLACES the whole default list, so adding one
origin means restating all seven correctly or breaking production CORS; preview
domains are per-branch so exact-match can never cover them; covering them needs
`allow_origin_regex`, a `server.py` change; and with `allow_credentials=True` a
`*.vercel.app` pattern would let ANY Vercel deployment call the API with
credentials.

### Unverified, and why this is a follow-up rather than a fix

Three things were not established, and two of them need someone with the
Vercel dashboard:

1. **Whether `expo export` inlines the variable at build time.** `EXPO_PUBLIC_*`
   is documented as build-time-inlined and Vercel injects env vars at build, so
   it should — but "should" is what the runtimeVersion fingerprint also did.
2. **`api.js:1062` and `1077` build ABSOLUTE asset URLs from the same
   constant** — `${API_BASE_URL}/api/reports/logbook-photo/...` and
   `${API_BASE_URL}/api/signatures/...`. With the base set to `/` these become
   relative. They should still resolve through the same rewrite, but they are a
   second consumer of a constant being repurposed, and they were not tested.
3. **The preview sits behind Vercel SSO.** `GET /api/health` on the preview
   domain returns 302 to `vercel.com/sso-api`, so the proxy path cannot be
   exercised from a terminal at all. A logged-in browser is required, which
   means verifying this needs the operator rather than a script.

### What happened instead

#279 was merged on CI and tested on production. That was the right call under
time pressure and is not what this entry is arguing against. This is the piece
of work that stops the next branch facing the same choice.

---

## PRACTICE — 2026-08-28 — two checks that ran, passed, and could not see the thing they were for

Same family as the `.cjs` enumeration entry and the CRLF-anchor entry below.
Both of these ran to completion, reported success, and were measuring nothing —
or nearly nothing — of what they were supposed to measure. Recorded together
because they are one failure with two surfaces, and the second is the pure form
of it.

### 1. A local test glob narrower than CI's, for the whole Dropbox redesign

The frontend suites were run locally as:

    for t in src/utils/*.test.cjs; do node "$t"; done

CI (`.github/workflows/tests.yml`) runs:

    find src app -type f \( -name '*.test.cjs' -o -name '*.test.js' \)

**85 files against 93.** The eight never run locally were:

    src/components/CpNav.clearance.test.cjs
    src/components/RiskScoreCircle.bandFor.test.cjs
    src/components/cameraPreview.test.cjs
    src/components/logbookStepper/stepper.test.cjs
    src/i18n/i18n.test.cjs
    src/styles/outdoorMatchesLight.test.cjs
    src/styles/theme.applyTheme.test.cjs
    src/styles/tokens.test.cjs

So "all frontend invariant suites pass" was reported four separate times, at
four separate stages of #279, on evidence that could not have contained a
failure in any of those eight. It did contain one: `tokens.test.cjs` measures
17 CP screens — `app/logbooks/*`, `login.jsx`, `settings.jsx` and
`documents.jsx` — and the redesign put a raw `#0061FF` into `documents.jsx`,
failing two assertions. CI caught it. The local runs could not have.

**Why the glob was wrong is the interesting part.** `src/utils/` holds ~85 of
the 93 and is where nearly every invariant test lives, so the narrow glob felt
exhaustive and behaved exhaustively for months of unrelated work. It only
mattered when a change touched a screen measured from `src/styles/`. A glob
that is right 91% of the time is worse than one that is obviously partial,
because nothing ever prompts you to check it.

**The fix is not a wider glob typed from memory.** It is to run what CI runs,
by reading the workflow — the two are allowed to diverge, and the workflow is
the authority.

### 2. A harness that extracted nothing, so every case passed

Verifying the destination guard added in #281, its shell body was extracted
from the workflow YAML and run against all eight combinations of
ref x branch x confirm. The extraction was:

    python - <<'PY' > /tmp/guard.sh
    ...
    io.open('/dev/stdout','w').write(g['run'])
    PY

The inner write to `/dev/stdout` fought the outer redirect and **/tmp/guard.sh
was written as 0 bytes.** `bash` on an empty file exits 0. So the matrix
reported:

    ref=feature-x branch=production confirm=false -> ALLOW

for the one combination the guard exists to refuse, alongside seven other
ALLOWs, and the table looked like a uniform, unremarkable pass. Re-run with a
working extraction, that row is the only REFUSE.

This is the cleaner specimen of the two: not a check that saw 91% of its
subject, but a check that saw **none** of it and could not report a failure
under any input.

### THE RULE

**A harness that produces no output is a failing harness, not a passing test.**

An empty script exits 0. An empty match list satisfies every `all()`. An empty
file read yields no assertions to break. In each case the absence of the
subject is indistinguishable, at the exit code, from the subject being fine —
and it is always the quieter of the two, so it never prompts a second look.

Concretely, and in this order:

1. **Assert the extraction is non-empty before running it.** Byte count, line
   count, or a required substring — `assert "EAS_BRANCH" in body and "exit 1"
   in body` would have failed the harness above instead of passing eight cases.
   The `tokens.test.cjs` scanner already does this deliberately: it pins
   `FILES.length === 17` and floors its literal counts, with the comment "a
   regex that silently stops matching would turn this file green while
   measuring nothing." That guard is the pattern; it was simply absent from
   the ad-hoc harnesses.
2. **Include a negative control where the harness is doing real work** — one
   input that MUST fail. Eight ALLOWs with no REFUSE among them was the tell,
   and it was visible in the output at the time.
3. **Read the authority rather than restating it.** CI's glob, not a glob typed
   from memory; the workflow's own `run:` body, not a paraphrase of it.

None of this needs new tooling. All three were available and none were applied.

---

## PRACTICE — 2026-08-28 — a CRLF anchor made a mutation not apply, and the negative control reported a pass

**The mirror of the line-ending entry below**, and worth recording separately
because it fails in the opposite direction. There, a source EXTRACTION anchored
on a bare newline read nothing and five assertions were skipped. Here, a source
MUTATION anchored on a bare newline wrote nothing and a negative control passed.
Both times, the edit that did not land looked exactly like an edit that landed
and was fine.

Verifying the registry-count assertion added in #271, four scenarios broke the
guard on purpose to prove it could fail. The fourth registered a thirteenth
logbook type with no tab and no render branch, by replacing the tail of
`LOGBOOK_TYPE_REGISTRY` in `backend/server.py`:

    const anchor = '        "activated_by": "cp",\n    },\n]';
    return s.slice(0, at) + added + s.slice(at + anchor.length);

`server.py` is CRLF. `indexOf` returned `-1`, the guard returned the input
unchanged, the harness wrote the file back byte-identical, and the suite then
ran against a **completely unmodified tree**:

    ### a 13th type is registered with no tab and no branch
      (nothing failed — THE GUARD IS BLIND)
      94 passed / 0 failed

The available reading was wrong in the most useful-looking way: *the count
assertion does not catch a thirteenth type*. It says the opposite of the truth,
and it says it in the voice of a completed check.

It was caught only because the other three scenarios DID fail and a silent
fourth was implausible beside them. Nothing in the output distinguished
"the mutation applied and the guard missed it" from "the mutation never
applied". **A negative control that cannot verify its own mutation is not a
negative control** — it is a second copy of the green run.

### The rule

A mutation whose replacement is a no-op is a FAILING scenario, never a passing
one. Assert it before writing:

    if (next === backup) throw new Error('mutation was a no-op — the scenario proves nothing');

That is the mutation-side twin of the rule below — *a failed extraction is a
FAILING ASSERTION, never a skipped block* — and it is the same sentence with
the read swapped for a write. With the anchors switched to explicit CRLF and
that guard in place, all four scenarios failed as intended (1, 1, 2 and 3
failures) and the restored tree returned to 94 passed, 0 failed.

### The part that is easy to draw the wrong lesson from

The regex that READ the registry in the same run was CRLF-safe, and by
accident:

    /^\s+"key": "([a-z_]+)",$/gm

JS treats `\r` as a LineTerminator, so in multiline mode `,$` matches before
`,\r\n` and this returned all twelve keys off a CRLF file without anyone
thinking about it. The exposure is in **string-literal anchors** —
`split` / `replace` / `indexOf` — not in regexes. So "we use regexes, we are
fine" is not the takeaway: the thing that read the file was safe by luck, and
the thing that wrote it was not, in the same script, in the same run.

### Scope

The harness was throwaway and is not in the repo — the defect is in the
technique, not in that file, which is why it is recorded here rather than
fixed somewhere. Any future mutation test, negative control or
codemod-style script in this repo meets the same edge: the repo normalises
line endings on checkout, so every Windows working tree is exposed, and
`server.py`, `app/site/logbooks.jsx` and the `.cjs` suites are all CRLF today.

---

## PRACTICE — 2026-08-28 — an enumeration grep that cannot see .cjs, which is where the fixtures live

Same family as the AST entry below and the receiver-group one: a search that
ran, reported a clean answer, and could not see the place the answer lived.

Enumerating every hand-copied copy of the logbook type list for #258, the sweep
was:

    grep -rn "<name>" --include=*.py --include=*.js --include=*.jsx --include=*.md

**Five copies were reported. There were six.** The sixth is
`frontend/src/utils/requiredLogbooksWiring.test.cjs` — `.cjs`, which no
`--include` in that list matches. It was never in scope, so it could not appear
as a miss; the grep returned five results and looked exhaustive.

It surfaced only because the rename in #259 gave a second, differently-worded
grep something to find, and it was found AFTER the enumeration had already been
reported as complete.

### Why this file extension in particular

`.cjs` is not a rare corner of this repo. It is **96 files**: the entire
frontend test suite (`src/**/*.test.cjs`, ~92 of them) plus the four static
analysis scripts (`find-bare-jsx-text`, `find-unbound-identifiers`,
`find-unpinned-palette-keys`, `smoke-mount`). So an `--include` list built from
`*.js`/`*.jsx` sees the application and is blind to everything that checks it —
the worst possible half to be blind to when the question is "where else is this
duplicated".

Note also what made it harmless HERE and would not next time: the fixture is a
`CATALOG` standing in for `/api/logbook-types`, and the two assertions touching
labels check SHAPE (`!/^[a-z_]+$/`, "not a raw key") not text. A stale name
fails nothing. It is read by people, not by the suite.

### The rule

**Any repo-wide enumeration must include `.cjs`, or omit `--include` and filter
after.** Prefer the second — `--include` is an allow-list, and an allow-list
built from the extensions you happened to think of is exactly the shape of
error above. `git grep` with a pathspec exclusion, or a bare `grep -rn` piped
through a filter, both fail loud rather than quiet: they return the file you
did not expect instead of silently declining to look at it.

A grep whose result is a COUNT ("five copies", "three call sites", "nothing
left") is an enumeration and carries this risk. A grep looking for one known
thing does not.

---

## PRACTICE — 2026-08-28 — a check that runs and cannot see the thing it is for

Same family as the AST entry below, and a worse shape: that one was an assertion
satisfied by an EXPLANATION of what it checked. This one is an assertion that
matched nothing at all in the place that mattered, reported a clean subset, and
looked like it was working.

`test_project_response_delivers_what_the_app_reads` sweeps the frontend for
fields read off a project and requires each to be declared on `ProjectResponse`
— because that model is a hand-maintained allow-list and pydantic drops
undeclared fields silently. Its first version was:

    ([A-Za-z_$][\w$]*[Pp]roject[\w$]*)\s*\??\.\s*([a-z_][a-z0-9_]*)

The receiver group requires **one character before "project"**. So it matched
`cachedProject`, `effectiveProject` and `projectData`, and never matched the
bare `project` — which is the commonest receiver in this codebase and the exact
one in the line that caused the outage:

    project?.dropbox_folder_path ? <Sync Dropbox> : <Link Dropbox Folder>

It found `dropbox_last_synced` and `dropbox_sync` and MISSED
`dropbox_folder_path`, the field the whole investigation was about.

NOTHING FAILED. The sweep ran, matched, and produced a plausible result. It was
caught only because the count looked wrong — two of three known fields, when all
three were equally undeclared — and that noticing was luck. Had the model been
missing only `dropbox_folder_path`, the sweep would have returned empty and read
as proof that nothing was wrong.

THE RULE THAT WOULD HAVE CAUGHT IT: a pattern-based check needs an assertion
that the PATTERN matches, on the literal shape it exists to find, separate from
the sweep that uses it. The file now carries `test_the_pattern_matches_a_bare_
project_variable` and three sibling receiver shapes, which fail on the old regex
and pass on the new one.

    A sweep that finds SOME of what it is looking for is not partially
    correct. It is a green test with a blind spot, and the blind spot is
    invisible precisely where the sweep is the only thing looking.

Cost, for the record: this field's absence produced three separate
investigations — a missing sync run record, an unreachable Sync button, and a
project reported as unlinked while the database held its folder path — before
the response model was suspected at all. The failure is invisible from every
direction: the database is right, the write is right, the client code is right,
and no error appears anywhere.

---

## SCOPE — 2026-08-27 — GET /checkins cannot resolve a trade pairing, and returns a blank instead

#248 removed the `worker.get("trade")` fallback from all five check-in read
paths that carried it. Four of them -- `/checkins/project/{id}` and its
`/flagged`, `/active`, `/today` variants -- also gained pairing resolution, so a
row that froze no trade now answers with THIS project's trade.

`GET /checkins` got only the removal, deliberately.

WHY IT CANNOT RESOLVE. The endpoint is COMPANY-scoped: its query is

    query = {"is_deleted": {"$ne": True}}
    query["company_id"] = company_id

so one response spans every project the company runs. `worker_project_trades`
is keyed `(worker_id, project_id)`, and there is no single project_id to key on
-- the rows in one page belong to many. The batched helper the other four use,
`_project_trades_for(project_id, worker_ids)`, takes exactly the argument this
endpoint does not have.

WHAT IT NOW RETURNS. A blank trade on any row that froze none, where it used to
return whatever `workers.trade` held. That value was one slot for a man who
works different trades on different jobs, filled by whichever project got to
him first -- so on an admin list spanning projects it was wrong more often than
right, and wrong invisibly. A blank is visibly incomplete. That is the trade
this deliberately makes, and it is the same one #246 recorded: a trade from
another project is worse than no trade.

WHAT CLOSING IT WOULD TAKE. A per-row lookup keyed on the row's OWN project:

  * group the page's rows by `project_id` (they are already on the check-in
    row, so no extra read is needed to find them);
  * one `worker_project_trades` query per distinct project in the page, or a
    single `$or` over the (project_id, worker_id) pairs -- the pairs are known
    up front, so it stays one round trip either way;
  * index check before shipping: the existing queries are equality on both
    keys, and an `$or` over pairs wants a compound (project_id, worker_id)
    index to avoid a collection scan on a company with many projects.

NOT DONE HERE because it is a different query shape from the other four, and
because the consumer is an admin list rather than anything a CP reads at a
gate or signs. Sized as small, not urgent. The four endpoints that feed the
daily log, the picker and the site screens are the ones that had to be right,
and they are.

---

## THEMING — 2026-08-27 — the outdoor pin is asserted for half the palette and none of the native layer

Reported from the CP's device: fields on the Daily Jobsite Log render with
dark-mode chrome on a light screen. The ruling behind the pin (#210, "the
pinned ink finally has a pinned canvas under it") is that light mode must be
PIXEL-IDENTICAL to before. Two independent holes let that ruling go unenforced.

### 1. `outdoorMatchesLight` covers 12 of the 25 `outdoor` tokens

The file's own docstring is the standard: "Every value below is asserted
against its source, so that drift fails here instead of on a jobsite." Every
value is not.

    ASSERTED (12)   backgroundStart, backgroundMiddle, backgroundEnd, cardTop,
                    cardBottom, surface, surfaceSelected, text, textSoft,
                    textDim, line, lineStrong

    NOT ASSERTED    surfaceSunk, textOnSelected, accent, accentBg,
    (13)            accentBorder, warnBg, warnBorder, warn, danger, okBg,
                    okBorder, ok, scrim

`surfaceSunk` is the one that stings: it is the READ-ONLY FIELD WELL, the exact
surface the report is about, and it is a free literal with nothing tying it to
`_light`. The light theme can be retuned and thirteen of these will sit still
while the other twelve follow, which is precisely the drift the file was
written to catch.

### 2. NOTHING asserts the native appearance, and no JS pin can reach it

`frontend/app.json` has carried

    "userInterfaceStyle": "dark"

since `446f8f2` (2026-01-30), flipped from `"light"`. It is a NATIVE setting --
baked into Info.plist / the Android theme at build time -- so every surface the
OS draws inside those screens follows it regardless of the palette: the
keyboard, the caret, selection handles and the magnifier, the autofill bar.
Nothing in the app sets `keyboardAppearance`, `selectionColor` or `cursorColor`
(zero occurrences), so nothing overrides it per-field either.

`outdoorCanvasPin.test.cjs` is 39 assertions of STRUCTURE -- the prop exists,
defaults false, both wrap sites carry it, the ten editors reference no live
palette. Not one of them compares a rendered pixel to light mode, and neither
test knows `app.json` exists.

So the pin is verified to EXIST and to be WIRED; the equivalence it exists to
guarantee is checked for half the palette and none of the native layer. The JS
side is provably clean -- every colour on daily_jobsite.jsx, the stepper
styles, primitives and DateField is an `outdoor.*` token -- which is what makes
the remaining dark chrome native by elimination.

NOT A REGRESSION FROM THE PIN. The flip predates #210 by seven months. The pin
never covered native surfaces and could not have; what is missing is anything
that says so out loud.

Two fixes, and they are separable: assert the remaining 13 tokens against
`_light` (mechanical, and it is what the file already claims to do), and decide
`userInterfaceStyle` deliberately -- pinning it, or setting `keyboardAppearance`
on the pinned editors -- with a test that pins whichever is chosen. Changing it
is a NATIVE change: a rebuild, not an OTA.

---

## PRACTICE — 2026-08-27 — a line-ending change voided five assertions and the suite still said ALL PASSED

Same class as the AST entry below, and a new way in. During PR #244 a
`git reset --hard` (recovering a commit that landed on the wrong branch)
re-checked-out the tree, and git normalised line endings to CRLF. A source
extraction in `dailyJobsiteEmptyCrew.test.cjs` was anchored on a bare newline:

    SCREEN.match(/num_workers: (Number\.isFinite[\s\S]*?),
/)

Against `,\r\n` it matches nothing. The match guard was `if (m) { ... }`, so
the five assertions inside -- the ones that actually EXECUTE the shipped
`commitAddCrew` expression rather than grepping for it -- silently did not run.
Count dropped 43 -> 37 and the suite reported ALL PASSED, because a skipped
block is not a failure.

It was caught only because the count moved and I looked. Nothing about the
output said anything was missing.

    A conditional around an extraction converts "I could not read the source"
    into "there was nothing to check". Those must never be the same result.

THREE RULES, all cheap:

- Strip `\r` at the boundary when reading source for assertions -- this repo
  normalises on checkout, so any Windows working tree hits it.
- A failed extraction is a FAILING ASSERTION, never a skipped block. Assert the
  match, then run the body unconditionally with a sentinel that cannot pass.
- Prefer an assertion count the runner reports, so a silent drop is visible as
  a number even when nothing fails.

The AST entry below says an assertion satisfiable by an explanation is not
checking anything. This is the mirror: an assertion that cannot be REACHED is
not checking anything either, and it is quieter -- there is no wrong number to
notice, only an absent one.

---

## DROPBOX — 2026-08-27 — two bounds left standing by #242

Both are real, both were reported before merging, and neither is fixed. #242
made the displayed count come from the sync response instead of a mid-sync
re-read of `project_files`; these are what that did not reach.

### 1. `file_count` never paginates, so the displayed target undercounts

`sync_project_dropbox` gathers its "Quick count from Dropbox for immediate
response" with a single `list_folder` call:

    json={"path": api_path, "recursive": True}

and never checks `has_more` / `list_folder/continue`. Past roughly 500 entries
the returned `file_count` is short by everything after page one.

STORED ROWS STAY CORRECT. `_sync_project_to_r2` paginates properly, so the
files themselves all arrive; only the number the screen shows is low. That
asymmetry is why this was left: the bug is cosmetic today and becomes a
support call only on a project big enough to cross a page boundary.

Note the same missing pagination in `get_dropbox_folders`, where it is NOT
cosmetic -- a directory whose first page is all files returns an empty folder
list, and the picker renders "no folders" on a folder that plainly has some.

### 2. Pressing Sync caches a PARTIAL list for offline

`sync-dropbox` "returns immediately, runs sync in background". The plans screen
then re-reads the list -- it renders rows, so it must -- and hands the result to
`adoptFiles`, which runs `cacheDocList`. That write-through is therefore a
MID-SYNC snapshot: the saved-for-offline list can be a strict subset of what
the project holds, and it is the copy the CP gets in a cellar.

Fixing it needs a completion signal the endpoint does not offer. `sync-dropbox`
returns before the task starts writing, and nothing polls or pushes. Options
are a status endpoint, a job id, or having the task stamp a terminal marker the
client can wait on -- all of which are the redesign, not a patch.

FILE THIS WITH ITEM 12, the offline warm with no observable state. They are one
problem: `warmDocCache` is fire-and-forget, sequential, `limit: 15` with no
sort despite a docstring promising "newest first", swallowed by `.catch(() =>
{})`, and NOTHING on screen ever reports what is on disk -- `getCachedDocFile`
is never called in the render path. A partial cached list is invisible for the
same reason a failed warm is: the feature has no readable state, so the CP
cannot verify readiness while they still have signal, which is the only moment
verification is worth anything.

---

## PRACTICE — 2026-08-26 — source assertions must read the AST, never text

A test that greps source for a construct can be satisfied by an EXPLANATION of
that construct. Five instances this session, all in tests I wrote:

- `find-bare-jsx-text` matched its own comment
- `outdoorCanvasPin` matched the exemption comment
- `signatureAffirmedLang` matched the comment quoting the literal
- `str(route.dependant)` -- a repr is not an API. It passed locally and failed
  in CI on a different FastAPI build; the local pass was luck, not a weaker
  check
- the `company_id` sweep count matched the fixed helper's own docstring, which
  quotes the removed line so a reader knows what changed

THE LAST IS THE WORST SHAPE. A green test asserting a number that is silently
wrong, where the number is the entire mechanism -- the sweep exists so the
bypass count cannot drift while individual PRs each look like progress. It read
35 instead of 34 with the fix applied, and would have kept reading high as more
prose about the bug was written.

Skipping comments does not fix it: a docstring is not a comment. Neither does
slicing to a function body: the docstring is inside it.

    If an assertion can be satisfied by an explanation of the thing it checks,
    it is not checking it.

Read the AST. `ast.If.test` is a condition and prose cannot be one;
`dependant.dependencies[].call` is a dependency and a repr is not one. Where a
regex is unavoidable, prove it against a real instance AND a near-miss in the
same file, so an edit that quietly stops matching fails loudly instead of
letting the count drift to zero.

Related: the ``-written-as-0x08 defect -- an escaped byte is the same class,
a check that cannot match anything and reports success.

---

## Three process failures from 2026-08-25, and the pattern under the third

Logged at the operator's instruction. The first two are mine and are already
corrected in habit; the third is a property of the test suite and is NOT yet
fixed - the sweep below is the inventory, deliberately without changes.

### 1. Never pipe a test command into `tail` before a commit

```
python -m pytest tests/ -q | tail -2 && git commit ...
```

`&&` reads the exit code of `tail`, which is 0 whatever pytest did. That
chain pushed a commit with 16 failing subtests while appearing to guard
against exactly that.

Use `${PIPESTATUS[0]}`, or run the command bare and read its own status.

### 2. Never merge on a partial view of checks

Read every check by name. `gh pr checks --watch | tail -4` shows four lines
of eight and the missing four are not sorted to the bottom - they are
wherever the API returned them.

THREE MERGES PAST A RED CHECK THIS SESSION:

  #201  find-bare-jsx-text failed on the PR run at 00:05:57, naming all four
        bare `//` lines. Merged anyway, then PUBLISHED - the login and
        register screens rendered a source comment as visible copy on
        production devices until the rollback.
  #214  frontend suite (node) was red; `tail -4` did not include it. Left
        main red until #215.
  the 16-subtest push above, which is item 1 wearing a different hat.

### 3. Tests that pin POSITION or SYNTAX rather than BEHAVIOUR

FIVE broke this session on changes that did not touch what they guard:

  test_409_when_onboarding_completed   fixture pinned an impossible state
                                       (completed + no company)
  test_advance_step_via_patch          asserted the screen CONTAINS
                                       "skipped" - it pinned the defect
  _setup_client                        hardcoded company_id=None
  stepper/dailyJobsiteStepper          matched `<AnimatedBackground>`
                                       exactly; a new prop broke both
  test_submit_no_content_gate          `fn[:5000]` / `fn[:6000]`
  submitSignatureGate.test.cjs         `indexOf(...) + 6000` - this one
                                       turned main red

THE WINDOWED-SLICE VARIANT IS THE WORST OF THEM, because the number is
invisible as a dependency: it equals the distance to the landmark at the
moment it was written, so any insertion above silently moves the target out
and the failure names something unrelated to the change.

THE FIX, WHERE IT HAS BEEN APPLIED, is to slice at a STRUCTURAL boundary -
the next top-level `def`, or the next sibling key - rather than a byte count.
See `_fn_body()` in test_submit_no_content_gate.py and the equivalent in
submitSignatureGate.test.cjs. Both keep the identical assertion.

#### Sweep: 31 windowed source slices across 17 files, unfixed

Response-body truncation in assertion MESSAGES (`r.text[:300]`) is excluded -
that is formatting and is fine. These are windows an assertion then searches:

```
backend/tests/test_company_less_tenancy.py            :137 :156 :180  (mine)
backend/tests/test_report_six_defects.py              :229 :358 :396 :437 :623 :641
backend/tests/test_worker_response_model.py           :85 :120 :138
backend/tests/test_eastern_date_helper.py             :117 :123 :135
backend/tests/test_startup_seed_guard.py              :94 :99
backend/tests/test_email_consolidation.py             :171 :193
backend/tests/test_activity_chips_endpoint.py         :408
backend/tests/test_logbook_write_guards.py            :311
backend/tests/test_onboarding_skip_trap.py            :193  (mine)
backend/tests/test_pending_deletion_and_purge_scope.py :199
backend/tests/test_report_print_width.py              :81
backend/tests/test_workers_tenant_isolation.py        :425  (mine)
frontend/src/utils/authScreenFold.test.cjs            :127  (mine)
frontend/src/utils/dailyJobsiteModel.test.cjs         :825
frontend/src/utils/onboardingSkipTrap.test.cjs        :99 :118  (mine)
frontend/src/utils/rowSaveState.test.cjs              :149
```

THREE OF THE 31 ARE NOT THE DEFECT and should be left alone:

  dailyJobsiteStepper.test.cjs:533-534  computes the block end by SEARCHING
                                        for the next sibling key, then
                                        slices. Structural already.
  test_worker_response_model.py:120     anchored to a landmark
                                        (`fn.index("return NfcTagInfo")`)
                                        with padding - partly structural.
  find-bare-jsx-text.cjs:134            truncates a DISPLAY snippet, not an
                                        assertion window. Not a test pin.

Six of the remaining 28 are mine, from this session. Marked above so the
inventory is not read as someone else's debt.

---

## ENHANCEMENT (FUTURE, LOW) — 2026-08-01 — optional per-worker signature on pre-shift sign-in

**Not a compliance gap — rigor only.** The pre-shift sign-in is compliant as-is:
each worker is documented by an SST-card-backed, timestamped NFC/QR check-in
(credentialed presence evidence, harder to forge than a handwritten mark) and the
Competent Person affirms the attendance record with an **affirmed CP signature**.
The OSHA/DOB documentation baseline (attendance record + responsible-person
certification) is met without a per-worker wet signature — confirmed by the
safety lead against the site-safety plan / GC contract (2026-08-01).

Optional rigor to consider later: capture a per-worker acknowledgment signature
**during the pre-shift meeting** — sign on the CP's device at meeting time
(`SignaturePad` is already imported in `app/logbooks/preshift_signin.jsx`, so it's
an **OTA-deliverable JS change**, no native build). **Timing note:** do NOT hang it
off NFC check-in — check-in is *arrival*, which precedes the meeting, so a
check-in signature wouldn't attest to the meeting. Render side (CP signature) is
already handled. Low priority.

## COMPLIANCE (MEDIUM) — 2026-08-01 — evaluate a worker acknowledgment signature on subcontractor orientation

**Distinct from pre-shift, and a real case — not optional rigor.** Orientation is
the **first-time worker attesting they RECEIVED and understood** site-specific
orientation (the worker's own sign-off), whereas pre-shift is the CP attesting to
attendance. Site-safety plans / GC contracts commonly expect a per-worker
orientation acknowledgment.

Current state: orientation already **captures + renders** the one-time
first-registration signature (with the honest UNSIGNED marker on manual rows).
**Open question for design:** does that first-registration signature count as the
orientation acknowledgment, or does a distinct "I was oriented on THIS project"
sign-off need to be captured?

Do NOT build yet — needs the capture-flow design: **where/how** the worker signs
(the orientation moment, on whose device), how it binds to the per-worker
orientation record (`data.worker_id` — see the name-match/worker_id followup), and
delivery (`SignaturePad` is already native/OTA-able). Scope deliberately when
prioritized. Separate from — and higher priority than — the pre-shift enhancement
above.

## CLEANUP (MEDIUM) — 2026-08-01 — dormant WatermelonDB still runs a background sync every launch

WatermelonDB is wired in but effectively abandoned as a data path: **no screen
reads or writes its local store.** The only offline wrapper built on it,
`src/utils/offlineapi.js` (imports `database` + `Q`), is imported by no screen;
the check-in UI calls `checkinsAPI` directly (`useCheckIns.js`,
`app/checkin/index.jsx`, `app/nfc/index.jsx`) with no local store. Logbook
offline (Phase A, 2026-08-01) deliberately uses AsyncStorage
(`src/utils/logbookDrafts.js`), not WatermelonDB.

**But it is not inert:** `DatabaseContext` still calls `setupAutoSync()` and
`syncDatabase()` on every launch (`src/context/DatabaseContext.jsx:30/72`), and
`offlineQueue.js:130` calls `syncDatabase()` after processing — so a WatermelonDB
`synchronize()` (pull/push to `/api/sync/*`) runs at startup doing no useful
work. This is the mechanism that historically caused the sync delays/collisions,
now pure dead-weight risk (startup cost + a chance of being accidentally
re-relied-on).

**Deferred, not done here** (per instruction — Phase A must not touch it). A
separate, dev-build-verified cleanup should: remove the `setupAutoSync()` /
`syncDatabase()` calls (DatabaseContext + offlineQueue), delete `offlineapi.js`,
and — once nothing references them — the WatermelonDB models/schema/migrations/
adapter (`src/database/*`) and the `@nozbe/watermelondb` deps. Verify check-ins
(direct API) and logbook drafts (AsyncStorage) are unaffected before/after.

---

## SECURITY (HIGH) — 2026-08-01 — NFC check-in proves a URL load, not physical presence

The worker check-in NFC tags encode a **STATIC** URL
(`/checkin/{project_id}/{tag_id}`). `tag_id` is a client-supplied value stored
verbatim in `nfc_tags` (`add_nfc_tag_to_project`, server.py ~9022) and validated
at POST only as `{tag_id, project_id, status:"active"}` — **no per-tap nonce, no
signature, no expiry, no rotation**. The two primary public creation endpoints,
`POST /api/checkin/register-and-checkin` (server.py:9298) and
`POST /api/checkin/submit` (server.py:9869), take no `request` object, so they
capture **no ip/user_agent/device** and have **no rate-limiting** (the
`checkin_rate_limiter`, server.py:574, is wired only to `/checkin` and
`upload-osha`). Same-worker+project+EST-day **dedupe** exists on every path; that
is the only abuse control.

**Impact:** anyone who ever holds the tag URL — from tapping the physical tag, a
screenshot/QR photo, browser history, or a shared link — can mint a real,
current-timestamped check-in for any roster-valid worker, from any device,
anywhere, unthrottled, with no origin recorded on the row. Confirmed live: a
false "on site" record for Mauro E Zumba at 588 Boyland (2026-08-01 12:24) was
created by opening the tag URL from a **desktop browser** during testing — no one
on site, no tag tapped. For a compliance product, "on site" today attests only
that the tag URL was loaded, not that a person was present.

**Fix BEFORE GCs rely on check-in data as presence evidence.** Ranked options
(effectiveness vs effort):
1. **FLOOR (very low effort):** add `request` + `checkin_rate_limiter` to
   register-and-checkin and submit; persist `ip`/`user_agent`/`device_info` on
   the check-in row. Ends silent, unattributable minting; enables forensics.
2. **Server-issued short-lived per-tap nonce (medium):** the tag GET mints a
   single-use, TTL-bound token bound to tag+project; POST must present it. Kills
   replay/bookmark reuse — the bare URL stops working. Best effectiveness-for-
   effort; the real presence fix.
3. **Signed tag payload / HMAC (medium):** stops URL forgery/guessing, but a
   static signed URL is still replayable unless paired with NFC SUN/SDM rotating
   counters (capable tags required).
4. **Geofence device GPS vs site (med-high):** rejects off-site check-ins;
   spoofable and coarse — a secondary signal.
5. **Device/selfie gate (high identity, high effort):** `selfie_image` is
   already captured (spot-check only) and could be surfaced for CP review cheaply
   before full liveness.

Recommended: ship #1 now as the floor, then #2 as the presence proof; keep #4/#5
as layered signals.

## DATA — 2026-07-29 — legacy subcontractor_orientation rows without `data.worker_id`

`POST /api/logbooks` now keys the upsert on `data.worker_id` for
`log_type == "subcontractor_orientation"` (per-worker, not the daily
`(project_id, log_type, date)` singleton) — the fix that stops a UI-created
orientation from `$set`-clobbering a DIFFERENT worker's check-in-created row.

Residual: any orientation row whose `data.worker_id` is **absent or null** —
legacy rows written before the check-in path stamped that field, or rows from
a client that never sent one — cannot be matched by a subsequent UI create for
that worker. The create mints a fresh `srv_<uuid>` id and inserts a SECOND row
rather than updating the legacy one. This is **harmless** (no clobber, no loss),
but produces a duplicate per affected worker.

Not shipped, because it needs production data to scope: a one-time backfill
could stamp `data.worker_id` onto legacy orientation rows (from the linked
check-in, or a synthesised `legacy_<uuid>` where no link exists), OR the
duplicate can be accepted as cosmetic. Decide against the real row count first —
run `db.logbooks.count_documents({"log_type":"subcontractor_orientation", "data.worker_id": {"$in": [None]}})`
plus the absent-field variant before choosing.

## RESILIENCE — 2026-07-29 — `data?.items ?? []` masks a malformed response as empty

The three unwrap clients shipped in `2b157f6` (`checkinsAPI.getByDate`,
`dailyLogsAPI.getByProject`, `logbooksAPI.getByProject`) return
`Array.isArray(data) ? data : (data?.items ?? [])`. That correctly handles the
`{items,...}` envelope and a bare array — but a **malformed or error-shaped**
body (`{error: ...}`, `null`, an HTML 500 page that slipped past the interceptor)
also collapses to `[]`, indistinguishable from a legitimately empty result. The
consumer renders an empty screen instead of surfacing the failure — the same
failure-masking class as the original wrapper bug, one layer down.

Deferred deliberately: the unwrap's job here was to stop the silent-empty and
the content loss, and it does. Hardening is a separate concern — distinguish
"no data" from "bad data" (e.g. treat a non-array, non-`{items:[]}` body as an
error: log it, surface a toast, or throw) so a broken endpoint is loud rather
than silently empty. Applies to these three and to any future client that
adopts the same `?? []` shape.

---

## PHOTO PIPELINE — 2026-07-29 — deblocking has hit its deterministic floor; ARCNN evaluation CANCELLED

Applies to `backend/lib/photo_enhance.py` (shipped in `5ddc56b`).

### The floor, and why it is a floor

Heavily-compressed dark CP photos — the ones that arrive via WhatsApp from the
CP's own camera roll, already re-compressed, never touching the app's capture
path — still show flat 8x8 tiles in lifted shadow. That is as good as it gets
deterministically, and the reason is worth writing down so nobody re-opens it.

JPEG blocking has two components:

1. **Boundary discontinuity** — the visible step between adjacent blocks. This
   is SOLVED. `_deblock_jpeg` removes it, and an ordering experiment on the
   basement photo (lift/deblock/denoise permuted four ways, everything else
   fixed) drove the blockiness metric from 1.278 down to 0.825 **with no
   visible difference between any of the four crops at 2x**. Below ~1.3 the
   metric is measuring boundary steps against ordinary image noise and has
   decoupled from what the image looks like. Do not tune against it further.

2. **Flat interiors** — the tiles themselves carry no texture. This is NOT an
   artefact that can be filtered out: JPEG quantisation zeroed the AC
   coefficients for those blocks. The information is destroyed, not degraded.
   Recovering it means SYNTHESISING plausible texture.

### ARCNN / FBCNN evaluation: cancelled, deliberately

Considered and rejected on 2026-07-29. The proposed success condition was
"visibly fills the flat block interiors" — which is synthesis by definition,
and this pipeline prohibits it: *"No generative/AI upscaling. Deterministic
image ops only; do not invent detail that wasn't in the frame."*

That constraint is not stylistic here. These photos are a DOB compliance
record. Invented texture on a concrete wall in a daily log is a defect with
legal weight, not a cosmetic nicety — the photo is evidence of site conditions
on a date, and a model's guess about what the wall looked like is not evidence.

Cost data gathered before cancelling, so it need not be re-derived:
  * no canonical ARCNN ONNX exists; weights ship as `.pth`
  * conversion would need PyTorch (~2.5 GB) as a one-time step
  * ARCNN weights are tiny (~100-200 KB, four conv layers); FBCNN ~70 MB
  * `cv2` itself is 112 MB installed (measured), and was already rejected for
    CLAHE on the same grounds
  * third-party ONNX mirrors exist but are unvetted; not used

### IF a presentation-grade derivative is ever wanted

It does NOT belong as a pipeline step. It belongs as a SEPARATE variant
alongside `enhanced` and `thumb` — generated on demand, stored under its own
R2 key, and CLEARLY LABELLED as enhanced-for-presentation wherever it renders.

Requirements if that is ever built:
  * outside the compliance path entirely — never substituted into the daily
    log, the DOB record, or anything a regulator reads
  * the original and the deterministic `enhanced` variant remain the record
  * the label travels with the image, not just the UI that happens to show it

That is the only context in which generative enhancement is appropriate here.

### Recommended stack IF the presentation variant is ever built

`onnxruntime` (CPU wheel ~20 MB) + Pillow + numpy. NOT `opencv-python-headless`
— 112 MB installed, and already rejected twice on this feature: once for CLAHE
(implemented in numpy instead, see photo_enhance._clahe_l_channel) and once for
ARCNN. Load the model once and run it on the existing photo threadpool rather
than per-request.

To be explicit, because the two decisions are easy to conflate: this stack note
does NOT reopen ARCNN for the compliance pipeline. Synthesis stays prohibited
there regardless of which runtime executes the model — the cancellation above
was about the PASS CONDITION (filling flat interiors is synthesis), not about
dependency size. A 20 MB runtime does not make invented detail acceptable on a
DOB record; it only makes the carve-out cheaper to build if the carve-out is
ever wanted.

---

## TENANT ISOLATION — 2026-07-28 — assigned_projects: stale-entry audit NOT RUN, + defense-in-depth

Both write vectors into `assigned_projects` are now gated (see the commit that
adds `validate_assignable_projects`). Two things remain OPEN.

### 1. Stale cross-company entries — audit NOT RUN, no production DB access

The gate is **prospective only**. It stops new foreign entries being written; it
does not revoke anything already stored. Any pre-existing cross-company entry is
a live key to another tenant's project and will keep passing
`require_project_access` branch 3.

This has NOT been checked. Nobody has run it against production. Read-only
query, no writes:

```javascript
db.users.aggregate([
  { $match: { assigned_projects: { $exists: true, $ne: [] }, is_deleted: { $ne: true } } },
  { $unwind: "$assigned_projects" },
  { $addFields: { pid: { $toObjectId: "$assigned_projects" } } },
  { $lookup: { from: "projects", localField: "pid", foreignField: "_id", as: "proj" } },
  { $unwind: { path: "$proj", preserveNullAndEmptyArrays: true } },
  { $match: { $expr: { $ne: ["$company_id", "$proj.company_id"] } } },
  { $project: { _id: 1, email: 1, role: 1, company_id: 1,
                project_id: "$assigned_projects", project_company: "$proj.company_id" } }
])
```

`$toObjectId` throws on a non-ObjectId id, so wrap it or run on a subset if the
collection has mixed id shapes. Rows returned are grants this fix does not
retroactively revoke — each needs a deliberate remediation decision (revoke, or
confirm as an intended contractor grant).

### 2. `require_project_access` trusts assigned_projects blindly

Branch 3 returns the project whenever its id appears in the caller's
`assigned_projects`, without re-checking the project's company. With both write
vectors gated, **the assignment guard is now the ONLY thing keeping that list
clean** — a single point of failure.

Re-verifying the project's company inside branch 3 would make a stale or bad
entry inert. The reason it was NOT done: that check would also kill the
legitimate cross-company contractor flow, which is the entire purpose of
branch 3 (a CP at another company granted access to a GC's project — see
`USER_C_ASSIGNED` in test_tenant_isolation_reads.py and
`test_assigned_contractor_allowed_cross_company` in
test_tenant_isolation_writes.py). That is a product decision, not a security
one, and needs an explicit answer: is cross-company assignment a supported
feature, or an accident that should be removed?

If it is NOT supported, branch 3 should verify company and this whole class of
bug disappears. If it IS supported, the assignment guard must stay the single
enforcement point and should be treated as security-critical code.

### Scope limit of the sweep

The vector list came from `grep -n "assigned_projects" backend/server.py` — complete
for that file. Direct DB writes, other services, and migration scripts were not
audited.

---

## TENANT ISOLATION — 2026-07-28 — Batch 2 tightened writes but did NOT complete isolation

25 project-scoped write endpoints now carry `require_approved` +
`require_project_access`. Four things remain open. **Isolation is TIGHTENED,
NOT COMPLETE** — do not treat the write batch as closing the multi-tenant story.

### 1. `POST /admin/users/{user_id}/assign-projects` — SEV-0, defeats the guards

`server.py:4880`. `get_admin_user` checks ROLE ONLY. The handler never loads the
target user to compare companies and never validates the submitted project ids:

```python
result = await db.users.update_one(
    {"_id": to_query_id(user_id)},
    {"$set": {"assigned_projects": project_ids.get("project_ids", []), ...}},
)
```

`require_project_access` branch 3 (`server.py:2819-2820`) treats
`assigned_projects` as sufficient authorization. So this one unscoped write
**manufactures** the membership that every guard added in Batch 1 and Batch 2
then honours. Until it is gated, cross-tenant access is still reachable on the
routes that look protected. Fix: scope the target user to the caller's company
AND validate every submitted project id belongs to that company.

Note the sibling `PUT /admin/users/{user_id}` (`server.py:4773+`) already has
this mitigation, commented "SEV-0 tenant scoping. get_admin_user checks ROLE
ONLY..." — assign-projects was missed.

### 2. Kiosk write path — `POST /daily-logs`, `PUT /daily-logs/{log_id}`

Not gated. A site device registered to project A can write a daily log to
project B. `require_project_access` cannot be applied as-written because
`project_id` arrives in the **body** (`DailyLogCreate`), not the path.

Device-auth shape is confirmed and the guard is a straight port, not new logic:
a kiosk authenticates against `db.site_devices` (`server.py:3092`) with a
`site_mode` JWT; `get_current_user` (`server.py:2431-2444`) resolves it to the
device row, sets `role="site_device"`, and re-derives `company_id` from the
device's project at request time. The device record carries `project_id`
(written at provisioning, `server.py:10769`). So the check is exactly
`require_project_access` branch 1 (`server.py:2806`) — device may write only to
its provisioned project — reading `body.project_id` instead of the path param.

Also fix while there: `create_daily_log` inserts even when the project lookup
returns `None` (`server.py:10540-10544`).

### 3. Per-endpoint route-level over-gate tests not written

`test_tenant_isolation_writes.py` asserts the three directions against the
SHARED guard, plus a source pin (ast) and a wiring pin (live FastAPI dependant
tree) proving all 25 routes declare and carry both dependencies. There is **no
route-level call** for any endpoint — in particular no per-endpoint
"own-company admin still works" mirror. A handler-local regression that breaks a
legitimate own-project write would not be caught.

The two 403 directions are cheap to add per route (the dependency raises before
body validation). The "works" direction is the expensive one: multipart for
`upload-file`, R2/Dropbox doubles for `sync-dropbox` and `reindex-*`, the stats
engine for `risk-score/calculate`.

### 4. Null-`company_id` deployment count — DO THIS BEFORE DEPLOYING

The hand-rolled checks these guards replace had the shape
`if company_id and project.get("company_id") != company_id:` — which **silently
passed** when the caller's `company_id` was falsy. `require_project_access`
fails closed instead. Any real admin/owner account with a null/missing
`company_id` therefore passed these 25 routes before and gets 403 now.

Count them first — `backend/scripts/audit_account_roles.py --mask` is the
natural place to add it. No production DB access from the dev environment.

### Also noticed, unrelated to this batch

`get_current_user`'s site-device branch looks the device up by `_id` only
(`server.py:2432`) and does **not** re-check `is_active` / `is_deleted`, though
the login endpoint does (`server.py:3092`). A deactivated kiosk's existing token
keeps working until it expires.

---

## CAMERA PERF — 2026-07-28 — daily-log camera is not fully pre-warmed; Android still cold-starts the device

Permission is now off the tap path (`4b712e3`), and the capture surface is
mounted-hidden rather than created on open (commit 2 of the same pair). What is
**not** done: the camera device is not held warm on every platform.

Read from VisionCamera 4.7.3's own native source, not assumed:

- **iOS** — `ios/Core/CameraSession.swift`: `configure()` acquires the device
  input and configures format/outputs in steps 1-9; `checkIsActive()` is step
  10 and only calls `captureSession.startRunning()`. The device **is** held
  from screen mount. iOS is genuinely pre-warmed.
- **Android** — `android/…/core/CameraSession.kt`: `configureOutputs` /
  `configureCamera` (CameraX `bindToLifecycle`) run first, `configureIsActive`
  runs fourth and only moves a `LifecycleRegistry` between `CREATED` and
  `RESUMED` (`CameraSession+Configuration.kt:341`). CameraX opens the physical
  camera on that transition, so **the device open is still on the tap**. The
  session graph is pre-built; the device is not held.

**The remaining lever, and why it wasn't pulled:** holding the Android
lifecycle at `STARTED` while idle would keep the camera device open, but that
means the camera hardware is held for the whole time the daily-log screen is
open — a real battery and thermal cost on a shift-long jobsite tablet, and it
lights the OS camera-in-use indicator while the user is only typing. Not worth
paying before device testing shows the open actually feels slow.

**Revisit if** device testing shows the Android open still lags noticeably
behind iOS. Until then this is a known, measured-by-source asymmetry, not a
defect.

**Unverified without a phone** (neither web nor emulator reproduces camera
cold-start; the production web export exercises the `.web.jsx` stub, not
VisionCamera): actual open time on either platform, and the four interaction
surfaces the overlay restructure introduced — Android hardware back dismissing
the camera, the overlay stacking above `FloatingNav`, full-bleed layout outside
the `SafeAreaView`, and AppState background/resume re-acquiring the preview
rather than returning black.

---

## TEST GAP — 2026-07-28 — nothing MOUNTS the shared components, so a crash ships green

While converting the shared components to per-render theming (`98e5577`), four
of them — `IconPod`, `SiteNav`, `ToastProvider`, `FloatingNav` — were left
referencing a module-scope `styles` that no longer existed. That is a hard
runtime crash: **"Something went wrong · styles is not defined"** on any screen
that raised a toast.

**Both gates passed anyway.**

- The frozen-ref grep reported 0 — it looks for `colors.*` inside a module
  `StyleSheet.create`, and the crash is a *missing binding*, not a frozen value.
- The wiring checker reported 0 unwired — it scanned from each component to
  end-of-file, swallowing the `buildStyles` definition, so every file's LAST
  component read as "already wired".
- Both CI suites were green: 2110 backend + 16 frontend, none of which render
  a React component.

It was caught only because the rendered screenshots were demanded in context —
the toast screenshot showed the error boundary instead of a toast.

**The gap:** the frontend suite is one Node harness that parses source text
(`RiskScoreCircle.bandFor.test.cjs`). Nothing in CI ever *mounts* a component,
so any render-time error — missing binding, bad hook order, undefined style,
a provider that throws — ships green.

**To close:** add a mount smoke test that renders each shared component (and
each provider) once and asserts it does not throw. It does not need assertions
about appearance; mounting is the assertion. Candidates, in dependency order:
`ToastProvider`, `ThemeProvider`, `AuthProvider`, `GlassCard`, `IconPod`,
`StatCard`, `GlassListItem`, `GlassSkeleton` (+ its four skeleton variants),
`Toast`, `OfflineIndicator`, `SyncButton`, `SiteNav`, `FloatingNav`.

Note this needs test infrastructure the repo does not have: there is no jest /
vitest / react-test-renderer, and `frontend/package.json` has no `test` script.
Adding one is the bulk of the work; the tests themselves are a few lines each.
Wire it into the existing `tests` workflow's `frontend-tests` job so it gates
like the rest.

**Cheaper interim option** if a runner is too much scope: extend the existing
Playwright verification into a committed script that loads a handful of routes
against a production build and fails on any console error or error-boundary
text. That would have caught this exact crash, without a component-test runner.

---

## OFFLINE CORRECTNESS — 2026-07-27 — offline "on site" count includes stale prior-day check-ins

`getActiveCheckIns` in `frontend/src/hooks/useCheckIns.js` falls back to a local
WatermelonDB query when the API call fails. That fallback filters **only** on
`check_out_time: null` — there is **no day boundary**:

```js
// useCheckIns.js:107 — the offline fallback
const queryConditions = [
  Q.where('is_deleted', false),
  Q.where('check_out_time', null),
];
if (projectId) {
  queryConditions.push(Q.where('project_id', projectId));
}
```

Offline, a worker who was never checked out on a **prior** day still satisfies
`check_out_time: null` and is counted as "on site today". The count silently
inflates with every un-checked-out worker, and nothing on screen indicates the
number came from the offline path.

Both surfaces share this: the dashboard **Active by site** section and the
project-detail **ON SITE** tile call the same hook (deliberately — one code
path so the two cannot disagree). They stay consistent with each other; both
are wrong together when offline.

**Online path is correct** and unaffected: `GET /checkins/project/{id}/active`
bounds the query with `get_today_range_est()` (the NYC-local day from the
check-in timezone fix). This is an offline-path-only defect.

**Second, related divergence found in the same file:** the sibling
`getTodayCheckIns` fallback (`useCheckIns.js:142`) *does* bound the day — but
with **device-local** midnight:

```js
const dayStart = new Date(date); dayStart.setHours(0, 0, 0, 0);
const dayEnd   = new Date(date); dayEnd.setHours(23, 59, 59, 999);
```

So a device outside America/New_York gets a different "today" offline than the
server's `get_day_range_est`. Two different day definitions now exist on the
offline path, and neither matches the server's.

**Why this matters beyond cosmetics:** "who was on site" is a compliance
record. An inflated on-site count offline is a false attendance statement, not
a display glitch.

**To close (offline audit):**
- Give the `getActiveCheckIns` fallback an NYC-local day bound so an
  un-checked-out prior-day record cannot count as present today.
- Derive the offline day boundary from a shared NYC-local helper rather than
  `setHours(0,0,0,0)`, so `getTodayCheckIns` and `getActiveCheckIns` agree with
  each other and with the server.
- Consider surfacing staleness in the UI when a count came from the local
  fallback — an offline number that looks identical to a live one is the part
  that makes this dangerous.

---

## COMPLIANCE GAP — 2026-07-27 — worker certification expiry renders with no warning state

**Priority: compliance, not polish.**

`frontend/app/workers/[id].jsx:558` renders a worker's certification expiry as

```jsx
<Text style={s.certExpiry}>Expires: {cert.expiry}</Text>
```

and `certExpiry` (line ~955) is `color: colors.text.muted` — **unconditionally**.
The date is printed as flat muted text whether it expires in a year, expires
tomorrow, or expired last month. There is no `daysUntil` / `isExpired`
evaluation anywhere in this file for certifications: the expiry is never
compared against today, so no code path can colour it.

On a NYC jobsite an expired SST or OSHA card means the worker **legally cannot
be on site**. A foreman scanning this screen gets no signal that a card has
lapsed, so this is a missing compliance warning, not a cosmetic gap.

The `Award` icon beside the row is a constant glyph for every certification and
was correctly routed to the neutral token in the amber sweep (`8b4830a`) — it
was never carrying the warning. That commit did not cause this gap; it surfaced
it.

**Second instance, same defect:** the OSHA card at
`frontend/app/workers/[id].jsx:414–417` renders `oshaData.expiration` with
`oshaFieldValue` (`colors.text.primary`) — also unconditional, also never
compared against today.

**To close:**
- Evaluate days-remaining for `cert.expiry` and `oshaData.expiration` (a
  `daysUntil` helper already exists at
  `frontend/app/project/[id]/dob-logs.jsx:72` — lift it into a shared util
  rather than re-implementing).
- Colour the expiry text `semantic.attention` when expiring soon (threshold to
  be agreed — the DOB permit surfaces use 30d, `settings.jsx` / safety-staff use
  60d/90d) and `semantic.criticalText` once expired.
- Consider surfacing an expired card at the worker-list level too, not only on
  the detail screen — an expired card is only actionable if someone sees it
  before the worker reaches the gate.

---

## 2026-07-27 — 85 hardcoded `#f59e0b` amber literals still bypass the token layer

The dual-theme contrast fix made the semantic state tokens per-theme, so
`semantic.attention` now resolves to a light-mode-safe amber. But **85
occurrences across 30 files** still hardcode the raw amber literal `#f59e0b`
(plus `rgba(245,158,11,…)` fills), which cannot follow the theme and therefore
still render at ~3.2:1 in light mode — below WCAG AA.

**Fixed in this pass (the screen named in the audit):**
`frontend/app/project/[id]/dob-logs.jsx` — all 22 amber literals routed to
`semantic.attention` / `semantic.attentionBg`.

**Still open:** the other 30 files, notably `app/admin/safety-staff.jsx`,
`app/admin/site-devices.jsx`, `app/daily-log.jsx`, `app/logbooks/*.jsx`,
`app/documents.jsx`, `app/demo.jsx`. Same class of bug exists for any
hardcoded red/green literal.

**To close:** sweep the remaining literals onto the semantic tokens (a
color-only change per site), then add a lint rule banning raw state-color hex
in `app/`/`src/` so the sprawl cannot reappear.

## 2026-07-27 — No per-project DOB-sync timestamp (Projects triage "Synced" column)

The desktop Projects triage table (`frontend/src/components/ProjectsTable.jsx`)
wants a **data-sync freshness** value per project, but no such field is written.
The only sync-ish project timestamp is `first_poll_completed_at`, stamped **once**
on the first DOB poll and never updated thereafter
(`backend/server.py:17395` — `if proj_doc and not proj_doc.get("first_poll_completed_at")`).
Rendering relative time off it ("synced 4m") would be a lie for any established
project — it's first-poll age, not last-sync freshness. (`last_synced_at`
[server.py:12419] is Dropbox files; `last_sync_at` [server.py:18383] is a global
rate-limit doc — neither is per-project DOB sync.)

**Interim (shipped):** the Synced column shows only the one truthful bit —
"Never" (attention) when `first_poll_completed_at` is null, "—" once synced. No
fake relative freshness.

**To close:** stamp a rolling `last_dob_sync_at` (UTC) on the project doc at the
end of each successful `run_dob_sync_for_project`, add it to `ProjectResponse`,
then render real relative freshness in the Synced column.

## 2026-07-26 — i18n gap on the DOB compliance screen (dob-logs.jsx)

`frontend/app/project/[id]/dob-logs.jsx` has **no i18n framework** — the
no-expiry permit disclosure ("N permit(s) without expiry data not counted") and
every other user-facing string on this screen (tile labels, "Sync Now", filter
banner, status badges, etc.) are **English-only**. This is against the app's
stated **bilingual EN/ES** principle for user-facing strings. The app has no
i18n library wired at all (no i18next/react-i18next; a few worker-facing screens
carry inline EN/ES strings, but the compliance screens do not).

**Interim:** English-only shipped honestly — commit `5e4a521`'s body records that
the disclosure is English because this screen lacks i18n.

**To close:** wire i18n on this screen (and the sibling compliance screens) so
its strings meet the bilingual convention — ideally via a shared translation
mechanism rather than per-string inline ternaries.

---

## 2026-07-26 — dob-summary active-permit boundary: UTC vs NYC-local (minor)

`GET /projects/dob-summary`'s `permits_expiring` facet uses **UTC midnight**
today (`server.py` ~7496), not NYC-local. The new `total_permits` (active)
facet deliberately reuses that **same UTC `today_start`** so `permits_expiring`
is always a subset of `active`. Immaterial for a 30-day permit window (a permit
sitting exactly on the UTC-vs-EDT boundary is a few hours' difference on a
month-scale horizon). Fully aligning to NYC-local would require changing
`permits_expiring` too (the open-count logic), which was explicitly out of
scope. Log-only; revisit if a day-boundary discrepancy is ever reported.

---

## 2026-07-26 — Violation-type code labels need an official DOB source

DOB violation-type codes (`JVIOS`, `JVCAT5`, `E`, `LBLVIO`, the `LL*` family,
and DOB NOW Safety `FTC-*/FTF-*` codes) are currently shown to customers as
`DOB code: {code}` — the honest raw code — because there is **no verified
official label** for them yet. The DOB Violations dataset (`3h2n-5cm9`) embeds a
description in its `violation_type` column, but that is dataset text, not a
dedicated authoritative DOB violation-type code list, so it is treated as
UNVERIFIED.

A transcribed-from-dataset map exists but is **quarantined** behind
`UNVERIFIED_VIOLATION_TYPE_LABELS_PENDING_SOURCE` in
`backend/dob_complaint_codes.py`, with a comment that it must not be displayed;
`violation_type_display()` deliberately does not read it, and a test
(`test_display_never_returns_an_unverified_label`) enforces that.

**To close:** confirm each code→label against DOB's official published
violation-type reference (or the `855j-jady` data-dictionary xlsx for the
`FTC-*/FTF-*` family), then promote the verified entries into the display path.
Until then, violation types stay prefixed. (Complaint category + disposition
labels already have official sources and DO display.)

---

## 2026-07-26 — OverviewByBinServlet: code was already clean; risk is stored data + doc drift

**Finding.** A repoint of violation tier-3 links off the decommissioned
`OverviewByBinServlet` was requested, but the builder was **already** clean: every
BIN fallback (`_build_dob_link` violation/permit/job_status/inspection/final)
routes through `_bis_bin_overview_url` → `PropertyProfileOverviewServlet?bin=`
(the confirmed-live BIN profile), and there is **zero** `OverviewByBinServlet` URL
construction in the deployed tree. The only residue was **stale docstring text**
in `_build_dob_link` (three "→ BIS OverviewByBin" lines plus an outdated
permit/job_status routing summary) — corrected this pass. `_bis_property_profile_link`
does not exist. The `SourceInvariantTest` guard already forbade the dead URL; a
functional guard (`test_no_record_type_emits_overviewbybin`) was added so no
future branch can reintroduce it regardless of URL literal.

**Why links can still LOOK dead (data, not code):** `dob_link` is written at
ingest, but the dob-logs read path (`server.py` ~18085) rebuilds it from each
row's `raw_record` on every read — so a stale stored `OverviewByBin` value is
replaced with the live URL at read time **iff the row has a `raw_record`**. A row
with no `raw_record` keeps its stale stored link. Remedy for those is a re-poll
(`/projects/{id}/dob-sync`), not a code change. `backend/scripts/violation_link_check.py`
reports, per record, stored-vs-freshly-built link and whether a `raw_record`
exists (auto-heal) or is missing (genuinely stale).

**Lesson — BIS legacy servlets are being retired mid-lifecycle.** DOB has quietly
decommissioned `OverviewByBinServlet` (now BIS "Page not found") while
`PropertyProfileOverviewServlet` stays live. BIS-based deep links therefore need
**periodic** re-verification, not one-time confirmation; treat any BIS servlet as
"confirmed as of <date>", and keep all BIN links flowing through the single
`_bis_bin_overview_url` helper so a future swap is one edit.

---

## 2026-07-26 — Permit / job_status links repointed to BIN property profile

**Done.** DOB NOW permit/job_status filings had no public per-record URL (DOB NOW
is a login-walled Angular SPA whose Job-Number search does not encode the job in
the URL — confirmed by live fetch; its result URL is `…/Index.html#!/search`),
and the old `data.cityofnewyork.us/w9ak-ipjd.html?job_filing_number=` link landed
on a generic dataset page because Socrata's `.html` surface ignores the column
filter. All permit/job_status now resolve to the SAME confirmed-working BIS BIN
property profile used for the violation fallback
(`PropertyProfileOverviewServlet?bin=`, via `_bis_bin_overview_url`); legacy
BIS-numeric permits (previously `JobsQueryByNumberServlet`) share it too. No BIN
→ no link.

**Candidate to verify when BIS is reliably up: `JobsQueryByLocationServlet` for
I1/inspection-suffix filings.** This per-location servlet was *proposed as a
possible per-filing surface but never fetch-confirmed* — it did not appear as a
tested/working destination in the link diagnostic. It was therefore NOT adopted;
I1 filings fall back to the BIN property profile like the rest. If a live fetch
(when BIS is not throwing its intermittent high-traffic / Access-Denied errors)
returns a real per-filing page for a DOB NOW `…-I1` job, it could be adopted for
that subset. Until fetch-confirmed, do not build it.

Note: BIS (a810-bisweb) was intermittently Akamai Access-Denied during
verification — `PropertyProfileOverviewServlet?bin=` loaded live (twice) while
`JobsQueryByNumberServlet` and `OverviewByBinServlet?requestid=2&allbin=` both
errored (the latter a genuine "Page not found", confirming that shape is dead —
only `PropertyProfileOverviewServlet?bin=` is the working BIN form).

---

## 2026-07-25 — Check-in date handling fixed, but never tested via a real NFC tap

**Done.** Bucketing check-ins by NYC-local day was fixed across all six date
sites (4 backend UTC-midnight `strptime(...tzinfo=utc)` sites → `get_day_range_est`,
frontend `getByDate` → NYC-local date, dashboard `on_site_now` → EST-today to
match the project ON SITE tile). Verified against synthetic boundary records
(8:30pm EDT rollover + early-EST lower boundary) via
`backend/scripts/checkin_tz_verify.py`.

**Deferred — physical device test required before customer reliance.** The full
NFC-tap → kiosk write → display path has **never** been exercised on a real
device; verification to date is synthetic records only. Per the
device-test-before-production principle, run a real on-device check-in end to
end before relying on the feature with a customer. Note: zero real check-ins
exist on either live project today, so the write path is unproven in production.

---

## 2026-07-25 — Rodent-inspection (p937-wjvj) removal: deferred statistical-engine scope

**Context.** `p937-wjvj` is NYC **DOHMH Rodent Inspection** data (rat inspections),
which the app ingested and labeled as **DOB inspections**. The `PC` (Pest Control)
job prefix was additionally fabricated into a `"Plumbing"` trade category by
`DOB_JOB_PREFIX_CATEGORY` / `_decode_job_prefix`. Verified against live Socrata
(source result = "Failed for Rat Activity") and the dataset metadata API
(name = "Rodent Inspection", attribution = DOHMH).

**Done (COMMIT 1, 2026-07-25).** Removed the two `p937-wjvj` ingest endpoints and
the inspection-only composite raw-id fallback in `server.py:_query_dob_apis`;
removed the now-callerless `DOB_JOB_PREFIX_CATEGORY` map, `_decode_job_prefix`,
and its three call sites (`_extract_inspection_fields`, `_generate_summary`
inspection branch, the read-time re-enrichment block). No new `record_type=
"inspection"` rows enter `dob_logs`.

**Deferred — folded into the score rebuild (NOT patched now, because the risk
score is getting a full rebuild and patching its rat-fed dimensions now is
throwaway work the rebuild redoes correctly):**

`DATASET_DOB_INSPECTIONS = "p937-wjvj"` (`lib/statistical_engine/socrata_client.py:85`)
still feeds the risk model **live via Socrata** on four surfaces — all currently
ranking/predicting on DOHMH **rat** inspections:

- **Peer inspection dimension** — `lib/statistical_engine/baselines.py`
  (`compare_project_to_peers`, ~lines 880/900/1163/1273) → `peer_compare["inspections"]`
  → `inspections_percentile` → averaged into the peer subscore
  (`score.py:_normalize_peer_comparison`). Both the project and its peer set are
  ranked on rat-inspection counts.
- **Borough-sweep trigger** — `lib/statistical_engine/triggers.py:741–907`
  (`borough_inspection_counts_90d` / `last_7d_count`, `TRIGGER_BOROUGH_SWEEP`).
- **Inspection prediction** — `lib/statistical_engine/predictions.py`
  (`predict_inspection_from_complaint`, chunked `bbl IN (...)` against p937-wjvj).
- **Calibration** — `lib/statistical_engine/calibration.py:89`
  (`TRIGGER_BOROUGH_SWEEP → (DATASET_DOB_INSPECTIONS, "inspection_date")`).

**Required in the rebuild.** Redesign these against the CORRECT DOB inspection
source(s). Per-trade construction inspections are **not** in NYC Open Data (they
live only in the DOB NOW public portal, per job); the open-data DOB inspection
sources are the periodic safety programs — Boiler `52dp-yji6`, Elevator
`e5aq-a4j2`, Facade FISP `xubg-57si`, CO/TCO `pkdm-hqz6` — each BIN-keyed with
plain-English results. Until then, the peer/trigger/prediction inspection
dimensions are contaminated by rodent data and must not be trusted.

**Also deferred (harmless display/link cleanup, no data behind it):** the
`record_type=="inspection"` display/link/template/notification code in
`server.py` (`_build_dob_link` inspection branch ~16899, severity map entry,
`dob-logs.jsx` `renderInspectionCard`) and the existing `dob_logs` rodent rows
(deleted separately in COMMIT 2).

## Toast is foreign-looking on the ten pinned logbook editors

Logged 2026-08-25, alongside the outdoor canvas pin (PR #210).

The ten logbook editors are pinned to the `outdoor` palette - frozen light,
because a CP fills a compliance log in direct sun. With the canvas now pinned
too, a toast raised on one of those screens in dark mode is a DARK opaque box
on a light page.

NOT INVISIBLE, which is why it is logged rather than fixed. `Toast` paints an
opaque fill in both themes (`#2a1313` dark, a mixed light value otherwise), so
it is a self-contained surface and its text contrasts with its own background.
Nothing disappears; it simply does not match the page it floats over.

The fix, if it is ever wanted, is the same `pinned` prop AnimatedBackground and
SignaturePad now take - but it is more awkward here, because a toast is raised
through a CONTEXT from anywhere, not mounted by the screen, so the screen has
no natural place to declare the pin. That is a real design question and not a
colour swap, which is the other reason it is not in #210.

---

### A `$match` on a field that does not exist matches EVERY document

Asked production how many signature events predated the consent gate. The query
filtered on `signed_at`. It returned **245 rows with `first: null, last: null`**
and looked like an answer — a plausible count, and two nulls that read as "the
dates are missing from these records".

Nothing was missing. **`signed_at` is not a field on `signature_events`.** The
field is `timestamp`; `signed_at` exists only INSIDE `logbooks.cp_signature`,
as a string, on a different collection entirely.

**And the absent field is what produced the 245.** In BSON comparison order a
missing field reads as `null`, and `Null` sorts before `Date` — so
`{signed_at: {$lt: ISODate(...)}}` is TRUE for every document in the
collection. The filter did not narrow anything. It matched the lot, and
`$min`/`$max` of a field that is not there is `null`.

So the two halves of the output agreed with each other and both were wrong: the
count was the whole collection and the nulls were the reason.

**Same family as the double whose `sort()` did nothing and still satisfied a
determinism assertion, the `--include=*.js` sweep blind to 96 `.cjs` files, and
the local glob that ran 85 of CI's 93.** It ran, it returned, it was shaped like
an answer — and it could not have been right. What failed was not the logic but
its REACH, and a plausible-looking result is exactly what hides that.

**The tell, and it is cheap.** A filter that removes nothing is worth one
glance: if a `$match` on a date range returns the same count as the unfiltered
collection, the field name is the first thing to doubt, not the data. Better
still, take the range with no filter at all — which is what the corrected query
does, since the range was the question.

**Two related shapes found in the same session, both in queries written for an
attorney's document:**

- A `$lookup` joining `logbooks._id` (ObjectId) to `signature_events.document_id`
  (declared `str`) matches NOTHING, so a query for "signed documents with no
  ledger row" would have returned every signed document and reported the entire
  corpus as unledgered. Fixed with `$toString` — and paired with a CONTROL
  query whose only job is to fail if the join is broken, because the broken
  output is alarming rather than obviously wrong.
- A count of `signature_events` is not a count of logbook signatures: the
  collection spans `logbook`, `daily_log` and `worker_registration`. Subtracting
  it from a logbook count is apples from oranges, and the difference looked
  meaningful.

**The rule.** A query is a control like any other, and the same question applies
to it: could this have failed? If a filter, a join or a grouping cannot be shown
to have EXCLUDED something it should have excluded, it has not been tested — it
has only been run.

---

### Role where capability was meant: diagnosed three times, real twice

The superintendent on 588 Thomas holds a `cp` account. So any control that asks
"is this person a superintendent" by reading `role` fails in the only case that
matters — it hides his own statutory log from him, and offers it to every CP who
is not a superintendent. That is a real defect, and it was found twice:

**THE CP NAV.** The slot offering the BC 3301.13.13 log gated on the account's
role in its first draft. Corrected before shipping, to a capability computed
server-side through `attribute_signer` — the same predicate the filed document
uses to say who signed it, so the menu and the record cannot disagree about who
the superintendent is.

**THE ROUTER.** `_layout.jsx` constrains role `cp` to `/logbooks`, `/documents`
and `/settings`, and routes every other role to the admin dashboard. `CpNav`
renders on those three CP screens and nowhere else. So a `superintendent`-ROLE
account reaches neither the CP logbook list nor the CP nav, and has no path to
the log named after his job. Unfixed, and moot only because no such account
exists in production.

── AND TWICE IT WAS NOT REAL, WHICH IS THE MORE USEFUL HALF ──────────────────

**`/finalize`.** Reported as gating on bare `role == "cp"`, and therefore as
working for the current CP "by accident". It does not gate there at all:
`_authorize_logbook_write` runs on the line above and calls
`user_can_act_on_project`, which is role-blind apart from its admin branch. The
`role == "cp"` check below it is a documented duplicate kept for its more
specific 403 message, and `update_logbook` and `amend_logbook` carry the same
one. See #348.

**THE LOGBOOK TILE.** Asserted to gate on `role == "cp"`, which would have made
the nav the last remaining path for a superintendent-role user. It has no role
gate: the sole role reference on that screen filters PROJECTS, and does the
opposite — role `cp` is narrowed to assigned projects while every other role
gets all company projects. And the nav was never a path for that user either,
since `CpNav` renders only on screens the router will not send him to.

── THE TELL, AND IT IS THE SAME BOTH TIMES ───────────────────────────────────

**A role check sitting AFTER a shared authorizer, mistaken for the gate.**

Read bottom-up, `if (role == "cp") { ... 403 }` names one role and refuses it,
which invites the conclusion that every other role is ungated. Read top-down,
the authorizer above it already decided — role-blind — and the check below is
belt-and-braces for a better message.

So the question to ask of a role check is not "what does this let through" but
**"what ran before it"**. If a shared authorizer precedes it, the role check is
not the gate and probably never was; an audit that stops at the role check
reports a hole that does not exist, and then proposes a fix that removes a good
error message.

**Neither false positive was free.** One produced a PR that deleted a deliberate
duplicate and had to be reverted; the other nearly justified keeping an item on
a nav bar measured at one point of headroom. A wrong diagnosis does not cost
nothing just because the code turns out to be fine.
