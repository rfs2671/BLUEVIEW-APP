# WhatsApp Phase 0 — security and stability (2026-10-07)

Base: `main` @ `772e4ef`. The source audit is
[`whatsapp-audit-2026-10-07.md`](whatsapp-audit-2026-10-07.md); its line numbers
refer to `main` before this change. The line numbers below refer to
`backend/server.py` **after** it.

## The invariant

    WhatsApp group -> company -> project

The group record is never trusted on its own word. Every path that can put
project data into a chat proves the project belongs to the group's company
first, by reading the project back with that company in the filter
(`_bot_project_scope`). If ownership cannot be established conclusively, the
bot gives no project answer and posts nothing project-specific.

- **Rules** live in `backend/lib/wa_security.py`. It is pure and needs no
  database.
- **Reads** are done by the helpers in `server.py`:
  - `_bot_project_scope`, `_resolve_group_binding`, `_group_history_filter`
  - `_assert_link_project_owned`, `_assert_group_not_owned_elsewhere`

## Security events

Each event is one log line, `[security-event] {json}`, at WARNING. The fields
come from an allow-list: `company_id`, `project_id`, `wa_group_id`, `user_id`,
`caller_company_id`, `project_company_id`, `other_company_id`, `companies`,
`projects`, `row_count`, `reason`, `remote_addr`, and `timestamp`. Unknown keys
are dropped, so a message body, plan text, token or header cannot reach the
log.

| event | when |
|---|---|
| `whatsapp_webhook_rejected` | webhook token missing, wrong, or secret unset |
| `whatsapp_cross_company_link_attempt` | initiate, verify, or pending-link names another company's project |
| `whatsapp_link_project_not_found` | same, project missing or deleted |
| `whatsapp_duplicate_group_link_attempt` | a link would create a second company's active binding |
| `whatsapp_duplicate_group_ownership` | an inbound message or job finds a group bound to more than one company or project |
| `whatsapp_group_binding_invalid` | a binding row has no company or no project, or the read failed |
| `whatsapp_group_project_not_owned` | the binding's project is missing or belongs to another company |
| `whatsapp_agent_scope_refused`, `whatsapp_tool_scope_refused`, `whatsapp_plan_send_refused`, `whatsapp_checklist_scope_refused` | defence-in-depth refusals below the binding |
| `whatsapp_plan_send_wrong_group` | the plan-image debug send targeted a group not bound to that project |
| `whatsapp_dm_contact_ambiguous` | a DM came from a number registered under two companies |

## Deploy order (no inbound message is dropped)

The new code rejects every webhook call that lacks the secret, and it also
rejects all calls when the secret is unset. The secret therefore has to be in
place **before** the code ships. The old code ignores the query string, so
steps 1 and 2 are harmless to the running build.

1. **Railway → backend service → Variables.** Add
   `WAAPI_WEBHOOK_SECRET` = the output of
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   It must be at least 32 bytes; anything shorter is treated as unset.
   Saving a variable restarts the old build, which ignores it.
2. **WaAPI dashboard → Instances → (the Levelog instance) → Webhook.** Change
   the webhook URL from
   `https://api.levelog.com/api/whatsapp/webhook`
   to
   `https://api.levelog.com/api/whatsapp/webhook?token=<the same secret>`.
   Leave the subscribed events unchanged. The old build keeps answering 200,
   because it ignores the query string.
3. **Merge and deploy this PR.** From the first request after the deploy,
   calls carry the token and are accepted.
4. **Verify.** Send one message in a linked group and confirm the bot answers.
   Then check the logs for a burst of `whatsapp_webhook_rejected`. A burst
   means the URL in step 2 does not match the variable in step 1.

**Rollback.** Revert the deploy. The old build ignores the token, so the WaAPI
URL can stay as it is.

WaAPI documents no webhook signature or custom-header option. Its SDK's
`updateInstance` takes only a webhook URL and a list of events. That is why the
secret is a query parameter. It is kept out of the logs in four places:
- `_RedactWebhookTokenFilter` rewrites uvicorn's access line.
- Sentry's URL and `query_string` are scrubbed for this path.
- The `[req]` request line prints the path only.
- `whatsapp_webhook_log` stores headers and body, never the URL.

The token is still visible in the WaAPI dashboard to anyone with access to it,
and may appear in Railway's edge HTTP logs. See "Not fixed" below.

## The unique index — written, NOT built

Do not build this until the PENDING duplicate query below returns nothing:

```js
db.whatsapp_groups.createIndex(
  { wa_group_id: 1 },
  { name: "whatsapp_groups_one_active_binding",
    unique: true,
    partialFilterExpression: { active: true } }
)
```

The definition is also kept as `wa_security.PROPOSED_UNIQUE_INDEX`.

## PENDING — read-only queries to run before or after deploy

```js
// Duplicate ownership: groups active under more than one company or project.
// Every row returned is a group the bot now refuses to serve.
db.whatsapp_groups.aggregate([
  { $match: { active: true } },
  { $group: { _id: "$wa_group_id", companies: { $addToSet: "$company_id" },
              projects: { $addToSet: "$project_id" }, n: { $sum: 1 } } },
  { $match: { $or: [ { "companies.1": { $exists: true } },
                     { "projects.1": { $exists: true } } ] } }
])

// Mis-bound groups: the group's company does not own its project.
// The bot now refuses these too.
db.whatsapp_groups.aggregate([
  { $match: { active: true } },
  { $lookup: { from: "projects", let: { pid: "$project_id" },
      pipeline: [ { $match: { $expr: { $eq: [ { $toString: "$_id" }, { $toString: "$$pid" } ] } } },
                  { $project: { company_id: 1, is_deleted: 1 } } ], as: "p" } },
  { $unwind: { path: "$p", preserveNullAndEmptyArrays: true } },
  { $match: { $or: [ { p: null }, { "p.is_deleted": true },
      { $expr: { $ne: [ { $toString: "$company_id" }, { $toString: "$p.company_id" } ] } } ] } },
  { $project: { wa_group_id: 1, project_id: 1, company_id: 1, project_company: "$p.company_id" } }
])

// Rows the new company filters would hide.
// dob_logs / material_requests / whatsapp_checklists without a company_id.
db.dob_logs.countDocuments({ $or: [ { company_id: { $exists: false } }, { company_id: null }, { company_id: "" } ] })
db.material_requests.countDocuments({ $or: [ { company_id: { $exists: false } }, { company_id: null }, { company_id: "" } ] })
db.whatsapp_checklists.countDocuments({ $or: [ { company_id: { $exists: false } }, { company_id: null }, { company_id: "" } ] })
// Group messages stored without a company (excluded from bot history / digests).
db.whatsapp_messages.countDocuments({ sender: { $ne: "bot" }, $or: [ { company_id: { $exists: false } }, { company_id: null } ] })

// Is anybody's debug access about to disappear? Only the flag passes now.
db.users.find({ is_platform_operator: true }, { email: 1 })

// Numbers registered under two companies (their DMs now get no data).
db.whatsapp_contacts.aggregate([
  { $match: { user_id: { $ne: null } } },
  { $project: { company_id: 1, d: { $replaceAll: { input: "$phone", find: "+", replacement: "" } } } },
  { $group: { _id: "$d", companies: { $addToSet: "$company_id" } } },
  { $match: { "companies.1": { $exists: true } } }
])
```

## Not fixed in this PR, and why

- **Collections that carry no `company_id` are gated rather than filtered.**
  `checkins`, `logbooks`, `daily_logs`, `document_page_index` and
  `document_page_chunks` are read by `project_id`. Each read sits behind
  `_bot_project_scope(company_id, project_id)` in the same function. Adding
  `company_id` to those filters without knowing whether every row carries one
  would silently hide data. It can be tightened once the PENDING counts are
  known.
- **Bot reply rows in `whatsapp_messages` still carry no company or project.**
  `send_whatsapp_message` has around 30 call sites and knows neither. History
  and digests admit bot rows only from the current binding's `linked_at`
  onward (`_group_history_filter`).
- **The token is visible in the WaAPI dashboard and possibly in Railway's edge
  logs.** WaAPI offers no header or signature alternative. Rotate it by
  changing both values (steps 1 and 2 above) together.
- **No unique index** (see above): data first.
- **Security events go to the app log, not a collection.** Rejected-webhook
  events can be triggered by anyone on the internet. A collection would be an
  unbounded write path for them, and the log is already shipped.
