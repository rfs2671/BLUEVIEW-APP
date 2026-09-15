"""Count every call to a paid vision model, as it happens.

WHY THIS EXISTS, AND IT IS NOT THE CEILING. Before this, NOTHING IN THIS SYSTEM
RECORDED THAT A VISION CALL HAPPENED. No counter, no log collection, no per-call
row. Two endpoints have been calling a paid model since launch —
`POST /checkin/upload-osha` on every card photo at every gate, and
`POST /enrollment/parse_card` — and the questions "how much did we spend on OCR
last month" and "which project drives it" could not be answered from our own
data at all.

The only available sources were a lower bound (`checkins.card_ocr_attempts`,
which exists only for workers who got PAST the card step, so the population
that failed wrote nothing), the Railway access log (bounded by retention), and
the provider's own billing dashboard (ground truth, and not ours).

A ceiling reads a number. There was no number. So this ships FIRST and ALONE.

NO LIMIT IS ATTACHED, DELIBERATELY.
  * nothing here refuses a request
  * nothing here raises an alert
  * nothing here has a threshold to tune
It is the same write a ceiling would need, so when the ceiling is set from a
week of real traffic, nothing is thrown away.

── COUNTED BEFORE THE MODEL CALL, NOT AFTER ────────────────────────────────

A call that errors after the provider has billed it is still spend. Counting on
success would systematically under-report exactly the failures worth knowing
about — a provider outage, a malformed image, a timeout — and those are the
ones that arrive in bursts.

── $inc IS ATOMIC SERVER-SIDE, AND THAT IS THE WHOLE DESIGN ─────────────────

We run at least two containers. The obvious implementation —

    row = await db.vision_calls.find_one(key)          # both containers read 4
    await db.vision_calls.update_one(key, {"$set": {"calls": row["calls"] + 1}})

— races: two containers read the same value and both write 5, so two calls
count as one. It undercounts by the container count under exactly the load
worth measuring, and it LOOKS more careful than the one-liner while doing it.
That is the same shape as the in-process rate limiter, which assumes a single
instance and therefore permits N times its intended cap.

`$inc` is applied by the server, on the document, under its own lock. Two
concurrent increments produce 2. There is no read, so there is nothing to race.
Any future change here that introduces a read-then-write reintroduces the
defect; `test_vision_meter.py` asserts the operator.

── EASTERN, LIKE EVERY OTHER DAY BOUNDARY ON THIS PROJECT ───────────────────

A UTC day boundary would split a New York shift across two rows from 20:00 EDT
onward — the same defect this codebase has recorded thirteen times. The zone is
resolved here rather than imported from server.py, because server.py imports
card_audit and a lib module importing server would be circular.

── FAILURE IS NEVER THE CALLER'S PROBLEM ────────────────────────────────────

A metering write that raised would turn a telemetry problem into a man not
working. Every call is wrapped; a lost count is a lost diagnostic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# The endpoints that spend money. Named, so a new one has to be added here
# deliberately rather than inheriting silence.
VISION_UPLOAD_OSHA = "upload_osha_card"
VISION_PARSE_CARD = "enrollment_parse_card"

# ── THE SET NAMED THE CARD PATHS AND STOPPED THERE ────────────────────────
#
# Two endpoints were named here and both are genuinely counted — upload_osha_
# card in server.py, enrollment_parse_card in card_audit.py. What the set did
# not say is that they are not the only paid vision calls in the system. There
# are four, and the two below went to the same model, on the same account, with
# nothing recording that they happened.
#
# The uncounted two are the WhatsApp side, which this module predates:
#
#   plan_index_page  — one call PER PAGE of an uploaded plan set. A forty-sheet
#                      architectural set is forty calls from a single upload,
#                      and nothing counted any of them.
#   whatsapp_visual_qa — one call per CANDIDATE SHEET while answering a plan
#                      question, not one per question. The handler walks its
#                      candidate list until a sheet answers, so a question
#                      about something not shown costs the whole list.
#
# Both are driven by inbound WhatsApp traffic, which is the one input to this
# system that nobody at Levelog controls.
VISION_PLAN_INDEX_PAGE = "plan_index_page"
VISION_WHATSAPP_VQA = "whatsapp_visual_qa"

# ── OCR FOR A PAGE WITH NO TEXT LAYER ─────────────────────────────────────
#
# Index version 3 reads a page's PDF text layer first, because a CAD-exported
# sheet carries its wording and numbers exactly and for free. A scanned sheet
# carries none, and for those alone the page image is sent to AWS Textract.
# That is a paid call made per scanned page during indexing, so it is counted
# here like every other one — and it is a separate name because its price and
# its trigger are both different from the vision-model calls beside it.
VISION_PLAN_INDEX_OCR = "plan_index_ocr"

VISION_ENDPOINTS = frozenset({
    VISION_UPLOAD_OSHA,
    VISION_PARSE_CARD,
    VISION_PLAN_INDEX_PAGE,
    VISION_PLAN_INDEX_OCR,
    VISION_WHATSAPP_VQA,
})

COLLECTION = "vision_calls"


def eastern_day(now: Optional[datetime] = None) -> str:
    """YYYY-MM-DD in America/New_York."""
    dt = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        # A missing tz database must not stop the count. UTC is wrong by up to
        # four hours at the boundary and is still better than no row.
        return dt.strftime("%Y-%m-%d")


def meter_key(day: str, project_id: Optional[str], endpoint: str) -> str:
    """One row per (day, project, endpoint). Deterministic, so the row IS the
    key and no lookup is needed to find it."""
    return f"{day}:{project_id or 'unknown'}:{endpoint}"


async def record_vision_call(
    db, *, endpoint: str, project_id: Optional[str] = None, now=None,
) -> None:
    """Count one paid vision call. Never raises, never refuses, never alerts."""
    try:
        if endpoint not in VISION_ENDPOINTS:
            # Not a refusal — the call still happens. A misnamed endpoint gets
            # counted under its own name and logged, rather than dropped.
            logger.warning("[vision_meter] unregistered endpoint %r", endpoint)
        day = eastern_day(now)
        stamp = now or datetime.now(timezone.utc)
        await db[COLLECTION].update_one(
            {"_id": meter_key(day, project_id, endpoint)},
            {
                # ATOMIC. Never find-then-write — see the module docstring.
                "$inc": {"calls": 1},
                "$set": {"last_at": stamp},
                # Disjoint from $set above: Mongo rejects a path in both.
                "$setOnInsert": {
                    "date": day,
                    "project_id": project_id or None,
                    "endpoint": endpoint,
                    "first_at": stamp,
                },
            },
            upsert=True,
        )
    except Exception as e:
        logger.warning("[vision_meter] count failed (non-fatal): %r", e)


__all__ = [
    "record_vision_call", "eastern_day", "meter_key", "COLLECTION",
    "VISION_ENDPOINTS", "VISION_UPLOAD_OSHA", "VISION_PARSE_CARD",
    "VISION_PLAN_INDEX_PAGE", "VISION_PLAN_INDEX_OCR", "VISION_WHATSAPP_VQA",
]
