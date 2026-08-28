"""Programming a chip is the ONLY thing that clears the provisional flag.

A provisional gate was minted in the field by a CP because the project had
none. It is QR-only - no chip anywhere carries the id - and a printed QR is
permanently shareable. The flag says "no chip exists", so the only honest way
to clear it is for a chip to start existing.

WHAT IS ASSERTED, and why each one is a way this could go quietly wrong:

  * the flip is ADMIN-ONLY - a CP clearing the flag on the gate they minted
    makes it self-certifying and it stops being evidence of anything;
  * a NON-provisional row is a 409, never a silent 200 - a client bug (wrong
    tag_id, stale list) must not look like a completed programming run;
  * attribution is WRITTEN AND KEPT - "minted in the field, later given a
    chip" is worth reading a year from now;
  * NOTHING IS RE-REGISTERED - same tag_id, same project, so every check-in
    already recorded against this gate stays attached to it;
  * THERE IS NO DISMISS ENDPOINT, asserted at the source, because the whole
    value of the flag is that it cannot be cleared by clicking.

Run:  pytest tests/test_clear_provisional_checkin_point.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402

PROJ = "projA"
TAG = "qr-3f9a2b7c1d4e"

ADMIN = {"_id": "ad1", "id": "ad1", "role": "admin", "company_id": "companyA",
         "account_status": "approved", "assigned_projects": []}
CP = {"_id": "cp1", "id": "cp1", "role": "cp", "company_id": "companyA",
      "account_status": "approved", "assigned_projects": [PROJ]}


class _Coll:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    @staticmethod
    def _match(doc, query):
        for k, v in (query or {}).items():
            if isinstance(v, dict):
                if "$ne" in v and doc.get(k) == v["$ne"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    async def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if self._match(d, query):
                return dict(d)
        return None

    async def update_one(self, flt, update, *a, **k):
        for d in self.docs:
            if self._match(d, flt):
                d.update(update.get("$set") or {})
        return None


class _Db:
    def __init__(self, **colls):
        self._c = dict(colls)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _Coll())

    def __getitem__(self, name):
        return getattr(self, name)


def _projects():
    return _Coll([{"_id": PROJ, "name": "A", "company_id": "companyA", "nfc_tags": []}])


def _tag(**over):
    row = {"_id": "t1", "tag_id": TAG, "project_id": PROJ, "status": "active",
           "is_deleted": False, "provisional": True, "created_by_role": "cp",
           "created_by": "cp1", "location_description": "Main Gate"}
    row.update(over)
    return row


def _post(user, tags):
    async def _fake_user():
        return user

    db = _Db(projects=_projects(), nfc_tags=tags)
    orig = (server.db, server.get_user_company_id, server.to_query_id)
    server.db = db
    server.get_user_company_id = lambda u: u.get("company_id")
    server.to_query_id = lambda v: v
    server.app.dependency_overrides[server.get_current_user] = _fake_user
    try:
        return TestClient(server.app).post(
            f"/api/projects/{PROJ}/checkin-points/{TAG}/programmed"
        )
    finally:
        server.db, server.get_user_company_id, server.to_query_id = orig
        server.app.dependency_overrides.clear()


class TestTheFlagClears(unittest.TestCase):

    def test_an_admin_clears_it(self):
        tags = _Coll([_tag()])
        res = _post(ADMIN, tags)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIs(tags.docs[0]["provisional"], False)
        self.assertIs(res.json()["provisional"], False)

    def test_attribution_is_written_and_kept(self):
        # "Minted in the field and later given a chip" must stay readable a
        # year from now; tidying the fields away destroys that.
        tags = _Coll([_tag()])
        _post(ADMIN, tags)
        row = tags.docs[0]
        self.assertEqual(row["provisional_cleared_by"], "ad1")
        self.assertIsNotNone(row.get("provisional_cleared_at"))
        self.assertEqual(row["created_by_role"], "cp",
                         "the origin of the gate must survive the clear")

    def test_nothing_is_re_registered(self):
        # The chip is programmed with THIS id, so the row is untouched apart
        # from the flag. A new tag_id here would strand every check-in already
        # recorded against this gate.
        tags = _Coll([_tag()])
        _post(ADMIN, tags)
        row = tags.docs[0]
        self.assertEqual(row["tag_id"], TAG)
        self.assertEqual(row["project_id"], PROJ)
        self.assertEqual(row["status"], "active")
        self.assertIs(row["is_deleted"], False)


class TestItIsNotSelfCertifying(unittest.TestCase):

    def test_a_cp_cannot_clear_the_flag(self):
        # The marker exists FOR admins. The CP who minted the gate clearing
        # their own flag makes it evidence of nothing.
        tags = _Coll([_tag()])
        res = _post(CP, tags)
        self.assertEqual(res.status_code, 403, res.text)
        self.assertIs(tags.docs[0]["provisional"], True)


class TestNothingToClearIsNotSuccess(unittest.TestCase):

    def test_a_non_provisional_row_is_409(self):
        # A silent 200 would let a client bug - wrong tag_id, stale list - look
        # exactly like a completed programming run, and the banner would
        # vanish for a gate nobody touched.
        tags = _Coll([_tag(provisional=False)])
        res = _post(ADMIN, tags)
        self.assertEqual(res.status_code, 409, res.text)

    def test_an_absent_row_is_404(self):
        res = _post(ADMIN, _Coll([]))
        self.assertEqual(res.status_code, 404, res.text)

    def test_a_deleted_row_is_404(self):
        res = _post(ADMIN, _Coll([_tag(is_deleted=True)]))
        self.assertEqual(res.status_code, 404, res.text)


class TestThereIsNoDismissPath(unittest.TestCase):
    """Asserted at the source, because the value of the flag IS that it cannot
    be cleared by clicking. If dismissal is the easy path it becomes the only
    path, and the flag stops meaning "no chip exists" and starts meaning
    "nobody clicked X" - the same as having no flag, with the added cost that
    everyone believes there is one.
    """

    def test_no_dismiss_endpoint_exists(self):
        src = code_of("server.py")
        for shape in ("/dismiss", "dismiss_provisional", "provisional_dismissed"):
            self.assertNotIn(
                shape, src,
                f"a dismissal path ({shape}) was declined on the grounds in "
                "mark_checkin_point_programmed; if it is ever revisited it must "
                "record who and when and read as acknowledged, not resolved",
            )

    def test_the_grounds_are_recorded_where_one_would_be_added(self):
        # The DECISION alone would read as arbitrary to the next person and get
        # reversed; the reasoning is what survives.
        raw = code_of("server.py", raw=True)
        self.assertIn("NO DISMISS ENDPOINT", raw)
        self.assertIn("nobody clicked X", raw)


class TestTheClientWritesTheChipFirst(unittest.TestCase):
    """Flag second, and only after a successful write.

    Flag-first then a failed write leaves a record claiming a physical tag that
    does not exist - precisely the silent state the flag exists to prevent.
    Write-first then a failed flip is merely over-cautious: the banner stays and
    re-writing the same URL to the same chip is idempotent.
    """

    def test_the_admin_screen_writes_before_it_flips(self):
        src = code_of("frontend/app/project/[id].jsx")
        write_at = src.index("NfcHelper.writeNfcTag(projectId, tagId)")
        flip_at = src.index("markCheckinPointProgrammed(projectId, tagId)")
        self.assertLess(write_at, flip_at,
                        "the chip must be written before the flag is flipped")

    def test_the_flip_is_gated_on_the_write_succeeding(self):
        src = code_of("frontend/app/project/[id].jsx")
        window = src[src.index("const handleProgramProvisionalTag"):]
        window = window[:window.index("markCheckinPointProgrammed")]
        self.assertIn("if (!result.success)", window)
        self.assertIn("return;", window)

    def test_it_programs_an_explicit_id_not_the_chips_uid(self):
        # registerNfcTag READS the chip's UID and registers THAT, which would
        # leave the provisional gate untouched and create a second one beside
        # it, with the existing check-ins stranded on the first.
        src = code_of("frontend/app/project/[id].jsx")
        window = src[src.index("const handleProgramProvisionalTag"):]
        window = window[:window.index("const handleScanNfcTag")]
        self.assertIn("writeNfcTag(projectId, tagId)", window)
        self.assertNotIn("registerNfcTag(", window)


if __name__ == "__main__":
    unittest.main()
