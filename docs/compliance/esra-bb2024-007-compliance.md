# Electronic site safety documents — compliance status against Buildings Bulletin 2024-007

**Prepared for legal review.** Last updated 2026-08-30, against `main` at `448410f`.

## What this document is, and is not

This is an engineering statement of **what the software does**, written so that a
reviewing attorney can compare it against what the bulletin and ESRA require. Each
section names the requirement, states what the code does, and cites the file and
line that does it.

**It does not certify compliance, and no statement in it should be read as legal
advice or as an opinion that any requirement is satisfied.** Whether the described
behaviour meets the bulletin, ESRA, or any other obligation is a legal judgment
that has not been made here. Where something is not built, it says so plainly and
without qualification.

**Scope.** The subject is the **BC 3301.13.13 construction superintendent log**,
which Buildings Bulletin 2024-007 names as a site safety document. The bulletin
permits contractors to "pick and choose which, if any" documents are kept
electronically, so this assessment is confined to that one log. LeveLog produces
several other records (pre-shift sign-in, toolbox talk, OSHA/SST register) that
are **also** named in the bulletin; **they have not been assessed here** and
should not be assumed compliant because this log is discussed.

**Status of the log itself: NOT YET BUILT.** The superintendent log described
here is a design under construction. Sections below distinguish between
infrastructure that exists and is in production today, and behaviour that is
planned. That distinction is marked on every line.

---

## Sources, and what was verified

| source | how it was obtained |
|---|---|
| Buildings Bulletin 2024-007, issued 2024-12-19 | Primary PDF retrieved from `nyc.gov/assets/buildings/bldgs_bulletins/bb_2024-007.pdf` and read in full (3 pages). All quotations below are from that document. |
| ESRA — NY State Technology Law Article 3 | **Section structure verified** from the NY Senate site: §301 Short title, §302 Definitions, §303 Electronic facilitator, §304 Use of electronic signatures, §305 Use of electronic records, §306 Admissibility into evidence, §307 Exceptions. |
| 9 NYCRR Part 540 (ESRA regulation, NYS ITS) | Summary retrieved from the NYS ITS site. |

**A limit on this document, stated because it matters.** The **operative
statutory text** of ESRA §§302, 304, 305 and 306 could not be retrieved
programmatically — the NY Senate pages render their text via JavaScript and
Justia returned HTTP 403. **The text has not been reconstructed from memory and
is not quoted here.** Section numbers and titles are cited as verified; the
substance of each section must be read by the reviewer from the primary source.
An engineering document that paraphrased a statute it could not open would be
worth less than one that says so.

**One nuance the reviewer will want to consider.** Per the NYS ITS summary,
9 NYCRR Part 540 defines its subjects as governmental entities — "any State
department, board, bureau, division, commission" and political subdivisions —
and **does not directly bind private parties**. The bulletin's instruction that
documents "must adhere to ESRA" therefore appears to import the **statute**
(Article 3) rather than the agency regulation. Whether the regulation's specific
mechanics nonetheless supply the standard of care is a legal question and is not
answered here.

---

## Bulletin § III — Accessible on a tablet or similar device

> "A dedicated tablet or similar device with access to the electronic site safety
> documents … must be readily available at the site at all times for use by the
> Department. The tablet or similar device must: 1. have a minimum screen size of
> 10 inches, as measured diagonally across the screen; and 2. at all times possess
> sufficient power, connectivity, and access for the department to readily view
> the electronic document."

**This is an operational obligation on the permit holder, not a software
feature.** No code can satisfy it. It requires a ≥10-inch device, powered and
connected, physically present at each jobsite for the duration of the job.

**What the software contributes:** the application runs on a site device today
and has a site-device mode with its own provisioning (`site_devices` collection,
in `SOFT_DELETE_NEVER_PURGE`, server.py:37594). **Unaddressed:** nothing in the
software verifies screen size, nothing monitors that a device is present and
powered at a given site, and nothing would alert if one were absent. If the
reviewer considers evidence of continuous availability necessary, that evidence
does not currently exist.

---

## Bulletin § IV — Emailable as a PDF or printable at the site

> "Electronic site safety documents … must be capable of being readily:
> 1. emailed to the Department as a pdf document; or 2. printed from a printer
> located at the site."

**In production.** The application renders each logbook as HTML and as PDF, and
emails a combined daily report.

- Per-logbook HTML: `generate_single_logbook_html`, server.py:15956
- Combined report: `generate_combined_report`, server.py:23129
- PDF rendering: WeasyPrint, with print CSS (`@page { size: A4 }`) already
  distinguishing the emailed and printed media

**Note for the reviewer:** the bulletin requires the alternatives disjunctively
("or"). PDF-by-email is the path the software supports; on-site printing is not a
software capability.

---

## Bulletin § V — Electronic document system

> "Electronic site safety documents … must be **created and stored as part of an
> electronic document system. Scans of paper documents, or malleable word or
> excel files, do not constitute compliance with this bulletin.** The electronic
> document system must ensure that [they] are tamper proof, provide validation of
> signatures, and indicate when a record was created."

**This is the provision that permits the electronic record to be the record**
rather than a copy: it requires the system to be the point of creation, and
expressly excludes scans of paper. Read with § I — documents not kept
electronically in compliance with the bulletin "must continue to be made
available in a paper format" — the reviewer may consider whether a compliant
electronic document discharges the obligation without a paper counterpart. **That
reading is not asserted here.**

The bulletin then lists eight safeguards. Each is taken in turn.

### V.1 — Compliance with ESRA

> "Electronic site safety documents … must adhere to the Electronic Signatures
> and Records Act (ESRA)."

**Not independently assessed.** ESRA's operative text could not be retrieved (see
*Sources*), and whether the behaviours described in V.2–V.8 satisfy it is a legal
judgment. The components a reviewer would likely examine — attribution of a
signature to a verified person, association of the signature with the record,
integrity of the record after signing, and retention — are described individually
below with their code references.

### V.2 — Document finalization

> "Once created, an electronic record cannot undergo further editing or
> alterations. Each document must bear a time stamp and digital fingerprint
> indicating who signed it and the date/time of the signature."

**In production, for existing log types.**

| requirement | where |
|---|---|
| No further editing after creation | `create_logbook` refuses an update to a submitted log with `FILED_LOG_DATA_IMMUTABLE`, server.py:20109 |
| Lock on signature | `is_locked` is set when status becomes `submitted` for an immediate-class log, server.py:20134; timing classes at `logbook_timing_class`, server.py:4045 |
| Digital fingerprint | `compute_content_hash` — SHA-256 over the JSON content snapshot with `sort_keys=True` for deterministic serialization, server.py:15435 |
| Who signed | `signature_events.signer` records `user_id`, `name`, client-claimed `role`, **server-verified `authenticated_role`**, and `acting_capacity`, server.py:15476 |
| Date/time of signature | `signature_events.timestamp`, server.py:15489 |
| Version chain | `version` increments per document, server.py:15467; stored at 15473 |

`acting_capacity` (model at server.py:4223) records the capacity in which a person
signed — "Construction Superintendent" versus "Competent Person — <discipline>" —
separately from their login role. The code comment states this exists to make
§3301.13.13 "signed as Superintendent" provable.

**Unaddressed / for the reviewer's attention:**

1. **A rendered document can differ from the stored one.** Two overlays resolve
   live data at render time rather than from the stored record: the pre-shift
   affirmation overlay (`preshift_affirmations`, server.py:22674) and the OSHA
   register's review column and class label (`osha_review_index`, server.py:22559).
   Both were deliberate — each corrects a filed document that otherwise
   contradicted a separate record — and the affirmation overlay prints its
   resolution on the document's face ("Affirmed 11:13"). **But a reviewer
   assessing "cannot undergo further editing or alterations" should know that
   what is printed is not in every particular what is stored.** The stored
   document is not modified; the rendering is composed.
2. **The content hash is not chained.** Each event hashes its own snapshot. There
   is no hash linking an event to its predecessor, so the sequence is not
   tamper-evident as a whole, only each entry individually.
3. **The hash is not externally anchored** — no timestamping authority, no
   third-party notarisation. Integrity rests on the database.

### V.3 — Forgery prevention

> "Electronic site safety documents … must be secure against forgery."

**Partially addressed.** The content hash (V.2) makes an alteration to a signed
snapshot detectable by recomputation. Tenant isolation prevents cross-company
writes (`require_project_access`, `_assert_project_access`). Signature affirmation
is checked for actual ink rather than mere presence — `_is_affirmed_signature`,
server.py:22288, exists because an empty-but-truthy signature object was
previously accepted and printed as affirmed.

**Unaddressed:** no cryptographic signing of the record by the signer (the hash is
computed by the server, not signed by a key the signer holds); no PKI; no
digital-certificate binding. A party with database access could write a consistent
record and hash. Whether the bulletin contemplates defence against that adversary
is a question for the reviewer.

### V.4 — Record retention

> "Electronic site safety documents … must be preserved and accessible for up to
> seven (7) years following the completion of the job."

**Partially addressed, and the largest identified gap.**

**What exists:** `logbooks`, `signature_events`, `signatures`, `daily_signatures`,
`audit_logs`, `checkins` and `workers` are all listed in `SOFT_DELETE_NEVER_PURGE`
(server.py:37594), which the scheduled purge refuses to touch. The purge is
additionally **disabled by default** (`SOFT_DELETE_PURGE_ENABLED`, default
`false`), retains for 90 days when enabled, and operates on only five collections,
none of which hold this log. Signature images are stored **inline** in the
document (base64 or vector strokes), not as external objects, so a signature
cannot be orphaned by object-store deletion.

**What is missing, stated plainly:**

1. **There is no job-completion date.** The seven-year clock starts at "completion
   of the job", and the `projects` record has no field recording it. Project
   `status` defaults to `"active"`; the only terminal transition in the code is a
   deletion path (`project_mark_delete`, server.py:11083). **The retention period
   is therefore not currently computable for any project.**
2. **A hard-delete path removes object-store contents by prefix.** The project
   hard-delete enumerates and deletes R2 objects under the project prefix
   (server.py:11151). Photographs attached to logbook entries live there. The
   logbook rows survive; **referenced images would not.**
3. **Nothing enforces or measures the seven years.** No retention field, no
   audit that a record still exists, no bar on deletion within the period.
4. **Accessibility over seven years is not addressed.** "Preserved and
   accessible" implies retrieval after the job, after a subscription ends, and
   after a customer relationship ends. No such provision exists.

### V.5 — Intent and consent

> "All involved parties must clearly intend to sign electronically and agree to
> conduct transactions electronically."

**BUILT.** Implemented in `backend/lib/esra_consent.py` and two endpoints, and
in production since `ad4625b` (2026-08-30).

> **CORRECTION, AND THE REASON IT IS FLAGGED HERE.** The first issue of this
> document said consent was NOT BUILT. That was true when the text was written
> and **false by the time it was published**: this file and the consent code
> landed in the *same commit*, `ad4625b`, and the text was not revised. A
> reviewer reading the first issue was told the system had no consent record
> while the commit that delivered the document also delivered one. The error is
> recorded rather than quietly overwritten, because a compliance document whose
> corrections are invisible is worth less than one that shows them.

What is stored, per agreement (`esra_consents`, one row per agreement,
append-only, nothing updated in place):

| field | why |
|---|---|
| `user_id`, `user_email`, `user_name`, `role_at_time`, `company_id` | denormalised so the consent stays readable when the user row is renamed, soft-deleted, or moved between companies |
| `consent_version` | dated, e.g. `2026-08-30.1` |
| **`consent_text`** | **the wording verbatim.** A version pointer alone resolves, years later, to whatever the registry says *then* — text the person never saw |
| `agreed_at`, `ip_address`, `user_agent` | when, and from where |

`lib/esra_consent.py` keeps an **append-only registry of every version ever
shown**, so a stored row can be checked against what it claims to have said.
`verify_stored_consent` distinguishes four outcomes and reports
`UNKNOWN_VERSION` as *"this build cannot check the row"* rather than *"the row
is wrong"* — a distinction that matters if a row is examined by a later build.

It is **one-time at account setup**, not a per-entry confirmation: a signer
learns to click through anything seen daily, and a consent clicked through is
poor evidence of intent. `esra_consents` is in `SOFT_DELETE_NEVER_PURGE` —
a consent is evidence *about* a signature and outlives the signature it
authorises.

It **fails closed**: a read error, a missing database, a missing user id, or a
superseded version all report "no current consent". Failing open on a consent
check is the one direction that cannot be undone, because an entry signed
without consent cannot be consented to afterwards.

**What is still not addressed under V.5:** the consent covers the account
holder signing on their own account. It does not, and cannot, speak for a
signature applied by anyone else.

### V.6 — Signature integrity

> "The software used must maintain the integrity of signatures, making any changes
> detectable after signing."

**In production.** `content_snapshot` stores the full document as signed, and
`content_hash` (computed server.py:15435, stored server.py:15487) is a SHA-256 over its canonical serialization. A
subsequent change to the stored document produces a different hash on
recomputation.

**Unaddressed:** nothing recomputes the hash on a schedule or on read, so a
divergence would be detectable **on inspection** but is not actively detected. No
alert exists. See also V.2's notes on chaining and external anchoring.

### V.7 — User authentication

> "Individuals who sign electronic records must be verified. This can be achieved
> through various means such as email or phone verification, multi-factor
> authentication, in-person verification, or digital certificates."

**Partially addressed.** Signing requires an authenticated session (JWT). The
signature event records the **server-verified** role alongside the client-claimed
one (server.py:15482), so a claim to have signed in a capacity the account does
not hold is visible in the record.

**Unaddressed:**

1. **No multi-factor authentication.** Password only.
2. **No email or phone verification of the signer at signing time.**
3. **No digital certificates.**
4. **The per-project password path has been ABANDONED.** It would have
   authenticated a *device session* on a shared tablet and then attributed the
   signature to the *named superintendent* on the project record — two
   different things by construction. Nothing in the record would distinguish a
   superintendent who signed on his own account from one signed for by whoever
   held the tablet.

   **Withdrawn from the roadmap entirely on 2026-08-31, not deferred**, after
   two independent readings reached the same conclusion: attribution to a named
   superintendent regardless of who typed a shared password does not satisfy
   V.7's requirement that individuals who sign be *verified*, and the log in
   question is signed under a **DOB licence**. It will not be built.

   The superintendent signs on his own account (`role: "superintendent"`,
   shipped `ad4625b`), on the site device or his own phone.

Accounts are additionally gated on approval before they can incur cost
(`require_approved`), which is an authorisation control rather than an identity
one.

### V.8 — Association with the document

> "Software should ensure that signatures are clearly connected to the specific
> document they authenticate."

**In production.** Each signature event carries `document_type`, `document_id` and
`version` (server.py:15472-15474), binding it to one document and one revision. The
content snapshot is stored on the event itself, so the association survives even
if the source document is later altered or removed.

---

## Bulletin § II — Responsibility for compliance

> "The permit holder or other entity responsible per Section 3301.7 … for
> maintaining and making the document available is responsible for ensuring
> compliance with this Bulletin when such document is made available in an
> electronic format."

**Responsibility rests on the permit holder, not on the software vendor.** The
reviewer may wish to consider what the vendor represents to the permit holder
about compliance, and what the permit holder must do independently — the tablet
requirement (§ III) being the clearest example of an obligation no software can
discharge.

---

## Bulletin § VI and § VII — Boundaries

**§ VI:** the bulletin does not extend to other records required by the
Construction Codes; those "must continue to be maintained in paper format",
including construction documents, shop drawings, monitoring reports and special
inspection records. **Nothing in this assessment should be read as covering any
document outside the site-safety set.**

**§ VII:** compliance with the bulletin does not relieve anyone of obligations to
FDNY, DOT, OSHA, EPA or DEP.

---

## Summary of what is not built

Listed without mitigation, so that nothing is obscured.

| # | requirement | status |
|---|---|---|
| V.5 | Intent and consent | **BUILT** — `ad4625b`. See the correction in V.5. |
| V.4 | Retention — 7 years post-completion | **Not computable.** No job-completion date exists. |
| V.4 | Object-store retention | Hard-delete removes photographs by prefix (server.py:11151). |
| V.4 | Accessibility after the relationship ends | Not addressed. |
| V.7 | Multi-factor / verified signer at signing | Not built. |
| V.7 | Shared-device password path attribution | **Abandoned 2026-08-31.** Will not be built. |
| V.3 | Cryptographic signing by the signer | Not built. Server-computed hash only. |
| V.2 | Hash chaining across events | Not built. |
| V.2 | External timestamp anchoring | Not built. |
| V.6 | Active integrity monitoring | Not built. Detectable on inspection only. |
| V.2 | Render-time overlays | Two exist; printed output is composed, not a byte copy of storage. |
| III | Tablet availability evidence | Not addressed; operational obligation. |
| — | The superintendent log itself | **Not built.** |

## Revision history

| date | commit | change |
|---|---|---|
| 2026-08-30 | `448410f` | First issue. Assessed against Bulletin 2024-007 for the BC 3301.13.13 log only. |
| 2026-08-31 | — | **V.5 corrected from NOT BUILT to BUILT.** The first issue was published in the same commit (`ad4625b`) that delivered the consent record and was not revised; a reviewer was told no consent existed while it did. V.7's password path moved from "designed, unresolved" to **abandoned**. |
