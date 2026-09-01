# Audit follow-ups

Running log of deferred fixes surfaced during audits. Newest first.

---

## QUEUED — 2026-09-01 — two open questions from the trades evening, neither investigated

Recorded at the operator's instruction so they survive the session. **Neither
has been looked at.** Everything below is the question and where to start, not
a finding — the code has not been read for either.

Both queue behind the superintendent editor, which is the last blocker to
Michael filing.

### 1. A worker uploaded a photo of his FACE instead of his SST card, and the gate accepted it

Happened at the gate on the evening of 2026-08-28. The card capture accepted a
selfie and the check-in completed.

**What has to be answered, in this order** — the first three decide whether
this is a data-quality annoyance or a retention problem:

  * **What is stored.** Does a `certifications[]` row exist for it, and with
    what `type` / `review_reason` / `extraction_completeness`? The capture path
    has a `not_sst` refusal for a purple Worker Wallet, so there IS a "this is
    the wrong card entirely" branch — the question is whether a face reaches it
    or falls through to `SST_UNSPECIFIED`.
  * **What the OSHA register shows.** If a cert row was written, does the man
    now READ as holding a credential on the register and the LL196 attestation?
    A row that satisfies the OSHA baseline because it is merely present is the
    worst outcome here.
  * **Whether the CP sees it.** `needs_review` / `review_reason` are what put a
    row in the cert-review queue. If the face landed with `needs_review` false,
    nobody is told.
  * **Whether the image is retained under a certification key.** This is the
    one with consequences beyond compliance: a photograph of a worker's face,
    stored as though it were a credential document, under whatever retention
    the cert images carry. Check the R2 key and what reads it.

Start at the capture path in `server.py` (the `resolved_kind` / `not_sst` block)
and at `card_audit`, then follow the stored row to the register and the
attestation PDF.

### 2. Who assigns a trade to a worker with NO pairing at all, and on which screen

The gate admits a worker with no roster: `not allowed_pairs` stamps
`trade`/`company` as `UNASSIGNED`, sets `needs_trade_assignment` with
`trade_flag_reason = "no_roster"`, and notifies the CP. That is deliberate and
correct — a config gap must not block a man at a turnstile.

**The open question is what happens next.** The admin path to assign one was
broken on 2026-08-28 in two ways at once (#340, and the picker's lost filter
from #224), and while it was broken nobody could complete the assignment the
gate had flagged. So:

  * Is the per-project roster screen (`app/project/[id]/trades.jsx`, reached
    from the project card titled "Check-in Trades") the ONLY way to resolve a
    flagged check-in, or is there a second path — from the flagged-review area,
    the daily jobsite log, or the notification itself?
  * If it is the only one, a single broken screen suspends every pending trade
    assignment in the company, and the flag has no other outlet.
  * The notification that fires on `needs_trade_assignment` — where does its
    deeplink land? If it lands somewhere that cannot complete the assignment,
    that is the gap.

Related and already recorded: the naming problem that sent the operator to the
wrong screen — "Check-in Trades" is a per-project SUBCONTRACTOR ROSTER, the
trade VOCABULARY is a Python literal in `server.py` with no admin screen at
all, and nothing on the roster screen says so.

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
