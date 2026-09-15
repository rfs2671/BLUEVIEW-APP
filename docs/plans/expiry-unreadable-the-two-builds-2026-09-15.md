# THE EXPIRY A SCANNER COULD NOT READ — TWO BUILDS, AND THE LINE BETWEEN THEM

Written 2026-09-15. Measured against production, not reasoned about.

This is the real cure for item 1. The card-check attestation (PR #530) clears
nobody: all 25 flagged certifications exit `_sst_cert_state`'s ladder above the
guard, and `class_source` is `color_only`/`conflict` on **zero rows in the
entire database**. What actually flags these men is the expiry.

---

## THE POPULATION

Census of all 75 certifications on production:

```
expiry parsed cleanly       : 56
expiry REFUSED and kept raw : 17
neither (no expiry at all)  :  2

review_reason   EXPIRY_UNPARSEABLE  17
                CLASS_UNVERIFIED     8
                (none)              50
```

The 17 and the 8 sum to the 25 flagged certifications.

**Every one of the 17 refused strings, verbatim:**

```
 11  '2027-10-03'      ISO
  1  '2026-05-06'      ISO
  1  'illegible'       the model's own word
  1  'null'            pre-fix OCR artefact
  1  '05/35'
  1  '10272029'
  1  '062427'
```

**Twelve of seventeen are valid, unambiguous ISO dates.** They were thrown away
because `_parse_mdy` accepts `%m/%d/%Y` and nothing else. Twelve men are flagged
for the parser's narrowness, not for anything wrong with their card.

---

## THE LINE BETWEEN THE TWO BUILDS

> **BUILD 1 takes the formats that are unambiguous BY CONSTRUCTION.
> BUILD 2 takes everything that is unambiguous only BY CONVENTION.**

`'10272029'` is the case that decides where the line sits, and it is the case
someone will later try to move into the parser. **It must not move.**

A human reads `10272029` as 27 October 2029 without hesitating. But that reading
is only available to someone who already assumes month-day-year. The same eight
digits are 10 December 7202 under a different assumption, and — more to the
point — nothing in the string itself says which. `2027-10-03` is different in
kind: ISO 8601 is self-describing, a four-digit leading field cannot be a month
or a day, and there is exactly one reading.

So: **`'10272029'` belongs on the correction path with the other four, and the
reason is not that it is hard to read. It is that the parser would be guessing,
and a guess about an expiry date on a §3301 compliance record is the thing this
product does not do.** Write that down wherever the parser is widened, because
the next reader will see an obvious date being sent to a human and try to fix it.

---

## BUILD 1 — WIDEN THE PARSER. Twelve rows, no human, no screen.

**Where.** `_parse_mdy`, a nested function at `backend/server.py:3696`, inside
`build_worker_certifications` (`server.py:3654-3922`).

```python
def _parse_mdy(s):
    try:
        return datetime.strptime(str(s), "%m/%d/%Y").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
```

**What to accept.** `%Y-%m-%d` in addition to `%m/%d/%Y`. Nothing else in this
build — every other observed shape is ambiguous and belongs to Build 2.

**Three consequences to handle, not one.**

1. **`_parse_mdy` also parses `issued`** — `issue_dt = _parse_mdy(od.get("issued"))`
   at `server.py:3759`. Widening it means issue dates that previously read as
   `None` will now resolve, which changes two live tests at `server.py:3783`:
   the `exp_dt <= issue_dt` sanity check, and the `SST_TEMPORARY` ceiling
   (`_base = issue_dt or now`). A card whose issue date starts parsing can
   therefore newly trip `EXPIRY_IMPLAUSIBLE`. **Measure this before shipping:**
   count how many stored `issued` strings are ISO, and what the plausibility
   gate would say about each once they parse.
2. **The reason is written once and never re-derived.** `needs_review` and
   `review_reason` are set only in `build_worker_certifications`, which runs at
   check-in/registration. Nothing recomputes them on read — `_sst_cert_state`
   and `validate_worker_certifications` never read `needs_review` at all. **So
   widening the parser clears nobody who is already flagged.** It only stops the
   next twelve.
3. Therefore Build 1 needs a backfill to reach the men who are already flagged
   — see below.

**The backfill, and why it is safe here.** The raw string is preserved verbatim
in `expiration_raw_rejected` (`server.py:3192`, written at `:3831`). So the
backfill is: for each certification carrying `expiration_raw_rejected`,
re-run the *widened* parser; where it now resolves, write `expiration_date`,
clear `expiration_raw_rejected`, and clear `EXPIRY_UNPARSEABLE`. It is
deterministic, it invents nothing, and it is auditable because the input is
still on the record.

**But it must not repeat #530's side door.** `card_image_may_be_replaced`
(`server.py:3586`) reads `needs_review or expiration_date is None`. Lowering the
flag flips it to `False`, which means a possibly-wrong card photo can no longer
be replaced by a later re-scan. That is the exact unadvertised effect that got
the card-check half parked. **The backfill must state what it does to that
predicate for each row it touches, and the twelve here are rows whose date is
now known-good — which is the one case where locking the image is arguably
correct. Argue it explicitly; do not inherit it silently.**

**Default the script to read-only `--report`. Do not run it against production
without showing the operator the row list first.**

---

## BUILD 2 — THE CORRECTION PATH. Five rows, four different problems.

A date picker expresses none of these. That is the design constraint, and it
comes from the data.

| value | worker | what it is | what the screen must allow |
|---|---|---|---|
| `'illegible'` | Dmitri Volkov | the model said, in words, that it could not read the card | **"the card cannot be read"** as a first-class outcome, not an empty field |
| `'null'` | the `null` worker | pre-fix OCR artefact; the boundary is already closed by `norm_ocr_str` in `backend/lib/ocr_text.py`, which maps `{"null","none","n/a"}` to `None` | nothing new — it is historical |
| `'05/35'` | WILMER CARRILLO | **two readings.** May 2035? Or May, day 35 — itself impossible — with the year lost? | a human with the card in hand |
| `'062427'` | Geovany Baten | **two readings, and one is an expired card.** 06/24/2027 or 06/24/1927 | a human with the card in hand |
| `'10272029'` | Juan Lopez | unambiguous to a person, a guess for a parser | a human, by the rule above |

**What the screen has to accept, stated as requirements:**

1. **Show the raw string.** The man correcting it must see exactly what the
   scanner produced, because that is what he is comparing against the card.
   Never show him a blank field and ask for a date.
2. **Preserve the raw string after correction.** `expiration_raw_rejected` is
   the audit trail. A corrected row must record both what was read and what a
   named person entered, with who and when — the same shape as the card-check
   attestation, which was the right idea attached to the wrong question.
3. **Accept "cannot be read" as an answer.** `'illegible'` is a real outcome and
   the only honest response to a worn card. An interface that forces a date
   produces a fabricated one.
4. **Never pre-fill a guess.** Offering `06/24/2027` for `'062427'` puts a date
   in front of a man who will accept it, and one of the two readings is an
   expired card. This is the same rule `designatedCpDefault` follows: a wrong
   default on a statutory item is worse than no default, because a name — or a
   date — that looks right is not questioned.
5. **Record the correction against the person, not the device.** Same reasoning
   as `_resolved_cp_name`: the account is the identity.

**What it must NOT do:** synthesise a correction from an existing
`review_decision`. `backend/scripts/backfill_sst_card_check.py` already refuses
this by raising, and the reason holds here — putting a named CP's id against an
attestation he never made, retroactively, on a compliance record.

### THERE IS NO GATED EDIT PATH, AND THE UNGATED ONE IS THE BIGGER PROBLEM

Every route on a worker, measured:

```
POST   /workers/{worker_id}/certifications                 (server.py:16668)  add
DELETE /workers/{worker_id}/certifications/{cert_index}    (server.py:16743)  remove by index
PUT    /workers/{worker_id}                                (server.py:16902)
```

**There is no `PUT` or `PATCH` on a certification.** Correcting an expiry
through the certifications sub-resource therefore means delete-then-re-add —
and the re-add runs through the shape gate at `server.py:16772`, which for the
four case-affected cards refuses the number printed on the physical card. Two
defects compound: a man flagged for an unreadable expiry cannot have it fixed,
and for four men the workaround is blocked by a case comparison.

**But `PUT /workers/{worker_id}` does admit the whole array**, and it is
ungated:

```python
ALLOWED_WORKER_FIELDS = {"name", "phone", "osha_number", "certifications",
                         "emergency_contact", "emergency_phone", "notes"}
update_data = {k: v for k, v in worker_data.items()
               if v is not None and k in ALLOWED_WORKER_FIELDS}
... {"$set": update_data}
```

A client can `$set` a certifications array straight onto the document: **no
`_card_number_shape` check, no expiry sanity gate, and no re-derivation of
`needs_review` or `review_reason`.** So today an expiry can be "corrected" to
anything at all while the flag keeps whatever value it had — or is set to
whatever the client sends. That is not a missing edit path; it is an unguarded
one, and it is the reason Build 2's endpoint must be narrow rather than a
general worker update.

### THE CORRECTION MUST RE-DERIVE, NOT LOWER A FLAG

The endpoint takes `(worker_id, cert_index, expiration_date)` and pushes the
value back through the SAME gate at `server.py:3809-3834` that wrote the reason
in the first place — recomputing `stored_exp`, the plausibility ceiling, and
`needs_review`/`review_reason` from it. It must never assign `needs_review =
False` by hand. A hand-lowered flag is what made PR #530 look like a cure, and
re-deriving is the only way the plausibility rules (`exp_dt <= issue_dt`, the
`SST_TEMPORARY` ceiling) still get a say on a human-entered date.

And `expiration_raw_rejected` is written and almost never read — only
`server.py:15450` and `server.py:37560` consult it, and **no frontend file reads
it at all.** The evidence a person needs in order to make the correction is
already on the record and has never been shown to anybody.

---

## ORDER, AND WHY

**Build 1 first.** It is the largest single clearance available, it costs one
format string plus a backfill, it needs no screen and no human, and it removes
twelve of the seventeen rows before anybody designs an interface for the
remainder. Designing the correction screen first would size it for seventeen
users when its real population is five.

## WHAT IS EXPLICITLY OUT OF SCOPE

- The 8 `CLASS_UNVERIFIED` rows. Different reason, different input
  (`resolve_card_class`), different fix.
- The card-number case defect (`_card_number_shape` is case-sensitive and
  nothing uppercases on write). Its own change, already in flight.
- PR #530's card-check attestation. Parked, and neither build depends on it.

---

# CORRECTION, 2026-09-15 — THE CENSUS ABOVE IS NOT TENANT-SCOPED

Everything above counts across all three companies in the database. It should
have counted one. Scoped to **BLUEVIEW CONSTRUCTION INC**, the real numbers are:

| | unscoped (above) | test company | **Blueview** |
|---|---|---|---|
| flagged certifications | 25 | 13 | **12** |
| `EXPIRY_UNPARSEABLE` | 17 | **13** | **4** |
| recoverable by Build 1 | 12 | **12** | **0** |

**Build 1 cleared twelve seeded rows and zero real workers.** The eleven
identical `'2027-10-03'` expiries were not a crew handed cards together; they
were a seeder writing one value eleven times into the operator's test company,
alongside sequential phone numbers and `created_at` values inside a single
second. Hector Ramirez's recovered-then-expired card is seeded data.

**Build 1 was still worth shipping and worth running.** The parser was genuinely
narrow, the widening is correct for any real ISO date that arrives next, and
executing the backfill proved the planner against real database rows rather than
a fixture — 12 written, idempotent, converged, the planner's verdicts identical
to the gate's. It simply did not help anybody.

**Build 2's real population is four, and three of them are the interesting
ones:**

```
WILMER CARRILLO   '05/35'      two readings
Juan Lopez        '10272029'   unambiguous by convention only
Geovany Baten     '062427'     two readings, one of them an expired card
null              'null'       the closed OCR artefact
```

Every real `EXPIRY_UNPARSEABLE` row needs a human with the card. Not one is
recoverable by widening a parser — which means **the whole of the real expiry
problem is Build 2**, and Build 1's value was structural, not remedial.

## AND THE LARGER HALF OF ITEM 1 IS NOT THE EXPIRY AT ALL

Of the 12 real flagged certifications, **8 are `CLASS_UNVERIFIED`**, not
`EXPIRY_UNPARSEABLE`: Jose David Hernandez Pena, Jhonatan Tipantuna, Angel
Lopez, Pablo Andrade, risthian M Cabrera, Amaury ayala ontero, Abel Alvarez,
Marcelino c garcia.

**It is not the colour-only path.** `class_source` is `None` on all eight, not
`color_only` or `conflict`, and `resolve_card_class` returns
`{'sst_type': 'SST_UNSPECIFIED', 'class_source': None, 'review_reason':
'CLASS_UNVERIFIED', 'color': ''}` for every one of them — because their stored
`osha_data` carries `card_type=None, card_class=None, card_color=None`. The scan
captured a number and an expiry and **no class information whatsoever**. That is
a different failure from Wilmer Carrillo's colour-only case, and it is not
curable by reading colour better.

Two of the eight (Jose David Hernandez Pena, Jhonatan Tipantuna) additionally
carry a stored `type` of `SST_LIMITED`, which is in `SST_DEAD_CLASSES`, so they
would remain flagged even if the class resolved.

That is its own investigation and its own build. Not this one.
