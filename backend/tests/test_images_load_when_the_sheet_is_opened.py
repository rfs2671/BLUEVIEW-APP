"""A SHEET'S TEXT LOADS FIRST; ITS SIGNATURE IMAGES ARE A SECOND READ.

#681 made the gate tablet's LIST cost the index instead of the corpus: 39 KB
and 167 ms for 43 dates, against 14,363,640 bytes and five pages. Opening one
day still cost that day's whole payload, and the payload is signature images.

── THE REMAINING DEFECT, MEASURED ON PRODUCTION 2026-10-08 ──────────────────

Every submitted record of every project, through a read-only probe:

    data.workers[].worker_signature          9,685,074 B   56.7%
    data.worker_signature  (orientation)     1,548,916 B    9.1%
    data.attendees[].worker_signature                0 B    0.0%
    data.attendees[].signature                       0 B    0.0%
    cp_signature.data                                0 B    0.0%
    ─────────────────────────────────────────────────────────────
    signature images                        11,233,990 B   65.8% of 17,080,794

Per day, for the one project with a history (43 dates, 339 records):

                   lightest     median    heaviest
    today             4,691    361,525   1,440,691
    text only         4,691     99,491     592,243

── THE TRAP THIS FILE EXISTS TO HOLD SHUT ───────────────────────────────────

`frontend/app/site/logbooks.jsx` keyed TWO blocks off one field:

    workers.some(w => w.worker_signature)    -> draw the signature images
    workers.some(w => !w.worker_signature)   -> list those names as UNSIGNED

So a payload that merely OMITTED the mark would tell a DOB inspector that every
one of the 505 men who signed at the kiosk had NOT signed. That is a false
statement on a legal record and it is strictly worse than a slow screen. There
are THREE states and section B asserts the wire carries all three.

── WHAT EACH SECTION GUARDS ─────────────────────────────────────────────────

  A. THE OLD READ IS BYTE-FOR-BYTE THE OLD READ, and so is the `date` read a
     #681-era tablet makes. Both new behaviours are behind `view=text`, which
     a tablet bolted to a gate cannot be made to send.

  B. THREE STATES ON THE WIRE. Signed-and-deferred, not-signed, and
     signed-with-no-bytes are three different things and none of them may be
     served as another.

  C. ONE READER FOR BOTH HALVES. What the day left out and what the signature
     endpoint brings are derived from the same walk, so they cannot drift.
     THIS TEST CAN FAIL: the last case removes a site from the table and
     asserts the parity check NOTICES.

  D. NOTHING STORED IS TOUCHED. The deferral is copy-on-write; the documents
     handed to the handler are byte-identical afterwards.

  E. THE FILED DOCUMENT IS BYTE-IDENTICAL. This is a transport change for one
     screen. The PDF renderer is run against the same record before and after a
     `view=text` read of it, and -- the instrument check -- the sheet is
     asserted to CONTAIN the mark, so the comparison is not two blank pages.

  F. THE ENDPOINT IS REACHABLE AND SCOPED. Reachable because a route of this
     shape has been shadowed in this file before; scoped because these are
     named workers' signatures, unlike the deliberately-open photo endpoint
     next door.

Run:  python -m pytest tests/test_images_load_when_the_sheet_is_opened.py -q
"""

from __future__ import annotations

import base64 as _b64
import copy
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

_HISTORY_JS = _REPO / "frontend" / "src" / "utils" / "siteLogbookHistory.js"
# THE PROTOCOL ITSELF, in a module that imports nothing -- which is what lets
# the screen's renderers be EXECUTED against the real `signatureMark` instead of
# a stub of it. See that file's own header for why that mattered.
_DEFERRAL_JS = _REPO / "frontend" / "src" / "utils" / "signatureDeferral.js"
_SCREEN_JSX = _REPO / "frontend" / "app" / "site" / "logbooks.jsx"
_LEGAL_RENDER = _BACKEND / "lib" / "legal_render"


# ── the fixture: the shape the measurement describes ─────────────────────────
#
# A data URI, because that is what all 583 marks in production are -- not bare
# base64. A predicate or a splice that only handled the bare form would pass a
# fixture that used one and fail on every filed record.
def _sig(seed: str) -> str:
    """~20 KB, WHICH IS WHAT A KIOSK MARK WEIGHS. The mean of the 583 in
    production is 20,040 B. The first version of this helper made a 1.4 KB mark
    and the size assertion in section B then compared five of those against the
    32 KB photo thumbnail beside them -- a fixture whose proportions were not
    the measurement's, asserting a saving the real payload does not have."""
    return "data:image/png;base64," + _b64.b64encode(
        (seed * 20000).encode("ascii")[:15000]).decode("ascii")


WORKER_SIG = _sig("W")
ACK_SIG = _sig("A")
ATTENDEE_SIG = _sig("T")
THUMB_B64 = _b64.b64encode(b"T" * (32 * 1024)).decode("ascii")

DAY = "2026-09-28"

# `cp_signature` AS PRODUCTION ACTUALLY STORES IT: affirmation metadata and no
# image. All 387 filed records are one of seven key sets of this shape and not
# one carries `data`, which is why it is not in SIGNATURE_IMAGE_SITES.
CP_SIG = {"affirmed": True, "affirmedLang": "en", "signerName": "Casey CP",
          "timestamp": f"{DAY}T15:31:00+00:00"}


def _preshift() -> dict:
    """Four men. Two signed at the kiosk, one has the key explicitly NULL and
    one has no key at all -- which are the two unsigned shapes production
    holds (98 of 603 roster rows) and must be left byte-identical."""
    return {
        "_id": "lb_preshift",
        "project_id": "proj1", "company_id": "co_test",
        "log_type": "preshift_signin", "date": DAY,
        "status": "submitted", "is_deleted": False,
        "cp_name": "Casey CP", "cp_signature": copy.deepcopy(CP_SIG),
        "created_at": f"{DAY}T07:00:00+00:00",
        "updated_at": f"{DAY}T07:05:00+00:00",
        "data": {"company": "Sub A", "total_count": 4, "workers": [
            {"name": "Signed One", "company": "Sub A", "osha_number": "SST-1",
             "worker_signature": WORKER_SIG},
            {"name": "Unsigned Null", "company": "Sub A", "osha_number": "SST-2",
             "worker_signature": None},
            {"name": "Signed Two", "company": "Sub A", "osha_number": "SST-3",
             "worker_signature": WORKER_SIG},
            {"name": "Unsigned Absent", "company": "Sub A", "osha_number": "SST-4"},
        ]},
    }


def _toolbox() -> dict:
    """An attendee who signed. ZERO production rows look like this -- all 558
    have both keys null -- and the fixture carries one anyway, because the
    renderer READS both keys and an uncovered site is the next trap."""
    return {
        "_id": "lb_toolbox",
        "project_id": "proj1", "company_id": "co_test",
        "log_type": "toolbox_talk", "date": DAY,
        "status": "submitted", "is_deleted": False,
        "cp_name": "Casey CP", "cp_signature": copy.deepcopy(CP_SIG),
        "created_at": f"{DAY}T07:30:00+00:00",
        "updated_at": f"{DAY}T07:35:00+00:00",
        "data": {"topic": "Ladders", "attendees": [
            {"name": "Attendee Signed", "worker_signature": ATTENDEE_SIG},
            {"name": "Attendee Other", "signature": ATTENDEE_SIG},
            {"name": "Attendee None", "worker_signature": None, "signature": None},
        ]},
    }


def _orientation() -> dict:
    """The second biggest site: `data.worker_signature`, 1,548,916 B, 9.1%."""
    return {
        "_id": "lb_orientation",
        "project_id": "proj1", "company_id": "co_test",
        "log_type": "subcontractor_orientation", "date": DAY,
        "status": "submitted", "is_deleted": False,
        "cp_name": "Casey CP", "cp_signature": copy.deepcopy(CP_SIG),
        "created_at": f"{DAY}T08:00:00+00:00",
        "updated_at": f"{DAY}T08:05:00+00:00",
        "data": {"worker_name": "New Hire", "worker_signature": ACK_SIG,
                 "topics": [{"topic": "PPE", "reviewed": "yes"}]},
    }


def _orientation_unsigned() -> dict:
    """A manual entry: the key is PRESENT AND NULL, which is what makes the
    screen say UNSIGNED. 15 of 93 filed orientations are in this state."""
    doc = _orientation()
    doc["_id"] = "lb_orientation_manual"
    doc["data"] = dict(doc["data"], worker_signature=None)
    return doc


def _daily() -> dict:
    """NO signature anywhere, and 32 KB of photo thumbnail that must stay. This
    is the record that proves `view=text` is not a general photo strip -- and
    on 2026-09-24 one record of this type is 555,232 B of thumbnails, which is
    what the heaviest day costs AFTER this change."""
    return {
        "_id": "lb_daily",
        "project_id": "proj1", "company_id": "co_test",
        "log_type": "daily_jobsite", "date": DAY,
        "status": "submitted", "is_deleted": False,
        "cp_name": "Casey CP", "cp_signature": copy.deepcopy(CP_SIG),
        "created_at": f"{DAY}T13:00:00+00:00",
        "updated_at": f"{DAY}T15:31:00+00:00",
        "data": {"weather": "Sunny", "activities": [{
            "activity_id": "act_1", "company": "Sub A",
            "photos": [{"thumb_base64": THUMB_B64}],
        }]},
    }


def _docs() -> list:
    return [_preshift(), _toolbox(), _orientation(), _orientation_unsigned(),
            _daily()]


# ── a Mongo faithful enough for a projection to mean something ───────────────

def _matches(doc: dict, query: dict) -> bool:
    for key, cond in (query or {}).items():
        val = doc.get(key, None)
        if isinstance(cond, dict):
            if "$ne" in cond and val == cond["$ne"]:
                return False
            if "$in" in cond and val not in cond["$in"]:
                return False
            if "$lt" in cond and not (val is not None and val < cond["$lt"]):
                return False
        elif val != cond:
            return False
    return True


def _strip(node, parts):
    if isinstance(node, list):
        for el in node:
            _strip(el, parts)
        return
    if not isinstance(node, dict):
        return
    head, rest = parts[0], parts[1:]
    if not rest:
        node.pop(head, None)
        return
    if head in node:
        _strip(node[head], rest)


def _project(doc: dict, projection) -> dict:
    """BOTH KINDS, AND A MIXED ONE IS A DRIVER ERROR -- Mongo refuses a
    projection that mixes inclusion and exclusion (bar `_id`), so a fake that
    accepted one would clear a handler the real driver rejects."""
    if not projection:
        return copy.deepcopy(doc)
    values = {bool(v) for k, v in projection.items() if k != "_id"}
    if len(values) > 1:
        raise AssertionError(f"mixed inclusion/exclusion projection: {projection}")
    if values == {True}:
        out = {}
        for key, keep in projection.items():
            if keep and key in doc:
                out[key] = copy.deepcopy(doc[key])
        if projection.get("_id", 1) and "_id" in doc:
            out["_id"] = doc["_id"]
        return out
    out = copy.deepcopy(doc)
    for path, keep in projection.items():
        if keep:
            continue
        _strip(out, path.split("."))
    return out


class _Cursor:
    def __init__(self, items):
        self._items = items

    def sort(self, spec, direction=None):
        keys = [(spec, direction if direction is not None else 1)] \
            if isinstance(spec, str) else list(spec)
        for field, direction in reversed(keys):
            self._items.sort(
                key=lambda d, f=field: (d.get(f) is None, d.get(f) or ""),
                reverse=(direction == -1),
            )
        return self

    async def to_list(self, n=None):
        return self._items if n is None else self._items[:n]


class _Logbooks:
    def __init__(self, docs):
        self.docs = docs
        self.writes = []

    def find(self, query=None, projection=None, *a, **k):
        hits = [d for d in self.docs if _matches(d, query or {})]
        return _Cursor([_project(d, projection) for d in hits])

    async def find_one(self, query=None, projection=None, *a, **k):
        for d in self.docs:
            if _matches(d, query or {}):
                return _project(d, projection)
        return None

    async def distinct(self, field, query=None, *a, **k):
        vals, seen = [], set()
        for d in self.docs:
            if not _matches(d, query or {}):
                continue
            v = d.get(field, None)
            marker = (type(v).__name__, v)
            if marker in seen:
                continue
            seen.add(marker)
            vals.append(v)
        return vals

    async def update_one(self, *a, **k):
        self.writes.append(("update_one", a, k))

    async def insert_one(self, *a, **k):
        self.writes.append(("insert_one", a, k))

    async def delete_one(self, *a, **k):
        self.writes.append(("delete_one", a, k))

    async def count_documents(self, query=None, *a, **k):
        return sum(1 for d in self.docs if _matches(d, query or {}))


class _FakeCollection:
    def __init__(self, one=None):
        self.one = one

    async def find_one(self, query=None, *a, **k):
        return self.one

    def find(self, *a, **k):
        return _Cursor([])

    async def count_documents(self, *a, **k):
        return 0


PROJECT = {"_id": "proj1", "name": "Test Tower", "company_id": "co_test",
           "is_deleted": False}


_DEFAULT = object()


class _FakeDb:
    def __init__(self, logbooks, projects=_DEFAULT):
        # A SENTINEL, NOT `None`. `projects=None` is how a caller says "this
        # project is GONE", and a default of None swallowed that: the scoping
        # test below handed in None, got the real project back, and passed.
        self._c = {"logbooks": logbooks,
                   "projects": _FakeCollection(
                       one=PROJECT if projects is _DEFAULT else projects)}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


SITE_USER = {
    "_id": "site_1", "id": "site_1", "role": "cp",
    "company_id": "co_test", "account_status": "approved",
    "full_name": "Site Tablet", "assigned_projects": ["proj1"],
}

OTHER_USER = {
    "_id": "other_1", "id": "other_1", "role": "cp",
    "company_id": "co_other", "account_status": "approved",
    "full_name": "Another Tenant", "assigned_projects": [],
}

BASE = "/api/logbooks/project/proj1/submitted"


def _get(docs, query="", project_override=False):
    """The SUBMITTED read. `require_project_access` is overridden, because what
    that gate does is #681's subject and not this change's."""
    logbooks = _Logbooks(docs)
    db = _FakeDb(logbooks)

    async def _fake_user():
        return SITE_USER

    async def _fake_project():
        return PROJECT

    ov = server.app.dependency_overrides
    ov[server.get_current_user] = _fake_user
    ov[server.require_project_access] = _fake_project
    try:
        with patch.object(server, "db", db):
            r = TestClient(server.app).get(BASE + query)
    finally:
        ov.clear()
    return r, logbooks


def _sigs(docs, logbook_id, user=SITE_USER, projects=_DEFAULT):
    """The SIGNATURE read. `require_project_access` is NOT overridden here: the
    scoping is this endpoint's own and section F is about exactly that."""
    logbooks = _Logbooks(docs)
    db = _FakeDb(logbooks, projects=projects)

    async def _fake_user():
        return user

    ov = server.app.dependency_overrides
    ov[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db):
            r = TestClient(server.app).get(
                f"/api/logbooks/{logbook_id}/signature-images")
    finally:
        ov.clear()
    return r, logbooks


def _rows(body):
    return {str(r.get("id") or ""): r
            for day in (body.get("dates") or {}).values() for r in day}


def _wire(obj) -> int:
    return len(json.dumps(obj, default=str))


def _strip_js_comments(src: str) -> str:
    """Comment prose is not code. This repo has had source-text assertions pass
    on a comment that MENTIONED the thing they were looking for."""
    out, i, n = [], 0, len(src)
    while i < n:
        two = src[i:i + 2]
        if two == "/*":
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if two == "//":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        ch = src[i]
        if ch in "'\"`":
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == ch:
                    break
                j += 1
            out.append(src[i:j + 1])
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _code(src: str) -> str:
    """The stripped source as one whitespace-collapsed line.

    `_strip_python` re-joins TOKENS with newlines, so a literal like
    `_row = _defer_signature_images(_row)` is never in its output however
    certainly it is in the file. Collapsing makes a claim about CODE rather
    than about the layout the stripper happened to produce."""
    return " ".join(_strip_python(src).split())


def _strip_python(src: str) -> str:
    """Docstrings and `#` prose out, for the same reason."""
    import io
    import tokenize
    out = []
    prev_type = tokenize.INDENT
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:
        return src
    for tok in toks:
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and prev_type in (
                tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE,
                tokenize.NL, tokenize.ENCODING):
            continue
        out.append(tok.string)
        if tok.type not in (tokenize.NL,):
            prev_type = tok.type
    return "\n".join(out)


# ═════════════════════════════════════════════════════════════════════════════
# A. THE OLD READS ARE THE OLD READS
# ═════════════════════════════════════════════════════════════════════════════

class TheInstalledTabletIsUntouched(unittest.TestCase):
    """A tablet bolted to a gate cannot be updated from the gate. Both new
    behaviours are behind `view=text`, and absent means absent."""

    def test_the_default_read_still_carries_every_signature(self):
        body = _get(_docs())[0].json()
        rows = _rows(body)
        workers = rows["lb_preshift"]["data"]["workers"]
        self.assertEqual(workers[0]["worker_signature"], WORKER_SIG)
        self.assertEqual(workers[2]["worker_signature"], WORKER_SIG)
        self.assertEqual(rows["lb_orientation"]["data"]["worker_signature"], ACK_SIG)
        self.assertEqual(
            rows["lb_toolbox"]["data"]["attendees"][0]["worker_signature"],
            ATTENDEE_SIG)

    def test_the_default_read_adds_no_deferred_key_anywhere(self):
        """The flag is the new shape. A body nobody asked it for must not carry
        it -- that is the mistake #681 made with `"view": null` and the pin in
        test_one_record_with_its_history.py caught."""
        raw = json.dumps(_get(_docs())[0].json(), default=str)
        self.assertNotIn("_deferred", raw)

    def test_the_681_era_date_read_still_carries_every_signature(self):
        """THE OTHER INSTALLED GENERATION. #681 shipped `?date=<key>` without
        `view`; a tablet on that OTA and not this one must still get the ink,
        or the trap fires one generation back."""
        rows = _rows(_get(_docs(), f"?date={DAY}")[0].json())
        self.assertEqual(
            rows["lb_preshift"]["data"]["workers"][0]["worker_signature"],
            WORKER_SIG)
        self.assertNotIn("_deferred",
                         json.dumps(rows["lb_preshift"], default=str))

    def test_the_index_read_is_unchanged_by_any_of_this(self):
        body = _get(_docs(), "?view=index")[0].json()
        self.assertEqual(body.get("view"), "index")
        for row in _rows(body).values():
            self.assertNotIn("data", row)
            self.assertNotIn("worker_signature_deferred", row)

    def test_text_is_a_known_view_and_a_misspelling_is_still_a_400(self):
        self.assertEqual(_get(_docs(), "?view=text")[0].status_code, 200)
        r = _get(_docs(), "?view=txet")[0]
        self.assertEqual(r.status_code, 400, r.text[:300])
        self.assertIn("txet", r.text)

    def test_the_echo_says_which_body_this_is(self):
        """A server that predates `view=text` IGNORES it and serves documents
        WITH their marks. The echo is the only way a client can tell that from
        a text body, and believing the wrong one is a tablet that caches
        'nobody signed'."""
        self.assertEqual(_get(_docs(), "?view=text")[0].json().get("view"), "text")
        self.assertNotIn("view", _get(_docs())[0].json())


# ═════════════════════════════════════════════════════════════════════════════
# B. THREE STATES ON THE WIRE
# ═════════════════════════════════════════════════════════════════════════════

class ThreeStatesNotTwo(unittest.TestCase):
    """THE WHOLE POINT. Signed-and-deferred, not-signed, and signed-with-no-
    bytes are three different claims about a legal record."""

    def setUp(self):
        self.rows = _rows(_get(_docs(), f"?date={DAY}&view=text")[0].json())

    def test_a_man_who_signed_is_flagged_and_not_omitted(self):
        w = self.rows["lb_preshift"]["data"]["workers"][0]
        self.assertNotIn("worker_signature", w)
        self.assertIs(w["worker_signature_deferred"], True)

    def test_a_man_who_did_NOT_sign_is_byte_for_byte_what_he_was(self):
        """THE TRAP. `worker_signature: null` and the ABSENT key are the two
        unsigned shapes production holds, and a flag on either of them would
        turn a man who did not sign into a man whose image is merely late --
        the same lie in the other direction."""
        before = _preshift()["data"]["workers"]
        after = self.rows["lb_preshift"]["data"]["workers"]
        self.assertEqual(after[1], before[1])
        self.assertEqual(after[3], before[3])
        for i in (1, 3):
            self.assertNotIn("worker_signature_deferred", after[i])

    def test_the_unsigned_list_the_screen_draws_is_the_same_list(self):
        """Derived the way the screen derives it -- "no value and no flag" --
        and asserted equal to the names the OLD body yields from "no value".
        The invariant, not the two sides."""
        old = [w["name"] for w in _preshift()["data"]["workers"]
               if not w.get("worker_signature")]
        new = [w["name"] for w in self.rows["lb_preshift"]["data"]["workers"]
               if not w.get("worker_signature")
               and not w.get("worker_signature_deferred")]
        self.assertEqual(new, old)
        self.assertEqual(new, ["Unsigned Null", "Unsigned Absent"])

    def test_both_attendee_keys_are_covered(self):
        a = self.rows["lb_toolbox"]["data"]["attendees"]
        self.assertIs(a[0]["worker_signature_deferred"], True)
        self.assertIs(a[1]["signature_deferred"], True)
        self.assertEqual(a[2], _toolbox()["data"]["attendees"][2])

    def test_the_orientation_acknowledgment_is_covered(self):
        d = self.rows["lb_orientation"]["data"]
        self.assertNotIn("worker_signature", d)
        self.assertIs(d["worker_signature_deferred"], True)

    def test_an_unsigned_orientation_keeps_its_PRESENT_AND_NULL_key(self):
        """`'worker_signature' in data` is what makes the screen say UNSIGNED
        rather than say nothing. Flagging it, or dropping it, changes what a
        filed record asserts about an unattested acknowledgment."""
        d = self.rows["lb_orientation_manual"]["data"]
        self.assertIn("worker_signature", d)
        self.assertIsNone(d["worker_signature"])
        self.assertNotIn("worker_signature_deferred", d)

    def test_an_affirmation_only_cp_signature_is_left_alone(self):
        """SIGNED, NO BYTES. All 387 filed `cp_signature`s are metadata with no
        `data`, so there is nothing to move -- and moving it would have put the
        'exists?' test the screen already does behind a second request."""
        self.assertEqual(self.rows["lb_preshift"]["cp_signature"], CP_SIG)
        self.assertEqual(self.rows["lb_daily"]["cp_signature"], CP_SIG)

    def test_a_record_with_no_marks_is_unchanged_including_its_photos(self):
        """`view=text` IS NOT A PHOTO STRIP. `thumb_base64` is the last inline
        copy and the finalize purge is forbidden to remove it; this read may
        not either."""
        daily = self.rows["lb_daily"]
        self.assertEqual(
            daily["data"]["activities"][0]["photos"][0]["thumb_base64"],
            THUMB_B64)
        plain = _rows(_get(_docs(), f"?date={DAY}")[0].json())["lb_daily"]
        self.assertEqual(daily, plain)

    def test_the_day_is_materially_smaller_and_the_number_is_reported(self):
        """BOTH STATUSES FIRST. A 400 body is also small, so this measurement
        passed on the pre-change tree -- where `view=text` was a refusal --
        until it was made to check that it is comparing two DAYS."""
        r_whole = _get(_docs(), f"?date={DAY}")[0]
        r_text = _get(_docs(), f"?date={DAY}&view=text")[0]
        self.assertEqual(r_whole.status_code, 200)
        self.assertEqual(r_text.status_code, 200, r_text.text[:200])
        self.assertEqual(r_text.json().get("view"), "text")
        whole = _wire(r_whole.json())
        text = _wire(r_text.json())
        self.assertLess(text * 2, whole,
                        f"text {text} B is not materially smaller than {whole} B")


# ═════════════════════════════════════════════════════════════════════════════
# C. ONE READER FOR BOTH HALVES
# ═════════════════════════════════════════════════════════════════════════════

class WhatLeftAndWhatComesBack(unittest.TestCase):
    """THE INVARIANT, NOT THE TWO SIDES. The set of addresses the day body
    flagged and the set the signature endpoint serves are one set."""

    @staticmethod
    def _flagged(row) -> set:
        """Every `*_deferred` address in a served row, read out of the body."""
        out = set()

        def walk(node, path):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k.endswith("_deferred") and v is True:
                        out.add(f"{path}.{k[:-len('_deferred')]}".lstrip("."))
                    else:
                        walk(v, f"{path}.{k}".lstrip("."))
            elif isinstance(node, list):
                for i, el in enumerate(node):
                    walk(el, f"{path}.{i}")

        walk(row.get("data"), "data")
        return out

    def test_every_flagged_address_is_served_and_no_others(self):
        r = _get(_docs(), f"?date={DAY}&view=text")[0]
        self.assertEqual(r.status_code, 200, r.text[:200])
        rows = _rows(r.json())
        # THE JOIN COUNT, PRINTED BESIDE THE RESULT. A parity check over zero
        # rows reports no disagreement and is indistinguishable from a clean
        # one -- which is exactly how this passed on the pre-change tree, where
        # `view=text` was a 400 and `rows` was empty.
        self.assertEqual(len(rows), 5, f"compared {len(rows)} records, not 5")
        self.assertEqual(
            sum(len(self._flagged(row)) for row in rows.values()), 5,
            "no record in this fixture flagged a mark, so the parity "
            "assertion below has nothing to compare")
        docs = _docs()
        for log_id, row in rows.items():
            flagged = self._flagged(row)
            served = _sigs(docs, log_id)[0].json()
            self.assertEqual(set(served["signatures"].keys()), flagged,
                             f"{log_id}: served {sorted(served['signatures'])} "
                             f"against flagged {sorted(flagged)}")
            self.assertEqual(served["count"], len(flagged))

    def test_the_served_bytes_are_the_stored_bytes(self):
        served = _sigs(_docs(), "lb_preshift")[0].json()["signatures"]
        self.assertEqual(served["data.workers.0.worker_signature"], WORKER_SIG)
        self.assertEqual(served["data.workers.2.worker_signature"], WORKER_SIG)
        self.assertEqual(sorted(served), ["data.workers.0.worker_signature",
                                          "data.workers.2.worker_signature"])

    def test_the_address_is_an_INDEX_so_two_men_with_one_name_differ(self):
        doc = _preshift()
        doc["data"]["workers"][2]["name"] = "Signed One"
        served = _sigs([doc], "lb_preshift")[0].json()["signatures"]
        self.assertEqual(len(served), 2)

    def test_a_record_with_no_marks_serves_an_EMPTY_answer_not_an_error(self):
        r, _ = _sigs(_docs(), "lb_daily")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["signatures"], {})
        self.assertEqual(r.json()["count"], 0)

    def test_THIS_TEST_CAN_FAIL_a_site_dropped_from_the_table_is_noticed(self):
        """The instrument check. With `data.worker_signature` removed from
        SIGNATURE_IMAGE_SITES the orientation mark is neither flagged nor
        served -- and since both halves read the table, the parity assertion
        above would still PASS. So the failure this proves is the one that
        matters: a dropped site stops the ink moving at all."""
        narrowed = tuple(s for s in server.SIGNATURE_IMAGE_SITES
                         if s != (None, "worker_signature"))
        self.assertEqual(len(narrowed), len(server.SIGNATURE_IMAGE_SITES) - 1)
        with patch.object(server, "SIGNATURE_IMAGE_SITES", narrowed):
            rows = _rows(_get(_docs(), f"?date={DAY}&view=text")[0].json())
            d = rows["lb_orientation"]["data"]
            # The mark is still on the wire: nothing was deferred, so nothing
            # was saved. The whole point of the site being in the table.
            self.assertEqual(d.get("worker_signature"), ACK_SIG)
            self.assertNotIn("worker_signature_deferred", d)
            self.assertEqual(_sigs(_docs(), "lb_orientation")[0].json()["count"], 0)
        # and restored
        rows = _rows(_get(_docs(), f"?date={DAY}&view=text")[0].json())
        self.assertIs(rows["lb_orientation"]["data"]["worker_signature_deferred"],
                      True)

    def test_a_blank_string_mark_is_not_an_image(self):
        """"   " IS NOT SIGNED. A whitespace mark that became a flag would add a
        man to the signature grid off a value that draws nothing."""
        doc = _preshift()
        doc["data"]["workers"][0]["worker_signature"] = "   "
        rows = _rows(_get([doc], f"?date={DAY}&view=text")[0].json())
        w = rows["lb_preshift"]["data"]["workers"][0]
        self.assertEqual(w["worker_signature"], "   ")
        self.assertNotIn("worker_signature_deferred", w)

    def test_a_dict_mark_WITH_bytes_is_deferred_and_served_whole(self):
        """The shape test_preshift_affirmation_record.py files. The object is
        served, not just its `data`, because the affirmation on it is part of
        the mark."""
        mark = {"data": "iVBORw0KGgo=", "affirmed": True}
        doc = _preshift()
        doc["data"]["workers"][0]["worker_signature"] = mark
        rows = _rows(_get([doc], f"?date={DAY}&view=text")[0].json())
        self.assertIs(
            rows["lb_preshift"]["data"]["workers"][0]["worker_signature_deferred"],
            True)
        served = _sigs([doc], "lb_preshift")[0].json()["signatures"]
        self.assertEqual(served["data.workers.0.worker_signature"], mark)

    def test_a_dict_mark_with_NO_bytes_stays_in_the_body(self):
        doc = _preshift()
        doc["data"]["workers"][0]["worker_signature"] = {"affirmed": True}
        rows = _rows(_get([doc], f"?date={DAY}&view=text")[0].json())
        w = rows["lb_preshift"]["data"]["workers"][0]
        self.assertEqual(w["worker_signature"], {"affirmed": True})
        self.assertNotIn("worker_signature_deferred", w)

    def test_the_version_is_the_stamp_the_client_names_its_files_with(self):
        """`updated_at || submitted_at || created_at`, resolved ONCE in
        `_submitted_stamp`. The day row's `cache_version` and this stamp have to
        agree or a device stores a record's ink under a name it will never look
        for."""
        served = _sigs(_docs(), "lb_preshift")[0].json()
        self.assertEqual(served["version"], f"{DAY}T07:05:00+00:00")
        no_updated = dict(_preshift())
        no_updated.pop("updated_at")
        no_updated["submitted_at"] = f"{DAY}T09:30:00+00:00"
        self.assertEqual(_sigs([no_updated], "lb_preshift")[0].json()["version"],
                         f"{DAY}T09:30:00+00:00")


# ═════════════════════════════════════════════════════════════════════════════
# D. NOTHING STORED IS TOUCHED
# ═════════════════════════════════════════════════════════════════════════════

class NothingIsWritten(unittest.TestCase):

    def test_no_stored_byte_of_a_filed_record_changes(self):
        docs = _docs()
        before = copy.deepcopy(docs)
        r, logbooks = _get(docs, f"?date={DAY}&view=text")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(docs, before,
                         "the documents handed in are byte-identical after")
        self.assertEqual(logbooks.writes, [])

    def test_the_signature_read_writes_nothing_either(self):
        docs = _docs()
        before = copy.deepcopy(docs)
        r, logbooks = _sigs(docs, "lb_preshift")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(docs, before)
        self.assertEqual(logbooks.writes, [])

    def test_the_deferral_does_not_reach_into_the_row_it_was_handed(self):
        """COPY-ON-WRITE, ASSERTED DIRECTLY. The handler passes a row whose
        `data` is still the driver's own dict -- `dict(_head)` is shallow -- so
        a deferral that mutated in place would corrupt the document the
        amendment collapse and `_logbook_cache_version` read next."""
        doc = _preshift()
        before = copy.deepcopy(doc)
        out = server._defer_signature_images(doc)
        self.assertEqual(doc, before)
        self.assertIsNot(out, doc)
        self.assertIsNot(out["data"], doc["data"])
        self.assertIsNot(out["data"]["workers"], doc["data"]["workers"])

    def test_a_record_with_no_marks_is_returned_WITHOUT_being_copied(self):
        """The 555 KB of photo thumbnail beside it is why. A deep copy to strip
        a field the record does not have would turn transfer cost into handler
        cost, which is the trade this change is not making."""
        doc = _daily()
        self.assertIs(server._defer_signature_images(doc), doc)

    def test_the_untouched_rows_of_a_list_are_not_copied_either(self):
        doc = _preshift()
        out = server._defer_signature_images(doc)
        # row 1 has no mark: same object. row 0 does: a copy.
        self.assertIs(out["data"]["workers"][1], doc["data"]["workers"][1])
        self.assertIsNot(out["data"]["workers"][0], doc["data"]["workers"][0])


# ═════════════════════════════════════════════════════════════════════════════
# E. THE FILED DOCUMENT IS BYTE-IDENTICAL
# ═════════════════════════════════════════════════════════════════════════════

class TheFiledDocumentIsUntouched(unittest.TestCase):
    """THIS IS A TRANSPORT CHANGE FOR ONE SCREEN. The PDF an inspector
    downloads renders from the STORED record and must not move a byte."""

    def _sheet(self, doc):
        """THROUGH `generate_single_logbook_html`, WHICH IS WHAT THE PDF ROUTE
        CALLS. `filed_sheet.render` freezes the clock, because two renders of
        one record have to be comparable -- without it this comparison would
        differ on a timestamp and say so as a lost document."""
        from tests.filed_sheet import render
        return render(doc)

    def test_the_rendered_sheet_is_identical_before_and_after_a_text_read(self):
        doc = _preshift()
        before = self._sheet(doc)
        r, _ = _get([doc], f"?date={DAY}&view=text")
        self.assertEqual(r.status_code, 200)
        after = self._sheet(doc)
        self.assertEqual(before, after)

    def test_AND_THE_SHEET_ACTUALLY_PRINTS_THE_MARK(self):
        """THE INSTRUMENT CHECK, without which the test above compares two
        blank pages and passes. 291 signature images once vanished from 49
        filed rosters and the word diff saw five unrelated words."""
        html = self._sheet(_preshift())
        self.assertIn(WORKER_SIG[:48], html,
                      "the filed roster does not print the mark, so the "
                      "before/after comparison above proves nothing")

    def test_the_renderers_never_see_a_deferred_key(self):
        """A SOURCE CENSUS, PROSE STRIPPED. `legal_render` renders from stored
        records; the deferral exists only on the wire. A reference to it in
        there would mean the filed document had learned about transport."""
        hits = []
        for path in sorted(_LEGAL_RENDER.rglob("*.py")):
            src = _strip_python(path.read_text(encoding="utf-8"))
            for token in ("_deferred", "_defer_signature_images",
                          "SIGNATURE_IMAGE_SITES", "signature_images"):
                if token in src:
                    hits.append(f"{path.name}: {token}")
        self.assertEqual(hits, [])

    def test_the_deferral_is_called_from_exactly_one_place(self):
        """ONE CALL SITE, AND IT IS THE SUBMITTED HANDLER. Asserting the
        function is pure is not enough -- a second caller is how a transport
        shim ends up on the PDF path."""
        src = _code((_BACKEND / "server.py").read_text(encoding="utf-8"))
        calls = re.findall(r"_defer_signature_images\s*\(", src)
        # one definition, one call
        self.assertEqual(len(calls), 2, f"found {len(calls)} occurrences")
        self.assertIn("_row = _defer_signature_images ( _row )", src)


# ═════════════════════════════════════════════════════════════════════════════
# F. THE ENDPOINT IS REACHABLE AND SCOPED
# ═════════════════════════════════════════════════════════════════════════════

class TheSignatureEndpoint(unittest.TestCase):

    def test_it_is_not_shadowed_by_the_bare_logbook_route(self):
        """`GET /logbooks/{logbook_id}` is registered 9,000 lines EARLIER in
        this file. A path parameter does not span a `/`, so it cannot match --
        asserted rather than reasoned about, because a live route in this repo
        has been shadowed by an earlier registration before."""
        r, _ = _sigs(_docs(), "lb_preshift")
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertEqual(sorted(r.json().keys()),
                         ["count", "logbook_id", "signatures", "version"])

    def test_a_record_in_another_tenant_is_refused(self):
        r, _ = _sigs(_docs(), "lb_preshift", user=OTHER_USER)
        self.assertEqual(r.status_code, 403, r.text[:300])

    def test_a_record_whose_project_is_gone_is_a_404_not_an_open_door(self):
        r, _ = _sigs(_docs(), "lb_preshift", projects=None)
        self.assertEqual(r.status_code, 404, r.text[:300])
        # `Project not found` IS THE SCOPING GATE ANSWERING, not Starlette
        # answering that no such route exists -- which is how every 404 in this
        # class passed on the pre-change tree.
        self.assertEqual(r.json().get("detail"), "Project not found")

    def test_a_record_with_no_project_at_all_is_refused(self):
        """ABSENCE IS NOT AUTHORIZATION -- the double-permissive shape
        `_same_company_or_403` documents. An unowned row must not be readable
        by anyone who knows an id."""
        doc = _preshift()
        doc["project_id"] = ""
        r, _ = _sigs([doc], "lb_preshift")
        self.assertEqual(r.status_code, 404, r.text[:300])
        self.assertEqual(r.json().get("detail"), "Logbook not found")

    def test_an_unknown_record_is_a_404(self):
        r, _ = _sigs(_docs(), "lb_nope")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json().get("detail"), "Logbook not found")

    def test_a_deleted_record_serves_nothing(self):
        doc = _preshift()
        doc["is_deleted"] = True
        r, _ = _sigs([doc], "lb_preshift")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json().get("detail"), "Logbook not found")

    def test_it_requires_a_user_unlike_the_photo_endpoint_next_door(self):
        """`get_logbook_activity_photo` is deliberately OPEN, because the people
        reading an emailed daily report have no login. These are named workers'
        signatures and the distinction is not a style point."""
        src = _code((_BACKEND / "server.py").read_text(encoding="utf-8"))
        m = re.search(
            r'@ api_router \. get \( "/logbooks/\{logbook_id\}/signature-images" \)'
            r' async def get_logbook_signature_images \((.*?)\) :',
            src)
        self.assertIsNotNone(m, "the route declaration has moved or changed")
        self.assertIn("Depends ( get_current_user )", m.group(1))
        self.assertIn("_assert_project_access", src)


# ═════════════════════════════════════════════════════════════════════════════
# G. THE CLIENT READS THE FLAG THE SERVER WRITES
# ═════════════════════════════════════════════════════════════════════════════

class TheTwoHalvesAgree(unittest.TestCase):
    """Two files, one protocol. Each assertion names the thing that breaks if
    they drift, because "the suffix changed" is not a failure anybody reads."""

    def test_the_suffix_is_the_same_string_on_both_sides(self):
        src = _strip_js_comments(_DEFERRAL_JS.read_text(encoding="utf-8"))
        m = re.search(r"SIG_DEFERRED_SUFFIX\s*=\s*'([^']+)'", src)
        self.assertIsNotNone(m, "SIG_DEFERRED_SUFFIX is no longer declared")
        self.assertEqual(m.group(1), server.SIGNATURE_DEFERRED_SUFFIX)

    def test_the_client_asks_for_the_view_and_checks_the_echo(self):
        src = _strip_js_comments(_HISTORY_JS.read_text(encoding="utf-8"))
        self.assertIn("view=text", src,
                      "the client no longer asks for the view this serves")
        self.assertIn("body.view === 'text'", src,
                      "the client no longer checks that the server honoured "
                      "it -- an old server ignores an unknown query param and "
                      "serves whole documents")

    def test_the_client_asks_the_endpoint_this_file_serves(self):
        src = _strip_js_comments(_HISTORY_JS.read_text(encoding="utf-8"))
        self.assertIn("/signature-images", src)

    def test_every_site_in_the_table_is_a_site_the_client_walks(self):
        """DERIVED FROM SIG_FIELDS' OWN SOURCE, not from a list retyped here.
        A site the server defers and the client does not walk is a mark that
        leaves the body and is never asked for again."""
        src = _strip_js_comments(_DEFERRAL_JS.read_text(encoding="utf-8"))
        m = re.search(r"SIG_FIELDS\s*=\s*\{(.*?)\n\};", src, re.S)
        self.assertIsNotNone(m, "SIG_FIELDS is no longer an object literal")
        client_fields = set(re.findall(r"'([a-z_]+)'", m.group(1)))
        server_fields = {field for _list, field in server.SIGNATURE_IMAGE_SITES}
        self.assertTrue(
            server_fields <= client_fields,
            f"the server defers {sorted(server_fields - client_fields)} and the "
            f"client never asks for it")

    def test_no_renderer_on_the_screen_still_tests_the_field_directly(self):
        """THE CENSUS THAT KEEPS THE TRAP SHUT. Every signed-ness test on the
        site screen must go through `signatureMark`; one that reads
        `w.worker_signature` itself is the UNSIGNED list telling an inspector
        that a man who signed did not.

        THE GRID AND THE SPLICE ARE THE TWO LEGITIMATE READS of the raw value:
        `mark.value` after `signatureMark` has answered, and the orientation
        block's own two-state fallthrough, which only runs on a record
        `signatureMark` reported neither way."""
        src = _strip_js_comments(_SCREEN_JSX.read_text(encoding="utf-8"))
        bad = []
        for m in re.finditer(r"(?:\w+)\.(worker_signature|signature)\b(?!_)", src):
            line = src[:m.start()].count("\n") + 1
            frag = src[max(0, m.start() - 80):m.end() + 10]
            # `data.worker_signature` inside the orientation fallthrough is the
            # branch `signatureMark` guards, and `log.cp_signature` is not a
            # roster mark at all.
            if "data.worker_signature" in frag or "cp_signature" in frag:
                continue
            bad.append(f"line {line}: {m.group(0)}")
        self.assertEqual(
            bad, [],
            "a signed-ness test on the site screen reads the mark directly "
            "instead of through signatureMark(): " + "; ".join(bad))

    def test_the_screen_imports_the_protocol_rather_than_restating_it(self):
        src = _strip_js_comments(_SCREEN_JSX.read_text(encoding="utf-8"))
        self.assertIn("signatureMark", src)
        self.assertIn("SIG_FIELDS", src)
        self.assertNotIn("'_deferred'", src,
                         "the screen spells the suffix itself; import it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
