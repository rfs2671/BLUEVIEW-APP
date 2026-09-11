# Open defects, 2026-09-11 — handoff

Everything here was found while doing other work between 2026-09-10 and
2026-09-11. **Nothing in this document has been investigated further than what
is written in it**, and nothing is being fixed from here: the restyle is the
track now, and this exists so the defects are not lost when it starts.

Read the three warnings first. They change what the lists mean.

> **1. A BRANCH TITLE IS NOT EVIDENCE.** Of the branches spot-checked before the
> triage, one had already been fixed in main by an entirely different commit and
> another's premise no longer matched main's text. Every verdict below was
> checked against main's current source, but main has moved since — six of these
> defects were closed on 2026-09-11 by the merges listed at the end, and the
> remainder should be re-checked before anyone acts on one.

> **2. THE FIFTY IS A POPULATION, NOT A COUNT OF HOLES.** The detector that
> produced it is shape-scoped, the same failure mode it was written to find. Two
> spot-checks disagreed in both directions: one is a deliberate public endpoint,
> one looks genuinely open. The number says how much reading is left, not how
> much is broken.

> **3. WHERE COUNTS DISAGREE, THE LIST WINS.** Running tallies were spoken
> during the work and do not all reconcile; the tables below were rebuilt from
> the verdicts themselves. Trust a row, not a total.

---

## A. Live defects

Verified against main by three read-only triage passes on 2026-09-11, then
re-stated here. Ordered by severity, and the ordering is argued rather than
asserted — the principle is: **a false or wrong statement on a filed legal
record outranks data loss, which outranks a capability the product advertises
and does not deliver, which outranks cost and latency.**

### A1. Dropbox R2 keys collide on basename — wrong document, right-looking

`backend/server.py:22658` builds `r2_key = f"{company_id}/{project_id}/{filename}"`
inside `_sync_project_to_r2`, whose listing is recursive and whose `filename` is
the **basename**. The row is keyed on `dropbox_path`, so `/Approved Plans/plan.pdf`
and `/Permits/plan.pdf` become two rows sharing one R2 object and the later sync
silently overwrites the earlier one's bytes. Direct upload has the same flat key
at `:22926`, and its de-duplication filters out soft-deleted rows, so re-uploading
a deleted file's name reuses that object.

**What a caller reaches:** an inspector opening one drawing can be served a
different drawing's bytes, with nothing on screen to say so.

**Second half, same branch:** four `list_folder` call sites read one page and
drop `has_more` — `:21578`, `:21806`, `:22066`, `:22762`. The second is the
source of the Site Device Visibility checkboxes, so a Dropbox subfolder past
page one can never be ticked for a gate tablet. A fifth site pages properly but
swallows a failed continue with a bare `break`.

**Branch:** `fix/dropbox-key-collision-and-pagination`, and it still applies.
**Why first:** it is the only defect here that can put the wrong legal document
in front of an inspector while looking correct.

### A2. A filed compliance log asserts a licence the superintendent does not hold

`backend/lib/logbook/cs_attribution.py:216-219` prints a sentence under the
signature on the BC 3301.13.13 log describing a match "by licence number". The
DOB card carries a **registration number**, and `registration_number` appears
nowhere in the repo. `CSRegistrationCreate` (`backend/server.py:5647-5653`) has
`license_number` and no issue or expiration date, so the CS registration expiry
is unstorable and `nightly_compliance_check` can never check the one credential
the log is about — while safety staff and workers are both swept.

**What it does:** a filed document makes a claim about a credential in terms the
credential does not use.

**Branch:** `fix/cs-registration-schema`, still applies.
**Why second:** a false statement on a filed record, but about wording and a
missing field rather than about which document a reader is handed.

### A3. A delete path that promises to keep the bytes deletes them

`backend/server.py:23419` — the R2 delete in `delete_project_file` is
unconditional, while the docstring twelve lines above (`:23395`) still promises
that for Dropbox-synced files only the Mongo row is removed. No `dropbox_path`
guard and no reference count exists in main. Because the key is not unique (A1),
deleting one row destroys the object a **sibling row still points at**, and sync
will not re-upload it because the content hash matches.

Also in the same branch: `hard_delete_project` caps its `project_files` scan at
5000 (`:13142`), and its logbook-photo prefix uses the raw project id (`:13199`)
while the key writer uses a segment helper (`:332`) — the two disagree by
construction, so a hard delete of a large project silently orphans rows and
objects.

**Authorisation is fine**: the route carries `require_approved` and
`require_project_access` plus an owner/admin check. This is destruction by an
authorised user, not a hole.

**Branch:** `fix/project-delete-r2-photo-loss`, still applies.

### A4. A filed orientation can carry "UNASSIGNED" as its scope of work

`backend/server.py:24401` — `_submit_missing_trade_detail` allows any non-empty
`worker_trade`, and the gate writes the literal `"UNASSIGNED"` at `:14935`/`:14947`,
carried into the orientation draft at `:15137`. `_recorded_trade` (`:14555`)
exists and the gate never calls it. The frontend mirrors it: the "No trade
assigned" repair box is suppressed for exactly those rows
(`subcontractor_orientation.jsx:466`, `:1245`).

**What it does:** a CP can sign and file a subcontractor orientation whose trade
is a sentinel string — the thing the gate exists to prevent. Not an
authorisation hole; both submit paths carry `require_approved`.

**Branch:** `fix/unassigned-trade-sentinel`, still applies.

### A5. An SST review flag nothing can clear, and a status never shown

Two items on one branch.

**Un-clearable:** the only `needs_review = False` in main is the Pydantic default
(`backend/server.py:3084`). Every other write is `True` or a scan-time
computation. No card-check route exists. A worker flagged by a colour-derived
class cannot be cleared by any action in the product.

**Never painted:** `frontend/app/logbooks/preshift_signin.jsx:427` treats only
`expired` and `unknown` as flags. The backend mints five statuses
(`server.py:15265-15273`), so `missing` — a worker with **no SST card at all** —
paints no warning on the gate sign-in screen, and `unknown`'s four distinct
review reasons collapse to one sentence.

**Branch:** `sst/card-check-clears-review-and-four-states`, still applies.

### A6. Inspector mode confines the gate tablet to half its own scope

`frontend/src/utils/inspectorConfinement.js:65` — while inspector-locked, every
path except `/site/logbooks` and `/login` redirects to logbooks. `/site/documents`
exists and the site home carries a Documents tile; neither is reachable.

**What it does:** a DOB inspector handed the tablet through "Hand to Inspector
(read-only)" cannot open plans, permits or agreements at all — the reason the
device exists.

**Branch:** `fix/site-device-scope`. **The branch no longer applies as written**:
the rule moved out of `app/_layout.jsx` into `inspectorConfinement.js`. The
behaviour is byte-for-byte the same defect; the diff needs re-pointing.

### A7. The gate tablet boots dark and cannot leave

`frontend/src/context/ThemeContext.js:9` defaults `isDark` to true and `:13` reads
only stored preference — no role read, no pin. Both theme toggles live on
`/settings` and in a nav modal, and `inspectorConfinement.js:75` confines a site
device to `/site`, so neither is reachable.

**What it does:** the one screen read outdoors in sunlight uses the palette that
is unreadable outdoors.

**Branch:** `fix/site-device-light-mode`, still applies.

### A8. Photographs vanish from a row that is no longer "camera ready"

`frontend/app/logbooks/daily_jobsite.jsx:2467` — the grid of already-taken photos
sits inside a block rendered only when the row is camera-ready, so a row whose
chips were deselected, or a legacy row, or an amendment copy, hides photographs
it already holds, with no message and nothing logged.

`frontend/app/site/logbooks.jsx:600` returns null for an unresolvable photo and
the images have no error handler, so the record says three and the strip draws
two, and a dead R2 key draws a permanent blank square.

**Branch:** `fix/crew-photo-visibility`, still applies.

### A9. Eight multi-worker reads fetch an inline base64 photograph each

`server.py:16740`, `:36716` (a nightly cron, unbounded cursor), `:17606`,
`:17655`, `:17703`, `:39476`, `:42613`, and
`backend/lib/statistical_engine/score.py:469`. `WORKER_NO_CARD_IMAGE` and a
worker projection module do not exist in main; only the LL196 site has since been
addressed independently.

**What it does:** the sort-memory and payload failure that already produced a 500
on `GET /workers` is still reachable on a large tenant roster, and the nightly
cron ships a phone photo per worker every night. Partly mitigated by the R2
migration — inline base64 survives only on unmigrated rows.

**Branch:** `fix/osha-card-image`, still applies.

### A10. A signer's name slot prints the role label — partially closed

`server.py:32070` and `:32099` read `signer_name`; `SignaturePad.js:282,327`
writes `signerName`. `SignatureData` (`:4057-4060`) declares `signer_name` and
`signed_at`, neither of which any writer produces.

**Already closed on 2026-09-11:** the combined report's two hand-rolled blocks
were removed with the dead superintendent section (#505), and both legacy
daily-log editors were retired (#504), so `app/daily-log.jsx` and
`app/site/daily-logs.jsx` are gone. `app/site/logbooks.jsx:507` already reads both
spellings.

**What remains:** the server-side model and any renderer still reading the wrong
spelling. **Re-verify before acting** — the branch `fix/daily-log-signer-name`
was written against text that has since changed twice.

### A11. Every notification in the app is a dead card

`frontend/src/components/NotificationsList.jsx:211` and `:241` call only
`handleMarkRead`; the file has no router import, while its own header claims
"Mark-read on click + deeplink follow".

Separately, `server.py:15515` and `:15991` emit `deeplink_anchor="workforce"`,
and "workforce" has zero matches anywhere under `frontend/app` or `frontend/src`.
`_build_deeplink` supports only `#anchor`, no sub-path.

**What it does:** an admin told to assign a worker with no trade has no tap that
reaches the roster editor.

**Branch:** `fix/workforce-deeplink`, still applies.

### A12. Two writers do not stamp `updated_at` — latent

`server.py:25874` rewrites photos of a finalized logbook without `updated_at`,
fire-and-forget after finalize has already bumped the stamp. `:27010`
(`_refresh_required_logbooks`) changes which compliance logs a project must file
without one, correct only by caller ordering.

**Severity today is latent**: main has no `updated_at`-based client reconcile
endpoint, so this becomes silent stale-cache data loss the moment tablet sync
ships. **It is now closer than it was**: the legal PDF cache version (#495)
reads `updated_at` first.

**Branch:** `fix/updated-at-writer-ratchet`, still applies.

### A13. Cache hydration waits on auth — availability, low

No cache-provider context exists in main and `app/_layout.jsx:412-417` mounts
none. Hydration is screen-local (`app/logbooks/index.jsx:235`) and gated on
`isAuthenticated`, which `AuthContext.js:100-163` only flips after a network call
resolves or rejects. On a cold offline boot the screen holds its loading state
for the full request timeout over a project list already in storage.

**Branch:** `feat/cache-hydration-parent-layout`, still applies. Note its own
CP-scoping change is **not** a defect in main and only becomes one after the
hoist.

### A14. No client version floor — fails open by design

`server.py:821` — `CLIENT_MINIMUM_SUPPORTED = None`, reported at `:28251` and
never enforced. No 426 anywhere.

**What it does:** no request is judged against a minimum client version, so an
arbitrarily old native build talks to the current API indefinitely. The branch
ships the mechanism with no value and fails open when unset, so merging it
changes nothing until someone sets the variable.

**Branch:** `fix/stale-bundle-detection`, still applies.

---

## B. Closed on 2026-09-11

These were live when triaged and are not any more. Listed so nobody works them
twice.

| Was | Closed by |
|---|---|
| Three report routes gated tenancy on `role == "admin"`, which an owner never reaches, while registration sets owner on every signup | #499 |
| Doubled `data:image/png;base64,` prefix — every worker acknowledgment signature a broken image on 72 filed orientation PDFs | #497 (a complete fix written 2 September and never proposed) |
| File stream had no project-access dependency; document index and the Dropbox link route ignored the folder allow-list; the link route sent a caller-supplied path to the company's Dropbox token | #501 |
| A 720-hour session JWT in document URLs, logged verbatim | #502 |
| Offline daily log promised a sync the drain refuses for that type | #504 (both editors retired) |
| "Site Superintendent Log" section rendering from a collection last written 16 April | #505 |

`fix/signature-ledger-observability` and `fix/site-device-no-space` were
**redundant** — main had already gone further than the branch.
`sdk54-path-a` was redundant. `feat/unpublished-count-surfacing` is **stale**:
`site_visible` has never existed in main's history.
`docs/two-measured-findings`, `docs/worker-enumeration-sweep` and
`probe/pdf-viewer-reload` carry no code.

---

## C. The fifty project-id routes

Ninety-four backend routes take `{project_id}`. Forty-four carry
`Depends(require_project_access)`. **Fifty reference neither that dependency nor
`project_access_ok`/`_assert_project_access` in their decorator or body.**

**This is not fifty holes.** A route may scope tenancy some other legitimate way,
and my detector only looked for the canonical names. Two spot-checks:

- `get_checkin_info` (`/checkin/{project_id}/{tag_id}/info`) — **deliberate**.
  Documented "Public endpoint - no auth required" and requires a valid tag id.
- `get_logbook_audit` (`/projects/{project_id}/logbook/audit`) — **looks open**.
  Takes the project id straight into a `logbook_entries` query with no company
  term and only a feature-flag check.

The one question for each: *can a caller from another company reach another
company's data through this route.* That needs reading, not scanning.

**NO GUARD at the time of the census (22, now 21):** `get_logbook_audit`, `get_logbook_missing`,
`get_logbook_deficiencies`, `get_logbook_attestations`, `export_logbook`,
`get_project_risk_score`, `get_project_risk_score_history`,
`get_project_peer_cohort`, `get_project_defcon_status`,
`get_project_recent_complaint_buckets`, `get_project_notification_preferences`,
`patch_project_notification_preferences`,
`delete_project_notification_preferences`, `hard_delete_project`,
`get_checkin_info`, `get_flagged_project_checkins`, `stream_project_file`†,
`whatsapp_get_groups`, `get_material_requests`, `get_project_model_endpoint`,
`unconfirmed_project_model_endpoint`, `get_schedule_endpoint`.

† `stream_project_file` gained the dependency in #501 and is no longer on this
list; it is named here only because the census predates that merge.

**BODY GUARD (28)** — these reference a canonical helper inside the function
rather than on the decorator, which the decorator-only reading would have
reported as ungated. They are listed in the session transcript and are the
lower-priority half.

---

## D. The 26 unproposed branches

Twenty-six remote branches carried commits whose patches were genuinely absent
from main (verified with `git cherry`, not a commit count) and which **never had
a pull request**. Eighteen share one date, 2026-09-02 — one session's output
committed and abandoned.

Their triage states are in sections A and B above. The class itself is written up
as §15 of `check-harness.md`: *work that is done and not proposed does not
exist*. The detection sweep is given there, and the conclusion is that it belongs
in a periodic job rather than CI, because a pull-request trigger cannot observe
work that never became one.

---

## E. Recorded and unbuilt

- **Three cosmetic items on the investor report, unruled.** Ragged card bottoms
  on the project record page; the "Not due today" placeholder renders about a
  third the width of a real thumbnail; the cover's date and address columns size
  to content and read as one line. All are appearance, none is data.
- **The query-token pattern on remaining routes.** #502 converted the file stream
  and the two report routes to short-lived grants. `get_single_logbook_pdf`
  (`server.py:19330`) still declares a `token` query parameter. **Recorded, not
  verified** — nobody has checked what passes it.
- **An empty site-device allow-list is closed, not open.** The helper returns
  False for an empty list, so a device on a project where no folder was ticked
  syncs nothing. Three of five provisioned devices are in that state. The default
  is right; the experience is not — an admin who ticks nothing gets an empty
  screen with no explanation. Usability, not exposure.
- **The prose rule's audit cost is unmeasured.** `code_of` strips comments and
  docstrings so an assertion cannot be satisfied by the prose explaining it. It
  is used in 33 of 348 backend test files. Requiring it means auditing the other
  315, most of which are expected to be merely unconverted rather than wrong.
  **Nobody has measured which.**
- **Seventeen assertions index a parse helper inside the assertion** and would
  raise rather than fail (§14). Ruled: state the count, fix on touch, do not
  sweep.
- **Seventy-eight assertions would print a whole source file on failure.** Now
  gated at a pinned total that can only fall (#507). They come down on touch.
- **Report #29 went out without page 4.** The scheduled send fired 44 minutes
  before the project-record page deployed, so #29 is the last report without it
  and #30 the first with it. Recorded beside the numbering scheme in `server.py`
  so a reader comparing two consecutive numbers finds the explanation.
- **Poppler, R2 and the thumbnail cache are confirmed working in production**
  and need no further attention.

---

## F. What this document is not

It is not a work plan and not a priority list beyond the ordering argued in
section A. Six of the defects it describes were closed between the triage and
the writing, which is the best evidence that **every row needs re-checking
against main before anyone acts on it**. The branch names are where to look, not
what to merge.
