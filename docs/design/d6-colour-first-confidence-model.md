# D6 — the colour-first confidence model

_2026-08-20. **Report only.** Supersedes the ordering in
[d6-colour-classification-capture-and-model.md](d6-colour-classification-capture-and-model.md);
its capture findings still stand._

**Ruled:** colour leads. Text corroborates when present, never leads.
**Hard constraint, unchanged:** colour PROPOSES, never ASSERTS. "Cannot
determine class from this photo" is a first-class answer and better than a
guess.

---

## 0. Three claims in the instruction, checked

I checked all three before writing. None of them hold, and the third matters
most because it changes where the colour has to come from.

### `card_class_signals` / `card_color_hint` / `border_color_hint` — **do not exist**

```
grep -rn "card_class_signals|card_color_hint|border_color_hint" *.py *.html *.jsx
→ no matches
```

Zero hits across the backend, `checkin.html`, and the frontend. So the premise —
*colour was requested once and something downstream stopped using it* — has no
subject. **There is no "what stopped using it" to report, because nothing ever
requested it.** The VLM prompt at `server.py:10123` asks for six fields (`name`,
`sst_number`, `card_type`, `card_class`, `issued`, `expiration`, plus `box_2d`)
and has never asked for a colour.

I would rather say this plainly than construct a plausible history for a field
that was never there.

### `_download_r2_object` — **does not exist**, but the capability does

No function by that name. However `_r2_client.get_object` is called directly in
about ten places (`server.py:405`, `:16181`, `:16502`, `:17442`, `:19020`,
`:28115`, `:28556`, `:28574`). So **reading an object back from R2 is easy and
well-established** — there is simply no shared named helper, and one would be
worth extracting if this work proceeds. Partial credit to the claim: the
mechanism is there, the name is not.

### `enhanced_r2_key` holds a 1600px card original — **no, on three counts**

1. **It is not a card field.** The enhance pass is scheduled only from the
   logbook activity-photo path — `_enhance_one_photo_sync(b64, project_id,
   logbook_id, ai, pi)`, keyed by logbook id, activity index and photo index.
   No card image ever enters it. Every `enhanced_r2_key` reference in the
   codebase is in the photo-serve ladder or the thumbnail retention path.
2. **It is not 1600px.** `photo_enhance.py` encodes the enhanced copy at
   **long edge 1800, q85**, with a 400px q80 thumbnail beside it.
3. **It is not an original.** It is the *output of an enhancement pass* —
   contrast and colour adjustment. **This is the important one:** reading a
   card's colour off an enhanced derivative would be reading a colour the
   enhancement produced. Even if cards did pass through it, it would be the
   wrong input for this specific job.

### Where the 1600px original actually is

**`osha_card_image`, inline base64 on the worker document** — the frame captured
at `compressImage(rawImage, 1600, 0.85)` (`checkin.html:1259`). It is the
highest-fidelity copy that exists anywhere, it is already server-side, and it is
already what the OCR call receives. **Colour classification should read from
that**, and needs no new download path at all on the live flow.

(The capture comment records that 1600/0.85 was itself a raise from 1200/0.7
because the class label was illegible — so the fidelity question has been
answered once already, in this direction.)

---

## 1. Why colour leads

The three field facts, and what each one kills:

| Field fact | Consequence |
|---|---|
| A 40-hour card carries **no class text at all** | On the most common card there is nothing for OCR to read. Text cannot lead a signal it does not have |
| **Text washes off worn cards; colour does not** | Text degrades to null exactly on the cards that most need reading. Card stock does not wear to a different colour |
| **Purple Training Connect reads as regular SST** | Text does not fail safe. It fails to a *confidently wrong class*, which is worse than unknown |

Colour survives all three. So colour is the primary signal — **and it still only
proposes**, because the failure modes that remain (colour cast, tinted sleeve,
auto-HDR, glare) are real and are exactly what a proposal is for.

**Nothing in this model asserts a class automatically.** Text does not get
promoted to asserting just because colour is not allowed to; a class reaches
"confirmed" only when colour and text agree, or when a human confirms it. That
is the direct consequence of holding the hard constraint while also demoting
text.

---

## 2. Which model, and how it is prompted

### The model

Same call, same model: `Qwen/Qwen2.5-VL-7B-Instruct` (`server.py:533`,
`QWEN_MODEL`-overridable), at `/checkin/upload-osha`, reading the same
1600/0.85 frame. No second model and no second round-trip — a man is standing at
a turnstile and a second dependency is a second thing that can be down.

**But prefer arithmetic to the model where you can get it.** A dominant hue is
computable from the JPEG directly, server-side, with no VLM involved:
deterministic, auditable, unit-testable offline against fixture images, and
incapable of hallucinating. If the colour→class map is a hue table, then the
VLM's role shrinks to reporting the *conditions* (sleeve, cast, glare) that say
when not to trust the hue. That is the strongest version of this and it should
be priced against the VLM-reports-colour version before either is built.

### The prompt — two new fields, and what they may not say

`card_class` keeps its existing instruction verbatim: "the exact class or level
**printed on** the card… If only hours are visible and no class word, set
`card_class` to null." That instruction is already correct and is now the
*corroborating* signal rather than the leading one.

Added:

```
"card_dominant_color": "the dominant background colour of the CARD STOCK — not
   the lanyard, sleeve, hand, or background behind it — as one of:
   WHITE, BLUE, GREEN, PURPLE, RED, YELLOW, ORANGE, GREY, OTHER.
   If the card is inside a tinted or reflective sleeve, if the lighting has an
   obvious colour cast, if glare covers much of the card, or if you are not
   confident, return null. Do NOT infer the colour from any words on the card.",

"card_color_confidence": "high | medium | low — how sure you are of
   card_dominant_color given glare, shade, colour cast and sleeve.
   null when card_dominant_color is null.",

"card_color_conditions": "any of: GLARE, SHADE, COLOR_CAST, SLEEVE,
   PARTIAL_CARD — the conditions that could be distorting the colour. [] if none."
```

**The prompt must contain no colour→class mapping, no SST class names, and no
card-type names in the colour instruction.** Three reasons, the last decisive:

1. a mapping in the prompt lets the model work backwards — read a class, then
   report the colour that justifies it;
2. a mapping in a prompt string is a rule no test can assert against;
3. it would make the model the thing that decides the class. **Keeping the table
   in Python is what makes "proposes, never asserts" an enforceable property
   rather than an intention.**

`Do NOT infer the colour from any words on the card` is load-bearing for the
purple case specifically: a Training Connect card that still has legible SST
wording is precisely where a model would be tempted to report the colour it
expects rather than the colour it sees.

---

## 3. The resolution rule, colour-first

```
colour present AND confidence high AND unambiguous in the map?
├─ NO  → text present and recognised?
│        ├─ YES → PROPOSED from text. needs_review = True.
│        │        class_source = "text_only"
│        │        (text corroborates; alone it does not confirm)
│        └─ NO  → SST_UNSPECIFIED / CLASS_UNVERIFIED
│                 "cannot determine class from this photo"
└─ YES → proposed := map[colour]
         ├─ text ABSENT (the 40-hour card)   → class_source = "color_only"
         │                                     needs_review = True
         ├─ text AGREES                      → class_source = "color_and_text"
         │                                     needs_review = False   ← the ONE
         │                                     confirmed state
         └─ text DISAGREES                   → see §4
```

Three properties make this a proposal rather than an assertion, and all three
are required:

1. **`needs_review` is True on every path except colour-and-text agreement.**
   One confirmed state, and it needs two independent signals.
2. **`class_source` is persisted** — `"color_and_text" | "color_only" |
   "text_only" | null`. Without it a proposed class is indistinguishable from a
   confirmed one the moment it is stored. This is the exact provenance failure
   already documented for `card_type` in
   [d6-where-card-type-comes-from.md](d6-where-card-type-comes-from.md), where
   an inferred kind is unrecoverable from the record. **Do not repeat it on a
   second field.** This is the single most important line in the change and is
   worth shipping on its own, before any colour work.
3. **`_sst_cert_state` returns `valid` only for `class_source ==
   "color_and_text"`.** Every other source lands on `unknown`. A class name
   present in the document must not be enough to make a credential valid.

---

## 4. When colour and text disagree

**Neither wins. The record says the photo could not settle it.**

```
CLASS_CONFLICTED
  type            = SST_UNSPECIFIED        ← NOT either candidate
  class_source    = "conflict"
  needs_review    = True
  review_reason   = "CLASS_CONFLICTED"
  card_color_seen = <the colour>           ← both candidates retained
  card_class_text = <the word>                for the human who resolves it
```

**Why not let colour win, given it leads?** Because "colour leads" is about
which signal is consulted first and which is trusted when the other is *absent*
— not about who wins a contradiction. The three field facts establish that text
can be confidently wrong; they do not establish that colour is never wrong. A
tinted sleeve, sodium lighting, or a colour-shifted auto-HDR frame all produce a
confident wrong colour. Letting colour win a disagreement would trade one
confidently-wrong class for another, which is the thing the hard constraint
forbids regardless of which signal produced it.

**Why not let text win?** The purple Training Connect card is exactly a
disagreement — purple stock, SST-looking wording — and text winning is the
current, broken behaviour.

**A disagreement is information, not noise.** Two independent signals
contradicting each other is the strongest available evidence that something is
unusual about this card: a reissued card, a lookalike, a card in someone else's
sleeve, or a forgery. Resolving it silently in either direction destroys that
signal. Surfacing it is the point — and it must be a *different* review reason
from `CLASS_UNVERIFIED`, because "we could not read it" and "two things about
this card disagree" send a reviewer to look for different things.

**One exception worth building in from the start:** if `card_color_conditions`
is non-empty — glare, sleeve, cast — a disagreement is *expected* and should be
recorded as `CLASS_UNVERIFIED` with the condition noted, not as
`CLASS_CONFLICTED`. A conflict flag that fires every time a card is read through
a scratched sleeve stops meaning anything, and the conditions field exists
precisely so that case is separable.

---

## 5. What is blocked, and what is not

**Blocked on the operator:** the full colour→class map and the purple rule.
Every branch of §3 depends on `map[colour]`, and that table must come from
DOB / Training Connect documentation or physical cards. I could not source it
from this repository and have not assumed any part of it, including whether
purple is unique to Training Connect or shared.

**Not blocked — buildable now, in this order:**

1. **`class_source` persistence.** Small, no behaviour change, and it closes the
   pre-existing `card_type` provenance hole. Do this first regardless of what
   happens to colour.
2. **A named R2 read helper**, extracted from the ten open-coded
   `_r2_client.get_object` calls. Useful independently; needed if colour ever
   reads from anywhere but the inline copy.
3. **The two prompt fields**, which can ship and be *logged only* — colour
   recorded, nothing branching on it — while the map is being sourced. That
   produces the real-world colour distribution the map should be validated
   against, from actual cards at actual gates, before a single classification
   decision depends on it.

Step 3 is the one worth starting: it turns the waiting period into measurement,
and it is reversible by deleting two fields.

## 6. What must not happen

- A colour-proposed class stored without `class_source`.
- `needs_review = False` on anything but colour-and-text agreement.
- The colour→class map living in the prompt.
- A disagreement resolved silently in either direction.
- `CLASS_CONFLICTED` and `CLASS_UNVERIFIED` collapsed into one reason.
- Reading colour from `enhanced_r2_key` or any enhanced derivative — that colour
  is partly the enhancement's, not the card's.
- Blocking a worker at the gate on any of it.
