"""A CP IS NEVER EMAILED, WHATEVER LIST HIS ADDRESS IS ON.

── THE RULING ──────────────────────────────────────────────────────────────

CP, Superintendent, and CP & Superintendent receive NO email of any kind. They
are field roles; the app is their logbook. Admin, Owner and Site Manager / PM
keep the DOB, permit and compliance mail. IN-APP NOTIFICATIONS FOR FIELD ROLES
ARE UNTOUCHED -- the injury card, the logbook alerts and the inbox are not
email and are not in scope.

── WHY THE FILTER IS AT SEND TIME AND NOT ON THE QUERIES ───────────────────

Seven paths reach `resend.Emails.send`, and THREE OF THEM DO NOT SELECT
RECIPIENTS BY ROLE AT ALL:

    report_email_list      raw addresses typed onto a project
    filing_reps[].email    raw addresses typed onto a company
    annotation "all"       every user id in the company, expanded

No role filter on a users query can reach any of those. And a CP carrying a
stale `renewal_digest_opt_in: true` would keep being emailed after the query
that set it was narrowed, because the opt-in is data and the query is code.

`resend.Emails.send` appears EXACTLY ONCE in this codebase -- in
lib/notifications.py, inside `send_notification` -- so there is one place where
the rule can be true for every path at once. That single-sender fact is
asserted below, because the moment a second sender exists this file is checking
one of two doors.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test_secret_for_the_suite")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib import notifications as N  # noqa: E402

FIELD = ("cp", "superintendent")
MAILED = ("admin", "owner", "pm")


class _Users:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    async def find_one(self, query, projection=None):
        # MODELS THE REAL QUERY SHAPE: an `$in` of exact terms, the way every
        # other user lookup in this codebase is written and the way Mongo can
        # serve it from the index. An earlier version of this fake decoded a
        # `$regex`, which is how a non-indexable query on the hot path of every
        # send went unnoticed -- the fake was built to fit the code instead of
        # the code being held to the codebase's own convention.
        self.queries.append(query)
        wanted = set((query.get("email") or {}).get("$in") or [])
        for r in self.rows:
            if r.get("email") in wanted:
                return r
        return None


class _DB:
    def __init__(self, rows):
        self.users = _Users(rows)


ROSTER = [
    {"email": "michaelcespedes99@gmail.com", "role": "cp"},
    {"email": "wilson@cp.com", "role": "cp"},
    {"email": "super@example.com", "role": "superintendent"},
    {"email": "michael@blueviewbuilders.com", "role": "admin"},
    {"email": "rfs2671@gmail.com", "role": "owner"},
    {"email": "pm@example.com", "role": "pm"},
]


def _role_of(address):
    return asyncio.run(N.recipient_is_field_role(_DB(ROSTER), address))


class TheRuleItself(unittest.TestCase):

    def test_a_cp_is_excluded(self):
        for address in ("michaelcespedes99@gmail.com", "wilson@cp.com"):
            with self.subTest(address):
                self.assertEqual(_role_of(address), "cp")

    def test_a_superintendent_is_excluded(self):
        self.assertEqual(_role_of("super@example.com"), "superintendent")

    def test_admin_owner_and_pm_ARE_emailed(self):
        """THE OTHER HALF. A rule that excludes everybody is a mail system
        nobody notices is broken until a permit expires."""
        for address in ("michael@blueviewbuilders.com", "rfs2671@gmail.com",
                        "pm@example.com"):
            with self.subTest(address):
                self.assertIsNone(_role_of(address))

    def test_an_address_belonging_to_nobody_is_emailed(self):
        """The normal case for a filing rep or a typed report address. A
        stranger's address is not a field role, and refusing it would silently
        stop the permit reminders this product exists to send."""
        self.assertIsNone(_role_of("accounts@somegc.example"))

    def test_whitespace_and_an_upper_cased_address_do_not_let_one_through(self):
        """The stored address is `wilson@cp.com`. A recipient string that
        arrives trimmed-and-folded, or shouted, still resolves -- the query
        carries both the address as given and its lowercase form."""
        for address in ("  wilson@cp.com ", "WILSON@CP.COM", "Wilson@Cp.Com"):
            with self.subTest(address):
                self.assertEqual(_role_of(address), "cp")

    def test_what_exact_matching_does_NOT_catch_is_stated(self):
        """A STORED address with capitals, against a recipient string with
        DIFFERENT capitals, does not match. This is the same gap `login` has on
        the same field, and it is pinned here so the limit is a known one
        rather than a surprise -- closing it means folding emails on write, not
        putting a collection scan on every send."""
        db = _DB([{"email": "Mixed@Case.com", "role": "cp"}])
        self.assertIsNone(
            asyncio.run(N.recipient_is_field_role(db, "mIxEd@case.com")))
        # and the two forms it DOES carry both work
        self.assertEqual(
            asyncio.run(N.recipient_is_field_role(db, "Mixed@Case.com")), "cp")

    def test_it_is_total(self):
        for bad in (None, "", "   "):
            with self.subTest(repr(bad)):
                self.assertIsNone(_role_of(bad))

    def test_it_fails_OPEN(self):
        """A missed exclusion is one unwanted email. A raise here would stop
        every permit-expiry reminder on the platform, and those have a deadline
        attached."""
        class _Boom:
            async def find_one(self, *a, **k):
                raise RuntimeError("no mongo")

        class _BadDB:
            users = _Boom()

        self.assertIsNone(
            asyncio.run(N.recipient_is_field_role(_BadDB(), "wilson@cp.com")))

    def test_the_dual_capacity_user_is_covered_by_cp(self):
        """CP & Superintendent is role=cp plus an is_superintendent capability,
        so he is excluded by the `cp` entry. A third role string would be a
        fourth name for a thing this codebase already has enough names for."""
        self.assertEqual(N.EMAIL_EXCLUDED_ROLES, frozenset({"cp", "superintendent"}))


class TheSendPathEnforcesIt(unittest.TestCase):

    def setUp(self):
        self.src = (_BACKEND / "lib" / "notifications.py").read_text(
            encoding="utf-8")

    def test_there_is_exactly_ONE_sender_in_the_whole_backend(self):
        """The load-bearing fact. A second `Emails.send` anywhere and this
        file is checking one of two doors."""
        hits = []
        for path in list((_BACKEND).rglob("*.py")):
            if "__pycache__" in str(path) or "/tests/" in str(path).replace(
                    "\\", "/"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.split("\n"):
                if "Emails.send(" in line and not line.strip().startswith("#"):
                    hits.append(f"{path.name}: {line.strip()[:70]}")
        self.assertEqual(len(hits), 1, hits)
        self.assertIn("notifications.py", hits[0])

    def test_the_check_runs_BEFORE_idempotency(self):
        """The idempotency window is 23 hours per (renewal, trigger,
        recipient). If the refusal sat after it, the first attempt of the day
        would log `suppressed_idempotent` for a CP and the reason he was not
        emailed would be recorded as the wrong one."""
        body = self.src[self.src.index("async def send_notification"):]
        self.assertLess(body.index("recipient_is_field_role"),
                        body.index("is_idempotent_skip"))

    def test_the_check_runs_BEFORE_the_send(self):
        body = self.src[self.src.index("async def send_notification"):]
        self.assertLess(body.index("recipient_is_field_role"),
                        body.index("Emails.send("))

    def test_it_logs_rather_than_vanishing(self):
        """A silent non-delivery is undiagnosable. The notification_log row
        says what would have gone out and why it did not."""
        self.assertIn("NOTIFICATION_STATUS_SUPPRESSED_FIELD_ROLE", self.src)
        self.assertIn('"suppressed_field_role"', self.src)
        body = self.src[self.src.index("async def send_notification"):]
        self.assertIn('"excluded_role"', body)


class TheDigestStopsBuildingTheList(unittest.TestCase):
    """Belt and braces on the chokepoint: no query that feeds an email selects
    a field role. The send-time filter would refuse them anyway; a list of
    people who may not be written to is how a stale opt-in keeps looking like
    an intention.

    ── BOTH CHECKS BELOW READ CODE, NOT PROSE ──────────────────────────────

    They read `server.py` off disk, and this file's subjects explain
    themselves at length -- the resolver's own docstring now QUOTES the query
    that was removed, in order to record why. Matched raw, the census counted
    that explanation as an offender and the whole suite went red over a
    paragraph saying the thing had been fixed.

    That is the shape tests/source_text.py exists to end, and it had been found
    five times before this one. `strip_python` removes docstrings and comments
    and leaves the code, so these now measure what they are about.
    """

    def setUp(self):
        from tests.source_text import strip_python
        raw = (_BACKEND / "server.py").read_text(encoding="utf-8")
        self.src = strip_python(raw)
        start = self.src.index("async def _resolve_renewal_digest_recipients")
        self.body = self.src[start:self.src.index("\nasync def", start + 10)]

    def test_no_field_role_is_selected_by_the_company_digest_query(self):
        """STRONGER THAN WHEN THIS WAS WRITTEN, AND THE ASSERTION MOVED WITH IT.

        #571 narrowed the opt-in cursor from `["pm", "cp"]` to `["pm"]`, and
        this test pinned both halves of that. The roles work then removed the
        cursor ENTIRELY: a Site Manager receives his own digest, scoped to his
        assigned projects, from `_pm_digest_audiences` -- because this body
        names every project the company runs and `require_project_access`
        refuses him most of them.

        So the `["pm"]` half was asserting the CURSOR'S EXISTENCE, which was
        never the fact this file is about. The fact -- no field role is built
        into this recipient list -- is now true of a query that does not exist
        rather than of one that was narrowed, and is asserted that way.
        """
        self.assertNotIn('"$in"', self.body)
        self.assertNotIn("renewal_digest_opt_in", self.body)
        # AND IT STILL SELECTS THE PEOPLE IT IS FOR. Without this, an empty
        # function passes every assertion above.
        self.assertIn('"role": "admin"', self.body)
        self.assertIn("renewal_digest_alias_email", self.body)

    def test_the_pm_did_not_lose_his_digest_when_the_cursor_went(self):
        """The removal above must not read as "Site Managers were dropped".
        They were moved to a pass that can scope the BODY, which the shared one
        cannot."""
        self.assertIn("async def _pm_digest_audiences", self.src)
        self.assertIn("_pm_digest_audiences(", self.src)

    def test_no_email_recipient_query_anywhere_selects_a_field_role(self):
        """THE CENSUS. Every users query that feeds an email must not name a
        field role. Derived rather than listed, so a new digest written next
        month fails this on the day it is written."""
        import re
        offenders = []
        for m in re.finditer(r'"role":\s*\{"\$in":\s*\[([^\]]*)\]', self.src):
            roles = {r.strip().strip('"\'') for r in m.group(1).split(",")}
            if roles & {"cp", "superintendent"}:
                line = self.src[:m.start()].count("\n") + 1
                # The in-app inbox and the permission checks legitimately name
                # these roles; only EMAIL recipient queries are in scope.
                window = self.src[max(0, m.start() - 2000):m.start()]
                if "email" in window.lower() or "digest" in window.lower():
                    offenders.append(f"server.py:{line} {m.group(0)[:60]}")
        self.assertEqual(offenders, [], "email recipient query names a field "
                         "role: " + "; ".join(offenders))

    def test_the_census_can_still_fail(self):
        """A regex over a file it can no longer match is a check that passes
        forever. The pattern is driven against a line of the shape it hunts, so
        a refactor that breaks the regex is loud rather than green."""
        import re
        sample = '        "role": {"$in": ["pm", "cp"]},'
        m = re.search(r'"role":\s*\{"\$in":\s*\[([^\]]*)\]', sample)
        self.assertIsNotNone(m, "the census regex no longer matches its own "
                                "subject")
        roles = {r.strip().strip('"\'') for r in m.group(1).split(",")}
        self.assertTrue(roles & {"cp", "superintendent"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
