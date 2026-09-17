"""The Site Manager's renewal digest is HIS projects, in an email of its own.

── THE RULE, IN THE OPERATOR'S WORDS ───────────────────────────────────────

"No PM may ever receive an email naming a project he cannot open."

That is a rule about the BODY, not about the address list, and it is why the
obvious implementation is not available. `renewal_digest_daily_cron` builds ONE
subject and ONE html per company and hands them to N recipients; a Site Manager
added to that list would be mailed every job the company runs, while
`require_project_access` scopes him to his assignments — so most of the links in
his own digest 404 for him. Narrowing the shared body instead would have changed
what an ADMIN receives, which the ruling forbids in the same breath.

So there are two passes and the second one has its own body.

── WHAT THE OLD CODE DID, AND WHY IT LOOKED FINE ───────────────────────────

`_resolve_renewal_digest_recipients` carried

    {"role": {"$in": ["pm", "cp"]}, "renewal_digest_opt_in": True}

and NOTHING IN THE CODEBASE HAS EVER WRITTEN `renewal_digest_opt_in`
(tests/test_reads_without_writers.py carried it as a read with no writer). So
the cursor matched zero rows, forever, and the defect it contained — a company-
wide body addressed to a project-scoped role — could not be observed. Creating
the `pm` role does not fix that; it is what makes it reachable.

── THE ASSERTIONS ARE ABOUT WHAT IS IN THE BODY ────────────────────────────

Not "was the pm on the recipient list". The whole point is that the recipient
list was never the thing. Each case below drives the real cron against a stand-
in database and reads the SENDS: who got mail, and which project names were in
it.
"""

import asyncio
import os
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://example.test")

import server  # noqa: E402

COMPANY = "company-a"
MINE = "project-mine"
THEIRS = "project-not-mine"
OTHER_TENANT = "project-another-company"


# ── The stand-in database ───────────────────────────────────────────────────
#
# Narrow on purpose: it answers the four reads this cron makes and nothing
# else, so a change in what the cron reads shows up as a KeyError naming the
# collection rather than as a silently empty result.

class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n):
        return list(self.rows)[:n]

    def __aiter__(self):
        async def gen():
            for r in self.rows:
                yield r
        return gen()


class _Coll:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.inserted = []

    def find(self, q=None, projection=None):
        return _Cursor([r for r in self.rows if _matches(r, q or {})])

    async def find_one(self, q=None, projection=None):
        for r in self.rows:
            if _matches(r, q or {}):
                return r
        return None

    async def insert_one(self, doc):
        self.inserted.append(doc)
        self.rows.append(doc)
        return type("R", (), {"inserted_id": "x"})()


def _matches(row, q):
    for k, v in (q or {}).items():
        if k in ("$or", "$and"):
            continue
        actual = row.get(k)
        if isinstance(v, dict):
            if "$ne" in v and actual == v["$ne"]:
                return False
            if "$in" in v and actual not in v["$in"]:
                return False
        elif actual != v:
            return False
    return True


class _DB:
    def __init__(self, users, projects, permits):
        self.users = _Coll(users)
        self.projects = _Coll(projects)
        self.dob_logs = _Coll(permits)
        self.companies = _Coll([{"_id": COMPANY, "name": "Acme", "is_deleted": False}])
        self.renewal_alert_sent = _Coll([])
        self.compliance_alerts = _Coll([])


@dataclass
class _Alert:
    """Stands in for lib.renewal_digest.RenewalAlert. Only the fields the cron
    and the body builders touch."""
    project_id: Optional[str]
    project_name: str
    threshold_days: int = 5

    def idempotency_key(self):
        return {"project_id": self.project_id, "kind": "permit"}


def _run(users, alerts):
    """Drive the real cron. Returns [(recipients, subject, html), ...]."""
    db = _DB(
        users=users,
        projects=[
            {"_id": MINE, "name": "MY JOB", "company_id": COMPANY, "is_deleted": False},
            {"_id": THEIRS, "name": "NOT MY JOB", "company_id": COMPANY, "is_deleted": False},
        ],
        permits=[{"_id": "p1", "project_id": MINE, "record_type": "permit",
                  "is_deleted": False}],
    )
    sends = []

    async def _fake_send(recipients, subject, html, *, company_id=None):
        sends.append((list(recipients), subject, html))

    # The body builders are the REAL ones — the assertions read project names
    # out of the html they produce, so a stub would be measuring the stub.
    import lib.renewal_digest as rd

    orig_compute = rd.compute_company_alerts
    rd.compute_company_alerts = lambda **kw: list(alerts)
    orig_html = rd.digest_html
    rd.digest_html = lambda al, name: " | ".join(
        f"{a.project_name or 'COMPANY-LEVEL'}" for a in al)
    orig_subject = rd.digest_subject
    rd.digest_subject = lambda al, name: f"{name}: {len(al)} item(s)"

    from unittest.mock import patch
    try:
        with patch.object(server, "db", db), \
             patch.object(server, "_send_renewal_digest_email", _fake_send), \
             patch.object(server, "drop_test_companies", lambda c, ids: c), \
             patch.object(server, "test_company_ids", _noop_ids):
            asyncio.run(server.renewal_digest_daily_cron())
    finally:
        rd.compute_company_alerts = orig_compute
        rd.digest_html = orig_html
        rd.digest_subject = orig_subject
    return sends, db


async def _noop_ids():
    return set()


def _admin(email="admin@acme.test", **kw):
    return {"_id": "u-admin", "company_id": COMPANY, "role": "admin",
            "email": email, "is_deleted": False, **kw}


def _pm(email="pm@acme.test", assigned=(MINE,), **kw):
    return {"_id": "u-pm", "company_id": COMPANY, "role": server.ROLE_PM,
            "email": email, "is_deleted": False,
            "assigned_projects": list(assigned), **kw}


class HeGetsHisOwnEmail(unittest.TestCase):
    def test_he_is_mailed_separately_from_the_admin(self):
        sends, _ = _run(
            [_admin(), _pm()],
            [_Alert(MINE, "MY JOB"), _Alert(THEIRS, "NOT MY JOB")],
        )
        to = {tuple(r) for r, _, _ in sends}
        self.assertIn(("admin@acme.test",), to)
        self.assertIn(("pm@acme.test",), to)
        # TWO SENDS, NOT ONE WITH TWO ADDRESSES. One send would mean one body.
        self.assertEqual(len(sends), 2, sends)

    def test_his_body_names_only_his_project(self):
        """THE RULE. Asserted on the BODY, because the address list was never
        the thing that was wrong."""
        sends, _ = _run(
            [_admin(), _pm()],
            [_Alert(MINE, "MY JOB"), _Alert(THEIRS, "NOT MY JOB")],
        )
        his = next(h for r, _, h in sends if r == ["pm@acme.test"])
        self.assertIn("MY JOB", his)
        self.assertNotIn("NOT MY JOB", his)

    def test_the_admin_body_is_UNCHANGED(self):
        """Both projects, exactly as before. The ruling narrows one audience
        and explicitly does not narrow the other."""
        sends, _ = _run(
            [_admin(), _pm()],
            [_Alert(MINE, "MY JOB"), _Alert(THEIRS, "NOT MY JOB")],
        )
        theirs = next(h for r, _, h in sends if r == ["admin@acme.test"])
        self.assertIn("MY JOB", theirs)
        self.assertIn("NOT MY JOB", theirs)

    def test_no_digest_at_all_when_none_of_his_projects_has_an_item(self):
        sends, _ = _run([_admin(), _pm()], [_Alert(THEIRS, "NOT MY JOB")])
        self.assertEqual([r for r, _, _ in sends], [["admin@acme.test"]])

    def test_he_is_mailed_even_when_every_admin_has_opted_out(self):
        """The old code `continue`d on an empty recipient list. That was right
        with one audience and would now silence every Site Manager at a company
        whose admins have all opted out."""
        sends, _ = _run(
            [_admin(renewal_digest_opt_out=True), _pm()],
            [_Alert(MINE, "MY JOB")],
        )
        self.assertEqual([r for r, _, _ in sends], [["pm@acme.test"]])

    def test_the_same_opt_out_flag_silences_him(self):
        """"The same emails as an admin" includes the way he stops getting
        them. One flag, not a second one meaning the same thing."""
        sends, _ = _run(
            [_admin(), _pm(renewal_digest_opt_out=True)],
            [_Alert(MINE, "MY JOB")],
        )
        self.assertEqual([r for r, _, _ in sends], [["admin@acme.test"]])


class TheCompanyListNoLongerCarriesHim(unittest.TestCase):
    """READ OFF THE CODE, NOT THE PROSE.

    The first version of this class searched `inspect.getsource(...)` and the
    raw file, and went red on its own explanation: the docstring below the
    function signature quotes the query it removed, so `assertNotIn('"cp"')`
    matched the paragraph saying cp is gone. That is the exact shape
    tests/source_text.py exists to stop, four times over, and it found a fifth
    here. `strip_python` removes docstrings and comments and leaves the code.
    """

    def setUp(self):
        from tests.source_text import strip_python
        import inspect
        self.code = strip_python(
            inspect.getsource(server._resolve_renewal_digest_recipients))

    def test_the_opt_in_cursor_is_gone(self):
        """ANCHORED, AND IT DOES NOT PRINT THE HAYSTACK.

        `"renewal_digest_opt_in":` with the colon is the DICT-KEY form the
        removed cursor used, so this bans the query filter rather than the
        word -- a bare token is also satisfied or broken by the word appearing
        in a sentence explaining it. And `assertTrue` with a message keeps a
        failure to one line instead of 2.3MB of escaped server.py; see
        tests/test_an_assertion_may_not_print_a_source_file.py, whose pinned
        total this would otherwise have raised.
        """
        from tests.source_text import code_of
        self.assertTrue(
            '"renewal_digest_opt_in":' not in code_of("server.py"),
            "the opt-in cursor is back - a company-wide digest body addressed "
            "to a project-scoped role",
        )

    def test_the_company_query_names_neither_cp_nor_pm(self):
        """A CP receives no email of any kind; a PM receives his own. The
        durable half of the CP rule is the send-time filter in
        lib/notifications.py, which a separate change owns — this asserts only
        that the query here does not put either of them on a shared list."""
        for needle in ('"cp"', "'cp'", '"pm"', "'pm'", "ROLE_PM"):
            self.assertNotIn(needle, self.code, needle)

    def test_it_still_selects_admins(self):
        """Without this, an empty function passes every assertion above."""
        self.assertIn('"role": "admin"', self.code)
        self.assertIn("renewal_digest_opt_out", self.code)


class AStaleAssignmentCannotLeakATenant(unittest.TestCase):
    """`assigned_projects` is not self-cleaning. It can name a deleted project,
    or — for a user moved between companies — one belonging to a tenant he is
    no longer in. An alert carries the project NAME, so a match on a stale id
    would put another tenant's jobsite in his inbox."""

    def test_an_assignment_outside_this_company_is_dropped(self):
        audiences = asyncio.run(_audiences(
            [_pm(assigned=(MINE, OTHER_TENANT))],
        ))
        self.assertEqual(len(audiences), 1)
        self.assertEqual(audiences[0]["project_ids"], {MINE})

    def test_a_pm_whose_assignments_are_all_stale_is_not_returned(self):
        """An entry with an empty set is an email waiting for a filter bug to
        fill it."""
        audiences = asyncio.run(_audiences([_pm(assigned=(OTHER_TENANT,))]))
        self.assertEqual(audiences, [])

    def test_a_pm_with_no_assignments_is_not_returned(self):
        self.assertEqual(asyncio.run(_audiences([_pm(assigned=())])), [])

    def test_a_pm_with_no_email_is_not_returned(self):
        self.assertEqual(asyncio.run(_audiences([_pm(email="")])), [])

    def test_a_soft_deleted_pm_is_not_returned(self):
        self.assertEqual(
            asyncio.run(_audiences([_pm(is_deleted=True)])), [])

    def test_nobody_but_a_pm_is_returned(self):
        """The admin is already served by pass 1; returning him here would mail
        him twice, once narrowed."""
        self.assertEqual(asyncio.run(_audiences([_admin()])), [])


async def _audiences(users):
    from unittest.mock import patch
    db = _DB(users=users, projects=[], permits=[])
    with patch.object(server, "db", db):
        return await server._pm_digest_audiences(COMPANY, {MINE, THEIRS})


class ACompanyLevelAlertIsNotHis(unittest.TestCase):
    """Insurance and GC-licence alerts carry `project_id = None`
    (lib/renewal_digest sets it only for permit alerts). They name no project,
    so including them would not break the operator's rule — the ruling says his
    digest lists his assigned projects, and this is the line that changes if
    the operator wants him told about the company's insurance."""

    def test_a_project_less_alert_does_not_reach_him(self):
        sends, _ = _run([_admin(), _pm()],
                        [_Alert(None, ""), _Alert(MINE, "MY JOB")])
        his = next(h for r, _, h in sends if r == ["pm@acme.test"])
        self.assertNotIn("COMPANY-LEVEL", his)
        self.assertIn("MY JOB", his)

    def test_and_it_does_not_by_itself_earn_him_a_digest(self):
        sends, _ = _run([_admin(), _pm()], [_Alert(None, "")])
        self.assertEqual([r for r, _, _ in sends], [["admin@acme.test"]])

    def test_the_admin_still_gets_it(self):
        sends, _ = _run([_admin()], [_Alert(None, "")])
        self.assertIn("COMPANY-LEVEL",
                      next(h for r, _, h in sends if r == ["admin@acme.test"]))


class TheIdempotencyRowRecordsBothPasses(unittest.TestCase):
    def test_it_names_everyone_who_received_a_digest(self):
        _, db = _run([_admin(), _pm()], [_Alert(MINE, "MY JOB")])
        row = db.renewal_alert_sent.inserted[0]
        self.assertEqual(set(row["recipients"]),
                         {"admin@acme.test", "pm@acme.test"})

    def test_nothing_is_marked_when_nothing_was_delivered(self):
        """A row written after a failed send means the alert is never retried.
        No recipients at all is the same state as a failure for that purpose."""
        _, db = _run([_pm(assigned=(THEIRS,))], [_Alert(MINE, "MY JOB")])
        self.assertEqual(db.renewal_alert_sent.inserted, [])


if __name__ == "__main__":
    unittest.main()
