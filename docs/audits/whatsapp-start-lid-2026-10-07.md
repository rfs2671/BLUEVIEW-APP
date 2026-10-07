# WhatsApp START got no reply: trace, cause, fix (2026-10-07)

**Report.** At 20:40 UTC, michael@blueviewbuilders.com (admin, phone +1 516-301-8154) sent START from that phone to the bot (+1 516-549-4475).
- WhatsApp showed the message delivered (two grey ticks).
- No reply came back, and no opt-in was recorded.
- The card stayed at "Not connected".
- WaAPI is subscribed to `message` and `group_join`, and the monitor reads "ready".

## Most likely cause: the sender arrived as a WhatsApp privacy id (@lid)

**What WhatsApp sends.** WhatsApp now identifies many one-to-one senders by a privacy id, `<digits>@lid`, instead of `<phone>@c.us`.

**What the code did with it.** On main before this fix, the direct-message branch took the digits of `from` as a phone number. The START handler then made three mistakes:
- It looked those digits up in `users.phone` and found nobody, so it refused the opt-in.
- It chose the neutral "not available" reply.
- It addressed that reply to `<lid digits>@c.us`, a chat that does not exist.

The result was no opt-in and no visible reply, which is exactly what was reported.

**Reproduced on main.** Running main's `server._process_whatsapp_message` on a START from `205842133426370@lid` gives:
```
opt-ins: []
sends:   [('205842133426370@c.us', "Blueview here. WhatsApp updates aren't available for this number.")]
```

**Still to confirm with the live payload.** The queries below show whether the 20:40 message really arrived as `@lid`. If it arrived as `@c.us`, the cause lies elsewhere in the drop-point table.

## The path a one-to-one START takes, and every place it can stop

Line numbers are `backend/server.py` on this branch.

| # | Step | Where it can stop | What it logs |
|---|---|---|---|
| 1 | WaAPI must call the webhook. Subscribed events: `message`, `group_join` | WaAPI never calls: instance down, wrong URL, event not subscribed | nothing in our logs; nothing in `whatsapp_webhook_log` |
| 2 | Token check, `whatsapp_webhook` :53493 | wrong or missing `?token=` → 401, body never read | `[security-event] {"kind": "whatsapp_webhook_rejected", ...}` |
| 3 | Raw body stored, :53539 | (stored before anything else, unless that write fails) | `webhook log insert failed: ...` on failure |
| 4 | JSON parse | body isn't JSON → 200, dropped | **nothing** |
| 5 | `_process_whatsapp_message` :52655, `parse_inbound_message` :43737 | any exception | `WhatsApp message processing error: ...` with traceback |
| 6 | Own-message filter, :52683 | `fromMe`, or the sender matches a known or learned bot identifier | **nothing** |
| 7 | DM branch: reply window opened, :53265 | window write fails → later replies refused | `reply window open failed: ...` |
| 8 | Command parse, `wa_dm.parse_dm_command` | body isn't exactly START or STOP (or `START <code>`) → treated as a normal DM; an unknown number then stays silent | **nothing** before this fix; now `[wa-dm] inbound start kind=lid\|c.us chat=...NNNN` |
| 9 | START → identity | **before:** `@lid` digits looked up as a phone → nobody | `[security-event] {"kind": "whatsapp_optin_refused", "reason": "no_user", ...}` |
| 10 | Opt-in write | write fails | **before:** `opt-in write failed: ...` and **no reply**; now `start_write_failed` plus a "try again" reply |
| 11 | Reply gate `_dm_send_verdict` :43152 | reply window missing or used up | `WhatsApp DM refused (no_active_optin) to ...NNNN` |
| 12 | Send | **before:** sent to `<lid>@c.us`, so WaAPI either errors or delivers to no one | `WhatsApp send failed to <chat>: http NNN`, or **nothing** if WaAPI returns 200 for a non-existent chat |

## Railway log searches (around 20:40 UTC)

- `whatsapp_webhook_rejected`: any hit means a token problem (row 2).
- `WhatsApp message processing error`: an exception (row 5).
- `whatsapp_optin_refused`: the reason field gives `no_user`, `role_not_eligible` or `ambiguous` (row 9). On main this is the `@lid` signature: `no_user` for a phone that *is* on an account.
- `WhatsApp DM refused` / `WhatsApp send failed to`: the reply gate or the send (rows 11–12). A chat id ending in `@c.us` that isn't `15163018154` is the `@lid` digits.
- After this fix, also: `[wa-dm] inbound start`, `[wa-dm] start_`, `[wa-dm] reply NOT delivered`, `[wa-dm] lid lookup`.

## Read-only mongosh queries

```js
// 1. Did WaAPI deliver the 20:40 START, and from which kind of id?
db.whatsapp_webhook_log.find(
  {received_at: {$gte: ISODate("2026-10-07T20:38:00Z"), $lte: ISODate("2026-10-07T20:45:00Z")}},
  {received_at: 1, raw_body_length: 1, raw_body_preview: 1}).sort({received_at: 1})
// In raw_body_preview, look at "from": "...@lid" vs "...@c.us", and search for
// "senderPn" / "participantPn" / "phoneNumber" (a phone carried beside the lid).

// 2. Same window, only messages whose body is START
db.whatsapp_webhook_log.find(
  {received_at: {$gte: ISODate("2026-10-07T20:38:00Z"), $lte: ISODate("2026-10-07T20:45:00Z")},
   raw_body_preview: /"body"\s*:\s*"START/i}, {received_at: 1, raw_body_preview: 1})

// 3. Any opt-in rows at all, and for michael's number
db.whatsapp_optins.find({}, {phone: 1, user_id: 1, status: 1, source: 1, updated_at: 1}).sort({updated_at: -1}).limit(10)
db.whatsapp_optins.find({phone: "15163018154"})

// 4. The reply window the START opened (keyed by the digits of the chat id)
db.whatsapp_dm_reply_windows.find({opened_at: {$gte: ISODate("2026-10-07T20:38:00Z")}})
// _id = 15163018154 means it arrived as @c.us; any other digits = the @lid.

// 5. What came back from the bot in that window
db.whatsapp_messages.find({is_dm: true, created_at: {$gte: ISODate("2026-10-07T20:38:00Z")}},
  {group_id: 1, body: 1, created_at: 1})
```

## The fix

**Every START gets exactly one reply, sent back to the chat it came from.** That reply is the intro, or one plain line saying what to do.

**Replies go to the chat id itself, never a rebuilt one.** `wa_dm.dm_chat_id` returns a JID unchanged, and the DM branch passes `parsed["from"]`.

**Finding the phone for a `@lid` sender** (`_resolve_dm_phone`). It tries these in order:
1. A phone field in the webhook payload: `senderPn`, `participantPn`, `phoneNumber`, `pn` (`wa_dm.phone_from_payload`). **Unverified** field names; all are tried.
2. An earlier verified opt-in from the same chat.
3. WaAPI `client/action/get-contact-by-id {contactId}` (`_waapi_contact_phone`). **Unverified** action. Each call logs `[wa-dm] lid lookup ...` with the response, minus the token, so the shape can be confirmed.

**The connect code works whatever WhatsApp withholds.** The app's "Turn on alerts" link sends `START <code>`.
- The code is a per-user, per-day HMAC (`wa_dm.connect_code`) that names the account. Issuing it stores nothing.
- It connects a `@lid` sender even when no phone can be found.
- If the sender's phone *is* known and differs from the profile phone, the opt-in is refused.

**Where alerts go.** The opt-in records `chat_id` and `chat_digits`. Proactive sends (`send_whatsapp_dm`) go to that chat. STOP from that chat ends the opt-in, and the reply gate finds the opt-in by chat.

**Every outcome now has a reply:**

| Outcome | Reply |
|---|---|
| unknown number / role that can't get alerts | `NOT_ELIGIBLE_TEXT` (deliberately the same for both) |
| `@lid` sender, no phone found, no code | `NEED_APP_TEXT` |
| unknown or expired code | `CODE_EXPIRED_TEXT` |
| code sent from a different phone | `WRONG_PHONE_TEXT` |
| account has no phone | `PHONE_MISSING_TEXT` |
| number on two accounts | `PHONE_SHARED_TEXT` |
| opt-in write failed | `TRY_AGAIN_TEXT` |
| opted in | `INTRO_TEXT` |

**Logging.** Each outcome logs `[wa-dm] <outcome> kind=lid|c.us chat=...NNNN`, plus a line if the reply could not be delivered.
