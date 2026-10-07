# WhatsApp integration audit: what exists today, and the gaps for F1–F4

**Commit audited:** `772e4efb9e116ef48d7bc3ae9a70cfb38a9b3613` (origin/main, 2026-10-06 "A guarded script removes the glyph rows…" #662). Local HEAD equals origin/main; this is not a worktree.
**Mode:** read-only. No code changes, branches, commits, DB queries or `railway run`.
**Tags:**
- **V** = VERIFIED, read in code.
- **NF** = NOT FOUND (search terms given).
- **I** = INFERRED (basis given).
- **PENDING** = needs data; a read-only query is given.

All line numbers refer to `backend/server.py` unless a path is given.

> An earlier doc, `docs/audits/whatsapp-integration.md` (last touched 2026-09-18), has drifted. Every one of its line numbers is stale. Several of its claims are now false:
> - The group agent model is gpt-4o, not gpt-4o-mini.
> - Address mode now defaults to loose.
> - Reply-to-bot now counts as addressing.
> - Group voice notes are now on.
>
> Nothing below relies on that doc.

---

# PART 1 — What exists today

## 1. WaAPI client

**Files.** All WhatsApp code is inline in `backend/server.py`, mostly in the block that starts at the `# ==== WHATSAPP INTEGRATION ====` banner at 42700 and runs to about 55180 (V). There are three helper modules:
- `backend/lib/voice_ingest.py` handles Whisper and translation (V).
- `backend/lib/group_match.py` matches a group name to a project (V).
- `backend/scripts/wa_corpus_harness.py` is an offline analysis script that is not wired into anything (V; per its header, idle).

**Environment variable names (V):**

| Name | Line(s) | Note |
|---|---|---|
| `WAAPI_BASE_URL` | 895 | default `https://waapi.app/api/v1` |
| `WAAPI_INSTANCE_ID` | 896 | |
| `WAAPI_TOKEN` | 897 | |
| `WHATSAPP_VENDOR` | 898 | default `waapi` |
| `WAAPI_DISPLAY_NUMBER` | 49162, 51925, 53249 | |
| `WAAPI_BOT_LID` | 49165 | |
| `WA_LINK_TOKEN_TTL_HOURS` | | |
| `OPENAI_API_KEY` | 900 | |

**WaAPI endpoints called.** All use the form `{WAAPI_BASE_URL}/instances/{WAAPI_INSTANCE_ID}/client/action/<x>` (V).

| action | where | purpose |
|---|---|---|
| `send-message` | `send_whatsapp_message` 42753–42814 (URL 42778) | All text sends, to groups and DMs. Optional `replyToMessageId` (42782–42783). |
| `send-media` | 48324–48365 (plan sheet image), 54206–54210 (debug) | Sends a drawing sheet image. |
| `download-media` | `download_audio` 43320–43360 | Fetches voice-note audio. |
| `get-group-info` | `_fetch_group_subject` 51245–51271 | Reads the group name on first sight. |
| send-media variants | `debug_probe_waapi_endpoints` 54097–54144 | Debug probe only. |

**Auth.** Every call sends the header `Authorization: Bearer {WAAPI_TOKEN}` (42779) (V).

**Account type.** I: this is a **WhatsApp Web session gateway**, not the official WhatsApp Business (Cloud) API. The evidence in the code:
- Payload fields are read from `msg._data`, described as "the raw WhatsApp-Web payload" (42822–42825).
- JIDs use `@c.us`, `@g.us` and `@lid` (49123, 42902).
- The `fromMe` flag is used (42885–42901).
- The server must decrypt `.enc` media itself using the `mediaKey` (`_decrypt_whatsapp_media` 43175–43260).
- There are no templates, no `messaging_product`, no `graph.facebook.com`, and no 24-hour-window handling. NF terms: `graph.facebook`, `messaging_product`, `template`, near the send code.

**Single number or per company.** **Single number, platform-wide** (V):
- Only one instance id and one token exist, both global environment variables (896–897).
- `whatsapp_config` holds only `{company_id, is_active, activated_at, activated_by}` (53252–53257). There is no per-company instance or number field.
- Every tenant's groups are served by the same WhatsApp account.

**Rate limiting.**
- Inbound: the webhook has a named limit of `120/1 minute` per IP (`lib/rate_limits.py:176`) (V).
- Outbound: **no throttle, queue or pacing**. NF: `sleep`, `semaphore`, `throttle` in `send_whatsapp_message` 42753–42814.

**Retries.**
- Sends: **none**. A send is one POST with a 15 s timeout. Any exception is logged and the function returns `None` (42785–42814) (V).
- Media downloads: they have their own retry policy (`lib/voice_ingest.py:102`; `download_audio` tries several paths, 43346–43360) (V).

**Error handling.**
- A missing credential returns `None` with a warning (42774–42776) (V).
- Every outbound line passes through `_strip_generic_offer`, which removes trailing "anything else?" filler (42724–42750, applied at 42780) (V).

**Send logging.** A successful send writes the outbound text into `whatsapp_messages` as `{group_id: chat_id, sender: "bot", body, has_audio, message_id: "", timestamp, created_at}` (42790–42803) (V). Two things to note:
- Bot rows carry **no `project_id` and no `company_id`** (V, 42793–42801).
- For a DM reply, the user's JID is stored in the `group_id` field (I, because `chat_id` is `parsed["from"]` at 52181).

`whatsapp_send_log` is **not** a send log. It is the per-day dedupe ledger for the two scheduled jobs (45017–45038) (V).

## 2. Inbound

**Webhook.**
- The only inbound route is `POST /api/whatsapp/webhook` (52206–52238) (V).
- **There is no signature or auth check of any kind.** The route has no `Depends`, no HMAC and no shared secret (52207–52238) (V). NF: `hmac`, `signature`, `x-waapi`, `WEBHOOK_SECRET` near the route.
- It writes every raw payload (first 4000 bytes, plus headers minus cookie and authorization) to `whatsapp_webhook_log` (52217–52227), returns 200, and processes the message in `asyncio.create_task(_process_whatsapp_message(payload))` (52236–52237) (V).

**Parse.** `parse_inbound_message` (42817–43172) returns a normalised dict with these fields (V):
- `event`, `message_id`, `message_id_serialized`
- `from`, `sender` (the author in a group), `to`, `body`
- `quoted_body`, `quoted_type`, `quoted_is_audio`, `quoted_message_id`, `quoted_from_me`, `quoted_author`
- `mentioned_jids`
- `is_group` (`"@g.us" in from`), `group_id`, `timestamp`
- `has_audio`, `audio_url`, `has_image`, `image_url`
- `raw`

Group lifecycle events (`group_join`, `group_leave`, `group_update`) are parsed separately (42849–42879) (V).

**Processing.** `_process_whatsapp_message` (51473–52186) (V):
- Lifecycle events go to `_handle_group_lifecycle` (51484–51486).
- `sender = parsed["sender"].split("@")[0]` (51488). This is digits only, and may be a phone number **or a LID** (I, from the LID handling at 49135–49165).
- **No `fromMe` filter** exists on the processing path (V, 51473–52186). `fromMe` is read only to learn the bot's LID (42883–42901).
- **No check of `whatsapp_config.is_active`** exists on the inbound path. NF `whatsapp_config` in 51473–52186; it is read only at 10034, 15053, 53247, 53295 and 54711.

**Group messages are ingested and stored (V).**
- **Collection:** `whatsapp_messages`.
- **Stored on the main path (51754–51768):** `group_id, project_id, company_id, sender, body, has_audio, transcribed, message_id, message_id_serialized, timestamp, created_at`.
- **Variants:**
  - Voice disabled: a row with `skipped:"voice_disabled"` (51668–51682).
  - Voice download failed: a row with `skipped:"voice_download_failed"` (51630–51645).
- **Not stored:** `mentioned_jids`, `quoted_*`, `quoted_author`, `has_image`/`image_url`, and any `is_group` flag (V, 51754–51768). The reply-to and mention structure is lost once the message has been processed.
- **Dedupe:** on `(group_id, message_id)` before processing (51549–51565) (V).
- **Unlinked groups:** messages from an unlinked group are **not stored**. They upsert a `whatsapp_pending_groups` row and send a one-time bilingual greeting, then return (51567–51581) (V).
- **Indexes (56497–56500):** `(project_id, timestamp desc)` and `(group_id, created_at desc)` (V).
- **Retention:** **no TTL on `whatsapp_messages`** (V; NF: an `expireAfterSeconds` on this collection). The only deletion is the project-delete cascade (`_PROJECT_OWNED_COLLECTIONS` 16796–16818) (V).
- `whatsapp_webhook_log` also has **no TTL and no index** (V; NF in the index blocks), and it holds full raw payloads, DMs included.

**1:1 DMs are processed but not stored as messages (V).**
- The DM branch (51968–52183) never inserts into `whatsapp_messages` (V, read in full).
- The branch first looks up the sender in `whatsapp_contacts` (51970). An unknown sender gets silence (51971–51973).
- Voice notes in a DM go to Whisper. Each voice note writes one row to `whatsapp_voice_events` (52040–52056).
- Text is classified by `classify_intent` (52147), which uses string rules and then gpt-4o-mini (43655–43700).
- Five fixed intents answer from a single project: `_find_project_for_contact` picks the user's first `assigned_projects` entry, otherwise the company's first project (44914–44933).
- The only DM record that persists is the raw payload in `whatsapp_webhook_log`, plus `whatsapp_voice_events` for audio, plus the bot's reply row (I, from the above).

**Media.**

| type | handling |
|---|---|
| Voice and PTT, group | Behind `features.voice_notes`, **default True** (44998). Download via `download_audio`, then `lib/voice_ingest.process_voice_note` (Whisper, then gpt-4o-mini translation to English). The English transcript replaces the body (51684–51749). Idempotent on message_id through `whatsapp_voice_events` (51686–51698). On failure the bot posts "Couldn't play that voice note…" (51698–51702) (V). |
| Voice, DM | The same pipeline, followed by the suffix "Reply CORRECT to confirm…" (51985–52061, 52173–52177) (V). |
| Images | `has_image` and `image_url` are parsed (42936–42940) and **never consumed**. NF: any read of `has_image` or `image_url` outside the parser. |
| PDFs and documents | **Not handled.** NF: a `document` mtype branch in the parser. Only the body or caption text would be stored (I). |
| Quoted voice notes | `quoted_is_audio` is parsed (43123–43130). There is no group consumer (I, not traced further). |

## 3. Group ↔ project mapping

**Linking: two paths, both write to `whatsapp_groups` (V).**
1. **Code path.**
   - `POST /whatsapp/group-link/initiate` (52486–52514) creates a 6-digit code in `whatsapp_link_codes` with a 5-minute TTL (56507).
   - Someone posts the code anywhere in a group message. The webhook matches any `\b\d{6}\b` run against `find_one({"code": code_val})`, which has **no company filter** (51519–51530).
   - `POST /whatsapp/group-link/verify` (52606–52684) then upserts `{company_id, wa_group_id, project_id, linked_by, linked_at, active:True}` and sets `bot_config` with `$setOnInsert`.
   - **Neither initiate nor verify checks that `project_id` belongs to the caller's company or that the caller can access it.** Both use only `require_approved`, and `project_id` is taken straight from the request body (52492–52510, 52615–52650) (V).
2. **Pending-group path.**
   - When the bot is added to a group, or a message arrives from an unknown group, a row is written to `whatsapp_pending_groups` (51288–51378).
   - An admin links it from `POST /whatsapp/pending-groups/{group_id}/link` (53024–53118).
   - This path does check tenancy: `_same_company_or_403(project)` at 53045–53048, plus pending-row visibility (V).
   - A name-based project suggestion comes from `lib/group_match.py` and is advisory only (52996) (V).

**Where group ids live.** `whatsapp_groups.wa_group_id` holds the `…@g.us` JID (V). Indexes are `(company_id, wa_group_id)`, which is **not unique**, and `project_id` (56497–56498) (V).

**Cardinality.**
- One group maps to one project. The webhook resolves a group with `find_one({"wa_group_id", active:True})` (51567), which has **no company filter** (V).
- One project can have many groups: the project listing returns up to 50 (52699–52703), and the code comment says "many groups may bind to one project" (52923–52926) (V).

**GC group versus sub-groups.** There is **no notion of a group type or role.** NF: `group_type`, `gc_group`, `sub_group`, `group_role`, `is_gc`, `trade_group`. Every linked group for a project is treated the same way.

**Resolving senders to users.**
- **On the group path: none.** The sender is stored as JID digits (51488). The agent sees only the last 4 digits, as `[1234]` (50778–50783).
- The only sender lookups are:
  - the on-demand checklist permission check (`_find_whatsapp_contact`, 51877)
  - the DM branch (51970)
  - the pending-group company resolution (51304)
- `_find_whatsapp_contact` (43298–43313):
  - It matches `phone ∈ _contact_phone_variants(sender)` (43283–43295), covering digits, `+digits`, and US 10/11-digit variants.
  - It requires `user_id ≠ None`.
  - It is **not scoped to a company** (V).
- **E.164 normalisation:** `normalize_phone` (2799–2808) strips non-digits and returns `+1XXXXXXXXXX` for 10 digits, otherwise `+digits` (V).
- **Contacts formats:** `whatsapp_contacts` is written in E.164 by user create, update, profile edit and company-admin create. The activation backfill writes bare digits (53266–53270) (V). Reads tolerate both.
- **Workers:** roster workers (`db.workers`) store phones as `XXX-XXX-XXXX` (`format_phone` 2810–2817; check-in 19581–19583). They have **no `user_id` link** and are **never matched to WhatsApp senders** (V/I; NF a `db.workers` phone lookup in the WhatsApp code).
- **LID senders:** if WhatsApp delivers an `@lid` author instead of `@c.us`, the stored `sender` digits are a LID that matches no phone (I, from 49135–49165 and the parser's use of `author`).

## 4. Existing bot / agent

**Group agent: `_run_group_agent`** (50707–51030) (V).

- **Trigger.** It runs only when `_is_bot_addressed` (49390–49530) returns true. Its routes, in order:
  - an explicit mention: the word "levelog", `@levelog`, or a native `@mention` of the bot's phone or LID (`_has_explicit_bot_mention` 49195)
  - a quoted message that mentioned the bot
  - a **reply to a bot message** (`quoted_from_me` or a quoted author matching the bot, 51937–51944)
  - a live 180 s per-sender session (`BOT_SESSION_TTL_SECONDS` 49255, kept in `whatsapp_conversation_state`)
  - in **loose** mode (the default, 44995), additionally any voice note or any soft-trigger word (`_BOT_ADDRESS_SOFT_TRIGGERS` 49113–49118)
- **Before the agent,** these hooks run in order:
  - a checklist-assignment reply (51780–51801)
  - `done N` (51804–51857)
  - `@levelog checklist` / `!checklist` (51859–51912)
- **After the agent,** if a message was not addressed:
  - a once-a-day "I'm here" nudge for question-shaped messages (51999–52000, 49357–49388)
  - material detection (52002–52011)
- **LLM.** OpenAI chat completions with `AGENT_MODEL = "gpt-4o"` (50703), temperature 0.2, `max_tokens` 800 (50704), and at most 4 tool rounds (50870–50881) (V).
  - The DM classifier, material detection and plan-query parse use gpt-4o-mini (43684, 44319, 47854).
  - `_handle_material_receipt` uses gpt-4o (44457).
  - The daily summary uses gpt-4o (54864).
  - Checklist extraction uses gpt-4o-mini (55016).
  - Plan indexing uses Qwen VL. Embeddings use `text-embedding-3-small` (45444) (V).
- **Prompts.** All are inline in server.py:
  - `_AGENT_STANCE` (49858)
  - `_AGENT_SYSTEM_PROMPT_BASE` (49882)
  - `_AGENT_NOREPLY_CLAUSE` (50087)
  - `_AGENT_EXPLICIT_CLAUSE` (50097)
  - `CHECKLIST_SYSTEM_PROMPT` (54932)
  - the inline daily-summary prompt (54866–54872)
  - the inline material prompt (44322–44330)
- **Context passed to the agent:**
  - the system prompt, plus `_agent_context_block(project_id, …)` (50558), which lists project identity, BIN/BBL and live facts (50803–50810)
  - the last 6 non-noise messages from the group, with human turns tagged by the last 4 digits of the phone (50743–50785)
  - the current message
- **Tools.** `_AGENT_TOOLS` (49534–49840), filtered by per-group features (50818–50842):
  - `who_on_site`, `list_workers`, `daily_log`, `dob_status`, `open_items`, `active_permits`, `material_status`
  - `check_drawing_set`, `search_plans`, `query_plan`
  - `project_info`, `start_permit_renewal`, `start_checklist`
  - Dispatch is in `_dispatch_agent_tool` (51037). Tool reads are keyed by `project_id` alone, for example `checkins` by `project_id` (43866–43872) and `dob_logs` by `project_id` (44033–44036) (V).
- **Reply path.** The reply goes to `send_whatsapp_message(group_id, reply, reply_to=message_id_serialized)` and quotes the question (51979–51980). A `NOREPLY` answer produces silence (V).
- **Language.** NF: any language instruction in the agent prompts (49858–50100; terms `language`, `spanish`, `english`). Spanish voice notes are translated to English before the agent sees them (`lib/voice_ingest.py:3, 109`). In practice replies are English (I).

**Existing classification, summarisation and extraction of chat content (V):**

| What | Function | Trigger | Output |
|---|---|---|---|
| Daily group digest | `_summarize_and_send_for_group` (54820–54885), gpt-4o | Job every 30 min (54888). Runs only if `daily_summary_enabled` (**default False**, 44948), on configured days and time, and through the `whatsapp_send_log` dedupe | Posted **into the group**, in English, as "*Daily Summary - {project}*" |
| Action-item checklist | `_extract_whatsapp_checklist` (54997–55118), gpt-4o-mini, `CHECKLIST_SYSTEM_PROMPT` | Job every 30 min (55121). Runs if `checklist_extraction_enabled` (**default True**, 44963), `checklist_frequency=="daily"` (44964) at `checklist_time` 16:00 (44965), and there was chat that day. Also on demand | Stored in `whatsapp_checklists` with items `{text, assigned_to (free text name or phone), due_date (free text), category incl. "inspection", priority}`, and **posted into the group** |
| Material request detection | `_detect_material_request` (44306), gpt-4o-mini | Every unaddressed group message of 15 characters or more, if `material_detection` | A `material_requests` row plus a confirmation message in the group (44399–44417) |
| DM intent classification | `classify_intent` (43655) | Every DM | One of 5 intents |

There is **no per-user summarisation, no urgency or importance scoring, and no date extraction into a structured date.** NF: `urgent`, `importance`, `reminder`, `remind_at`, `due_at` in the WhatsApp code. `due_date` exists only as free text inside checklist items (54937).

## 5. Outbound today

Every WhatsApp send goes through `send_whatsapp_message`, except plan images, which use `send-media` at 48329 (V). Grouped by the function that calls it:

| Sender (line) | Trigger | Recipient | Content | Language |
|---|---|---|---|---|
| `_process_whatsapp_message`, 13 sites (51698, 51740, 51799, 51818, 51825, 51854, 51887, 51979, 52053, 52093, 52138, 52155, 52181) | inbound message | the group, or the DM sender (`parsed["from"]`) | agent replies, voice errors, checklist and `done N` acks, permission refusal, DM intent replies, "No project found…" | EN |
| `_nudge_once` 49385 | question-shaped and not addressed, at most once a day per group | group | `NUDGE_TEXT` (49329) | EN |
| `_handle_plan_query` 49036–49103 (5 sites) and send-media 48329 | plan tool | group | sheet image plus status lines | EN |
| `_send_material_confirmation` 44417 | material detected | group | confirmation | EN |
| `_greet_pending_group_once` 51403 | first message from, or bot added to, an unlinked group | group | `PENDING_GREETING` (51202–51208) | **EN + ES** |
| `_handle_group_lifecycle` 51464 | bot added by a known adder | group | "Tap to connect: {url}" / "Toca para conectar" | **EN + ES** |
| `whatsapp_group_link_verify` 52673 | code link completes | group | welcome text | EN |
| `whatsapp_pending_group_link` 53110 | pending link completes | group | "Connected to {address}." / "Conectado a…" | **EN + ES** |
| `_summarize_and_send_for_group` 54883 | scheduled, opt-in | group | daily digest | EN |
| `_extract_whatsapp_checklist` 55112 | scheduled (**on by default**) or on demand | group | checklist | EN |
| `_handle_bot_added_to_group` 52198 | **never called** (V: the only occurrence is its `def` at 52189) | any group | the oldest unverified link code of **any** company | dead code |

**No proactive 1:1 DM exists anywhere.** Every DM send is a reply to an inbound DM. NF: constructing an `@c.us` JID anywhere in the code; the only occurrence is a docstring at 49123.

**Opt-in, consent and unsubscribe.**
- The per-group `bot_enabled` kill switch exists (44947, 51771–51772) (V).
- `daily_summary_enabled` is opt-in (V).
- **There is no per-person opt-in, consent record, STOP or unsubscribe handling, or quiet hours.** NF: `opt_in`, `optin`, `consent`, `unsubscribe`, `STOP`, `quiet_hours` in the WhatsApp code.

## 6. Users & settings

**Phones.**
- `users.phone` holds E.164 from `normalize_phone`. It is applied at profile edit (9994), admin create (11307–11309), admin update (11487–11488) and company-admin create (15017) (V).
- Phone uniqueness is checked at 10007–10019 (V).
- `whatsapp_contacts {company_id, phone, user_id, name|display_name}` has a unique `(company_id, phone)` index (56501–56506). Its writers are at 10038/10045, 11377, 11610/11616/11629, 11666, 15055 and 53270 (V).
- **Verification state: none.** NF: `phone_verified`, `verify_phone`, `otp`, `twilio`, `sms` (apart from a placeholder SMS channel at `lib/notification_preferences.py:131`). The frontend checks only that the phone has 10–15 digits (`frontend/app/settings.jsx:506–514`). Its hint reads "Required for WhatsApp integration" (`settings.jsx:708`) (V).
- **Language field: none** on users or workers. NF: `preferred_language`, and `"language"` on user or worker models.
  - The only language data: `signature_affirmed_lang` en/es at check-in (19553–19555, 20202) and the gate `lang` (18898–18900) (V).
  - Frontend i18n is in `frontend/src/i18n/`. `es.js` covers only the `signature` and `waGroups` namespaces (es.js:49, :59). `setLocale` is deliberately never called (`index.js:46–62`) (V).

**Roles (V).**
- `ROLE_SUPERINTENDENT` (7612), `ROLE_PM` (7626), `ROLE_DEMO` (7650).
- The assignable roles are `("admin", pm, superintendent, "cp")` (7851). "worker" and "owner" are retired (7834, ~7838).
- `COMPANY_ADMIN_ROLES = ("admin",)` (8229).
- The platform operator is a flag (`is_platform_operator` 8650).
- `is_company_admin` checks rank only, **not tenancy** (its own docstring, 8710–8723).

**WhatsApp settings, backend (V).**
- **Company level:** `whatsapp_config` is created by `POST /whatsapp/activate` (53239–53284), which has **no role check**, so any approved user can activate. It returns `already_active` and skips the contacts backfill on every later call (53247–53249).
- **Group level:** `whatsapp_groups.bot_config` is described in the table below.
- **Group config route:** `PUT /whatsapp/groups/{id}/config` (52732–52890) is admin-only (52745) and company-checked (52757). It validates keys, HH:MM times, days 1–7, booleans and `address_mode ∈ {strict, loose}`.
- **Unlink:** `DELETE /whatsapp/groups/{id}` (52912) is company-scoped with **no role check**.
- **Pending-group routes:** `_require_link_role` (52935) allows `("owner","admin","cp")`. It includes the retired "owner" and excludes pm and the operator flag.

| `_default_bot_config` (44938–45000) | default |
|---|---|
| bot_enabled | True |
| daily_summary_enabled / _time / _days | False / "17:00" / Mon–Fri |
| checklist_extraction_enabled / _frequency / _time | **True** / "daily" / "16:00" |
| features.who_on_site, dob_status, open_items, material_detection, plan_queries | True |
| features.address_mode | "loose" |
| features.voice_notes | True |
| cross_project_summary | False (NF: any reader of it outside the config plumbing) |

**WhatsApp settings, frontend (V).**

| File | What it does | Who can reach it |
|---|---|---|
| `frontend/app/admin/integrations.jsx` | Activate, number, vCard, link to groups (:261, :559) | admin UI only when `role==='admin'` (:73, :337) |
| `frontend/app/admin/whatsapp-groups.jsx` (also `app/wa/link.jsx`, a re-export) | pending groups, link and ignore, EN/ES via `waGroups` | `LINK_ROLES = ['owner','admin','cp']` (:61), redirect otherwise (:90–98) |
| `frontend/app/projects/[id]/whatsapp-groups.jsx` | linked groups, code flow (:261, :291), unlink (:306), config gear (:494) opening `GroupConfigPanel` (:524) | authenticated users only (:110–114). Non-admins see the gear, but the save returns 403 |
| `frontend/app/projects/[id]/whatsapp-checklists.jsx` | extracted checklists, item toggles | authenticated (:99) |
| `frontend/src/components/whatsapp/GroupConfigPanel.jsx` | master switch, summary, checklist, 5 feature toggles. **No address_mode or voice_notes control.** Saves the whole object (:205) | via the project screen |
| `frontend/app/project/[id].jsx` | WhatsApp status card (:338–353) | project viewers |

**Drift:** `GroupConfigPanel` `DEFAULT_CONFIG` sets `checklist_extraction_enabled: false` (:25) and `plan_queries: false` (:33). The backend defaults for both are True (V). I: saving from the panel for a group whose stored config lacks those keys writes `false`.

**Per-user WhatsApp preference: none.**
- `/settings/notifications` offers Email, SMS (disabled) and In-App (`frontend/app/settings/notifications.jsx:186–189`).
- The backend `VALID_CHANNELS = {email, sms, in_app}` (`lib/notification_preferences.py:130–134`) (V). NF: `whatsapp` in either file.

## 7. Scheduler

`scheduler = AsyncIOScheduler()` is created with no timezone (1007). Jobs are registered in `startup_event` (56076) and the scheduler is started at 57789 (V). `run_whatsapp_startup_migrations()` runs *after* `scheduler.start()` (57795) (V).

| id | trigger | function | line |
|---|---|---|---|
| report_email_scheduler | cron, every minute | `check_and_send_reports` (41915) | 56758 |
| v2_logbook_nightly_tick | cron 03:00 ET | local | 56830 |
| dob_nightly_scan | **interval 15 min** | `nightly_dob_scan` (40698) | 56854 |
| dob_approval_watcher | interval 15 min | `dob_approval_watcher` (55320) | 56870 |
| dob_311_fast_poll | interval 30 min | `_poll_311_fast_complaints` (38746) | 56909 |
| nightly_compliance_check | cron hour=22, **no tz** | `nightly_compliance_check` (40349) | 56918 |
| whatsapp_daily_summary | interval 30 min | `_send_whatsapp_daily_summaries` (54888) | 56925–56930 |
| whatsapp_checklist_extraction | interval 30 min | `_run_whatsapp_checklist_extractions` (55121) | 56932–56937 |
| card_read_canary | interval (env) | `_card_read_canary` (18560) | 56950 |
| card_audit_expiration_check | cron 02:15 ET | `card_audit.check_card_expirations` | 56964 |
| card_audit_fraud_detection | cron 02:30 ET | `card_audit.run_fraud_detection` | 56970 |
| eligibility_shadow_sweep | interval 30 min, only in shadow mode | `_eligibility_shadow_sweep` (41204) | 56996 |
| peer_stats_refresh | interval (engine) | local | 57030 |
| prediction_resolution_sweep | interval 30 min | local | 57058 |
| prediction_cleanup | cron 03:45 ET | local | 57086 |
| notifications_cleanup | cron 03:55 ET | `notifications_inbox.cleanup_inbox` | 57119 |
| soft_delete_purge | cron 04:30 ET (env-gated) | local | 57183 |
| renewal_digest_daily | cron 07:00 ET | `renewal_digest_daily_cron` (40781) | 57202 |
| pr15a_nightly_panel_build | cron 01:30 ET | local | 57486 |
| pr15b_nightly_panel_refit | cron 02:45 ET | local | 57532 |
| pr15b_validation_audit_sweep | cron 04:15 ET | local | 57540 |
| phase1w3_weekly_baseline_aggregator | Mon 03:00 ET | local | 57577 |
| phase1w13_weekly_causal_lift | Mon 03:30 ET | local | 57614 |
| weekly_phase_inference | Sun 04:00 ET | local | 57648 |
| digest_dispatcher | interval 15 min | `notification_preferences.dispatch_digests` | 57775 |

Unscheduled or dead:
- `renewal_reminder_cron` (55715; its entry was removed per the comments at 56875 and 56894) (V).
- `permit_renewal.run_dob_now_health_check` is uncalled (`permit_renewal.py:1355`) (V).

A separate `asyncio` loop, `_plan_index_worker` (47230, started at 56180), claims jobs per host:pid (V).

**Workers and replicas.**
- `Procfile:1` runs `uvicorn server:app` with no `--workers` (V).
- `Dockerfile:89` is the same, with no `--workers` (V). The comment says Railway builds from the Dockerfile (`Dockerfile:45–49`) (V).
- One process per container. A code comment confirms this (26827) (V).
- **The Railway replica count is not in the repo.** NF: `railway.json`, `railway.toml`, `nixpacks.toml`, gunicorn config. **PENDING:** read it in the Railway dashboard (service → Settings → Replicas).

**Locks against double firing.**
- **No scheduler lock, leader election or env gate.** NF: `leader`, `RUN_SCHEDULER`, `SCHEDULER_ENABLED`, `scheduler_lock`, `job_lock`, `advisory`, `WEB_CONCURRENCY`, `numReplicas`.
- `max_instances=1` applies within a single process only.
- The WhatsApp jobs are still safe across replicas, because `_whatsapp_send_log_try_mark` is an atomic insert against a unique index (45017–45038, 45186–45191) (V/I).
- Most email ledgers are check-then-act and not race-safe: `notification_log` (`lib/notifications.py:295–319`), `report_emails` (41942/42089), the non-unique `renewal_alert_sent` (57299–57309), and `digest_queue` (`lib/notification_preferences.py:778–883`) (V/I).

## 8. Notification infrastructure (non-WhatsApp)

**Resend.**
- There is a single send site, `resend.Emails.send`, at `lib/notifications.py:580`, inside `send_notification` (324) (V).
- The pipeline runs in this order (V):
  1. The kill switch (375–390).
  2. **Field-role suppression** (398–414).
  3. The 23-hour idempotency check on `notification_log` (417–432).
  4. Per-user preferences, applied **only if `metadata.signal_kind` is set** (441–523).
  5. `NOTIFICATIONS_ENABLED`.
  6. The API key check.
  7. The send.
  8. A `notification_log` row for every outcome (612–648).
- Email flows (V):

| Flow | Line(s) |
|---|---|
| project daily report | 41915/42066 |
| renewal digest | 40781, 41016, 41161 |
| `critical_dob_alert` | 38140–38267, to admin/"owner" (38155–38161) |
| renewal completed / filing stuck | 55438, 55521 |
| annotation note / reply | 42186, 42272 |
| card canary | 18768 |
| preference digest | `lib/notification_preferences.py:861` |
| admin resend | 13165 |
| T-30/14/7 renewal reminders | 55627, **unscheduled** |

- The templates are Python renderers in `lib/email_templates.py` (494–501) (V).

**Push.** **None.** NF in the backend: `expo_push`, `push_token`, `ExponentPushToken`, `fcm`, `apns`, `onesignal`. NF in the frontend: `expo-notifications`, `getExpoPushTokenAsync`.

**In-app inbox.** `lib/notifications_inbox.py`:
- `dispatch_notification` (:169) fans out to company admins plus users assigned to the project, capped at 100 (:97).
- It dedupes on `(user_id, source_kind, source_id)`.
- Items are kept 90 days (:103) (V).

**Preferences model.**
- The `notification_preferences` collection holds `user_id`, `project_id` (null = global), `signal_kind_overrides{channels, severity_threshold, delivery}`, `channel_routes_default` and `digest_window{daily_at, weekly_day, timezone}` (`lib/notification_preferences.py:40–73`). The digest queue is `digest_queue` (75–99) (V).
- Endpoints are at 13334–13656 (V). Screens are `frontend/app/settings/notifications.jsx` and `…/notifications/project/[project_id].jsx` (V).
- **Currently inert for real sends** (I): no `send_notification` call in server.py passes `signal_kind`. NF: `"signal_kind":` in send metadata. The DOB alert metadata at 38258–38264 has none.

**CP and Super get no email.**
- `EMAIL_EXCLUDED_ROLES = frozenset({"cp","superintendent"})` (`lib/notifications.py:142`).
- It is enforced at send time for all Resend paths (398–414). If the user lookup fails, the email is sent anyway (145–194) (V).
- The module states explicitly that the in-app inbox and WhatsApp are **not** covered (`lib/notifications.py:99–101`) (V).

**Reusable for F1–F4.**
- Reusable:
  - the `notification_preferences` digest windows (`daily_at`, `weekly_day`, timezone) and the `digest_queue`
  - the `notification_log` idempotency pattern
  - the `whatsapp_send_log` atomic pattern
- No WhatsApp channel exists in the preferences model, and there is no biweekly or monthly cadence. The windows are daily and weekly only (`lib/notification_preferences.py:40–73`) (V).

## 9. Data sources for proactive alerts

**`dob_logs`.**
- **Writer:** `run_dob_sync_for_project` (39882) updates at 40203 and inserts at 40236. 311 rows are inserted at 38673 (V).
- **Schema:** the base document is at 40166–40195. Key fields: `project_id`, `company_id`, `nyc_bin`, `record_type`, `raw_dob_id`, `ai_summary`, `severity` ("Action"/"Good"), `next_action`, `dob_link`, `detected_at`, `current_status`, `previous_status`, `status_changed_at`, `is_seed_transition`, `signal_kind` and `read_by_user[]`. Type-specific extras are at 39008–39442 (V).
- **Datasets.** All are NYC Open Data Socrata, queried in `_query_dob_apis` 37670–38126 (V):

| record_type | dataset id(s) |
|---|---|
| job_status | w9ak-ipjd |
| violations | 855j-jady (DOB NOW), 3h2n-5cm9 (BIS), 6bgk-3dad (ECB/OATH) |
| permits | rbx6-tga4, dm9a-ab7w, ipu4-2q9a |
| complaints | eabe-havv |
| swo | 3usq-5cid |
| cofo | pkdm-hqz6 |
| fisp | xubg-57si |
| boiler | 52dp-yji6 |
| elevator | e5aq-a4j2 |
| 311 | erm2-nwe9 (38421) |

- **Cadence:**
  - `dob_nightly_scan` runs every **15 minutes** despite its name (56827–56832) (V).
  - 311 runs every 30 minutes (V).
  - Socrata lags DOB NOW by about 24–48 h (`lib/eligibility_v2.py:185–195`) (V).
- **Project mapping:**
  - Each project is queried separately, by BIN first, then by an address fallback (`house + street LIKE '%X%'`), then a BBL→BIN heal, then a BIN-vote heal (39914–39998). 311 uses BBL, then address (38475–38522) (V).
  - I: the `%street%` LIKE can bleed into neighbouring streets.
  - I: the diff lookup `find_one({"raw_dob_id"})` (40188–40191) has no `project_id`, so two projects that share a BIN can diff against each other's rows.
- **New / notified state:**
  - A new row is written only on a status change (40186–40240).
  - Seen state is `read_by_user`.
  - Notified state lives in `system_config` under the keys `dob_alert_sent:{project}:{raw_dob_id}` (38332–38369) and `initial_scan_done:*` (38296–38329) (V).
- **Plain-language text:** deterministic, with no LLM.
  - `_generate_summary` says "without AI" (39578–39579).
  - `dob_complaint_codes.py` covers dispositions and categories (524–576).
  - **Violation type codes are not translated**: they display as "DOB code: X" (`dob_complaint_codes.py:484–515`).
  - `lib/dob_signal_templates.py` renders a title, body and action per `signal_kind` (V).
- **Existing alerting:** Resend email for `severity=="Action"` (40211–40240, 38677–38681), sent to admin/owner only, throttled to once per 24 h per record, with the initial scan suppressed (38372–38412) (V).
  - `lib/dob_signal_notifications.py` (a per-kind routing policy) is imported only by tests (V).
  - The only WhatsApp touchpoint is the on-demand `dob_status` tool (44012–44046) (V).

**Permit expiration.**
- **Stored:** `dob_logs.expiration_date`, a raw string, on `record_type="permit"` (39158), along with `issuance_date` and `permit_class` (V). It is refreshed every 15 minutes from rbx6-tga4, dm9a-ab7w and ipu4-2q9a. Only the newest row per `job_filing_number` is kept (37999–38016) (V).
- **`check_permit_expirations` (41291–41330):** runs after each scan. It sets `severity="Action"` at ≤30 days and sends no message. Its docstring says 14 days, but the code uses 30 (41292 vs 41313) (V).
- **`renewal_digest_daily`** (07:00 ET email) computes permit dates from **`issuance_date` + 365 days (+90 for sheds)**, not from `expiration_date` (`lib/renewal_digest.py:253–296`; projection at 40845–40852) (V).
- **Fresh?**
  - Freshness is bounded by Socrata's lag (V).
  - **PENDING:** what share of permit rows have a parseable `expiration_date`. The query is in Part 4.

**DOT permits and violations.** **No ingestion.** NF: `\bDOT\b`, `dot_`, `street permit`, `sidewalk` (apart from shed permits and complaint categories), `tcvp`, `nycstreets`, `street works`, `department of transportation`. No DOT Socrata resource id appears.

**Inspections.**
- **DOB building inspections:** no ingest. It was removed because the dataset was DOHMH rodent data (37807–37818) (V).
- Boiler and elevator rows carry `inspection_date` and `inspection_result` from their datasets (39089–39110) (V).
- `lib/dob_signal_classifier.py:156–196` can infer `inspection_scheduled`, but no live feed writes `record_type="inspection"` (I).
- **Con Ed, FDNY, DEP, TCO, final inspection:** none. NF: `con ed`, `coned`, `con_ed`, `scheduled_inspection`, `final_inspection`, `\btco\b`, `\bDEP\b`.
- **No manual inspection-date model or collection.** NF: `db.*inspection*`.
- Internal CP walks and logbooks (`INSPECTION_ORDER` 34664–34668) are site-safety records, not regulatory inspections (V).

## 10. Tests

**WhatsApp-focused, 9 files, 279 test functions (V):**

| File | Tests |
|---|---|
| `backend/tests/test_the_crew_does_not_learn_a_syntax.py` | 40 |
| `test_pending_group_linking.py` | 34 |
| `test_f1_voice_ingest.py` | 47 |
| `test_live_defects_2026_09_14_2333.py` | 32 |
| `test_live_defects_2026_09_14_2102.py` | 39 |
| `test_agent_knows_the_project.py` | 34 |
| `test_conversation_state_holds_more_than_one_row.py` | 18 |
| `test_group_match.py` | 32 |
| `test_address_mode_is_written.py` | 3 |

**Partial WhatsApp coverage:**
- `test_c2_rate_limits.py`: the class `TestWhatsappWebhookRule` (:606–662)
- `test_group_d_scoped_at_the_query.py`
- `test_unowned_documents_fail_closed.py`
- `test_empty_phone_matches_nobody.py`
- `test_startup_index_integrity.py` (:339–386)
- `test_owner_is_not_a_role.py`

In all, 28 files and 736 test functions reference WhatsApp terms in some way.

**Gaps.** NF: tests for the daily-summary or checklist **scheduled jobs**, for `/whatsapp/activate`, for the config-PUT role gate, or for **group-link initiate/verify project ownership**. There are no frontend WhatsApp tests. Only `frontend/src/i18n/i18n.test.cjs` checks EN/ES parity, including `waGroups`.

**Adjacent suites:** there are notification tests (8 files), DOB, permit and renewal tests (19 files), and scheduler tests (6 files). File names are listed in the source notes.

---

# PART 2 — Gap map

### F1. Per-user DM summaries of important group activity, per project, user-selected frequency → **PARTIAL (mostly MISSING)**

| Need | State | Reusable / absent |
|---|---|---|
| Group history stored per project | EXISTS | `whatsapp_messages` with `project_id` and `company_id` (51754–51768), indexed `(project_id, timestamp)` (56499). **No TTL.** Bot rows lack `project_id` (42793). |
| LLM summarisation of a group's day | EXISTS (group-level) | `_summarize_and_send_for_group` (54820). Prompt at 54866; gpt-4o. It posts to the **group** and covers today only. |
| "Important" filter | MISSING | No importance or urgency classification exists. |
| Per-user targeting | MISSING | No proactive DM send path exists. NF: `@c.us` construction. `send_whatsapp_message` would accept a DM chat id (42753). |
| user → WhatsApp number | PARTIAL | `users.phone` in E.164 (unverified), plus `whatsapp_contacts`. No verification and no opt-in. |
| Which projects a user follows | PARTIAL | `users.assigned_projects` (used at 44921). Admins span the whole company. |
| Frequency daily/weekly/biweekly/monthly | PARTIAL | `notification_preferences.digest_window` has daily and weekly only (`lib/notification_preferences.py:40–73`). It has no WhatsApp channel, and its scheduler is `digest_dispatcher` every 15 min (57775). |
| Dedupe ledger | EXISTS (pattern) | `whatsapp_send_log` is atomic, but it is keyed by group, job and date (45017). It would need a per-user key. |
| Language | MISSING | No user language field. Summaries are English. |

### F2. DM a user only when a group message needs his reply and is urgent or important → **MISSING** (only signals exist, and they are not persisted)

**Deterministic "addressed to him" signals present today:**

| Signal | Parsed? | Stored? | Resolvable to a user? |
|---|---|---|---|
| Native @mention JIDs (`mentioned_jids`) | V (43087–43122) | **No** (51754–51768) | Only if the JID is a phone (`@c.us`) that matches `whatsapp_contacts`. An `@lid` mention cannot be matched to a phone (I). |
| Reply-to (quoted author `quoted_author`, `quoted_from_me`) | V (43050–43085) | **No** | Same constraint as above. Only "reply to the bot" is consumed (51947–51955). |
| Quoted message id | V (43010–43032) | **No** | — |
| Name match in the text | **NF** | — | Users have `name`. No matcher exists for human recipients (the checklist `assigned_to` is LLM free text, 54936). |
| Role ("super", "PM", "CP" in text) | **NF** | — | — |
| Sender → user | PARTIAL | `sender` digits stored | `_find_whatsapp_contact` only. It is not company-scoped (43298–43313), and roster workers are never matched. |

**Urgency or importance:** **NF.** The closest things are the LLM `priority` on checklist items (54940) and the `_looks_like_a_question` heuristic (49339–49355).

**Reusable:** the parser fields; `_contact_phone_variants`; the question heuristic; the gpt-4o-mini JSON-mode pattern from material detection (44306).

**Absent:** persisting mentions and replies on stored messages; a mention→user resolver; an urgency model; per-user DM send and rate limits; opt-in.

### F3. Chat-extracted reminders (date said in chat → DM at 7/3/1 days before) → **MISSING**

- **Extraction:** the only date-like extraction is `due_date` as **free text** inside `whatsapp_checklists.items` (54937). It is never parsed to a date and never scheduled (V; NF: a parse of `due_date` into a datetime). It is also **anchored to nothing**: there is no message id, no source date and no address. Relative phrases like "in 7 weeks" would need the message timestamp, which the extractor is not given. Lines are passed as `"{sender}: {body}"` with no time (55160–55166).
- **Where extracted dates would live:** **no collection exists.** NF: `reminders`, `remind_at`, `scheduled_reminders`, `inspection_dates`. `whatsapp_checklists` is the nearest store, but its items have no structured date.
- **Confirmation step today:**
  - For chat-derived items: **none**. Checklists post straight to the group (55110–55112).
  - The only human-confirmation patterns in the product are:
    - scheduling-model `proposed → confirmed` (`app/scheduling/project_model.py:8–18, 65–77`; `PATCH /projects/{id}/model/confirm` 55954)
    - the DM voice suffix "Reply CORRECT to confirm" (52173–52177), which stores nothing
    - the checklist-assignment conversation state, a 10-minute draft in `whatsapp_conversation_state`
- **Address resolution** ("555 E 5th"): no address-to-project matcher for chat text. `lib/group_match.py` matches **group names** to projects and could be adapted (I).
- **The 7/3/1 scheduler** would be a new job. The T-minus pattern exists in email (`renewal_digest` thresholds `lib/renewal_digest.py:62–68`; `renewal_alert_sent` idempotency, which is non-unique, 57299–57309).

### F4. GC-group broadcasts: inspection reminders, permit-expiry reminders, new DOB/DOT violations with a short explanation → **PARTIAL**

| Sub-feature | State | Reusable / absent |
|---|---|---|
| Identify the "GC group" | MISSING | No group type. All linked groups for a project are equivalent (NF `group_type` and similar). |
| Scheduled group send + dedupe | EXISTS | The 30-min job pattern plus `whatsapp_send_log` with a `job_type` (45017; e.g. 54888–54925). |
| Per-group opt-in toggles | EXISTS (pattern) | `bot_config` plus `_WHATSAPP_CONFIG_KEYS` and the PUT validator (45003–45013, 52732–52890). A new key needs both lists and `GroupConfigPanel`. |
| New DOB violations | PARTIAL | Detection is deterministic (status-change insert, 40186–40240). An email alert exists (38140–38267) with a 24 h throttle and initial-scan suppression (38372–38412). Explanation text comes from `dob_complaint_codes.py` and `dob_signal_templates.py`, with no LLM. **Violation type codes have no plain-language mapping** ("DOB code: X", `dob_complaint_codes.py:484–515`). No WhatsApp hook exists. |
| New DOT violations | MISSING | No DOT ingestion at all. |
| Permit-expiry reminders | PARTIAL | `expiration_date` is stored (39158). `check_permit_expirations` flags ≤30 days with no send (41291–41330). The renewal digest uses issuance + 365, not `expiration_date` (`lib/renewal_digest.py:253–296`). The T-30/14/7 reminder cron is unscheduled (55715, 56875). |
| Inspection reminders | MISSING | No inspection-date source: no DOB inspection feed (removed, 37807), no Con Ed, FDNY or DEP. Only boiler and elevator `inspection_date` values exist on dataset rows (39089–39110). |
| Bilingual | PARTIAL | Hand-written EN+ES strings exist for three group messages (51202–51208, 51464, 53110). There is no i18n layer on the backend. |

---

# PART 3 — Constraints and risks

**WhatsApp ban and ToS risk (I, outside the code).**
- The integration runs on a WaAPI **WhatsApp Web session**, which is an unofficial client, not the Business Platform (see §1).
- WhatsApp's terms prohibit automated and bulk messaging through unofficial clients. Its spam detection weighs unsolicited messages to people who have not messaged the number, high send volume, and recipients blocking or reporting.
- F1, F2 and F3 are **proactive outbound DMs**, which are exactly that pattern. Today the code sends DMs only as replies to inbound DMs (§5).
- **Blast radius:**
  - One number serves every tenant (single `WAAPI_INSTANCE_ID`, 896). A ban takes WhatsApp down for all customers at once, group bots included.
  - No outbound pacing or retry exists (42785–42814).
- The official Cloud API would require approved templates and per-user opt-in for business-initiated messages outside a 24 h window. No template or opt-in machinery exists (NF, §1 and §5).

**Conflicts with stated principles.**
- **No LLM on the compliance hot path.**
  - The `dob_logs` sync and alerting have no LLM today (39578–39579) (V).
  - F4's "short explanation" for violations would conflict if it were LLM-written. The violation-type gap ("DOB code: X") means a deterministic mapping does not yet exist (V).
  - F3 relies on LLM date and address extraction from chat, which is compliance-adjacent for inspections.
  - No written repo-wide principle was found. NF: `no llm`, `hot path`. Closest: `app/scheduling/engine.py:4`, server.py 55874.
- **Operator confirmation for compliance-critical fields.**
  - The pattern exists for scheduling fields (`project_model.py:8–18`).
  - Chat-derived checklist items and material requests are written with **no confirmation** (55095–55112, 51994–52002) (V).
  - F3 dates would be compliance-critical, and they have no confirmation step today.
- **Bilingual EN/ES:**
  - Only three hard-coded group strings are bilingual.
  - Agent replies, summaries, checklists and nudges are English only (§5).
  - Users have no language field (§6).
  - Spanish voice is translated **to** English (`lib/voice_ingest.py`).
- **CP and Super get no email.**
  - This is enforced only for Resend (`lib/notifications.py:142, 398–414`). The module explicitly does not cover WhatsApp (99–101) (V).
  - I: WhatsApp DMs to CP and Super would be the first proactive channel to field roles, which is presumably the intent, but no policy in code governs it.
  - Note also that `critical_dob_alert` still targets the retired "owner" role string (38159) (V).

**Multi-tenant scoping: can chat-reading paths cross company boundaries?**

1. **YES, VERIFIED. Debug endpoints.**
   - `GET /whatsapp/debug/recent-messages` (52551–52569) returns the latest 20 `whatsapp_messages` across **all companies** (sender, group_id, first 140 characters of body).
   - `GET /whatsapp/debug/webhook-log` (52462–52483) returns 20 raw payloads across all tenants (first 1500 characters, DMs included).
   - Both are gated only by `is_company_admin`, which is a rank test that explicitly does not scope tenancy (8710–8723). Any customer's admin can read other customers' chat.
2. **YES, VERIFIED gap; impact INFERRED. Code-link path.**
   - `group-link/initiate` and `/verify` accept `project_id` from the body without checking that it belongs to the caller's company (52492–52510, 52615–52650).
   - A group could be bound under company A to company B's `project_id`.
   - The agent tools then read by `project_id` alone (43866–43872, 44033–44036, `_agent_context_block` 50558), so B's roster, DOB and permit data would be served into A's chat.
   - This requires knowing B's project id.
3. **Possible, INFERRED. Ambiguous group resolution.**
   - The webhook resolves `whatsapp_groups.find_one({"wa_group_id", active:True})` with no company filter (51567).
   - The `(company_id, wa_group_id)` index is not unique (56497).
   - If two companies hold active rows for the same group, the pick is arbitrary. **PENDING** query below.
4. **Unscoped lookups. INFERRED low risk.**
   - `_find_whatsapp_contact` is not company-scoped (43298–43313). A number registered in two companies resolves arbitrarily on the DM path. The follow-on project lookup stays within that user's company (44914–44933).
   - The link-code match in the webhook is unscoped (51521). Two companies would need the same 6 digits inside 5 minutes.
5. **Dead but dangerous.** `_handle_bot_added_to_group` (52189–52201) would post **any** company's pending code into an arbitrary group. It is never called (V).
6. **Scoped correctly (V):**
   - the daily summary and checklist extraction (both read by `group_id`)
   - `GET /whatsapp/groups/{project_id}`, filtered by company (52699–52703)
   - the config PUT (52757)
   - the pending-group link (53045–53048)

**Half-built, dead, flag-gated or unmerged.**
- **Dead or unused code:**
  - `_handle_bot_added_to_group` is never called (52189).
  - `has_image` and `image_url` are parsed but unused (42936–42940).
  - `quoted_is_audio` has no group consumer (I).
  - `cross_project_summary` is a config key with no reader (I; NF a reader outside the config plumbing).
  - `lib/dob_signal_notifications.py` is imported only by tests.
  - `notification_preferences` is inert because no sender passes `signal_kind` (I).
- **Unscheduled jobs:** `renewal_reminder_cron` (55715) and `run_dob_now_health_check` (`permit_renewal.py:1355`).
- **Flag-gated:**
  - Per-group `features.*` and `bot_enabled` (44938–45000).
  - `voice_notes` is default on, but the code says it is unverified against this WaAPI account (51613–51619).
  - `NOTIFICATIONS_KILL_SWITCH` and `NOTIFICATIONS_ENABLED` (`lib/notifications.py:52–63`).
- **Default-on unsolicited send.** `checklist_extraction_enabled` defaults to **True**, with frequency "daily" at 16:00 (44963–44965). Newly linked groups therefore get an auto-posted checklist every day there is chat. This contradicts the comment at 44955–44962 ("A checklist only appears when somebody asks for one").
- **Frontend drift.** `GroupConfigPanel` defaults disagree with the backend (`GroupConfigPanel.jsx:25, :33`), and the panel has no `address_mode` or `voice_notes` controls.
- **Idle tooling.** `backend/scripts/wa_corpus_harness.py` is offline and unused.
- **Retention.** No TTL on `whatsapp_messages` or `whatsapp_webhook_log` (§2).
- **Unmerged branches with WhatsApp work.** Matched on tip commit subject against main. Main appears squash-merged, so ahead-counts are meaningless.
  - `whatsapp-live-defects-2`, tip `b8a72ae6`, 2026-09-14, "show me <element> answers, and the sheets come from text not rank". Its subject is **not on main**. I: likely superseded, because the plan-answer pipeline it touches was rewritten on main (#541, #553, #569).
  - `whatsapp-pre-trial-safety`, tip `ead156e7` "(#524)". Not on main under that number. Main has the same title as #525, and the test file `test_the_crew_does_not_learn_a_syntax.py` it adds exists on main. I: superseded.
  - All other WhatsApp branches are on main by subject (V): `whatsapp-addressing-and-voice` (#525), `whatsapp-group-autodetect` (#527), `whatsapp-live-test-defects` (#526), `whatsapp-live-defects-3` (#534), `agent-brain-context` (#537).
  - No open PRs mention WhatsApp (GitHub search `whatsapp is:open`: 0 results).

---

# PART 4 — Open questions for you

These are decisions or facts the code cannot answer.

**Decisions**
1. **Account type.** Stay on the WaAPI Web-session number for proactive DMs, or move DMs (or everything) to the official WhatsApp Business Cloud API, with templates and opt-in? This sets the ban risk for F1–F3 and whether one number keeps serving every tenant.
2. **Consent model.** What counts as opt-in for a proactive DM: an in-app toggle, a first inbound message from the user, or an admin enrolling them? Is a STOP keyword required?
3. **Who receives DMs.** App users only, which today means admin, pm, cp and superintendent? Or also roster workers, who have phones but no user link?
4. **"Important" and "urgent" (F1, F2).** Should these be decided by an LLM classifier? If so, is that acceptable given the no-LLM principle, and is F2 compliance-path? Or must it be deterministic: mentions, replies, keywords, role?
5. **F3 confirmation.** Must every chat-extracted date be confirmed before reminders fire, and by whom (the sender, the PM, an admin)? In-app or by WhatsApp reply?
6. **GC group (F4).** How is a project's GC group designated: an admin flag on one linked group, one per project, or more? Do sub or trade groups ever get broadcasts?
7. **F4 violation explanations.** Deterministic templates only, which means a violation-type code table must be built first, or are LLM-written explanations allowed?
8. **Inspection data (F4).** Will inspection dates come only from manual entry or chat extraction (F3), or is an external source expected? Which agencies: DOB, Con Ed, FDNY, DEP, elevator?
9. **DOT scope.** Which DOT datasets matter (street-work permits, sidewalk violations), and is DOT ingestion in scope at all?
10. **Language.** Is a per-user language field acceptable, or should every proactive message be EN and ES together, like the three existing bilingual strings?
11. **Frequency options.** Biweekly and monthly do not exist in the preferences model (daily and weekly only). Extend that model, or build a separate WhatsApp preference?
12. **Field roles.** Is WhatsApp the intended channel for CP and Super? Should the email exclusion have a WhatsApp counterpart for any role?
13. **Retention.** How long should `whatsapp_messages` and `whatsapp_webhook_log` be kept? Neither has a TTL, and both hold full chat content.

**Facts that need data (PENDING)**

Run these read-only:

```js
// P1. Railway replica count. Not in the repo; read the Railway dashboard (service → Settings → Replicas / regions).

// P2. Same WhatsApp group active under more than one company (ambiguous webhook resolution, Part 3 #3)
db.whatsapp_groups.aggregate([
  { $match: { active: true } },
  { $group: { _id: "$wa_group_id", companies: { $addToSet: "$company_id" }, projects: { $addToSet: "$project_id" }, n: { $sum: 1 } } },
  { $match: { $or: [ { "companies.1": { $exists: true } }, { "projects.1": { $exists: true } } ] } }
])

// P3. Linked groups whose project belongs to another company (code-link path, Part 3 #2)
db.whatsapp_groups.aggregate([
  { $match: { active: true } },
  { $lookup: { from: "projects", let: { pid: "$project_id" },
      pipeline: [ { $match: { $expr: { $eq: [ { $toString: "$_id" }, { $toString: "$$pid" } ] } } }, { $project: { company_id: 1 } } ],
      as: "p" } },
  { $unwind: { path: "$p", preserveNullAndEmptyArrays: true } },
  { $match: { $expr: { $ne: [ { $toString: "$company_id" }, { $toString: "$p.company_id" } ] } } },
  { $project: { wa_group_id: 1, project_id: 1, company_id: 1, project_company: "$p.company_id" } }
])

// P4. Groups per project (one vs many)
db.whatsapp_groups.aggregate([
  { $match: { active: true } },
  { $group: { _id: "$project_id", groups: { $sum: 1 } } },
  { $group: { _id: "$groups", projects: { $sum: 1 } } }
])

// P5. Message volume and human senders per group (is there any real traffic to summarise?)
db.whatsapp_messages.aggregate([
  { $match: { sender: { $ne: "bot" }, project_id: { $exists: true } } },
  { $group: { _id: "$group_id", msgs: { $sum: 1 }, senders: { $addToSet: "$sender" }, last: { $max: "$created_at" } } },
  { $project: { msgs: 1, distinct_senders: { $size: "$senders" }, last: 1 } },
  { $sort: { last: -1 } }
])

// P6. DM volume (DMs are not stored in whatsapp_messages; only in the raw log)
db.whatsapp_webhook_log.countDocuments({ raw_body_preview: { $regex: '"from"\\s*:\\s*"[0-9]+@c\\.us"' } })
db.whatsapp_webhook_log.aggregate([{ $group: { _id: null, n: { $sum: 1 }, oldest: { $min: "$received_at" }, newest: { $max: "$received_at" } } }])

// P7. Are sender ids phones or LIDs? (affects mention / reply resolution for F2)
db.whatsapp_messages.aggregate([
  { $match: { sender: { $ne: "bot" } } },
  { $project: { len: { $strLenCP: { $ifNull: ["$sender", ""] } } } },
  { $group: { _id: "$len", n: { $sum: 1 } } }
])

// P8. Phone coverage among users by role (who could receive a DM at all)
db.users.aggregate([
  { $match: { is_deleted: { $ne: true } } },
  { $group: { _id: "$role", total: { $sum: 1 }, with_phone: { $sum: { $cond: [ { $gt: [ { $strLenCP: { $ifNull: ["$phone", ""] } }, 0 ] }, 1, 0 ] } } } }
])

// P9. whatsapp_contacts phone formats, and the same number duplicated in two formats
db.whatsapp_contacts.aggregate([
  { $project: { plus: { $eq: [ { $substrCP: ["$phone", 0, 1] }, "+" ] }, digits: { $replaceAll: { input: "$phone", find: "+", replacement: "" } }, company_id: 1 } },
  { $group: { _id: { c: "$company_id", d: "$digits" }, n: { $sum: 1 }, plus: { $push: "$plus" } } },
  { $match: { n: { $gt: 1 } } }
])

// P10. Default-on checklist: groups currently auto-posting daily checklists, and how many were generated
db.whatsapp_groups.countDocuments({ active: true, "bot_config.checklist_extraction_enabled": true, "bot_config.checklist_frequency": "daily" })
db.whatsapp_checklists.countDocuments({ generated_at: { $gte: ISODate("2026-09-01") } })

// P11. Permit expiration_date coverage (F4 permit reminders)
db.dob_logs.aggregate([
  { $match: { record_type: "permit", is_deleted: { $ne: true } } },
  { $group: { _id: { has_exp: { $gt: [ { $strLenCP: { $ifNull: [ { $toString: "$expiration_date" }, "" ] } }, 0 ] } }, n: { $sum: 1 } } }
])

// P12. Boiler/elevator rows with a future inspection_date (only existing inspection-date signal)
db.dob_logs.countDocuments({ record_type: { $in: ["boiler", "elevator"] }, inspection_date: { $exists: true, $ne: null } })

// P13. Any chat-extracted checklist items already carrying a due_date (F3 baseline)
db.whatsapp_checklists.aggregate([
  { $unwind: "$items" },
  { $group: { _id: { has_due: { $ne: [ { $ifNull: ["$items.due_date", null] }, null ] }, cat: "$items.category" }, n: { $sum: 1 } } }
])
```
