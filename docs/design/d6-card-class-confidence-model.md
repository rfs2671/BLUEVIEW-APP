# D6 — the card-class confidence model

_2026-08-19. Report only; nothing in this document is built._

**The rule this is written to:** colour PROPOSES, never ASSERTS. And "cannot
determine class from this photo" must be a first-class answer — a thing the
model can *return*, not a thing that falls out when nothing else matched.

---

## 1. What exists today

Everything below is in `backend/server.py` unless stated.

| Piece | Where | What it does |
|---|---|---|
| VLM extraction prompt | `server.py:10118-10139` | Asks for `card_class` as a WORD, explicitly forbids returning course hours, and says "If a field is not visible or you are not certain, set it to null — do NOT guess the class" |
| `_map_sst_class(raw)` | `server.py:2108-2120` | Substring match on the OCR string → `SST_SUPERVISOR` / `SST_TEMPORARY` / `SST_FULL` / `SST_LIMITED`, else `SST_UNSPECIFIED` |
| `_map_osha_level(raw)` | `server.py:2123-2131` | `"30"` → `OSHA_30`, `"10"` → `OSHA_10`, else `OSHA_UNSPECIFIED` |
| `SST_CLASS_TYPES` | `server.py:2097` | The four classes that count as *legible* |
| `_sst_cert_state()` | `server.py:2132-2157` | Three-state verdict `valid` / `unknown` / `expired`; a future expiry is `valid` **only** if the class was legible |
| `CLASS_UNVERIFIED` | `server.py:2216`, `:2240` | The review reason written when the class could not be read |
| `sst_unknown_reason` | `server.py:10873-10884` | Freezes `CLASS` / `EXPIRY` / `BOTH` onto the check-in row at check-in time |
| Worker-facing copy | `frontend/src/i18n/en.js:56` | "Card class could not be read — verify the card" |

**The good news, and it is substantial:** the anti-silence rule is already
built and already load-bearing. `_sst_cert_state` will not return `valid` for
an unread class even when the expiry is clean and in the future
(`server.py:2154`). A class that could not be read is `unknown`, `unknown`
raises `needs_review`, and `needs_review` surfaces the row in the CP/admin
review queue with its own sentence. The *shape* D6 asks for exists.

**Colour does not appear anywhere.** There is no colour extraction, no colour
field on the cert row, no colour term in the prompt. Grepping the card path for
colour returns only CSS. So this is not a question of correcting how colour is
used — it is a question of whether to admit it at all, and under what
constraint.

---

## 2. Why colour is tempting, and exactly what is wrong with taking it

The pull is obvious: card stock is printed in distinct colours per class, a
colour survives glare and motion blur far better than 8-point text, and a
phone camera at a turnstile at 6:40am produces a lot of glare and motion blur.
When the class WORD is unreadable the colour is very often still readable.

Three reasons it can never be the assertion:

1. **The failure is silent and systematic.** A misread word usually produces
   nonsense that fails the substring match and lands in `SST_UNSPECIFIED` —
   the safe state. A misread colour produces *a different valid class*. It
   fails into a confident wrong answer, which is the one failure mode this
   whole subsystem is built to prevent.

2. **The camera is not a colorimeter.** White balance under sodium vapour, a
   yellow-tinted site light, a blue phone screen used as a fill light, an
   auto-HDR pass, a JPEG at q0.7 — every one of these moves hue. The colour in
   the pixels is a function of the lighting as much as of the card.

3. **A card is not the only thing that is card-coloured.** A holder, a lanyard
   badge, a photocopy, a laminate, a card from another jurisdiction.

So: colour may raise or lower confidence in a class the *text* proposed. It may
never originate one.

---

## 3. The model

Three evidence sources, three different powers. The powers are not
configurable and are the whole point.

| Source | Power | Why |
|---|---|---|
| **Class word** (OCR/VLM `card_class`) | **ASSERTS** | The only source that names the class. It is what is legally printed on the card |
| **Course hours** (e.g. "40 hours", "62 hours") | **CORROBORATES** | Deterministically tied to class by the LL196 curriculum, and already extractable. Can confirm or contradict a word; cannot originate one — the prompt already forbids returning hours *as* the class (`server.py:10126-10131`) |
| **Card colour** | **PROPOSES** | May raise confidence in a word that was read, or lower it. May never originate a class, and may never be the sole reason a row is treated as legible |

### The resolution rule

```
class_word read and recognised?
├─ NO  → DETERMINATE ANSWER: cannot determine. Full stop.
│        Colour is not consulted. Hours are not consulted.
│        (A proposal with nothing to attach to is a guess.)
└─ YES → class := the word.
         corroboration := hours agree? colour agrees?
         ├─ nothing contradicts  → legible, normal confidence
         ├─ a source is absent   → legible, normal confidence (absence ≠ conflict)
         └─ a source CONTRADICTS → still class := the word,
                                   but flagged CLASS_CONFLICTED
```

Two consequences worth stating plainly, because they are what stop this from
becoming a colour classifier by degrees:

- **Colour never resolves an unread word.** The branch where colour would be
  most useful is exactly the branch where it is refused. That is deliberate: it
  is the branch where it would be doing the asserting.
- **Contradiction does not overrule the word — it downgrades trust in the
  row.** A green card that OCR read as SUPERVISOR does not become a WORKER
  card. It becomes a SUPERVISOR card a human is asked to look at.

### `CLASS_CONFLICTED` is a new review reason, not a new state

It joins `CLASS_UNVERIFIED` in the same machine-code vocabulary
(`server.py:2082-2084`, rendered from `frontend/src/i18n/en.js:56`). It must
not collapse into `CLASS_UNVERIFIED`: those are different sentences to a human.
"Could not be read" means *look at the card*. "Two things about this card
disagree" means *look at the card and consider that it may not be genuine*.

---

## 4. "Cannot determine" as a first-class answer

It is *representable* today (`SST_UNSPECIFIED` + `CLASS_UNVERIFIED` +
`state == "unknown"`). What stops it being first-class is that it is currently
a **fall-through**, not a **decision**, and three specific things follow from
that.

### 4a. The mapper cannot tell "no class printed" from "a word I don't know"

`_map_sst_class` (`server.py:2108-2120`) is four substring tests and a default.
Everything that is not one of the four returns `SST_UNSPECIFIED`:

- `card_class: null` — the VLM correctly declined to guess. **This is the
  system working.**
- `card_class: "WORKER"` — the VLM read a real word off a real card and the
  mapper does not know it. **This is the system failing.**

They are recorded identically. The first needs a better photo; the second needs
a code change, and nothing anywhere will ever say so. The fix is small: return
a reason alongside the type — `no_class_offered` vs `unrecognised:<value>` —
and log the second. An unrecognised value is a signal about the *taxonomy*, and
today it is thrown away.

> **VERIFY BEFORE BUILDING — likely live bug.** The accepted vocabulary is
> FULL / LIMITED / SUPERVISOR / TEMPORARY. The 40-hour LL196 credential is, as
> far as I can tell from the card itself rather than from this repo, printed as
> **"Worker"**, and `"WORKER"` matches none of the four substring tests. If
> that is right, every correctly-read full-worker card in production is landing
> in `SST_UNSPECIFIED` → `unknown` → `needs_review`, and the review queue is
> full of cards that were read perfectly. I could not confirm the printed
> wording from anything in this repo, so this is stated as a question, not a
> finding. It is cheap to answer — one query for the distribution of
> `card_class` values against `SST_UNSPECIFIED` rows — and it should be
> answered before any of section 3 is built, because if it is true it is a much
> larger effect than anything colour would fix.

### 4b. `extraction_completeness` is named like a confidence and is not one

`server.py:2213`, `:2245`. It is `(fields_present / fields_expected)`, rounded
to 3dp. It measures **arity**, not **certainty**: four fields the model
hallucinated score 1.0. Its docstring is honest about the intent — it
deliberately "replaces the uncalibrated model self-`confidence` that was
structurally null" (`server.py:2087-2089`) — and replacing an uncalibrated
number with a deterministic one was the right move. But the name invites a
future reader to threshold on it as though it were confidence. If a real
confidence lands as part of this work, that number needs a different name and
this one should keep meaning exactly what it measures.

### 4c. The three surfaces are not equally honest

- The **review queue** says it well: "Card class could not be read — verify the
  card" (`en.js:56`, `frontend/app/workers/[id].jsx:169`).
- The **check-in row** freezes `CLASS` / `EXPIRY` / `BOTH`
  (`server.py:10873-10884`) — a good immutable record of what was unknown *at
  the time*, which is the right thing to freeze.
- The **gate** admits the worker, which is correct: an unread class is not
  grounds to turn a man away, and `RECOGNIZED_SST_TYPES` (`server.py:2103`)
  deliberately includes `SST_UNSPECIFIED` so the OSHA baseline is still
  satisfied.

The gap is downstream. `SST_TEMPORARY` is in `SST_CLASS_TYPES`
(`server.py:2097`) but is absent from `CertificationType`
(`server.py:2048-2050`), from `ll196._SST_CERT_TYPES`
(`backend/lib/logbook/ll196.py:47`) and from the scoring list
(`backend/lib/statistical_engine/score.py:475`). So a temporary card is a
*legible, valid* class at the gate and an *unrecognised* one in LL196
reporting and in the risk score. That is a four-way vocabulary split for one
concept — see [D7](d7-field-name-unification-plan.md), where it is item 2.

---

## 5. Recommendation

**Do not build colour yet.** Not because the model in section 3 is wrong, but
because of sequencing. Colour buys accuracy on the branch where the word could
not be read — and section 3 forbids it from acting on that branch anyway, so
its actual yield here is *corroboration only*. Meanwhile 4a may mean a large
share of the current `CLASS_UNVERIFIED` volume is a five-line taxonomy fix.
Measuring that first tells you whether there is a colour-shaped problem left.

In order:

1. **Measure.** Distribution of raw `card_class` values on rows that resolved
   to `SST_UNSPECIFIED`. This answers 4a and sizes everything else. Read-only,
   one query, no code.
2. **Split the fall-through** (4a). Distinguish "no class offered" from
   "unrecognised value", and log the second. Small, no schema change, and it
   makes the taxonomy self-reporting from then on.
3. **Unify the vocabulary** (4c / D7 item 2). Four lists, one concept.
4. **Then** hours-as-corroboration, then colour-as-proposal, then
   `CLASS_CONFLICTED` — in that order, because hours are already extracted and
   deterministic, and they exercise the whole corroboration path with none of
   colour's measurement problems. If corroboration proves worthless with the
   easy source, colour will not rescue it.

---

## 6. What must not happen

- A colour-only class. No branch where colour is the reason a row is treated as
  legible.
- Colour resolving an unread word. That is the assertion, wearing a
  proposal's clothes.
- Folding `CLASS_CONFLICTED` into `CLASS_UNVERIFIED`. Different sentence,
  different action, and one of them is a possible forgery signal.
- Thresholding on `extraction_completeness` as if it were confidence (4b).
- Blocking a worker at the gate on any of this. An unread class is a records
  problem, and the gate already knows that (`server.py:2103`).
