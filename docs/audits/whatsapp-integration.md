# The WhatsApp integration, explained

For a developer who has never opened this code. It is spread across roughly
5,000 lines of `backend/server.py` with no module boundary, and the parts that
matter most are the ones a reading of the code does not make obvious.

Everything here was established by reading the source, except where it says
**measured** — those come from a production export of `whatsapp_messages`
taken 2026-09-14 and from counts run by the operator. Line numbers are against
the working tree at the time of writing and will drift; the function names
will not.

**Read the surprises section even if you read nothing else.** Every item in it
cost somebody a wrong conclusion.

---

## 1. The shape

Sixteen routes live under `/whatsapp/`. **One of them carries inbound
messages.** The other fifteen are debug, configuration, and group
administration.

| route | what it is | line |
|---|---|---|
| `POST /whatsapp/webhook` | the only inbound message path | `server.py:42886` |
| `POST /whatsapp/activate` | switch the integration on for a company | `server.py:43439` |
| `POST /whatsapp/group-link/initiate` · `/verify` | bind a group to a project | `server.py:43024`, `43147` |
| `GET` · `PUT` · `DELETE /whatsapp/groups/…` | list, configure, unlink | `server.py:43200`, `43245`, `43426` |
| `GET /whatsapp/status` | is it on, and what number | `server.py:43487` |
| `GET /whatsapp/contact.vcf` | the bot's contact card, so it can be added to a group | `server.py:44139` |
| `GET /whatsapp/debug/…` (7 routes) | audio probe, bot identifiers, raw webhook log, recent messages, pending codes, WaAPI config | `server.py:42921`–`43112` |

The webhook returns `200` immediately and hands the payload to a background
task. Nothing in the request path waits on a model.

### Two agent paths, and they are not equivalent

`_process_whatsapp_message` (`server.py:42413`) branches on whether the
message came from a group or a direct chat. The two branches were written at
different times and share almost nothing.

| | group | direct message |
|---|---|---|
| entry | `_run_group_agent` (`server.py:42108`) | `classify_intent` (`server.py:38524`) |
| decides with | gpt-4o-mini, temp 0.2, ≤4 tool rounds, 500 max tokens | string match, then gpt-4o-mini as a label classifier |
| can call | 10 tools (`_AGENT_TOOLS`, `server.py:41496`) | 5 fixed intents, no tools |
| stores the message | yes | **no** — see §7 |

The DM path is the older design. The group path is where the product is.

---

## 2. How a message finds its project

WhatsApp gives the server a group id. It does not give it anything that maps
to a Levelog project, and it never will — the group existed before Levelog did
and nobody at Meta knows the two are related.

So the binding is established by a **six-digit code that has to travel through
the chat**:

1. The app calls `group-link/initiate` (`server.py:43024`). A code is written
   to `whatsapp_link_codes` with a five-minute expiry (`server.py:43050`).
2. Somebody posts the code as a message in the group.
3. The webhook fires. The code check runs **first**, before the linked-group
   test and before any permission check (`server.py:42429`). Finding a match,
   it records the group id on the code document.
4. The app calls `group-link/verify` (`server.py:43147`), which now has a group
   id to write into `whatsapp_groups`.

### Why the round trip exists

**The message is the only thing that carries the group id.** Step 3 is not
verification in the security sense and it is not a confirmation dialog. It is
the only moment the server learns which WhatsApp group the operator means,
because the operator cannot type a group id he has never seen and WhatsApp does
not expose one.

Someone will eventually try to replace this with a form field. There is nothing
to put in the field.

Two consequences fall out of the ordering, and both are deliberate:

- **Anyone in the group can post the code.** The check precedes every
  permission test, so the poster needs no Levelog account. That is required: a
  superintendent may be linking a group he is not a member of.
- **The code must be the entire message body.** It is matched with
  `re.match(r"^\s*(\d{6})\s*$", …)`, so `481920` links and `code 481920` does
  not.

The screens for all of this are in `frontend/app/projects/[id]/whatsapp-groups.jsx`
(linking, unlinking, per-group config) and `frontend/app/admin/integrations.jsx`
(activation, contact card). See surprise §7.5 before you go looking for them.

---

## 3. Addressing

**This is the most consequential behaviour in the integration and the least
documented.** It decides whether the bot answers at all, and getting it wrong
is invisible: a message that fails the test is stored and silently ignored.

`_is_bot_addressed` (`server.py:41435`) is the whole decision. There are two
modes, set per group at `bot_config.features.address_mode`, defaulting to
`strict` (`_default_bot_config`, `server.py:39397`).

### The six ways a message counts as addressed

In **strict** mode, three:

1. A native WhatsApp `@mention` whose JID matches the bot's phone digits or its
   LID, including LIDs auto-learned from outbound traffic
   (`_has_explicit_bot_mention`, `server.py:41335`).
2. The literal text `@levelog`, or a body starting `levelog `.
3. The sender is inside a live 180-second session window.

In **loose** mode, three more:

4. Any voice note, unconditionally.
5. Any message containing a soft-trigger word.
6. (Still) everything strict accepts.

The soft-trigger list is `_BOT_ADDRESS_SOFT_TRIGGERS` (`server.py:41260`):

> who, show, how many, how much, what, where, find, pull, open, dob, violation,
> punch, open items, material, delivery, create checklist, make checklist, new
> checklist, add checklist, assign, `done `

**In strict mode that list is never consulted.** The loop that reads it sits
inside `if mode == "loose"`. This is worth stating plainly because the list
looks like a global fallback and is not.

### The session window does not extend itself

`_mark_bot_session` (`server.py:41392`) is called from exactly two places, both
inside `_is_bot_addressed`: on an explicit mention, and on a quoted explicit
mention. It is **not** called when the session branch itself matches.

So the 180 seconds (`BOT_SESSION_TTL_SECONDS`, `server.py:41389`) run from the
last message that explicitly tagged the bot, not from the last exchange. A
conversation that stays lively dies at 180 seconds anyway, and the fourth-minute
follow-up is ignored.

### Replying to the bot does not address it

The docstring on `_is_bot_addressed` says a message counts as addressed when it
"is a reply to a bot message." **The code does not do that.** It tests whether
the *quoted text* mentions the bot (`server.py:41469`), and the bot's own
replies do not contain `@levelog`.

The parser extracts `quoted_body` and `quoted_is_audio` (`server.py:38068`) and
never extracts the quoted message's author, so the check the docstring
describes cannot be made with what the parser returns today.

### What this costs, measured

Of the operator's 34 unaddressed group messages, **eleven were real questions
the bot never saw**:

> "Who's on site?" · "Active permits" · "Permit status?" · "Who's on sote" ·
> "Done 2" · "Done 3" · "lunch at 12?" · "Yes" ×3 · "?"

Every one of the first six would have matched a soft trigger in loose mode.
"Done 2" and "Done 3" look like replies to a checklist prompt, which is the
case §3's third paragraph covers: replying to the bot opens no window.

Note what this is *not*. It is not the 15-character gate — that gate only
decides whether material detection runs (`server.py:42683`) and has nothing to
do with addressing. An unaddressed message never reaches the agent at any
length.

### Switching the mode

There is no control for it. The settings panel
(`frontend/src/components/whatsapp/GroupConfigPanel.jsx`) renders five feature
switches and no addressing control. `PUT /whatsapp/groups/{id}/config` accepts
`features.address_mode` (`server.py:43367`); until 2026-09-14 it validated the
value and then `continue`d past the write, returning `200` on a change that
never happened.

---

## 4. What consults `whatsapp_contacts`, and what does not

**Group membership is enough. The group path never looks a sender up.**

This is the opposite of the natural assumption, so it is worth being explicit:
a phone number in a linked group with no `whatsapp_contacts` row is answered
normally. Not silent, not an error.

`whatsapp_contacts` is read in exactly two places:

| reader | line | consequence of no row |
|---|---|---|
| on-demand checklist request in a group | `server.py:42596` | a reply telling them to add their phone. Also requires an admin / owner / cp role, and the feature defaults **off**. |
| the direct-message branch | `server.py:42696` | silence — `return` before anything else |

Nothing writes the collection by hand and there is no screen for it. Rows
appear as a side effect of user management: nine `update_one` call sites across
user create, user update, self-service profile edit, new-admin creation, user
delete, and the activation backfill.

See surprise §7.4 for why most of those rows do not work.

---

## 5. The model calls, and which are metered

| call | model | fires on | metered |
|---|---|---|---|
| group agent | gpt-4o-mini | every addressed group message, up to 4 rounds | no |
| DM classifier | gpt-4o-mini | a DM that no string rule matched | no |
| material detection | gpt-4o-mini, JSON mode | every **unaddressed** group message ≥15 chars (`server.py:38765`, called at `42684`) | no |
| voice transcription | Whisper | a DM voice note (`lib/voice_ingest.py`) | per-call USD in telemetry |
| voice translation | gpt-4o-mini | a non-English transcript | per-call USD in telemetry |
| plan indexing | Qwen2.5-VL-7B | **each page** of an uploaded PDF (`_index_single_page`, `server.py:39972`) | yes — `plan_index_page` |
| ~~plan visual Q&A~~ | ~~Qwen2.5-VL-7B~~ | **deleted 2026-09-17** — questions are answered from records, so a question costs no vision call | the `whatsapp_visual_qa` endpoint name is kept so the rows already written can still be read |

The remaining Qwen row is counted by `lib/vision_meter.py`, whose frozenset
(`vision_meter.py:99`) names all four paid vision endpoints in the system. The
units matter more than the coverage: a forty-sheet plan set is forty calls from
one upload, and a plan question about something the drawings do not show costs
the length of the candidate list, not one call.

**No ceiling is attached to any of it, deliberately.** The meter ships the count
first so a limit can be set from real traffic rather than guessed. See
`lib/vision_meter.py`'s own header for the argument.

The seven read tools the group agent can call — `who_on_site`, `list_workers`,
`dob_status`, `open_items`, `active_permits`, `material_status`, `project_info`
— are all plain Mongo queries. **None of them calls a model.** What the language
model buys on those paths is the routing decision and the sentence around the
result, nothing else.

### Tools run one at a time

Both dispatch branches are `for tc in tool_calls: await …`
(`server.py:42278`, `42298`). There is no `asyncio.gather` anywhere in
`_run_group_agent`. A two-tool turn costs two round trips.

The system prompt used to claim otherwise. It was corrected on 2026-09-14; the
note at `server.py:41735` explains why a false latency claim in a prompt is a
bug rather than a stale comment.

---

## 6. The plan pipeline

> **Superseded, 2026-09-17.** Section 6's "Answering, on a question" describes
> a pipeline that no longer exists. `_classify_plan_question`, the RRF fusion
> of a vector rank and a keyword rank, `_pages_with_element`, the keyword
> matcher in `lib/plan_extract.py` and `_qwen_visual_qa` are all deleted.
>
> A question is answered from typed records by `search_plans`
> (`lib/plan_search.py`), ranked by the evidence behind them, and every
> composed answer passes `gate_plan_answer`: a number that no returned record
> prints is refused and replaced. The vision model is not asked questions at
> all — it is used during indexing and nowhere else. `query_plan` sends the
> sheet and answers nothing.
>
> The record of why, and what was lost with it, is
> `backend/eval/migrated-from-the-matcher.md`. What the reader scores is
> `backend/eval/boyland.json` and the runs in `backend/eval/results/`.
>
> Section 6's "There is no version awareness" is also out of date:
> supersession by revision date and file-name date shipped 2026-09-15
> (`_supersede_plan_pages`), and every read excludes superseded and deleted
> pages through `_current_record_page_ids`.
>
> Indexing, below, still stands.

### Indexing, on upload

A PDF triggers indexing only when `QWEN_API_KEY` is set. Each page is rendered
to JPEG (bounded memory, semaphore of 5), sent to Qwen with
`_PLAN_INDEX_PROMPT` (`server.py:39688`), parsed, embedded with OpenAI
`text-embedding-3-small`, and upserted as **one row per page, whole**. There is
no chunking.

The prompt asks for ten labelled sections — sheet id, title, discipline, floor,
spaces and rooms, dimensions, materials and specs, code refs, detail and
section refs, notes — **and nothing else**. Everything the retrieval layer can
filter on comes from that prompt.

**Unchanged pages are never re-scanned.** The whole file is skipped when a row
matches both the MD5 of the PDF bytes and `index_version >= 2`
(`server.py:40332`). Repeated Dropbox syncs cost nothing. Bumping
`index_version` is the deliberate re-index switch.

### Answering, on a question

Text-first. The vision model is not touched unless the question needs the
picture.

1. Optional floor filter, word-boundary safe so `4` does not match `14TH FLOOR`
   (`_floor_regex`, `server.py:40768`).
2. Rank A: cosine similarity on the stored embedding, cut at 0.05.
3. Rank B: keyword hits over sheet number, title, keywords, materials, spaces.
4. Fuse with Reciprocal Rank Fusion, k = 60, top 50 of each list
   (`server.py:40752`).
5. `_classify_plan_question` (`server.py:40783`) decides: send the image, or ask
   the picture a question.
6. If asking: `_qwen_visual_qa` per candidate sheet until one answers or the
   list is exhausted.

### There is no version awareness

No revision, supersession, sheet-set, addendum, bulletin or issue-date concept
exists for drawings anywhere in the backend. Every `supersede` match in
`server.py` belongs to no-completion records or SST cards; every `issue_date`
match belongs to DOB permits and violations.

The indexing prompt does not ask the model for a revision or an issue date, so
**the raw text to build it from is not being captured either**. Adding it is a
new feature and a full re-index, not a change to retrieval.

---

## 7. Things that are true and surprising

Each of these cost a wrong conclusion during the 2026-09 scoping pass.

### 7.1 The DM branch stores nothing

`server.py:42694`–`42800` contains no insert into `whatsapp_messages`. It looks
up the contact, transcribes audio, classifies, answers, and returns.

So **"zero direct messages in the database" measures the code, not the
traffic.** That count is what the branch produces whether one DM arrived or ten
thousand did. Answering the question needs `whatsapp_webhook_log`, where a
direct message is a `from` without `@g.us`.

A conclusion was drawn from that zero — that the DM path was dead and unifying
it would be a deletion. The evidence does not support it.

### 7.2 `whatsapp_send_log` is a digest ledger, not a record of replies

It has **one writer**: `_whatsapp_send_log_try_mark` (`server.py:39446`), the
deduplication mark for scheduled digest jobs, called at `server.py:44357` and
`44584`. It carries a unique compound index on
`(group_id, job_type, sent_date_est)` and a **45-day TTL**
(`server.py:39602`).

`send_whatsapp_message` (`server.py:37825`) never touches it. Conversational
replies are logged into `whatsapp_messages` with `sender: "bot"`
(`server.py:37844`), so the agent's history loader can recall them.

So "zero outbound sends logged" means no scheduled digest fired inside 45 days.
It says nothing about whether the bot ever replied.

**And it means `whatsapp_messages` is not a human corpus.** Bot turns are in
there with the crew's.

### 7.3 There is no `is_group` field

`parse_inbound_message` computes `is_group = "@g.us" in from_field`
(`server.py:37907`) **in memory**. It is never written to a document.

Stored documents carry `group_id, project_id, company_id, sender, body,
has_audio, message_id, timestamp, created_at`. Group membership is the presence
of `group_id`. A query filtering on `is_group: true` returns zero against a
collection full of group messages, which reads like an anomaly and is a typo in
the question.

### 7.4 Most `whatsapp_contacts` rows cannot be matched

The lookups search `{"phone": sender}` where `sender` is the digits of the
sender's WhatsApp JID — no leading plus.

| writer | line | stores | matches |
|---|---|---|---|
| activation backfill | `server.py:43470` | `15165494475` | yes |
| admin creates a user | `server.py:8895` | `+15165494475` | **no** |
| admin edits a phone | `server.py:8978`, `8984` | `+15165494475` | **no** |
| self-service profile edit | `server.py:7701`, `7708` | `+15165494475` | **no** |
| new admin created | `server.py:11666` | `+15165494475` | **no** |

`users.phone` is normalised to E.164 by `normalize_phone` (`server.py:2393`) at
every write site, and five of the six contact writers pass that value straight
through. Only the activation backfill strips it to digits — and **the backfill
runs once**: `whatsapp_activate` returns `already_active` and skips the sweep
on every later call (`server.py:43439`).

So every user added since the integration was switched on has a contacts row
the bot cannot find. The failure is silent on both sides: the row looks correct
in the database and the bot simply never replies.

There is a second sting. The checklist refusal message tells the user to "add
your phone in Settings → Personal Details so the bot can recognize you". That
path writes `+1`. Following the instruction produces a row that still does not
match.

This affects direct messages and on-demand checklists only. It does not affect
group traffic — see §4.

### 7.5 `GroupConfigPanel` is in `frontend/src` and imported by nothing there

A grep for its name scoped to `frontend/src` returns one hit, its own
definition, which reads as dead code. It is not dead. It is imported by
`frontend/app/projects/[id]/whatsapp-groups.jsx:40`.

**The screens live in `frontend/app`, the Expo Router tree; the shared
components live in `frontend/src`.** A search that covers only one of those
directories will confidently report that a feature has no UI. Five files
mention WhatsApp under `frontend/app` and one under `frontend/src`.

### 7.6 There is no `fromMe` filter on the processing path

`parse_inbound_message` reads `fromMe` for exactly one purpose: to auto-learn
the bot's own LID so later `@mentions` match (`server.py:37872`–`37890`).
Nothing downstream checks it, and `_process_whatsapp_message` has no event-type
filter either — every payload that parses is processed.

If WaAPI is ever configured to deliver `message_create` alongside `message`,
the bot's own sends arrive back as inbound webhooks and are stored as group
messages under the bot's phone digits. The current export shows one human
sender, so echoes are **not** arriving today. It is a latent trap: the next
corpus would be contaminated in a way that looks fine.

### 7.7 Group voice notes are dropped by product decision

The group branch stores the message and ignores the audio
(`server.py:42455`–`42480`), marking the row `skipped: "voice_disabled"`. The
reason is recorded in place: WaAPI's download-media returns encrypted `.enc`
bytes and mediaKey resolution was unreliable.

The voice pipeline is reachable **only** from the direct-message branch
(`server.py:42776`). Combined with §7.1, that means the entire Whisper and
translation stack — `lib/voice_ingest.py`, roughly 600 lines with its own cost
model and short-circuit rules — **has never run on production traffic.**

---

## 8. State

Conversation and checklist state is in the database, not in memory and not in a
session object. `whatsapp_conversation_state`, one row per group, unique index
on `group_id`, TTL index on `expires_at` with `expireAfterSeconds = 0`
(`server.py:39628`–`39636`).

A checklist draft expires in ten minutes (`server.py:41933`). A bot session
expires in 180 seconds (`server.py:41401`). Both survive a restart and both
survive running two containers, which is why this is worth saying: the obvious
in-process implementation would not.

`_is_in_bot_session` (`server.py:41416`) also checks `expires_at` in code rather
than trusting the TTL reaper, which runs on its own schedule. That belt-and-
braces is correct and should not be removed.

---

## 9. The history, and why it should temper everything above

**Measured**, from the production export on 2026-09-14:

| | |
|---|---|
| linked groups that ever carried traffic | 1 |
| stored messages | 217 |
| written by a person | 117 |
| distinct human senders | **1** |
| voice notes | 19, all from that sender |
| last message | 2026-04-20 |
| material requests, ever | **0** |
| direct messages | unmeasurable — see §7.1 |

Every one of the 117 is the operator testing his own bot. There is no delivery
report, no shortage, no material event, and no second voice in five months.

Two things follow, and both matter to anyone about to change this code:

- **This integration has never carried real traffic.** Every behaviour
  documented above is a behaviour under test conditions from one cooperative
  user who knows to type `@levelog`. The addressing recall problem in §3 was
  invisible until somebody counted, and it was counted against a corpus of one
  person.
- **The corpus cannot support tuning.** A material-request prefilter was
  scoped, designed and then deliberately not built, because a classifier tuned
  against zero positives is tuned against a test transcript. The harness that
  will measure it is at `backend/scripts/wa_corpus_harness.py`, written and
  idle; it reads an export file and imports no database driver.

The right order is: run the trial, collect a real corpus, then tune. Not the
other way round.

---

## Where each claim came from

**Read from source** — §1 through §6, §8, and every `file:line` in §7.

**Measured** — the eleven missed questions in §3, the whole of §9, and the
export composition. Counts supplied by the operator from a production
`mongoexport` of `whatsapp_messages`; no database was contacted from the
machine this was written on.

**Changed on 2026-09-14** (branch `whatsapp-pre-trial-safety`) — the parallel
claim in the system prompt, a voice duration cap, language-gated translation,
metering for the two Qwen call sites, a named rate limit for the webhook, and
the `address_mode` write in §3. Anything above describing those as broken
describes the state before that branch ships.
