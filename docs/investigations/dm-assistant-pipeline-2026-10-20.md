# WhatsApp DM assistant: what runs before and after the model (main @ 11503f25)

This is a report of the code as it was before the `dm_brain_v2` rebuild. All paths are under `backend/`, and `S:` means `server.py`.

## The three live failures, Tue 9:02 AM

| Message | What went out | Why (code) |
|---|---|---|
| "Update on 588" | "588 Update / DOB Status: / Want the full list?" | The job agent wrote a real multi-section answer. `_dm_send_answer` then ran `wa_style.tighten` on it. That function cuts any answer over 300 chars, or over 3 lines, or with a list item after line 1, to the first lines plus an offer. Only the two headings survived. |
| "Dot and Akron" | "No Dot or Akron sub…" | This is the most likely path. `wa_subs.company_question` matches sub names only as exact whole words, so "akron" ≠ "Arkon" and the question went to the job agent. There `find_sub` searched the whole phrase "dot and akron" as one term ("and" is not a generic word), with no typo matching. `render_find`'s template produced "No {what} sub {where}." DOT (the city agency) is never considered. |
| "Arkon is framer" | "I don't have that in the records." | No rule recognised a statement of fact. The read-only job agent (no write tool) answered, and the number guard or empty trace fell back to `NO_RECORDS_TEXT`. Nothing can save a correction from a DM except the narrow `add_sub` flow. |

## Before the model (in order)

**Webhook DM branch, `_process_whatsapp_message`**
1. `_open_dm_reply_window` (S:46036) opens a 10 min / 4-send reply window.
2. START / STOP / PARAR. `wa_dm.parse_dm_command` matches the whole message. Replies are fixed `wa_dm` texts. STOP with a question open drops it.
3. "contact" (`wa_contact.is_contact_request`) sends the contact card.
4. GC confirm: "1/yes/2/no" to an open GC-group question.
5. Identity gate `_dm_assistant_identity` (S:50554). It needs an active opt-in, an admin or PM role, the same company, and the same phone. Projects are every job for admins and full-access PMs, else `assigned_projects`. Anyone else gets `NOT_FOR_YOU_TEXT`, or a `done P-…` answer.
6. Voice notes go through Whisper, then a translation. There are fixed replies for:
   - the daily cap: "Voice notes are paused…";
   - a download failure;
   - no speech, too long, or a failed note;
   - an unreliable note: `DM_UNRELIABLE_REPLY`;
   - an unheard note with a question open: `DM_CANT_HEAR`.
7. `_punch_dm_turn` (S:66389), the walkthrough state machine, runs these regexes in order:
   - `parse_done_ref`: "done P-588-1";
   - `parse_query`: who closed / show P photo / what's open (punch);
   - `super_verdict`: "P23 ok";
   - the resend words;
   - `start_request`: "start walkthrough at 588";
   - `walk_intent` / `WALK_HELP`;
   - with a walk open: `add_item_words`, `correction`, `send_shortcut`, `add_photo_ref`, then `_punch_fast`, then the `_punch_think` model, then the stage handlers. These use their own models: punch brain, location, batch and vision.

**`_dm_assistant_reply` (S:55275)**, first match wins:
1. `dm_actions.is_drop` with a question open: "OK, dropped it." With nothing open (and not undo): "OK."
2. `_dm_action_turn(new=False)` answers an open change question (yes/no/pick/fill).
3. `wa_react.social_reaction` (thanks / praise) reacts 🙏 or ❤️ with no text.
4. `_upcoming_dm_turn`: reminder yes/no, or the "remind me…" regex. Replies are fixed confirm texts.
5. `_dm_sheet_turn`: show verbs and nouns, plus the sheet id or the sheet Levelog last cited. It sends the image, or one of 4 fixed texts.
6. `dm_more` + `wa_style.wants_more`: "yes/names/list…" sends the stored full text.
7. `_dm_user_level_turn` (brief), from `wa_facts.user_topic` regexes: resend the brief or report its status. The status text is also put through `tighten`.
8. `_dm_closer_turn`: bare "Done" or "Cancel X" (`wa_assistant.closer`) gets "Done with what?…" or "There's no X open here to cancel."
9. `_dm_action_turn(new=True)`: the `dm_actions` hint regex, then the `_dm_action_model` (gpt-4o, JSON), then `dm_actions.rules` regexes. Questions and confirms are `dm_actions.TEXT` templates.
10. `_dm_user_level_turn` (settings): `wa_facts.settings_text`.
11. `_dm_report_turn` (`project_report.is_request` regex) builds the PDF.
12. No jobs: `NO_JOBS_TEXT`.
13. `dm_clarify` ("Since 8:07 or 7am?") state machine.
14. `dm_menu` ("Which job?") state machine: `pick_from_menu`, `MENU_AGAIN_TEXT`, `MENU_EXPIRED_TEXT`.
15. Reply-to, nudge or job-only: `with_quoted`, `is_nudge` (`NUDGE_TEXT`), `is_job_only` (the last question).
16. `wa_headcount.intent` regexes (COUNT / ADDED / LIST / SUBS / PRESENCE / CHALLENGE) plus the `dm_last` follow-ups.
17. Job resolution:
    - `find_jobs` / `job_named`;
    - the other-company refusal for PMs;
    - `wa_subs.company_question` goes to the subs model;
    - "Which one?";
    - scope from `question_scope` regexes or the `_dm_scope` model (gpt-4o-mini, 3 tokens), which routes to general (`_dm_answer_general`) or all jobs (`_dm_answer_all`);
    - `_dm_job_context`;
    - `NOT_A_QUESTION_TEXT`;
    - "Which job?".
18. Headcount goes to `_dm_answer_headcount`. Its answer is a fixed template (`compose_short`), reworded by gpt-4o only if `wa_headcount.check` passes. Otherwise the fixed text goes out.
19. Everything else goes to `_dm_answer_job`, which is the job agent.

## After the model

**`_dm_answer_job` post-guards** (S:53066-53148):
- Voice-note denial or not-found: send the stored notes.
- `denies_walk`: `WALK_HELP`.
- The memory (project history) answer returns early.
- `denies_subs`: the subs fallback.
- `denies_quoted_access`: "You replied to your …".
- Attendance denial: the attendance fallback.
- A claim about the brief without the log: the brief status.
- **Number check:** any digit not in the question or the tool results replaces the answer with "From the records:" plus the raw last tool result, or with "I don't have that in the records."

**`_dm_send_answer`** (S:55730):
- `wa_style.tighten` (MAX_CHARS 300, MAX_LINES 3; the offer is "Want the names? / Want the full list? / Want the details?").
- The no-repeat blocker (`repeat_of_last`: the same text to a different question within 30 min gets "That's what I just sent…").
- The `Heard: "…"` prefix for voice.

**`send_whatsapp_message`** (S:55820):
- `_strip_generic_offer` (a trailing "anything else?" and similar).
- The DM send verdict (opt-in / reply window).
- Pacing and retry.

Shabbos quiet hours do not apply to replies.

## Models

| Where | Model |
|---|---|
| Job agent `_run_group_agent` | **gpt-4o** (`AGENT_MODEL`), temp 0.2, 800 tokens, max 4 tool rounds |
| Router `_dm_scope` | gpt-4o-mini |
| Change reader, subs answer, general / all-jobs answers, headcount rewording, report summary, punch brain / location / batch | gpt-4o |
| Project memory answer | gpt-4o, plus text-embedding-3-small |
| Voice | whisper-1, then gpt-4o-mini translation |
| Punch photo words | Qwen vision |

There is no Anthropic model anywhere on the DM path.

## Context the job agent gets

- **History:** the last 20 DM messages **within 4 hours**, both sides, each cut to 1500 chars. Older than 4 h is gone.
- **Job:** a context block for **one active job only**: name, address, GC, roster today, open items, permit counts, sheet index.
- **User:** nothing about the user. No name, no role, no list of their jobs. `sender` is only phone digits for logging and tools.
- **Open flows:** none. A walk in progress, a pending change ("Add it?"), the "Which job?" menu, "Since…?", and the "Want the names?" offer are not given to the model. They are visible only as earlier message text.
- **Tools** (DM): who_on_site, daily_log, dob_status, open_items, active_permits, material_status, check_drawing_set, search_plans, project_info, search_project_history, recent_voice_notes, find_sub, list_subs, follow_ups, brief_status, sub_attendance, site_headcount, punch_status, upcoming_events. All are read-only, and all except find_sub/list_subs are bound to the one job chosen before the model ran. Removed in DMs: start_permit_renewal, start_checklist, list_workers, query_plan.

## Net effect

At least 19 rule-based routers decide what a message *is* before any model sees it. Each has fixed reply texts. The model, when reached, sees one job, no user and no open state. Its answer then passes through 7 rewrite guards, a 300-char / 3-line cutter and a repeat blocker. Most of the dm_eval failures, and all three on Tuesday, come from those layers, not from the model.
