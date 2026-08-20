# D6 — colour classification: the capture question, and the model

_2026-08-20. **Report only — nothing built.** Written against the override:
colour classification is wanted, because the field facts change the answer._

---

## 0. The override, and why the earlier objection does not survive it

The earlier reports argued against colour. That argument was made without three
facts, and each of them breaks it:

| Field fact | What it breaks |
|---|---|
| **A 40-hour card carries NO class text at all** | "Text is the only source that names the class." On the most common card there is no text to read, so text is not the primary signal — it is an absent one |
| **Text washes off worn cards; colour does not** | The assumption that OCR degrades gracefully. It does not: it degrades to null on exactly the cards most in need of reading |
| **Purple Training Connect cards read as regular SST** | The claim that text "fails safe". It does not fail safe here — it fails to a *confidently wrong class*, which is the outcome the whole ruling exists to prevent |

Colour survives all three. Text survives none. The override is correct and the
earlier position is withdrawn.

**The hard constraint is unchanged and is not in tension with any of this:**
colour PROPOSES a class, never ASSERTS one. "Cannot determine class from this
photo" stays a first-class answer and is better than a guess.

---

## 1. THE CAPTURE PREMISE IS WRONG, AND THE ERROR IS IN YOUR FAVOUR

**There is no 480px card image and no 0.65 quality anywhere in the card path.**

The live capture is [checkin.html:1259](../../backend/checkin.html):

```js
const compressed = await compressImage(rawImage, 1600, 0.85);
```

**1600px wide, JPEG quality 0.85.** And the comment directly above it records
that this is already the result of one round of exactly this problem:

> Item 4: OCR reads the WHOLE card (full native-camera photo — there is no
> app-side crop; box_2d crops AFTER OCR, for display only). **1200px / 0.7 was
> too low-res for the small CLASS label**, so OCR caught the big "40/62 hours"
> course text but missed Supervisor/Limited. Capture at higher res/quality so
> the class label is legible to OCR.

So the capture was already raised once, for the class-label reason, and it
landed at 1600/0.85.

### Where 480 probably comes from — a different pipeline

`backend/lib/photo_enhance.py:229-230` — `THUMB_MAX_EDGE = 400`,
`THUMB_QUALITY = 80`. That is the **daily-log activity photo** pipeline
(enhanced at long-edge 1800 q85, thumbnail at 400 q80). It has nothing to do
with card capture; no card image passes through it.

**This matters for the decision:** a 480px q0.65 input would make colour
classification genuinely marginal and the capture work a prerequisite. A
1600px q0.85 input does not. **The capture problem, as stated, does not exist on
this path** — which removes the main blocker to building the model.

### What 1600/0.85 actually costs colour

JPEG chroma subsampling is the real risk at any quality, not the pixel count.
At q0.85, 4:2:0 subsampling halves colour resolution in each axis while leaving
luma intact — which is why *text* survives compression better than people
expect and *flat colour fields* survive better still. A card's colour is a large
uniform region, which is the single most robust thing to a JPEG round-trip. A
1600px q0.85 photo of a purple card is purple.

The genuine risks are upstream of compression and are **not fixed by more
pixels**: white balance under sodium vapour or a yellow site light, auto-HDR
shifting saturation, and a card read through a scratched PVC sleeve. §4 handles
those by making the model report them rather than by raising fidelity.

---

## 2. Does the pipeline already retain anything better?

**On the live check-in path: no. The 1600/0.85 frame is the best copy that
exists, and it is already what OCR sees.**

| Stage | What exists |
|---|---|
| Native camera frame | Full sensor resolution, **in the browser only**, never uploaded |
| `compressImage(1600, 0.85)` | The single frame used for everything |
| `POST /checkin/upload-osha` | Receives that frame |
| Stored as `osha_card_image` | **The same frame**, inline base64 on the worker doc |
| `box_2d` crop | Display only — deliberately not stored (comment at checkin.html:1275) |

One frame, three uses. No downscale happens server-side, and no second copy is
kept. So there is nothing better to reach for today — but also nothing being
thrown away *after* upload. The loss is entirely at `compressImage`, in the
browser, before anything leaves the phone.

### The one higher-fidelity copy in the codebase, and why you cannot use it

`card_audit.upload_card_photo_to_r2` writes the **raw uploaded bytes** to the
object-locked card-audit bucket with a SHA-256 for chain of custody
(`card_audit.py:1108-1140`). That is a genuinely better original.

It is unreachable for this purpose, for two independent reasons:

1. **It is on the shadowed flow.** `server.py:9688` describes the card_audit
   family as *"the runtime flow is route-shadowed, but rows may exist from any
   earlier exercise of it"*. `upload_card_photo_to_r2` has exactly one caller,
   `enrollment_complete` on `gate_router` — which is mounted, but is the
   enrollment flow, not the live `register-and-checkin` path the workers use.
2. **It is object-locked with 7-year retention, deliberately.** D5 established
   the boundary: the card-audit bucket is evidence, and writing
   classification inputs there would put a spot-check artefact under a
   retention lock it does not warrant. Reading from it for classification is
   less objectionable than writing to it, but it still couples a live gate
   decision to an evidence store.

**Recommendation: do not route classification through the card-audit bucket.**
Treat it as what it is — a separate evidence path — and give classification its
own input.

---

## 3. Keeping a higher-fidelity copy, if it turns out to be needed

Ordered by cost. §1 argues none of these is a prerequisite; they are here so the
decision is priced.

### Option A — a client-side colour sample at full resolution *(recommended if anything)*

Before `compressImage` runs, the full-resolution frame is already in an
`<img>`/canvas in the browser. Sample it there and send a handful of numbers
alongside the photo:

- median RGB/HSV of the card's interior region, from the **uncompressed** canvas;
- a small colour histogram (say 16 hue buckets);
- the white-balance evidence available client-side.

**Why this is the right shape.** It reads the colour *before any compression
happens at all* — so it is strictly better than any stored-image option, not
merely bigger. It adds a few hundred bytes rather than megabytes. It costs no
storage, no bucket, no retention decision, no delete-cascade change. And it
keeps the classification input separate from the evidence photo, which is the
boundary D5 spent effort establishing.

**Its cost is honest:** the sample is computed by the client, which makes it
untrusted input and unverifiable after the fact. The photo remains the auditable
artefact; the sample is a hint that must be treated as one — which is exactly
what §4's PROPOSES constraint already requires of colour.

**Prerequisite:** the region matters. Sampling the whole frame averages in the
background, the worker's hand and the lanyard. It needs the card's interior,
and `box_2d` — which the OCR already returns — is the natural crop. But box_2d
arrives *after* the OCR round-trip, so either the sample is taken in a second
pass once box_2d is known (still pre-compression if the raw frame is retained in
memory), or a coarse centre-crop is used. **This is the one real design
question in Option A** and it should be settled before building.

### Option B — raise the JPEG quality for the card only

`compressImage(rawImage, 1600, 0.85)` → `(1600, 0.92)`, or 4:4:4 if the encoder
allows it (browser `toDataURL` does not expose subsampling, so in practice this
means quality only). One-line change, no new storage path, and it helps OCR too.

Cheapest thing on this list. Also the weakest: it does not address white balance
at all, and q0.85 → q0.92 on a flat colour field buys very little.

### Option C — a second, larger original in R2

A `card-originals/{worker_id}/` prefix in the **ordinary** bucket (never the
object-locked one), holding a 2400px q0.9 copy alongside the display frame.

Most expensive and least justified: it is the D5 selfie work again, for an input
§1 argues is already adequate, and it inherits every question D5 had to answer —
failed-upload semantics, delete cascade, backfill, and the strip PR's
verification requirement. **Do not do this first.**

### Not an option: reaching back to the native frame after upload

It never left the browser. Once `handleOshaPhoto`'s `reader.onload` returns,
the full-resolution frame is gone.

---

## 4. The model, and how it is prompted to PROPOSE

### Which model

Today: `Qwen/Qwen2.5-VL-7B-Instruct` (`server.py:533`, env-overridable via
`QWEN_MODEL`), called at `/checkin/upload-osha`.

**Use the same model and the same call.** Not a second model and not a second
request:

- a card photo already goes to a VLM on this exact path, so colour costs no new
  round-trip, no new dependency, and no new failure mode at the turnstile;
- a dedicated colour classifier would be a second thing to be down, on the
  hot path of a man at a gate;
- and a 7B VLM naming a dominant colour is a far easier task than the class-word
  reading it is already asked to do.

**The alternative worth pricing separately:** colour does not need a model at
all. If Option A lands, the median hue is a number, and a lookup table from hue
to card type is deterministic, auditable, testable offline, and cannot
hallucinate. **That is strictly better than asking a VLM** — and it is the
strongest argument for Option A over B or C. The VLM path below is the fallback
for when only the photo is available.

### The prompt change

`card_class` keeps its instruction exactly as written — it is already correct,
already says "the exact class or level **printed on** the card", and already
says to return null rather than guess.

Two fields are **added**, and neither is allowed to name a class:

```
"card_dominant_color": "the dominant background colour of the card itself,
   as one of: WHITE, BLUE, GREEN, PURPLE, RED, YELLOW, ORANGE, GREY, OTHER.
   Report the colour of the CARD STOCK, not of the lanyard, sleeve, hand or
   background. If the card is in a tinted or reflective sleeve, if the
   lighting has an obvious colour cast, or if you are not confident, return
   null. Do NOT infer a colour from the words on the card.",

"card_color_confidence": "high | medium | low — how sure you are of
   card_dominant_color given glare, shade, colour cast and sleeve. null if
   card_dominant_color is null."
```

**The prompt must not mention SST classes, card types, or what any colour
means.** The model reports a colour; the mapping lives in server code. Three
reasons, and the third is the one that matters:

1. a colour→class table in the prompt invites the model to work backwards —
   read a class, then report the colour that justifies it;
2. the table then lives in a string that no test can assert against;
3. and it would make the model the thing that asserts the class, which is the
   one thing the constraint forbids. **Keeping the table in Python is what makes
   "proposes, never asserts" enforceable rather than aspirational.**

### The resolution rule

```
class_word read and recognised?
├─ YES → class := the word.                         [text ASSERTS]
│        colour disagrees?  → CLASS_CONFLICTED, class still the word
│                              (the record is flagged, not overruled)
└─ NO  → colour present AND confidence high AND unambiguous in the table?
         ├─ YES → class := PROPOSED, never confirmed.               [colour PROPOSES]
         │        type = the proposed class
         │        class_source = "color"
         │        needs_review = True            ← ALWAYS. no exceptions.
         │        review_reason = CLASS_FROM_COLOR_UNCONFIRMED
         └─ NO  → SST_UNSPECIFIED / CLASS_UNVERIFIED
                  "cannot determine class from this photo"
```

**What makes this a proposal and not an assertion — three properties, all
required:**

1. **`needs_review` is unconditionally True on the colour path.** A
   colour-derived class never reaches "confirmed" without a human. If it could,
   colour would be asserting.
2. **`class_source` is persisted** (`"text" | "color" | null`). Without it, a
   colour-derived class is indistinguishable from a read one the moment it is
   stored — which is precisely the `card_type` provenance failure documented in
   [d6-where-card-type-comes-from.md](d6-where-card-type-comes-from.md). **Do
   not repeat it.** This field is the single most important line in the change.
3. **`_sst_cert_state` must not return `valid` for `class_source == "color"`.**
   It already refuses `valid` for an unread class; the colour path must land on
   `unknown`, not sneak into `valid` by virtue of now having a class name.

**And low confidence resolves to unknown, not to a guess.** The whole point of
asking the model for `card_color_confidence` is to have something that can say
no.

### The Training Connect case, specifically

The purple card is the clearest win and also the sharpest trap. Today it reads
as a regular SST — *confidently wrong*. Under this model, if purple is
unambiguous in the table it proposes Training Connect, flagged for review; if
purple is ambiguous or the confidence is low, it lands on
`CLASS_UNVERIFIED` — which is **still a strict improvement**, because unknown
beats confidently wrong.

**But this only holds if the table is right.** Before any of this ships, the
colour→class mapping has to come from DOB/Training Connect documentation or from
physical cards, not from the model and not from inference. **I could not source
it from this repository, and I have not assumed it.** That mapping is the
factual input the build needs and the one thing here I cannot supply.

---

## 5. Recommended order

1. **Source the colour→class table** from documentation or physical cards. Nothing
   below is buildable without it, and it is the only true blocker.
2. **Add `class_source` persistence** — on its own, ahead of colour. It closes
   the existing `card_type` provenance gap, is small, changes no behaviour, and
   means that when colour lands there is already a way to tell a proposed class
   from a read one.
3. **Option A**, the client-side colour sample, settling the box_2d region
   question first. If it lands, prefer the deterministic hue→class lookup over
   the VLM.
4. **The VLM fields as the fallback** for cards where only the photo exists.
5. **`CLASS_CONFLICTED`** last — it is the smallest win and depends on both
   signals being trustworthy.

**Not recommended:** Option C, and routing anything through the card-audit
bucket.

## 6. What must not happen

- A colour-derived class that is not flagged `needs_review`.
- A colour-derived class stored without `class_source` — the provenance failure
  this project has already had once, repeated on a second field.
- The colour→class table living in the prompt.
- `_sst_cert_state` returning `valid` for a colour-proposed class.
- Colour overruling a class word that WAS read. It flags; it does not replace.
- Blocking a worker at the gate on any of it. An undetermined class is a records
  problem, and `RECOGNIZED_SST_TYPES` already knows that.
