"""When a project's records may be destroyed — and, almost always, may not.

ONE DEFINITION, for the same reason `project_state.py` is one definition: the
question "is this project still owed to a regulator?" is asked by the purge
endpoint, by the response model and by the owner's review screen, and three
copies of it would drift into three different answers about the same project.

WHAT THIS IS. A brake on `DELETE /projects/{id}/hard-delete`, which physically
destroys a project's entire compliance history and, by prefix sweep, the stored
photographs referenced from it. ESRA BB2024-007 §V.4 requires seven years past
job completion. Until now that period was, in the compliance doc's own words,
"Not computable. No job-completion date exists."

WHAT THIS IS NOT, and must never become. Nothing here schedules, expires, or
deletes. These are pure functions over a project document; this module has no
database handle and cannot act even if a caller wanted it to. `purge_eligible_at`
is COMPUTED FOR DISPLAY and stored nowhere — the moment it becomes a stored
field, something will eventually sort on it. A date seven years past does not
cause a deletion; it only stops this module objecting to one a human asked for.

ABSENCE IS NOT A DATE — THE dob_logs TTL INCIDENT.
`docs/runbooks/dob-logs-ttl-removal-2026-07-24.md` records what happens when a
retention clock is keyed on the wrong instant. Two TTL indexes on `dob_logs`
were keyed on `detected_at` — the moment the app FIRST SAW a record, not the
date the event occurred. Every row on both tracked projects carried the same
`2026-07-21` first-sync stamp, so a 2019 violation and a 2026 violation shared
one expiry, and the indexes would have physically destroyed every permit,
complaint, inspection and job-status row around 2026-10-19.

`job_completion_date` is therefore asserted by a human and by nothing else. It
is never inferred from `updated_at` (which moves when an NFC tag is minted),
never from `last_dob_sync_at`, never from last activity, and never from
`projects.status` — which `project_state.py` documents as written once at
creation and never updated. A field written once at creation is not a
lifecycle, and a guess about when a job ended is exactly the class of mistake
that runbook exists to prevent.

The name is `_date`, not `_at`, and the value is a `"YYYY-MM-DD"` string,
matching `ssp_expiration_date`. It is a calendar date a human asserts about the
past, not an instant. A tz-aware datetime here would re-introduce the
Eastern-vs-UTC bug `eastern_date()` was added to fix: from 20:00 EDT the UTC day
is already tomorrow in New York, and a completion stamped a day late moves the
whole seven-year period a day late with it.

THE COMPLETION IS A PAIR: A CO NUMBER AND A DATE, OR NOTHING.
A claim about a legal event carries the event's identifier. `job_completion_date`
without `job_completion_co_number` is an unattributable assertion that some job
finished on some day, and it is the assertion that starts a seven-year clock and
then ends it. The two are written together by `update_project` and a partial
entry is refused there rather than stored — so this module never has to reason
about half a completion, and the read path below can treat "a usable date" and
"a completion of record" as the same thing.

WHAT THE CO NUMBER IS VALIDATED AGAINST: NOTHING, DELIBERATELY, AND SAID SO.
See `co_number_problem()`. It is an ATTESTED STRING. This repo cannot verify it
and does not pretend to.

ABSENCE REFUSES, AND AN ATTESTATION IS THE WAY THROUGH.
The earlier build of this module returned None — no objection — when no
completion was recorded, on the reasoning that refusing forever would disable
the owner's only cleanup path. That reasoning was right about the consequence
and wrong about the remedy. NO project in production carries
`job_completion_date`; the field ships in this change. A brake that only bites
on a field nothing has ever been written to is a brake that, on the day it
merges, protects nothing at all and leaves every existing project exactly as
hard-deletable as it was.

So absence refuses. The way through is not an inference and not a timeout — it
is a person, on the record: either the completion itself (number and date), or
`no_completion_attested`, an explicit statement that this project was never
completed and may be purged. Named, timestamped, reasoned and audited, exactly
like the legal hold beside it. Nothing here expires, decays, or grants itself.

The attestation answers ONLY the absent case. It is read after the recorded
completion and after the hold, so it can never shorten a seven-year period that
a recorded completion has started, and never lift a hold. It removes an
UNKNOWN; it does not overrule a KNOWN.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Optional

# ESRA BB2024-007 §V.4. Also the period `docs/coi-retention-guarantee.md`
# already argues for, so the product has one retention number, not two.
RETENTION_YEARS = 7

# `ssp_expiration_date`'s convention, matched exactly. Strict on purpose:
# "2020-3-1" and "03/01/2020" are REJECTED rather than coerced, because a
# coerced date is an invented one and this value governs destruction.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_calendar_date(value: Any) -> Optional[date]:
    """A `"YYYY-MM-DD"` string as a date, or None if it is not one.

    None means "no usable assertion" for every caller. Nothing downstream may
    read that as "eligible" — see `purge_eligible_at`.
    """
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        # A well-shaped string that is not a real day: "2026-02-30".
        return None


# The CO number is stored as entered, minus surrounding whitespace. The cap is
# a storage sanity bound, not a format: the longest thing anyone has ever called
# a CO number is far short of it, and a 64-character limit rejects a paste of a
# whole PDF without rejecting any identifier.
CO_NUMBER_MAX_LEN = 64


def co_number_problem(value: Any) -> Optional[str]:
    """Why this cannot be stored as a CO number, or None if it can.

    NO FORMAT IS ENFORCED, AND THAT IS THE FINDING, NOT LAZINESS.

    This repo cannot say what a valid NYC Certificate of Occupancy number looks
    like, and the evidence is in the repo itself. `_extract_cofo_fields` in
    server.py reads the field from NYC Open Data `pkdm-hqz6` under EITHER
    `co_number` OR `certificate_of_occupancy_number` because it does not know
    which the dataset returns; `statistical_engine/daily_panel.py` queries the
    same dataset for different column names again. Two code paths, one dataset,
    three spellings, no agreement. Nothing in this codebase has ever asserted
    the SHAPE of a value from that column, and no fixture here carries a real
    one.

    Beyond the repo, the space is genuinely heterogeneous: BIS-era certificates,
    DOB NOW certificates, temporary COs carried with sequence suffixes, and
    amended certificates all circulate on paper an admin may be reading from.

    A regex invented here would therefore be a guess with a rejection attached,
    and the rejection lands on an admin holding the actual certificate, at the
    moment they are trying to record it. The failure mode of a wrong regex is
    that a real CO number cannot be entered; the failure mode of no regex is a
    typo stored as attested. The second is visible in the audit trail and
    correctable. The first is an admin who cannot do the thing the ruling
    requires.

    So: an attested string. It is checked only for things that are not about
    the CO at all — that it is text, that it is not blank, that it fits, and
    that it is one line rather than a smuggled block of content.
    """
    if not isinstance(value, str):
        return "certificate of occupancy number must be text"
    stripped = value.strip()
    if not stripped:
        return "a certificate of occupancy number is required"
    if len(stripped) > CO_NUMBER_MAX_LEN:
        return (
            f"certificate of occupancy number must be "
            f"{CO_NUMBER_MAX_LEN} characters or fewer"
        )
    # An identifier occupies one line. A newline or a control character here is
    # a paste of something else, and storing it would put unreviewed content
    # into a field a regulator may later be shown.
    if any(ch < " " or ch == "\x7f" for ch in stripped):
        return "certificate of occupancy number must be a single line of text"
    return None


def normalize_co_number(value: str) -> str:
    """The stored form: exactly what was entered, minus surrounding whitespace.

    NOT upper-cased, NOT stripped of punctuation, NOT re-spaced. Every one of
    those is a small rewrite of a number a human copied off a certificate, and
    a rewritten identifier is no longer the one on the document. If this value
    is ever compared against an ingested CO record, the comparison must do the
    normalising — at the point of comparison, where the two formats are both
    in view — rather than this field having quietly discarded the original.
    """
    return value.strip()


def has_recorded_completion(project: Dict[str, Any]) -> bool:
    """Whether a usable completion is on record for this project.

    A DATE THAT DOES NOT PARSE IS NOT A COMPLETION. `parse_calendar_date`
    returning None means "no usable assertion", and this function agrees with it
    rather than reading the key's mere presence as a record. Otherwise a
    document carrying `job_completion_date: "sometime in 2019"` would count as
    completed, compute no eligibility date, and — under the old rule — sail
    through the brake on the strength of a string nothing could read.
    """
    return parse_calendar_date(project.get("job_completion_date")) is not None


def add_retention_years(completed: date) -> date:
    """`completed` plus the retention period.

    THE LEAP DAY. A job completed 2020-02-29 has no 2027-02-29 to land on.
    Resolved toward MARCH 1 — retaining one day longer — because this value
    only ever gates a destruction. Clamping to February 28 would release the
    brake a day early, and "a day early" is the direction that loses records.
    """
    year = completed.year + RETENTION_YEARS
    try:
        return completed.replace(year=year)
    except ValueError:
        return date(year, completed.month + 1, 1)


def purge_eligible_at(project: Dict[str, Any]) -> Optional[str]:
    """The first day the retention brake is off, as `"YYYY-MM-DD"`.

    NEVER STORED. NEVER ACTED ON. Computed for the response so an owner can
    see the date before deciding, and recomputed on every read so it cannot go
    stale against a corrected completion date.

    None means "not computable", which is the honest answer for a project
    nobody has asserted a completion for — and it is the answer FOREVER, not
    "eligible now". This mirrors the soft-delete purge, which skips rows with
    no `deleted_at` rather than inventing one.
    """
    completed = parse_calendar_date(project.get("job_completion_date"))
    if completed is None:
        return None
    return add_retention_years(completed).isoformat()


def legal_hold_view(project: Dict[str, Any]) -> Dict[str, Any]:
    """The hold, flattened for a response payload.

    A hold NEVER EXPIRES. There is deliberately no duration, no review date and
    no age at which it lapses: it is set by a human and cleared by a human. The
    placement fields survive the clearing, so a hold that was lifted still says
    who placed it and why.
    """
    return {
        "legal_hold": bool(project.get("legal_hold")),
        "legal_hold_reason": project.get("legal_hold_reason"),
        "legal_hold_by": project.get("legal_hold_by"),
        "legal_hold_at": project.get("legal_hold_at"),
    }


def no_completion_attestation_view(project: Dict[str, Any]) -> Dict[str, Any]:
    """The "never completed, may be purged" attestation, flattened.

    Shaped exactly like `legal_hold_view` above, and for the same reason: this
    is the other statement a named person makes on the record about whether
    these records may be destroyed. WHO said it and WHY travel with the boolean
    everywhere the boolean goes, because a bare True on the screen of the person
    about to purge is an anonymous permission slip.
    """
    return {
        "no_completion_attested": bool(project.get("no_completion_attested")),
        "no_completion_reason": project.get("no_completion_reason"),
        "no_completion_attested_by": project.get("no_completion_attested_by"),
        "no_completion_attested_at": project.get("no_completion_attested_at"),
    }


def retention_refusal(
    project: Dict[str, Any], today: Optional[str] = None,
) -> Optional[str]:
    """Why this project's records may not be destroyed, or None if nothing
    objects.

    ORDER MATTERS. The hold is checked first and answers on its own, so a held
    project whose seven years have long elapsed is refused for the RIGHT
    reason — the reason is shown to the person who asked, and "the retention
    period ends 2017-01-01" would read as a reason to proceed.

    A None return is NOT permission. It is the absence of a retention
    objection; the caller's tenancy and role gates are unaffected and still
    apply. Nothing in this module authorises anything.

    THE ABSENT-COMPLETION CASE REFUSES, and the attestation is the way through.
    A project nobody has recorded a completion for is not a project whose
    retention period has elapsed — it is a project whose retention period is
    UNKNOWN, and destroying records on an unknown is the thing this module
    exists to stop. The earlier build returned None here, which on merge day
    would have meant every project alive (none of which carries the field)
    stayed exactly as deletable as before: a brake bolted to nothing.

    The way through is a person, not a clock. Either record the completion —
    CO number and date — or attest that there is none. Both are named,
    reasoned, timestamped and audited. Neither is ever inferred, and no amount
    of elapsed time produces either one.
    """
    if project.get("legal_hold"):
        reason = (project.get("legal_hold_reason") or "").strip()
        detail = "A legal hold is in force on this project"
        if reason:
            detail = f"{detail}: {reason}"
        return (
            f"{detail}. Records cannot be deleted while the hold stands. "
            "A hold does not expire; an admin must lift it."
        )

    eligible = purge_eligible_at(project)

    if eligible is None:
        # NO USABLE COMPLETION ON RECORD.
        #
        # Read the attestation ONLY here, below the hold and below the recorded
        # completion. Its entire scope is "there is no completion to compute
        # from"; it is not an override, and this placement is what keeps it from
        # becoming one. A held project is already refused above. A project with
        # a recorded completion never reaches this branch, so an attestation
        # sitting on such a document — which `update_project` refuses to create
        # and clears when a completion is recorded — could not shorten its
        # seven-year period even if one somehow existed.
        if project.get("no_completion_attested"):
            return None
        return (
            "This project has no recorded job completion, so the "
            f"{RETENTION_YEARS}-year retention period cannot be computed and "
            "its records may not be destroyed. An admin must either record the "
            "final Certificate of Occupancy (number and date) or attest on the "
            "record that this project was never completed and may be purged."
        )

    # Compared as `"YYYY-MM-DD"` strings, which sort lexicographically exactly
    # as dates. `today` comes from eastern_date() — the NEW YORK calendar day,
    # since NYC DOB compliance is anchored to it and the UTC day is already
    # tomorrow in New York from 20:00 EDT.
    #
    # A MISSING `today` DOES NOT RELEASE THE BRAKE — the empty string fails the
    # `now and` guard and falls through to the refusal below, not past it.
    # Written this way round on purpose: there is no reading of "I do not know
    # what day it is" that should end in a destroyed compliance history.
    now = today or ""
    if now and now >= eligible:
        return None

    return (
        f"This project's records are retained for {RETENTION_YEARS} years after "
        f"job completion ({project.get('job_completion_date')}). "
        f"They may not be deleted before {eligible}."
    )
