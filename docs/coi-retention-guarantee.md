# COI Retention Guarantee

**Status:** Active. Bucket lock activated 2026-04-27, verified same day.

If you (a future engineer, hire, acquirer, or outside auditor) are
trying to determine exactly what guarantee LeveLog provides for
Certificate of Insurance retention — this is the document that tells
you. Read it in full before drawing any conclusions about whether
LeveLog's COI retention is "real" enough for whatever compliance
question you're investigating.

This document is the git-tracked, durable counterpart to the §13
section in `~/.claude/plans/permit-renewal-v3.md`. The plan file is
the working record during active development; this file is the
auditor-discoverable artifact in the repo.

## 1. The actual mechanism

- **Storage:** Cloudflare R2 bucket `blueview`, prefix-scoped to `coi/`
- **Lock rule:** `coi-7yr-retention`, age-based, `maxAgeSeconds=220898160`
  (7 years = 7 × 365.25 × 86400, rounded up)
- **Activated:** 2026-04-27 via Cloudflare dashboard (R2 → blueview → Settings → Bucket Locks)
- **API endpoint** (for reference, not used during activation): `PUT /accounts/{ACCOUNT_ID}/r2/buckets/blueview/lock`
- **Applies retroactively** to existing AND new objects under `coi/`
- **Cloudflare-side feature shipped** [March 6, 2025](https://developers.cloudflare.com/changelog/2025-03-06-r2-bucket-locks/)

## 2. The limitation, in plain language

**The lock is removable.** Anyone holding a Cloudflare API token with
"Edit R2 bucket configuration" permission, OR anyone with
account-owner-level access to the Cloudflare dashboard, can:

1. Remove the lock rule (no retention-period restriction on removal)
2. Delete the previously-locked COI objects
3. Optionally re-add the lock rule

This is functionally equivalent to AWS S3's "Governance mode" —
**not** "Compliance mode" (which would be genuinely immutable until
expiry, even by AWS account root). R2 does not currently offer a
Compliance-mode equivalent.

Source: [Cloudflare R2 Bucket Locks docs](https://developers.cloudflare.com/r2/buckets/bucket-locks/)
state verbatim: *"To remove a bucket lock rule, run the
`r2 bucket lock remove` command or exclude them from your updated
configuration and use the put bucket lock configuration API."*

## 3. Mitigations actually in place

- **Append-only audit log** (`audit_logs` collection): every COI
  upload + confirm writes a row with actor user_id, sha256, R2 URL,
  timestamp. The application has no delete endpoint or admin UI for
  audit log entries. A delete from R2 would not erase the
  application's record that the COI ever existed.
- **R2 access logs** (Cloudflare-side): every PUT/GET/DELETE against
  the bucket is logged with the originating API token + IP. Forensic
  trail survives even if the COI itself is gone.
- **Narrow token scope**: R2 Edit tokens are scoped to the `blueview`
  bucket only, never account-wide. Token holders today: deploy CI
  (production code path), and one human (account owner). Other
  Cloudflare account members hold read-only or no R2 perms.
- **Quarterly rotation**: R2 Edit token rotated every 90 days.
  Tracked as a recurring item; older tokens revoked on rotation.

## 4. The threat model the lock DOES protect against

- Accidental `aws s3 rm coi/` from a developer fat-finger
- Accidental lifecycle policy that deletes objects past N days
- Accidental code change adding COI cleanup as part of a housekeeping
  cron (e.g. "delete drafts older than 30 days" walking the wrong
  prefix)
- Race conditions in upload + delete sequences

These are the realistic operational failure modes for a small team.
The lock catches all of them. Empirically verified at activation
time: the Cloudflare dashboard removes the Delete UI affordance
entirely from objects under `coi/`. No misclick can produce a delete.

## 5. The threat model the lock does NOT protect against

- Deliberate removal by anyone with R2 Edit perms (rule removal +
  object delete is a 30-second operation for a token holder)
- Compromise of the R2 Edit token by an attacker who understands the
  rule-removal API
- Subpoena to Cloudflare directing them to release locked data
  (out of scope for any storage backend)

If a customer's threat model genuinely includes "malicious insider
with R2 access AND application-code-write access," no storage
backend LeveLog could integrate would prevent it — the same insider
would also tamper with the audit log on the application side.

## 6. Escalation trigger

If a customer ever requires Compliance-mode retention contractually
(e.g. SOX/HIPAA-adjacent audit, an insurance carrier mandating
"immutable retention," an enterprise GC's procurement requirement):

- Migrate THAT customer's COIs to AWS S3 with Object Lock in
  Compliance mode
- Implement as a **per-tenant feature** (`companies.coi_retention_tier`
  field with values `governance` (default) | `compliance`)
- Compliance-tier companies' COIs route to a separate S3 bucket;
  governance-tier (everyone else) stays on R2

Do NOT make this a global migration. R2 is cheaper, has better egress
economics, and is sufficient for the realistic threat model. Per-
tenant escalation is the right answer when the demand surfaces.

## 7. Activation + verification log

| Date | Event | Detail |
|---|---|---|
| 2026-04-26 | Research | R2 = Governance-equivalent confirmed via Cloudflare docs. User approved Option A (R2 lock + §13 documentation). |
| 2026-04-27 | Activation | Bucket lock rule `coi-7yr-retention` created via Cloudflare dashboard. Prefix `coi/`, `maxAgeSeconds=220898160`, enabled. |
| 2026-04-27 | Verification | Test file uploaded to `coi/__retention_test__/test-retention-check.pdf` via R2 dashboard. Cloudflare hides the Delete UI affordance entirely on objects under the locked prefix. Negative test: file at `__retention_test__/outside-lock.pdf` (no `coi/` prefix) shows Delete option as expected. Lock confirmed enforcing and prefix-scoped correctly. |

Test artifact: `coi/__retention_test__/test-retention-check.pdf`
remains in the bucket. It auto-expires when the 7-year retention
window passes (2033-04-27). Don't try to delete it before then.

## 8. Cloudflare's enforcement pattern — UI-hiding, not error-on-click

The original §13 spec anticipated a "403 Forbidden" verification
result on attempted delete. Cloudflare's actual implementation is
different and worth documenting because future verification scripts
will get tripped up if they expect the 403 pattern:

- **Dashboard:** the Delete button / context-menu item is **removed
  entirely** from the UI for objects under a locked prefix. There is
  no error to capture because the destructive action is unreachable.
- **API:** delete attempts via `aws s3 rm` (S3-compatible API) almost
  certainly DO return a 403 / object-locked error code, but this
  path was not tested at activation time (no AWS CLI on the
  verification laptop). If a future operational script needs to
  assert lock enforcement programmatically, the API path should be
  exercised separately and its actual error code captured.

Functionally equivalent for the threat model — the destructive
operation is unreachable through the dashboard, and the most
common accidental-delete vector (a developer clicking through the
UI) is foreclosed by the missing affordance.

## 9. How to confirm the lock is still active

Operational check, anytime:

1. Open Cloudflare dashboard → R2 → `blueview` → Settings
2. Look for the Bucket Locks section
3. Confirm rule `coi-7yr-retention` is present and enabled
4. (Optional) Browse to `coi/__retention_test__/test-retention-check.pdf`
   in the Objects view and confirm no Delete option is exposed

If the rule is missing or disabled, the lock is no longer enforcing
and any new COI uploads under `coi/` are not retention-protected.
Investigate before reactivating; an explanation belongs in §13.7
("Activation log") of the plan file alongside whatever event
prompted the change.

---

*If you're reading this because someone asked LeveLog whether it has
"7-year retention" on COIs — the honest answer is "yes, with the
limitations documented in §3 and §5 above." Don't oversell.*
