# Finding B — what actually drives "unverified SST"

Report only. **No flagging logic was changed.** Awaiting the operator's ruling.

## 1. The exact chain

The string is `unknownSst: 'Unverified SST'` — `frontend/src/i18n/en.js:52`, and
as a literal at `frontend/app/site/checkins.jsx:552`.

It renders off `sst_status === 'unknown'`:
`site/checkins.jsx:442`, `logbooks/preshift_signin.jsx:253`, `app/workers.jsx:86`.
The CP review screen uses a coarser signal — `flag_reasons` containing
`'unknown_sst'` — at `logbooks/review.jsx:368`.

Backwards from there:

1. `sst_status` is frozen onto the check-in row at `backend/server.py:10173-10174`
   — `elif "SST_UNKNOWN" in _warning_types: sst_status = "unknown"`.
2. `SST_UNKNOWN` is emitted by `validate_worker_certifications`,
   `server.py:2188-2195`, when `sst_state == "unknown"`.
3. `sst_state` is `unknown` when no SST cert resolves to `valid` and none to
   `expired` (`server.py:2159-2167`).
4. Per-cert verdict is `_sst_cert_state`, `server.py:1929-1952`. It returns
   `"unknown"` in exactly two cases:
   - **future expiry, unreadable class** — `:1950-1951`, class not in
     `SST_CLASS_TYPES` (`:1894`), i.e. `SST_UNSPECIFIED`;
   - **no usable expiry** — `:1952`, missing, unparseable, or
     suppressed-as-implausible.

**It is not driven by card-photo presence.** Nothing on this path reads whether
a photo exists. It reads the worker's `certifications[]` rows only. A photo
matters only upstream, as the thing OCR would have read.

### Why this is consistent with a seed artifact

`_map_sst_class(raw)` (`server.py:1904-1916`) returns `SST_UNSPECIFIED` for any
class string it cannot match. Seeded card data with no photo means no OCR ran,
so the class was never populated → `SST_UNSPECIFIED` → case (a) above →
`unknown` → flagged. Thirteen for thirteen is what that would look like.

**I cannot prove it.** There is no seed script in this repository — searched
`backend/`; the only match is `backend/migrations/20260426_fee_schedule_seed.py`,
which is unrelated (fee schedule). The seeding happened outside the tree, so
what it wrote into `certifications[]` is not verifiable from here. Confirming it
needs one read against the seeded workers: for each, `certifications[].type` and
`.expiration_date`. If `type` is `SST_UNSPECIFIED` with a future
`expiration_date`, it is the seed, not the gate.

## 2. Does a real gate check-in always produce a photo?

**No.**

- `osha_card_image: Optional[str] = None` — `server.py:2270`.
- `server.py:10119-10122`, verbatim: the returning-worker quick check-in path
  "sends NO card evidence (no osha_data / osha_card_image, often no
  osha_number)".
- The fallback at `:10126-10127` uses the worker's stored
  `osha_number` / `osha_card_image` so prior proof still counts.

So a returning worker routinely checks in with no photo in the request. His
verdict is computed from certs already on file. If those certs were written
with an unread class, he is `unknown` on every subsequent visit, forever,
without anyone re-photographing anything.

**When the upload fails:** the request carries no image, the fallback at `:10127`
supplies the stored one if any, and `build_worker_certifications`
(`server.py:1955`) runs on whatever evidence exists. A first-time worker whose
upload failed has no stored image either → no SST cert row → `sst_state`
`missing` (`:2160-2161`) → `MISSING_SST` (`:2196-2204`), which is a **different**
warning from `SST_UNKNOWN`.

## 3. Is a failed upload distinguishable from a genuinely expired card?

**In the data: yes, three ways over.**

| Discriminator | Where | Values |
|---|---|---|
| `sst_status` | `server.py:10172-10180` | `expired` / `unknown` / `expiring_soon` / `missing` / `valid` |
| `sst_unknown_reason` | `server.py:10187-10199` | `CLASS` / `EXPIRY` / `BOTH`, frozen at check-in |
| `card_ocr_attempts`, `card_ocr_failure_reason` | `server.py:10252-10253` | exists precisely so an admin "sees the photo was tried and unreadable rather than never supplied" (`:10249-10251`) |

**In the CP's review UI: no.**

`logbooks/review.jsx` reads `flag_reasons` only (`:366-369`). It never reads
`sst_status`, `sst_unknown_reason`, `card_ocr_attempts`, or
`card_ocr_failure_reason` — grepped, zero occurrences of any of the four in that
file. Every `unknown` cause collapses to one undifferentiated
`'unknown_sst'` chip rendered at `:397-400`.

So the CP sees the same "Unverified SST" for:

- a card whose class the OCR could not read (seed artifact, or a bad crop),
- a card with no parseable expiry,
- a worker who never supplied a photo at all.

An **expired** card is separately distinguished (`isExpired`, `:367`), so the
three genuine flags in the operator's set are not literally identical to the
thirteen — but they sit in the same list, styled by the same
`s.reasonExpired` (`:398`), and the count is what a CP reads.

**The defect the operator suspected is real, and it is in the UI layer, not the
gate.** The backend already froze enough to tell these apart at
`server.py:10187-10199` and `:10252-10253`. `review.jsx` throws that resolution
away.

## What I did not do

No flagging logic was touched. The fix — if the operator wants one — is to
surface the existing discriminators in `review.jsx`, which changes no gate
behaviour and no stored data. That is a separate change from U1 and is not
included in it.
</content>
</invoke>
