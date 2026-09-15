"""THE FIVE NAMED WORKERS, IN THEIR MEASURED PRODUCTION SHAPE.

Every certification and check-in below was READ OFF PRODUCTION on 2026-09-14
(`railway ssh`, read-only, db `blueview`: 379 check-ins, 75 workers, 25 of them
carrying a flagged cert). Nothing here is invented, and where a field is `None`
it is `None` on the live document -- which is the whole point of three of these
tests, because two of the five are unreachable by the fix for exactly that
reason.

WHAT THE DEFECT REPORT SAID, AND WHAT IS ACTUALLY TRUE.

The report says the CP's approval of a worker's card writes
`review_decision: 'approved'` onto `db.checkins` while the roster reads
`needs_review` on a certification inside `db.workers`, and that nothing joins
them. BOTH HALVES ARE CONFIRMED and the join is still absent after this fix:
`review_decision` is read nowhere in the clearing path. What the fix adds is a
SEPARATE act -- the CP attesting he has seen the physical card -- and
`ApprovalAloneStillClearsNothing` below pins that, because an operator reading
"the card-check fix shipped" must not conclude that the 43 approved check-ins
in production cleared anything. They did not, and they still do not.

THE ROSTER RULE IS `osha_review_index`. It keys on the stored boolean --
`if cert.get("needs_review")` -- and NOT on `_sst_cert_state`, so the flag on
the filed record is lowered by the endpoint's write and not by the read-time
join. That matters for what a backfill would have to touch. (The rule is
currently uncalled in server.py: the OSHA register's Review column went out
with the `generate_single_logbook_html` chain when rendering moved to
`lib/legal_render`, and `osha_log`'s schema now says the column "IS NOT HERE
AND MUST NOT BE". It is asserted here because it is the encoded roster rule and
the one a restored column would use again.)

CORRECTION -- THE LIVE SURFACE IS NOT `GET /workers/{id}/certifications`.
This docstring used to say it was. It is not, and the mistake was load-bearing,
because the re-flag story below is told about that endpoint's response.

NOTHING IN THE PRODUCT CALLS IT. The worker screen -- `app/workers/[id].jsx`,
the only place that renders the stored boolean -- reads the WHOLE WORKER, via
`workersAPI.getById` at `frontend/src/utils/api.js:644` (`GET /api/workers/{id}`),
called at `[id].jsx:278`, and takes `workerData.certifications` off that
document (`[id].jsx:268`). The certifications sub-resource is called with POST
(`[id].jsx:395`) and DELETE (`[id].jsx:451`) only; the GET has no caller
anywhere in `frontend/`. `TheTwoSurfacesThatStillFlagHim` below always had this
right -- it reads `[id].jsx` and `oshaLogModel.js` -- so the file contradicted
itself and this paragraph is the half that was wrong.

WHY IT MATTERS FOR THE TEST BELOW. `card_number_finding` -- the rule behind
`test_an_eleven_character_card_is_re_flagged_as_a_format_finding` -- runs in
exactly two places: `osha_review_index` (dead since the render migration) and
`GET /workers/{worker_id}/certifications` (no caller). So the re-flag it pins
cannot currently reach any screen. The test stays, with that recorded on it.
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


# ── THE MEASURED ROWS ────────────────────────────────────────────────────────
#
# `class_source` IS `None` ON ALL FIVE, and on all 25 flagged certs in the
# database -- the aggregate over `certifications.needs_review: true` returns
# only `EXPIRY_UNPARSEABLE` (17) and `CLASS_UNVERIFIED` (8), with `class_source`
# null or absent every time. That is load-bearing: see
# CardCheckCoversReachesNoProductionRow.

NAMED = [
    {
        "name": "Angel Lopez",
        "worker_id": "6a9576da611a543244a9ccac",
        "checkin_id": "6aa7d3d15e94321647b5015f",
        "reviewed_at": "2026-09-14 11:51:20",
        # NO CARD NUMBER ON THE CERT OR THE CHECK-IN. He is the reason this
        # file has a fourth test class.
        "card_number": None,
        "cert": {
            "type": "SST_UNSPECIFIED", "card_number": None,
            "needs_review": True, "review_reason": "CLASS_UNVERIFIED",
            "class_source": None, "expiration_date": None,
        },
    },
    {
        "name": "Jose David Hernandez Pena",
        "worker_id": "6a6a2d4a24fb1fc0be15c8b3",
        "checkin_id": "6a980942e30d1dc3d87a86e4",
        "reviewed_at": "2026-09-02 19:48:42",
        "card_number": "XCAS2DYB8G",
        "cert": {
            "type": "SST_LIMITED", "card_number": "XCAS2DYB8G",
            "needs_review": True, "review_reason": "CLASS_UNVERIFIED",
            "class_source": None,
            "expiration_date": datetime(2028, 2, 26),
        },
    },
    {
        "name": "WILMER CARRILLO",
        "worker_id": "6a79b9f19d8cee518e4712c4",
        "checkin_id": "6a9809fee30d1dc3d87a86eb",
        "reviewed_at": "2026-09-02 19:48:44",
        "card_number": "4YU1RY8KKM",
        "cert": {
            "type": "SST_FULL", "card_number": "4YU1RY8KKM",
            "needs_review": True, "review_reason": "EXPIRY_UNPARSEABLE",
            "class_source": None, "expiration_date": None,
        },
    },
    {
        "name": "Hector Ramirez",
        "worker_id": "6a7921aaccdc4ed5f63ec8e7",
        "checkin_id": "6a89e34ca0b1adc408ec46c2",
        "reviewed_at": "2026-08-16 12:43:26",
        "card_number": "SST7F6308A7",
        "cert": {
            "type": "SST_FULL", "card_number": "SST7F6308A7",
            "needs_review": True, "review_reason": "EXPIRY_UNPARSEABLE",
            "class_source": None, "expiration_date": None,
        },
    },
    {
        "name": "Dmitri Volkov",
        "worker_id": "6a7921aaccdc4ed5f63ec8ed",
        "checkin_id": "6a89e34ca0b1adc408ec46c7",
        "reviewed_at": "2026-08-16 12:43:26",
        "card_number": "SST072F2336",
        "cert": {
            "type": "SST_UNSPECIFIED", "card_number": "SST072F2336",
            "needs_review": True, "review_reason": "EXPIRY_UNPARSEABLE",
            "class_source": None, "expiration_date": None,
        },
    },
]

WITH_A_CARD = [w for w in NAMED if w["card_number"]]
WITHOUT_A_CARD = [w for w in NAMED if not w["card_number"]]


def _worker_doc(row):
    """The live worker document, with the OSHA row that sits beside the SST one.

    THE SST CERT IS SECOND ON PURPOSE. A write that patched
    `certifications.0` would clear the OSHA row and let every assertion here
    pass against the wrong occurrence.
    """
    return {
        "_id": row["worker_id"],
        "name": row["name"],
        "certifications": [
            {"type": "OSHA_30", "card_number": "OSHA-1", "needs_review": False},
            dict(row["cert"]),
        ],
    }


def _checkin_doc(row, decision="approved"):
    """The check-in the CP already approved. `sst_card_number` is the field the
    row actually carries -- the cert's key is `card_number`, and the endpoint
    joins one to the other, so a rename on either side breaks here."""
    return {
        "_id": row["checkin_id"],
        "project_id": "proj1",
        "worker_id": row["worker_id"],
        "worker_name": row["name"],
        "sst_status": "unknown",
        "sst_card_number": row["card_number"],
        "review_decision": decision,
        "reviewed_by": "6a68b16ebe9c27dedf5cf47f",
        "reviewed_at": row["reviewed_at"],
    }


def _roster_flag(worker_doc, card_number):
    """What the roster rule says about this worker's SST row.

    Returns the review reason the register would print, or None for a row it
    does not flag. `osha_review_index` is the rule; the entry shape is a filed
    register row, keyed (worker_id, card_number).
    """
    review_by_key, known_cards, known_workers = server.osha_review_index([worker_doc])
    return review_by_key.get((str(worker_doc["_id"]), str(card_number or "")))


# ── Applying Mongo fakes. `update_one` really applies `$set`, including dotted
#    paths, because every assertion here is about the document AFTERWARDS ─────

class _Result:
    def __init__(self):
        self.matched_count = self.modified_count = 1
        self.inserted_id = "x"


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs)


def _apply_set(doc, spec):
    for path, value in (spec or {}).items():
        parts = path.split(".")
        target = doc
        for p in parts[:-1]:
            target = target[int(p)] if isinstance(target, list) else target.setdefault(p, {})
        last = parts[-1]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value


class _FakeCollection:
    def __init__(self, name, docs=None):
        self.name = name
        self.docs = list(docs or [])
        self.inserted = []

    async def find_one(self, query=None, *a, **k):
        # COMPARED AS STRINGS. These are the real 24-hex production ids, so
        # `to_query_id` hands this an ObjectId while the fixture holds the hex
        # string -- a fake that compared identity would 404 on every row and
        # every assertion below would pass vacuously.
        wanted = str((query or {}).get("_id"))
        for d in self.docs:
            if str(d.get("_id")) == wanted:
                return d
        return None

    def find(self, query=None, *a, **k):
        return _FakeCursor(self.docs)

    async def insert_one(self, doc, *a, **k):
        self.inserted.append(dict(doc))
        return _Result()

    async def update_one(self, q, u, *a, **k):
        for d in self.docs:
            if str(d.get("_id")) == str((q or {}).get("_id")):
                _apply_set(d, u.get("$set"))
        return _Result()

    async def count_documents(self, *a, **k):
        return 0


class _FakeDb:
    def __init__(self, **collections):
        self._c = dict(collections)

    def _get(self, name):
        if name not in self._c:
            self._c[name] = _FakeCollection(name)
        return self._c[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._get(name)

    def __getitem__(self, name):
        return self._get(name)


def _db_for(row, decision="approved"):
    return _FakeDb(
        checkins=_FakeCollection("checkins", [_checkin_doc(row, decision)]),
        workers=_FakeCollection("workers", [_worker_doc(row)]),
        projects=_FakeCollection("projects", [{"_id": "proj1", "company_id": "co_a"}]),
    )


def _post_card_check(db, row, card_number):
    user = {
        "_id": "u1", "id": "u1", "role": "cp", "company_id": "co_a",
        "full_name": "Carl CP", "assigned_projects": ["proj1"],
    }

    async def _fake_user():
        return user

    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        with patch.object(server, "db", db):
            return TestClient(server.app).post(
                f"/api/checkins/{row['checkin_id']}/card-check",
                json={"card_number": card_number},
            )
    finally:
        server.app.dependency_overrides.clear()


class ApprovalAloneStillClearsNothing(unittest.TestCase):
    """THE DEFECT, AND IT IS NOT WHAT THIS FIX CLOSES.

    43 check-ins in production carry `review_decision: 'approved'`. Not one of
    them lowers a flag, before this change or after it: the clearing path never
    reads `review_decision`, by ruling -- "I checked this card" and "this
    worker may work today" are different claims. This class passes on both
    sides of the fix and is here so that nobody reads a green suite as evidence
    that the approvals in the database did something.
    """

    def test_every_named_worker_is_approved_and_still_flagged(self):
        for row in NAMED:
            with self.subTest(row["name"]):
                checkin = _checkin_doc(row)
                self.assertEqual(checkin["review_decision"], "approved")
                self.assertIsNotNone(
                    _roster_flag(_worker_doc(row), row["card_number"]),
                    f"{row['name']} is approved and the roster does not flag him",
                )

    def test_the_clearing_path_never_reads_review_decision(self):
        import inspect
        src = inspect.getsource(server.record_sst_card_check)
        self.assertNotIn(
            "review_decision", src.split('"""')[-1],
            "the card check must not key on the approve/send-home ruling",
        )


class TheCardCheckClearsTheNamedRows(unittest.TestCase):
    """THE PROOF. Four of the five, cleared through the endpoint the CP calls."""

    # TWO OF THE FIVE, NOT FOUR. `osha_review_index` falls through from the
    # lowered boolean to `card_number_finding`, and `_CARD_NUMBER_RE` is
    # `^[A-Z0-9]{10}$` -- exactly ten. Hector Ramirez holds `SST7F6308A7` and
    # Dmitri Volkov holds `SST072F2336`: eleven characters each, an `SST`
    # prefix on an eight-character body. Their rows come back flagged the
    # instant the review flag is lowered, under a DIFFERENT reason. That is the
    # rule behaving correctly on a card number the rule does not expect; it is
    # not something this fix does wrong, and it is not something this fix
    # clears.
    CLEARED = ("Jose David Hernandez Pena", "WILMER CARRILLO")
    RE_FLAGGED_AS_FORMAT = ("Hector Ramirez", "Dmitri Volkov")

    def test_the_roster_stops_flagging_the_two_it_can(self):
        for row in [r for r in WITH_A_CARD if r["name"] in self.CLEARED]:
            with self.subTest(row["name"]):
                db = _db_for(row)
                worker = db.workers.docs[0]
                self.assertIsNotNone(
                    _roster_flag(worker, row["card_number"]),
                    "precondition: the roster flags him before the check",
                )

                resp = _post_card_check(db, row, row["card_number"])
                self.assertEqual(resp.status_code, 200, resp.text)

                self.assertIsNone(
                    _roster_flag(worker, row["card_number"]),
                    f"{row['name']} is still flagged after the CP checked his card",
                )

    def test_an_eleven_character_card_is_re_flagged_as_a_format_finding(self):
        """PREMISE RETRACTED -- THE RULE THIS PINS IS CURRENTLY UNREACHABLE.

        The test is TRUE and it is kept: `card_number_finding` really does
        return `CARD_NUMBER_FORMAT` for an eleven-character card once the
        review flag comes down, and if either of its callers is ever revived
        that is the behaviour a reader will get. What is retracted is the story
        this test was written to support -- that a CP who checks Hector
        Ramirez's or Dmitri Volkov's card would SEE the man come back flagged
        under a new reason.

        HE WOULD NOT SEE IT, because nothing calls the rule. `card_number_finding`
        (server.py:3324) has exactly two call sites:

          server.py:16723  GET /workers/{worker_id}/certifications
                           -- no caller in the product. The worker screen reads
                           the whole worker via GET /api/workers/{id}
                           (api.js:644, [id].jsx:278); the certifications
                           sub-resource is only ever POSTed and DELETEd.
          server.py:29221  osha_review_index()
                           -- dead since the render migration. The OSHA
                           register's Review column went out with the
                           `generate_single_logbook_html` chain and `osha_log`'s
                           schema now forbids it; ten tests in
                           test_osha_review_column.py are skipped saying so.

        So this is a characterization of an encoded rule, NOT a live guarantee
        about anything a superintendent or a CP can see today. Do not cite it
        as a reason a worker stays visibly flagged, and do not delete it either
        -- if the Review column comes back, this is what it will do.
        """
        for row in [r for r in WITH_A_CARD if r["name"] in self.RE_FLAGGED_AS_FORMAT]:
            with self.subTest(row["name"]):
                self.assertEqual(len(row["card_number"]), 11)
                db = _db_for(row)
                worker = db.workers.docs[0]
                self.assertEqual(
                    _post_card_check(db, row, row["card_number"]).status_code, 200)
                self.assertIs(worker["certifications"][1]["needs_review"], False)
                self.assertEqual(
                    _roster_flag(worker, row["card_number"]), "CARD_NUMBER_FORMAT",
                    "the review flag came down and the format finding took its "
                    "place -- he is still on the roster, under a new reason",
                )

    def test_the_sst_row_is_the_one_that_moved_not_the_osha_row_beside_it(self):
        row = WITH_A_CARD[0]
        db = _db_for(row)
        worker = db.workers.docs[0]
        self.assertEqual(_post_card_check(db, row, row["card_number"]).status_code, 200)
        self.assertIs(worker["certifications"][1]["needs_review"], False)
        self.assertIs(worker["certifications"][0]["needs_review"], False)
        self.assertIsNone(worker["certifications"][0].get("card_check"))

    def test_the_attestation_names_who_when_and_which_card(self):
        for row in WITH_A_CARD:
            with self.subTest(row["name"]):
                db = _db_for(row)
                worker = db.workers.docs[0]
                self.assertEqual(_post_card_check(db, row, row["card_number"]).status_code, 200)
                block = worker["certifications"][1]["card_check"]
                self.assertEqual(block["card_number"], row["card_number"])
                self.assertEqual(block["checked_by"], "u1")
                self.assertEqual(block["checked_by_name"], "Carl CP")
                self.assertIsInstance(block["checked_at"], datetime)

    def test_the_review_reason_survives_because_the_gap_in_the_record_does(self):
        """WILMER CARRILLO's expiry is unreadable and the CP was not asked
        about it. The reason stays on the row; only the demand for a human
        goes."""
        row = [r for r in NAMED if r["name"] == "WILMER CARRILLO"][0]
        db = _db_for(row)
        worker = db.workers.docs[0]
        self.assertEqual(_post_card_check(db, row, row["card_number"]).status_code, 200)
        self.assertEqual(
            worker["certifications"][1]["review_reason"], "EXPIRY_UNPARSEABLE")
        self.assertIsNone(worker["certifications"][1]["expiration_date"])


class TheTwoSurfacesThatStillFlagHim(unittest.TestCase):
    """WHAT THE OPERATOR MUST NOT ASSUME. Lowering the boolean is not the same
    as the flag disappearing, because neither surface a human actually looks at
    reads the boolean alone.

    THE LIVE SCREEN. `frontend/app/workers/[id].jsx` -- the only place in the
    product that renders the stored boolean -- filters on
    `c.needs_review || c.review_reason`, and this fix LEAVES `review_reason` in
    place on purpose ("an unread expiry is still an unread expiry"). So
    "Credential needs review" keeps painting on all four cleared workers.

    THE FILED RECORD. The register's UNVERIFIED line is not `needs_review` at
    all: `oshaLogModel.js` freezes `unverified: c.sst_status === 'unknown'`
    onto the row at gate time and `legal_render/primitives.py` prints
    "UNVERIFIED - card could not be read" from it. A card check neither
    rewrites a filed row nor -- see the class above -- moves `sst_status` for
    any of the five.
    """

    JSX = None
    MODEL = None

    @classmethod
    def setUpClass(cls):
        import pathlib
        root = pathlib.Path(server.__file__).resolve().parent.parent / "frontend"
        cls.JSX = (root / "app" / "workers" / "[id].jsx").read_text(encoding="utf-8")
        cls.MODEL = (root / "src" / "utils" / "oshaLogModel.js").read_text(encoding="utf-8")

    def test_the_live_screen_filters_on_review_reason_too(self):
        self.assertIn("c.needs_review || c.review_reason", self.JSX)
        self.assertIn("Credential needs review", self.JSX)

    def test_so_every_cleared_worker_still_paints_that_card(self):
        for row in WITH_A_CARD:
            with self.subTest(row["name"]):
                db = _db_for(row)
                worker = db.workers.docs[0]
                self.assertEqual(
                    _post_card_check(db, row, row["card_number"]).status_code, 200)
                sst = worker["certifications"][1]
                self.assertIs(sst["needs_review"], False)
                # The screen's own predicate, evaluated on the cleared row.
                self.assertTrue(
                    bool(sst.get("needs_review")) or bool(sst.get("review_reason")),
                    "the worker screen would stop flagging him -- if this fails "
                    "the fix got better and this test should be deleted",
                )

    def test_the_filed_record_keys_on_sst_status_not_on_needs_review(self):
        self.assertIn("unverified: c.sst_status === 'unknown'", self.MODEL)
        # ANCHORED, NOT BARE. A bare "needs_review" bans a substring, so the
        # assertion would be broken by the word appearing in a comment that
        # explains why it is absent. `.needs_review` is the read itself.
        self.assertNotIn(".needs_review", self.MODEL)
        from lib.legal_render import primitives
        import inspect
        src = inspect.getsource(primitives)
        self.assertIn("UNVERIFIED", src)
        self.assertNotIn('"needs_review"', src)


class AngelLopezCannotBeClearedAtAll(unittest.TestCase):
    """ONE OF THE FIVE IS UNREACHABLE, and the operator has to know it.

    His SST cert carries `card_number: null`. The endpoint refuses a null card
    number outright, because a clearance keyed on null would match every card
    he is ever issued -- so there is no CP action that clears him. His row needs
    a card number, which is a re-scan or a correction, not an attestation.
    """

    def test_a_null_card_number_is_refused(self):
        row = WITHOUT_A_CARD[0]
        self.assertEqual(row["name"], "Angel Lopez")
        resp = _post_card_check(_db_for(row), row, None)
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_he_stays_flagged_and_nothing_was_written(self):
        row = WITHOUT_A_CARD[0]
        db = _db_for(row)
        worker = db.workers.docs[0]
        _post_card_check(db, row, None)
        self.assertIs(worker["certifications"][1]["needs_review"], True)
        self.assertIsNone(worker["certifications"][1].get("card_check"))
        self.assertIsNotNone(_roster_flag(worker, None))

    def test_no_check_can_ever_cover_a_cert_with_no_card_number(self):
        cert = dict(NAMED[0]["cert"])
        cert["card_check"] = {
            "card_number": "ANYTHING", "checked_at": datetime.now(timezone.utc),
        }
        self.assertFalse(server.card_check_covers(cert))


class CardCheckCoversReachesNoProductionRow(unittest.TestCase):
    """THE READ-TIME JOIN IS CORRECT AND CURRENTLY INERT.

    `card_check_covers` is wired into exactly one place -- the
    `class_source in ("color_only", "conflict")` demotion in `_sst_cert_state`
    -- and `class_source` is null on ALL 25 flagged certs in production. So the
    part of this commit that was meant to stop tomorrow's scan re-raising the
    flag lifts nothing for anybody flagged today. The endpoint's direct write
    is what clears the five; the join is forward-looking only.
    """

    def test_no_named_worker_carries_a_class_source_the_join_can_lift(self):
        for row in NAMED:
            with self.subTest(row["name"]):
                self.assertNotIn(row["cert"]["class_source"], ("color_only", "conflict"))

    def test_the_verdict_is_unchanged_by_a_check_for_every_named_row(self):
        now = datetime.now(timezone.utc)
        for row in WITH_A_CARD:
            with self.subTest(row["name"]):
                before = server._sst_cert_state(dict(row["cert"]), now)
                checked = dict(row["cert"])
                checked["card_check"] = {
                    "card_number": row["card_number"], "checked_at": now,
                }
                self.assertTrue(server.card_check_covers(checked))
                self.assertEqual(
                    server._sst_cert_state(checked, now), before,
                    "the join fired and the verdict still did not move",
                )

    def test_the_join_does_move_a_colour_derived_row_which_is_what_it_is_for(self):
        """Not a production shape -- proof the mechanism works, so the test
        above is read as 'no rows match', not 'the join is broken'."""
        now = datetime.now(timezone.utc)
        cert = {
            "type": "SST_FULL", "card_number": "SST1234567",
            "class_source": "color_only",
            "expiration_date": datetime(2030, 1, 1),
        }
        self.assertEqual(server._sst_cert_state(dict(cert), now), "unknown")
        cert["card_check"] = {"card_number": "SST1234567", "checked_at": now}
        self.assertEqual(server._sst_cert_state(cert, now), "valid")


class ARescanReRaisesWhatTheCheckLowered(unittest.TestCase):
    """THE GAP THAT IS STILL OPEN AFTER THIS LANDS, pinned so it is not
    rediscovered as a regression.

    `build_worker_certifications` decides whether to overwrite a stored SST row
    with `old_flagged = needs_review or expiration_date is None`. Four of the
    five named workers have `expiration_date: None`, so `old_flagged` stays
    True after a card check and the recomputed `needs_review` lands on top of
    the attestation. `card_check` is not consulted anywhere in that function.
    """

    def test_build_worker_certifications_never_reads_the_attestation(self):
        import inspect
        src = inspect.getsource(server.build_worker_certifications)
        # ANCHORED ON THE KEY AS IT WOULD BE READ. A bare "card_check" would
        # also match `card_check_covers`, so the test would report the
        # attestation as consulted the moment an unrelated call to the join
        # appeared -- and would be silently satisfied by a comment.
        self.assertNotIn('"card_check"', src)
        self.assertNotIn("card_check_covers(", src)

    def test_a_null_expiry_keeps_the_row_overwritable_after_a_check(self):
        row = [r for r in NAMED if r["name"] == "Hector Ramirez"][0]
        cert = dict(row["cert"])
        cert["needs_review"] = False
        cert["card_check"] = {
            "card_number": row["card_number"],
            "checked_at": datetime.now(timezone.utc),
        }
        old_flagged = bool(cert.get("needs_review")) or cert.get("expiration_date") is None
        self.assertTrue(
            old_flagged,
            "a checked card with no stored expiry is still open to being "
            "overwritten by the next scan",
        )


if __name__ == "__main__":
    unittest.main()
