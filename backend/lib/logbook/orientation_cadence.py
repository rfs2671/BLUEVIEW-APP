"""AN AS-NEEDED LOG IS NOT DUE UNTIL SOMEBODY NEEDS IT.

── WHAT THE CP'S SCREEN WAS DOING ──────────────────────────────────────────

`subcontractor_orientation` is declared `frequency: "as_needed"` in
LOGBOOK_TYPE_REGISTRY and is due for ONE reason: a worker checked in on this
project and has no orientation on it. `get_required_logbooks` never reads
`frequency` -- it resolves the required set from `applicable_classes` and
`conditional` alone -- so the type came back on every project, every day, and
the logbook list asked `todayLogs["subcontractor_orientation"]` about it. That
read is by DATE, so it answered "pending", and the completion bar counted it.

MEASURED ON PRODUCTION, read-only across all three active projects:

    8 Walworth      0 checked-in workers,  0 orientations
    588 Thomas     63 checked-in workers, 65 oriented
    857 Prescott   13 checked-in workers, 13 oriented

Not one worker anywhere is waiting for an orientation. The tile was Pending on
every project on every day, and the count read 4/6 where the sixth item was
not due at all.

── WHY THE RULE IS HERE AND NOT IN THE SCREEN ──────────────────────────────

The screen HAD an as-needed rule once -- `notifications.unsigned_orientations
> 0` in getVisibleLogTypes' local fallback -- and it is unreachable in normal
operation: the server branch returns before it. That was deliberate (the
comment there calls the local filtering "a second model"), and the half that
was never built is this one. The server is authoritative; the answer it was
missing belongs on the server.

── COVERED BY EITHER RECORD, AND COMPARED AS STRINGS ───────────────────────

Orientation coverage was written in two places over two eras and BOTH still
hold live rows:

  * `logbooks` -- a `subcontractor_orientation` document whose
    `data.worker_id` is the worker, written at the gate since the type existed
  * `workers.safety_orientations[]` -- an embedded entry carrying `project_id`,
    written in the same breath by the register-and-check-in path

A worker named by either one has been oriented. Counting only the logbook
would re-open the log for a man who was oriented before the logbook document
was being written; counting only the embedded list would miss one a CP filed
by hand. So: EITHER.

Every identifier is compared as `str`. Production holds `checkins.worker_id`
as a string and `workers._id` as an ObjectId, and `ObjectId(x) != str(x)` --
a set difference across the two shapes would report every worker uncovered and
turn a permanently-green tile into a permanently-red one.

PURE. No I/O; the caller supplies the three sets. That is what makes the rule
testable against a roster rather than against a database.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional

#: Reported on the period so a client can say WHY the orientation log is open.
#: NOT a cadence code. The weekly rule's reasons name an elapsed period; this
#: one names people.
WORKER_NOT_ORIENTED = "WORKER_NOT_ORIENTED"

#: How many uncovered workers a row will name before it stops listing them.
#: A due_reason is a sentence for a CP to read, not a roster export -- and the
#: one surface that renders it is a line under a tile on a phone.
NAME_LIMIT = 20


def as_ids(values: Iterable) -> set:
    """A set of non-empty string ids from anything iterable.

    TOTAL, and str on purpose. See the module note: the two sides of this
    comparison are stored in different shapes.
    """
    out = set()
    for v in (values or []):
        if v is None:
            continue
        text = str(v).strip()
        if text:
            out.add(text)
    return out


def uncovered_workers(
    checked_in_ids: Iterable = (),
    oriented_by_logbook_ids: Iterable = (),
    oriented_by_worker_doc_ids: Iterable = (),
) -> list:
    """Who checked in on this project and has no orientation on it, sorted.

    EXPORTED SEPARATELY so the caller can look the names up without having to
    read them back out of a row that has already substituted them -- the row
    falls back to an id where no name is known, and a caller that took those
    ids for names would be reading its own default.
    """
    covered = (as_ids(oriented_by_logbook_ids)
               | as_ids(oriented_by_worker_doc_ids))
    return sorted(as_ids(checked_in_ids) - covered)


def orientation_period(
    checked_in_ids: Iterable = (),
    oriented_by_logbook_ids: Iterable = (),
    oriented_by_worker_doc_ids: Iterable = (),
    names: Optional[Mapping] = None,
) -> Dict:
    """Is the orientation log due, and if so, for whom.

    `checked_in_ids`              every worker who has checked in on this project
    `oriented_by_logbook_ids`     `data.worker_id` on this project's orientations
    `oriented_by_worker_doc_ids`  workers whose `safety_orientations[]` names it
    `names`                       id -> worker name, for the reason line only

    Returns a row shaped like `toolbox_period`'s, so the client renders it
    through the same `periods` channel with no new payload:

        {log_type, frequency, period_start, period_end, satisfied, filed_on,
         due_reason, uncovered_weekend_workers, uncovered_workers,
         uncovered_worker_count}

    `period_start` / `period_end` are None. AN AS-NEEDED LOG HAS NO PERIOD,
    and putting today's date in those fields would be this function asserting
    a cadence nobody has defined -- the exact thing `_logbook_periods` refused
    to do when it declined to emit this row at all.

    `uncovered_weekend_workers` is [] for the same kind of reason: it is the
    weekly rule's field, it does not apply here, and the one client that reads
    it must not find a value in it that means something else.
    """
    uncovered = uncovered_workers(
        checked_in_ids, oriented_by_logbook_ids, oriented_by_worker_doc_ids)

    lookup = names or {}
    named = [str(lookup.get(w) or lookup.get(str(w)) or w)
             for w in uncovered[:NAME_LIMIT]]

    return {
        "log_type": "subcontractor_orientation",
        "frequency": "as_needed",
        "period_start": None,
        "period_end": None,
        "satisfied": not uncovered,
        "filed_on": [],
        "due_reason": WORKER_NOT_ORIENTED if uncovered else None,
        "uncovered_weekend_workers": [],
        # NAMES, NOT IDS, where a name is known. "3 workers have no
        # orientation" tells a CP there is work; naming them tells him who he
        # is sitting down with, which is the difference between a badge and an
        # instruction. Truncated at NAME_LIMIT; the count below is not.
        "uncovered_workers": named,
        "uncovered_worker_count": len(uncovered),
    }
