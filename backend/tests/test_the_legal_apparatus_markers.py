"""A REGISTRY OF LEGAL-APPARATUS MARKERS, CHECKED AGAINST RENDERED OUTPUT.

WHY THIS FILE EXISTS, AND IT IS A REPLACEMENT RATHER THAN AN ADDITION.

`test_report_legal_vs_investor.py` walks the call graph from
`generate_combined_report` and requires every `render_signature_html` it
reaches to be passed `show_affirmation=False`. That check is correct and it
stays. What it cannot do is the thing its title suggests: it holds SIGNATURES,
not markers, because it works by asserting a keyword argument.

"Added after filing" took no keyword argument. It was a photograph caption on
a tile, produced by a helper that reads one flag off the photograph and
returns a string. There was no convention for it to violate, so the call-graph
walk had nothing to refuse, and the marker rendered on the investor report for
five weeks across two rulings that it should not. On the 2026-09-09 report it
printed eight times.

AND IT WAS INVERTED. It printed zero times on the per-logbook PDF, which is
where it was ruled to stay. That renderer contained no reference to the flag at
all. A call-site convention cannot see that either: absence of a call is not a
call with the wrong argument.

── SO THIS ASSERTS THE DOCUMENT, NOT THE CALL ────────────────────────────────

Each marker is named once, with the record that produces it. Both renders are
run on THAT record, and the marker must be:

    ABSENT from the investor report -- it is filing apparatus, and the report
        is read by lenders who are not owed an audit trail
    PRESENT on the legal render    -- which is what the investor report's own
        index links to, so nothing is lost by taking it off the report

BOTH HALVES, ALWAYS. Asserting only absence is how a marker string that no
longer exists anywhere passes forever: the check would be looking for nothing
and finding it. The presence half is the anchor, and it is why a marker cannot
be quietly deleted and called fixed.
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402

PROJECT = "p-apparatus"
DATE = "2026-09-09"

_SIGNATURE = {"paths": [[{"x": 1, "y": 2}, {"x": 30, "y": 20}]],
              "signerName": "daniel kaplan"}
#: A signature with an affirmation record, which is what produces the AFFIRMED
#: banner rather than the UNAFFIRMED one.
#:
#: NO `affirmation_flag`. A flag takes the third branch -- "AFFIRMED, claimed
#: time NOT VERIFIED" -- which is a different marker saying a weaker thing, and
#: a fixture that reached it by accident would have this test asserting the
#: presence of a banner it never produced.
_AFFIRMED = dict(_SIGNATURE, affirmed=True,
                 affirmedAt="2026-09-09T12:00:00Z",
                 affirmed_received_at="2026-09-09T12:00:01Z")


def _match(doc, query):
    for k, v in (query or {}).items():
        if k in ("$or", "$and"):
            continue
        cur = doc
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if isinstance(v, dict):
            if "$ne" in v and cur == v["$ne"]:
                return False
            if "$in" in v and cur not in v["$in"]:
                return False
        elif cur != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs): self._docs = docs
    def sort(self, *a, **k): return self
    def limit(self, *a, **k): return self
    async def to_list(self, n=None): return [copy.deepcopy(d) for d in self._docs]


class _Coll:
    def __init__(self, docs=None): self.docs = docs or []
    def find(self, q=None, p=None): return _Cursor(
        [d for d in self.docs if _match(d, q or {})])
    def aggregate(self, *a, **k): return _Cursor([])
    async def find_one(self, q=None, p=None, sort=None):
        for d in self.docs:
            if _match(d, q or {}):
                return copy.deepcopy(d)
        return None
    async def count_documents(self, q=None):
        return sum(1 for d in self.docs if _match(d, q or {}))


class _DB:
    def __init__(self): self._c = {}
    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self[n]
    def __getitem__(self, n):
        self._c.setdefault(n, _Coll())
        return self._c[n]


def _base(log_type, **data):
    return {
        "_id": f"lb-{log_type}", "project_id": PROJECT, "date": DATE,
        "log_type": log_type, "status": "submitted", "cp_name": "daniel kaplan",
        "cp_signature": copy.deepcopy(_SIGNATURE),
        "data": dict({"activities": [], "attendees": [], "entries": [],
                      "signins": [], "workers": []}, **data),
    }


# ══════════════════════════════════════════════════════════════════════════
#  THE REGISTRY
# ══════════════════════════════════════════════════════════════════════════
#
# (name, marker text, the record that produces it).
#
# ADDING A MARKER IS ADDING A LINE HERE. That is the whole mechanism: a marker
# nobody registers is a marker nobody checks, and the one that got away was a
# photograph caption that no convention described. A name in a list is
# something a reviewer can count against the document in front of them.

def _appended_photo_record():
    r = _base("daily_jobsite", general_description="plumbing")
    r["data"]["activities"] = [{
        "company": "Quality Plumbing", "work_description": "risers",
        "num_workers": 3,
        "photos": [
            {"photo_id": "ph-1", "original_r2_key": "k/1.jpg",
             "timestamp": "2026-09-09T08:00:00Z"},
            {"photo_id": "ph-2", "original_r2_key": "k/2.jpg",
             "timestamp": "2026-09-09T08:05:00Z",
             "added_after_filing": True,
             "added_at": "2026-09-10T15:04:00Z",
             "added_by_name": "Michael Cespedes"},
        ],
    }]
    return r


def _affirmed_record():
    r = _base("daily_jobsite", general_description="framing")
    r["cp_signature"] = copy.deepcopy(_AFFIRMED)
    return r


def _unaffirmed_record():
    return _base("daily_jobsite", general_description="framing")


MARKERS = (
    ("the appended-photograph notice",
     server._PHOTO_ADDED_AFTER_FILING_LABEL, _appended_photo_record),
    ("the affirmation banner",
     "AFFIRMED for this document", _affirmed_record),
    ("the unaffirmed warning",
     "UNAFFIRMED", _unaffirmed_record),
)


def _investor(record):
    db = _DB()
    db.projects.docs = [{"_id": PROJECT, "name": "588 Thomas S Boyland Street",
                         "address": "588 Thomas S Boyland Street",
                         "company_name": "Metro Build Constructors LLC"}]
    db.logbooks.docs = [record]
    db.checkins.docs = []
    with patch.object(server, "db", db), \
            patch.object(server, "to_query_id", lambda x: x):
        return asyncio.run(server.generate_combined_report(PROJECT, DATE))


def _legal(record):
    db = _DB()
    db.projects.docs = [{"_id": PROJECT, "name": "588 Thomas S Boyland Street",
                         "address": "588 Thomas S Boyland Street",
                         "company_name": "Metro Build Constructors LLC"}]
    db.logbooks.docs = [record]
    with patch.object(server, "db", db), \
            patch.object(server, "to_query_id", lambda x: x):
        return asyncio.run(server.generate_single_logbook_html(record))


class EveryRegisteredMarkerIsOnTheLegalDocumentOnly(unittest.TestCase):

    def test_each_marker_is_PRESENT_on_the_legal_render(self):
        """THE ANCHOR HALF, and it is not optional.

        Absence alone is satisfied by a string that no longer exists anywhere,
        which is the failure this whole file is a reaction to. If a marker
        cannot be produced on the document it belongs on, the registry entry is
        wrong or the marker has been deleted, and either is worth failing for.
        """
        for name, text, make in MARKERS:
            with self.subTest(marker=name):
                html = _legal(make())
                self.assertIn(
                    text, html,
                    f"{name}: not on the per-logbook PDF, which is the "
                    f"document it exists for. A marker that is absent here "
                    f"cannot be meaningfully asserted absent anywhere else.")

    def test_each_marker_is_ABSENT_from_the_investor_report(self):
        """The report is read by lenders. The audit trail is one click away on
        the record index, which links every card to this same legal render."""
        for name, text, make in MARKERS:
            with self.subTest(marker=name):
                html = _investor(make())
                self.assertNotIn(
                    text, html,
                    f"{name}: filing apparatus on the investor report. It was "
                    f"ruled off with the affirmation banner and the citations; "
                    f"the reader who needs it clicks through to the filing.")

    def test_the_registry_is_not_empty_and_names_the_one_that_got_away(self):
        """A registry that quietly empties is a gate that quietly stops.

        The appended-photograph notice is named explicitly because it is the
        marker this file exists for: it rendered on the investor report through
        two rulings and zero times on the legal PDF, and the check that was
        described as covering it could not see it.
        """
        self.assertGreaterEqual(len(MARKERS), 3)
        self.assertIn(server._PHOTO_ADDED_AFTER_FILING_LABEL,
                      [t for _n, t, _m in MARKERS])


class TheConventionCheckIsStillOnlyAboutSignatures(unittest.TestCase):
    """The call-graph walk stays, and stops being described as more than it is.

    It holds the fourteen `render_signature_html` call sites reachable from the
    report, which is a real job and the only one it can do. Saying so in both
    files is what stops the next person reading its title and concluding that
    markers are covered.
    """

    def test_the_other_file_says_what_it_does_not_cover(self):
        src = (Path(__file__).resolve().parent
               / "test_report_legal_vs_investor.py").read_text(encoding="utf-8")
        self.assertIn(
            "test_the_legal_apparatus_markers", src,
            "the convention check does not point at the registry that covers "
            "what it cannot: a reader who finds only that file will believe "
            "markers are held when they are not")


if __name__ == "__main__":
    unittest.main(verbosity=2)
