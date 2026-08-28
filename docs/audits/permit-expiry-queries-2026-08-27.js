// Permit-expiry claim — production evidence queries.
// Read-only. Nothing here writes. Paste section by section into mongosh.
//
// Companion to docs/audits/permit-expiry-claim-2026-08-27.md
//
// Order matters: §0 first (it decides whether §5 is urgent), then §3.

// ═══════════════════════════════════════════════════════════════════
// §0 — Has ANY notification ever actually left the building?
// ═══════════════════════════════════════════════════════════════════
// notification_log is written on EVERY outcome (backend/lib/notifications.py
// :477-513), so absence of a row means the cron never reached send_notification;
// presence of a non-"sent" row means it reached it and was stopped, and the
// status says by what.
//
// NOTIFICATIONS_ENABLED defaults to "false" (notifications.py:61-63). If it was
// never set on Railway, everything here is `suppressed_flag_off` and nothing
// was delivered.

db.notification_log.aggregate([
  { $group: { _id: "$status", n: { $sum: 1 },
              first: { $min: "$sent_at" }, last: { $max: "$sent_at" } } },
  { $sort: { n: -1 } }
])

// ═══════════════════════════════════════════════════════════════════
// §1 — renewal_reminder_cron specifically: did T-30/14/7 fire?
// ═══════════════════════════════════════════════════════════════════
// Trigger names: backend/server.py:34681-34685.

const REMINDER_TRIGGERS = [
  "renewal_t_minus_30", "renewal_t_minus_14", "renewal_t_minus_7"
];

// 1a. Every outcome, per trigger. `sent` is the only one that reached a person.
db.notification_log.aggregate([
  { $match: { trigger_type: { $in: REMINDER_TRIGGERS } } },
  { $group: { _id: { trigger: "$trigger_type", status: "$status" },
              n: { $sum: 1 },
              first: { $min: "$sent_at" }, last: { $max: "$sent_at" },
              recipients: { $addToSet: "$recipient" } } },
  { $sort: { n: -1 } }
])

// 1b. The number that decides the order of removal.
db.notification_log.countDocuments({
  trigger_type: { $in: REMINDER_TRIGGERS },
  status: "sent"
})

// 1c. THE DUPLICATE BLAST. One (recipient, day, trigger) with n > 1 means that
// person got n identical emails that morning — one per duplicate renewal row,
// each with its own permit_renewal_id, which is exactly why the 23h
// idempotency window (notifications.py:201-206, keyed on permit_renewal_id +
// trigger_type + recipient) did not collapse them.
db.notification_log.aggregate([
  { $match: { trigger_type: { $in: REMINDER_TRIGGERS }, status: "sent" } },
  { $group: {
      _id: { recipient: "$recipient",
             day: { $dateToString: { format: "%Y-%m-%d", date: "$sent_at" } },
             trigger: "$trigger_type" },
      n: { $sum: 1 },
      renewal_ids:  { $addToSet: "$permit_renewal_id" },
      days_claimed: { $addToSet: "$metadata.days_until_expiry" },
      subjects:     { $addToSet: "$subject" } } },
  { $match: { n: { $gt: 1 } } },
  { $sort: { n: -1 } }
])

// 1d. Collapse the duplicated sends back to real permits. If distinct
// renewal_ids resolve to ONE raw_dob_id, the customer was emailed n times
// about a single permit.
db.notification_log.aggregate([
  { $match: { trigger_type: { $in: REMINDER_TRIGGERS }, status: "sent" } },
  { $addFields: { _rid: { $convert: { input: "$permit_renewal_id",
                                      to: "objectId", onError: null } } } },
  { $match: { _rid: { $ne: null } } },
  { $lookup: { from: "permit_renewals", localField: "_rid",
               foreignField: "_id", as: "_r" } },
  { $addFields: { _r: { $first: "$_r" } } },
  { $addFields: { _log_oid: { $convert: { input: "$_r.permit_dob_log_id",
                                          to: "objectId", onError: null } } } },
  { $lookup: { from: "dob_logs", localField: "_log_oid",
               foreignField: "_id", as: "_log" } },
  { $group: {
      _id: { raw_dob_id: { $first: "$_log.raw_dob_id" },
             recipient: "$recipient" },
      emails_sent:  { $sum: 1 },
      renewal_ids:  { $addToSet: "$permit_renewal_id" },
      triggers:     { $addToSet: "$trigger_type" },
      days_claimed: { $addToSet: "$metadata.days_until_expiry" },
      // null raw_dob_id = the renewal points at a dob_logs row that no longer
      // exists (reset-resync deleted it). Those emails rendered job number "—"
      // (server.py:34716-34720 falls back to renewal.job_number, which is null).
      first: { $min: "$sent_at" }, last: { $max: "$sent_at" } } },
  { $sort: { emails_sent: -1 } }
])

// 1e. Every recipient who has ever received one, with a count. This is the
// customer-contact list if disclosure is needed.
db.notification_log.aggregate([
  { $match: { trigger_type: { $in: REMINDER_TRIGGERS }, status: "sent" } },
  { $group: { _id: "$recipient", n: { $sum: 1 },
              first: { $min: "$sent_at" }, last: { $max: "$sent_at" },
              triggers: { $addToSet: "$trigger_type" } } },
  { $sort: { n: -1 } }
])

// ═══════════════════════════════════════════════════════════════════
// §2 — Exposure of the daily-report claim itself
// ═══════════════════════════════════════════════════════════════════
// report_emails is written per (project, date) with the recipient list and
// who actually got it (backend/server.py:27418-27424).

const P = db.projects.findOne({ name: /588\s*Thomas/i }, { _id: 1, name: 1, address: 1 });
P

db.report_emails.aggregate([
  { $match: { project_id: P._id.toString() } },
  { $group: { _id: null, days: { $sum: 1 },
              first: { $min: "$date" }, last: { $max: "$date" },
              recipients: { $addToSet: "$actually_sent_to" } } }
])

// How many of those carried a non-zero permit count. The count itself was
// never persisted, so this is the closest proxy: the daily-report sends that
// landed, cross-checked against whether eligible renewal rows existed that day.
db.notification_log.countDocuments({
  trigger_type: "project_daily_report",
  status: "sent",
  "metadata.project_id": P._id.toString()
})

// ═══════════════════════════════════════════════════════════════════
// §3a — Does any permit_renewals row have a non-null job_number?
// ═══════════════════════════════════════════════════════════════════
// Prediction: rows written after the ELIGIBILITY_REWRITE_MODE=live cutover are
// null by construction (backend/lib/eligibility_dispatcher.py:178).

db.permit_renewals.countDocuments({
  is_deleted: { $ne: true },
  job_number: { $nin: [null, ""] }
})

// Split, so the `newest` on the has-job bucket dates the cutover.
db.permit_renewals.aggregate([
  { $match: { is_deleted: { $ne: true } } },
  { $group: {
      _id: { has_job:  { $not: [ { $in: ["$job_number",  [null, ""]] } ] },
             has_type: { $not: [ { $in: ["$permit_type", [null, ""]] } ] } },
      n: { $sum: 1 },
      oldest: { $min: "$created_at" },
      newest: { $max: "$created_at" } } },
  { $sort: { n: -1 } }
])

// ═══════════════════════════════════════════════════════════════════
// §3b — Of the rows that have a job_number, is days_until_expiry right?
// ═══════════════════════════════════════════════════════════════════
// days_until_expiry was computed at write time, so it must equal
// (current_expiration - created_at) in whole days. Tolerance ±1 for the
// tz/rounding boundary.
//
// A row is sound ONLY if it lands in the `sound` bucket.

db.permit_renewals.aggregate([
  { $match: {
      is_deleted: { $ne: true },
      job_number: { $nin: [null, ""] },
      days_until_expiry: { $ne: null },
      current_expiration: { $nin: [null, ""] } } },

  // current_expiration is mixed-format (ISO and M/D/YYYY both in prod).
  // Try ISO, fall back to MDY, else null.
  { $addFields: { _exp: { $ifNull: [
      { $dateFromString: { dateString: "$current_expiration",
                           onError: null, onNull: null } },
      { $dateFromString: { dateString: "$current_expiration",
                           format: "%m/%d/%Y", onError: null, onNull: null } } ] } } },
  { $match: { _exp: { $ne: null } } },

  { $addFields: { _expected: { $floor: { $divide: [
      { $subtract: ["$_exp", "$created_at"] }, 86400000 ] } } } },
  { $addFields: { _drift: { $abs: {
      $subtract: ["$days_until_expiry", "$_expected"] } } } },

  { $facet: {
      sound:  [ { $match: { _drift: { $lte: 1 } } }, { $count: "n" } ],
      broken: [ { $match: { _drift: { $gt:  1 } } }, { $count: "n" } ],
      worst:  [ { $sort: { _drift: -1 } }, { $limit: 10 },
                { $project: { _id: 1, job_number: 1, permit_type: 1, status: 1,
                              current_expiration: 1, days_until_expiry: 1,
                              _expected: 1, _drift: 1, created_at: 1,
                              permit_dob_log_id: 1 } } ] } }
])

// Rows excluded above because current_expiration would not parse at all —
// they are neither sound nor broken, they are unreadable. Counted separately
// so the three buckets add up.
db.permit_renewals.aggregate([
  { $match: { is_deleted: { $ne: true },
              job_number: { $nin: [null, ""] },
              days_until_expiry: { $ne: null },
              current_expiration: { $nin: [null, ""] } } },
  { $addFields: { _exp: { $ifNull: [
      { $dateFromString: { dateString: "$current_expiration",
                           onError: null, onNull: null } },
      { $dateFromString: { dateString: "$current_expiration",
                           format: "%m/%d/%Y", onError: null, onNull: null } } ] } } },
  { $match: { _exp: null } },
  { $count: "unparseable" }
])

// ═══════════════════════════════════════════════════════════════════
// §3c — Reproduce the "3" for 588 Thomas
// ═══════════════════════════════════════════════════════════════════

const PIDS = [P._id.toString(), P._id];   // writers store both forms
const ELIGIBLE = ["eligible", "needs_insurance", "ineligible_insurance",
                  "ineligible_license", "draft_ready", "awaiting_gc"];

// 3c-i. The exact rows _count_permits_expiring_soon walks
// (backend/server.py:27239-27253).
db.permit_renewals.find({
  project_id: { $in: PIDS },
  status: { $in: ELIGIBLE },
  is_deleted: { $ne: true }
}, { permit_dob_log_id: 1, job_number: 1, permit_type: 1, current_expiration: 1,
     days_until_expiry: 1, status: 1, created_at: 1 })
  .sort({ created_at: 1 })

// 3c-ii. Collapse them to real permits. raw_dob_id IS the stable per-permit
// key; permit_dob_log_id is not. `rows: 3` against a single _id is the proof
// that "3 permits" is one permit counted three times.
db.permit_renewals.aggregate([
  { $match: { project_id: { $in: PIDS }, is_deleted: { $ne: true },
              status: { $in: ELIGIBLE } } },
  { $addFields: { _log_oid: { $convert: { input: "$permit_dob_log_id",
                                          to: "objectId", onError: null } } } },
  { $lookup: { from: "dob_logs", localField: "_log_oid",
               foreignField: "_id", as: "_log" } },
  { $addFields: { raw_dob_id: { $first: "$_log.raw_dob_id" } } },
  { $group: { _id: "$raw_dob_id", rows: { $sum: 1 },
              expirations: { $addToSet: "$current_expiration" },
              days_values: { $addToSet: "$days_until_expiry" },
              statuses:    { $addToSet: "$status" },
              renewal_ids: { $push: "$_id" } } },
  { $sort: { rows: -1 } }
])

// 3c-iii. Portfolio-wide version of the same collapse — how much of the whole
// collection is duplication.
db.permit_renewals.aggregate([
  { $match: { is_deleted: { $ne: true }, status: { $in: ELIGIBLE } } },
  { $addFields: { _log_oid: { $convert: { input: "$permit_dob_log_id",
                                          to: "objectId", onError: null } } } },
  { $lookup: { from: "dob_logs", localField: "_log_oid",
               foreignField: "_id", as: "_log" } },
  { $addFields: { raw_dob_id: { $first: "$_log.raw_dob_id" } } },
  { $group: { _id: "$raw_dob_id", rows: { $sum: 1 } } },
  { $group: { _id: null,
              distinct_permits: { $sum: 1 },
              total_rows: { $sum: "$rows" },
              max_rows_for_one_permit: { $max: "$rows" } } }
])

// 3c-iv. Orphans: renewal rows whose permit_dob_log_id no longer resolves.
// These are the reset-resync leftovers. Their reminder emails rendered the
// job number as "—".
db.permit_renewals.aggregate([
  { $match: { is_deleted: { $ne: true }, status: { $in: ELIGIBLE } } },
  { $addFields: { _log_oid: { $convert: { input: "$permit_dob_log_id",
                                          to: "objectId", onError: null } } } },
  { $lookup: { from: "dob_logs", localField: "_log_oid",
               foreignField: "_id", as: "_log" } },
  { $match: { _log: { $size: 0 } } },
  { $group: { _id: "$project_id", orphans: { $sum: 1 },
              oldest: { $min: "$created_at" },
              newest: { $max: "$created_at" } } },
  { $sort: { orphans: -1 } }
])
