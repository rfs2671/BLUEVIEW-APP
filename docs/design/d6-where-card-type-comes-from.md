# D6 — where `card_type` actually comes from

_2026-08-19. Report only. **D6 is NOT ruled.** This answers the provenance
question that has to be settled before any ruling._

---

## 0. First, the number

**The ~68% fill rate did not come from me, and I cannot confirm it.** I have no
query access to production and have measured no fill rate at any point. It
should not be treated as a finding of mine or used as an input to a ruling until
someone runs the query in §5.

What follows is provenance, which is answerable from the code alone.

---

## 1. The short answer

**`card_type` is not read from the card. It is inferred, and the inference can
overrule the only place a reading could have come from.**

There are three inference rules and one of them requires nothing to have been
read at all. `server.py:2188-2199`, verbatim:

```python
    # Resolve ONE class for this ONE image (Amendment B).
    card_type = str(od.get("card_type") or "").strip().upper()
    card_class = od.get("card_class")
    raw_expiry = od.get("expiration")
    if card_type == "OSHA" and not raw_expiry:
        resolved_kind = "OSHA"
    elif card_type == "SST" or raw_expiry:
        resolved_kind = "SST"      # an expiry means SST (OSHA post-2020 is lifetime)
    elif osha_number or osha_card_image:
        resolved_kind = "SST"      # ambiguous NFC card → SST (still satisfies OSHA baseline)
    else:
        resolved_kind = None
```

- **Rule 2** — `or raw_expiry` — makes a card SST because *a date was read*.
- **Rule 3** — `osha_number or osha_card_image` — makes a card SST because
  **a photo exists.** Nothing needs to have been read from it.

## 2. Is the model even asked to read it?

No. It is asked to **judge**. The extraction prompt (`server.py:10123`) asks
for:

```
"card_type": "OSHA or SST — which kind of card this is"
```

Compare it with the sibling field one line later, which *is* a transcription
instruction — "the exact class or level **printed on** the card", with an
explicit "If only hours are visible and no class word, set `card_class` to
null".

So `card_class` is asked to be read and permitted to be null. `card_type` is
asked to be classified, and is given no null instruction and no "printed on the
card" anchor. The prompt treats the two differently, and only one of them is
transcription.

**This supports the operator's position directly.** If most cards do not print
the words "OSHA" or "SST", then a model asked "which kind is this?" will answer
from layout, colour, wording, or prior — and that answer arrives in the same
field a reading would have.

## 3. What the code does — demonstrated, not described

Run against the real shipped `build_worker_certifications`:

| Case | OCR returned | Row written | completeness |
|---|---|---|---|
| **A** | `card_type: null`, nothing else read at all. A card photo exists | **`SST_UNSPECIFIED`** | 0.25 |
| **B** | `card_type: null`, an expiry only | **`SST_UNSPECIFIED`** | 0.25 |
| **C** | `card_type: **"OSHA"**`, class `"30"`, plus an expiry | **`SST_UNSPECIFIED`** | 0.75 |
| **D** | nothing read, **and no photo, no number** | no row written | — |

Three things to draw out.

**Case A is the operator's concern, exactly.** The VLM read *nothing* — no name,
no number, no type, no class, no date. A certification row is still written, and
it is typed **SST**. The only input was that a photo existed. The "SST" in
`SST_UNSPECIFIED` is itself an inference; the `UNSPECIFIED` half honestly
reports that the *class* is unknown, and says nothing about the *kind* being
equally unknown.

**Case C is worse than a guess — it is a guess that overrode a reading.** The
model said **OSHA**. The record says **SST**, because rule 2 sees the expiry and
fires first. The one case in this table where the model actually produced a
type, that type was discarded. And it scores the *highest* completeness of the
three (0.75), because completeness counts name/number/class/expiry and **not**
`card_type` — so the row whose kind contradicts what was read looks like the
best-extracted row of the set.

**Case D shows what the row's existence actually depends on:** a photo or a
number, not a successful read.

## 4. Why this matters beyond the field itself

`RECOGNIZED_SST_TYPES = SST_CLASS_TYPES | {SST_UNSPECIFIED}` (`server.py:2103`),
described in its own comment as:

> Every value the gate treats as "a NYC SST card exists on this worker".

So the chain is: a photo exists → rule 3 → `SST_UNSPECIFIED` → the gate treats
the worker as holding a NYC SST card, satisfying the OSHA baseline. **On a
compliance record.** Nothing in that chain required a single character to be
read off the card.

The anti-silence work is real and does hold for the *class*: `_sst_cert_state`
refuses to call an unread class `valid`, `needs_review` is raised, and the review
queue names it. All of that is about `card_class`. **Nothing anywhere expresses
doubt about the KIND**, because nothing records that the kind was inferred.

## 5. What would actually settle the fill-rate question

The provenance above is certain from code. The *volume* is not, and the
distinction the operator is asking about is answerable with one read-only query:

1. **How often is each rule the one that fired.** Not recoverable from stored
   data today — `card_type` is never persisted, only `resolved_kind` as `type`.
   **This is the gap that has to be closed before any percentage means
   anything.** The cheapest version: persist the raw `card_type` and which rule
   resolved the kind, then read the distribution after a week of real check-ins.
2. In the meantime, a proxy from what *is* stored: among SST rows, count those
   with `extraction_completeness <= 0.25` (nothing but the row's existence was
   established) and those with `review_reason == "CLASS_UNVERIFIED"`. A high
   share of the former is rule 3 firing.

Until (1) exists, **any fill-rate number describes how often a row got a type,
not how often a type was read.** Those are different questions and only the
second one bears on the ruling.

## 6. The honest next step, stated as the operator framed it

If the gap is real, it is an **OCR problem or a CP-confirmation problem**, and
this report adds a third that is prior to both:

**It is a provenance problem first.** Right now the record cannot distinguish
"read from the card" from "assumed because a photo existed", so neither an OCR
improvement nor a CP-confirmation flow could be measured against it. In rough
order of cost:

1. **Record the provenance.** Persist raw `card_type` and the rule that
   resolved the kind. Small, no behaviour change, and it makes every later
   question answerable.
2. **Let the kind be unknown.** There is no `SST_KIND_UNVERIFIED` and no
   `resolved_kind = None` path for "a photo we could not read". Rule 3 exists
   because *something* had to be written; "cannot determine the kind from this
   photo" is not currently expressible, exactly as "cannot determine the class"
   was not a first-class answer before.
3. **Then** decide between better OCR and CP confirmation, with numbers.

**Colour is not on this list**, and the case against it is stronger now than
when D6 was first drafted: it would add a second inferred signal to a field
whose problem is that its existing signal is already inference nobody can audit.

---

## Not ruled, deliberately

No recommendation is made here on building or not building anything. §5 item 1
is the prerequisite for a defensible ruling either way, and it is small.
