"""«Owner» is not a role anybody can hold, and the operator is not locked out.

── THE RULING ────────────────────────────────────────────────────────────────

There is no "owner" role. There is a platform operator — one human, one
account, hard-coded to an email — and `is_platform_operator` is the only
function that means it. Everything else that read `role == "owner"` was either
a company-admin power wearing the wrong word, or a cross-tenant operation that
should have been asking the operator question all along.

── THE TWO HALVES, AND WHY THE SECOND ONE IS THE DANGEROUS ONE ───────────────

RETIRING THE WRITER is easy: `register` minted `role = "owner"` on every
self-serve signup and now mints ROLE_DEMO. The census below proves no writer
anywhere in server.py still puts that string on a user document — a census,
not a sample, because the writer that matters is the one nobody remembered
(the boot-time seed rewrote the operator's own role to "owner" on EVERY
deploy, which would have silently undone the account migration that follows
this change).

SWEEPING THE READERS IS WHERE THE PRODUCT BREAKS. The operator's own account
still literally holds `role: "owner"` — his migration to "admin" is a later
step that has not run. So the moment "owner" leaves COMPANY_ADMIN_ROLES he is
an account whose role string matches nothing, and every company-admin gate in
the product closes in his face. The fix is not to leave "owner" in a tuple: it
is that every swept gate admits him on `is_platform_operator`, the flag, which
no API path can write.

`TheOperatorIsNotLockedOutOfHisOwnProduct` below is the test that proves it,
and it asserts BOTH directions — the flag admits, and the bare role string
does not. A test that only checked the first would pass just as well if the
gates had been left wide open.

── WHY SO MUCH OF THIS IS A SOURCE CENSUS ────────────────────────────────────

Thirty-odd of the swept checks are three inline lines in the middle of a route
that needs a database, a company and a project to call. Running each one would
be thirty fixtures asserting the same single fact. The behavioural tests here
cover the SHAPES — the three admin dependencies, the operator gate, the role
vocabulary — and the census covers the long tail by reading the code with the
prose already removed (`code_of`, which strips comments and docstrings; this
file's own paragraphs above say "owner" many times and must not be what a
banned-token scan is counting).
"""

from __future__ import annotations

import ast
import asyncio
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")
# The operator must be admitted by the FLAG, not by the bootstrap email list.
# Clearing it is what makes the negative half of every assertion below mean
# something: with an allow-list loaded, `is_platform_operator` would answer
# True for the fixture's address and the role test would never be reached.
os.environ.pop("PLATFORM_OPERATOR_EMAILS", None)

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from tests.source_text import code_of  # noqa: E402

SRC = code_of("server.py")
RAW = code_of("server.py", raw=True)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _refused(coro):
    """The HTTPException a gate raised, or a failure naming what it returned."""
    try:
        got = _run(coro)
    except HTTPException as e:
        return e
    raise AssertionError(f"expected a 403, got {got!r}")


# ── The three principals every assertion below is written against ───────────
#
# THE OPERATOR STILL CARRIES role "owner". That is not a quirk of the fixture,
# it is the production state this change ships into: rfs2671@gmail.com holds
# the string today and a later step rewrites it. A fixture that had already
# migrated him would test a world that does not exist yet and would pass
# whether or not the flag was honoured.
def _operator():
    return {"_id": "op1", "id": "op1", "email": "ops@levelog.test",
            "role": "owner", "is_platform_operator": True,
            "company_id": "coA", "account_status": "approved"}


def _customer_owner():
    """The same legacy role string WITHOUT the flag — a customer."""
    return {"_id": "u1", "id": "u1", "email": "gc@example.test",
            "role": "owner", "company_id": "coA", "account_status": "approved"}


def _admin():
    return {"_id": "u2", "id": "u2", "email": "admin@example.test",
            "role": "admin", "company_id": "coA", "account_status": "approved"}


class TheRoleVocabularyNoLongerOffersIt(unittest.TestCase):
    def test_owner_is_in_none_of_the_three_admin_tuples(self):
        for name in ("COMPANY_ADMIN_ROLES", "USER_MANAGEMENT_ROLES",
                     "PROJECT_ADMIN_ROLES"):
            with self.subTest(tuple=name):
                self.assertNotIn("owner", getattr(server, name))

    def test_the_tuples_did_not_merely_become_empty(self):
        """The instrument, checked. An assertNotIn passes on an empty tuple,
        which would be a gate that admits nobody rather than one that was
        swept — so the admin it must still admit is asserted beside it."""
        for name in ("COMPANY_ADMIN_ROLES", "USER_MANAGEMENT_ROLES",
                     "PROJECT_ADMIN_ROLES"):
            with self.subTest(tuple=name):
                self.assertIn("admin", getattr(server, name))

    def test_the_demo_role_exists_and_is_spelled_demo(self):
        self.assertEqual(server.ROLE_DEMO, "demo")

    def test_neither_owner_nor_demo_may_be_assigned_by_an_admin(self):
        self.assertNotIn("owner", server.ASSIGNABLE_ROLES)
        self.assertNotIn(server.ROLE_DEMO, server.ASSIGNABLE_ROLES)

    def test_assert_assignable_role_refuses_both(self):
        for bad in ("owner", "demo", " Owner ", "DEMO"):
            with self.subTest(role=bad):
                with self.assertRaises(HTTPException) as c:
                    server.assert_assignable_role(bad)
                self.assertEqual(c.exception.status_code, 422)

    def test_is_demo_reads_the_role_and_normalises_it(self):
        self.assertTrue(server.is_demo({"role": "demo"}))
        self.assertTrue(server.is_demo({"role": " Demo "}))
        self.assertFalse(server.is_demo({"role": "admin"}))
        self.assertFalse(server.is_demo({}))
        self.assertFalse(server.is_demo(None))


class NoWriterAnywhereStillMintsTheRole(unittest.TestCase):
    """THE CENSUS. Every place server.py writes a `role`, enumerated.

    Not "does `register` still say owner" — that was the known writer, and the
    boot seed that rewrote the operator's role on every deploy was the one
    nobody had counted. So this walks the AST for the two shapes a role write
    can take and reports the value at each, which makes the answer a list
    rather than a spot check.
    """

    TREE = ast.parse((_BACKEND / "server.py").read_text(encoding="utf-8"))

    def _role_writes(self):
        """[(lineno, value)] for every literal written to a `role` key.

        TWO SHAPES, because those are the two this file uses:
          doc["role"] = <literal>          a subscript assignment
          {..., "role": <literal>, ...}    a dict literal (insert_one, $set)
        A non-literal value (a variable, a call) is not counted — it cannot be
        read statically and is not what this census is about.
        """
        out = []
        for node in ast.walk(self.TREE):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (isinstance(tgt, ast.Subscript)
                            and isinstance(tgt.slice, ast.Constant)
                            and tgt.slice.value == "role"
                            and isinstance(node.value, ast.Constant)):
                        out.append((node.lineno, node.value.value))
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if (isinstance(k, ast.Constant) and k.value == "role"
                            and isinstance(v, ast.Constant)):
                        out.append((k.lineno, v.value))
        return out

    def test_the_census_found_role_writes_at_all(self):
        """The instrument. If the walker found nothing, the assertion below is
        vacuous and would go on passing after somebody reintroduced the role."""
        self.assertGreaterEqual(len(self._role_writes()), 3,
                                "the AST walk stopped finding role writes")

    def test_not_one_of_them_writes_owner(self):
        offenders = [(ln, v) for ln, v in self._role_writes() if v == "owner"]
        self.assertEqual(
            offenders, [],
            "server.py still writes the retired role at "
            + ", ".join(f"line {ln}" for ln, _ in offenders))

    def test_registration_mints_the_demo_role_by_constant(self):
        reg = SRC[SRC.index("async def register("):]
        reg = reg[:reg.index("result = await db.users.insert_one(user_dict)")]
        self.assertIn('user_dict["role"] = ROLE_DEMO', reg)

    def test_the_boot_seed_no_longer_rewrites_the_operators_role(self):
        """The writer that would have undone the account migration.

        The seed used to carry `elif owner and owner.get("role") == "admin":`
        followed by a $set back to "owner" — so the deploy after the operator
        was migrated would have put the retired role straight back on him."""
        self.assertNotIn(
            '"$set": {"role": "owner"', SRC,
            "the boot seed still writes the retired role back onto an account")


class TheOperatorIsNotLockedOutOfHisOwnProduct(unittest.TestCase):
    """THE ONE THAT MATTERS.

    His `role` is still the string this change retires. Every company-admin
    gate must admit him anyway, on the flag — and must refuse the identical
    account without it, or the sweep achieved nothing.
    """

    GATES = ("get_admin_user", "get_user_admin", "get_project_admin_user")

    def test_the_flag_admits_him_to_every_company_admin_gate(self):
        for name in self.GATES:
            with self.subTest(gate=name):
                got = _run(getattr(server, name)(current_user=_operator()))
                self.assertEqual(got["id"], "op1")

    def test_the_same_account_without_the_flag_is_refused(self):
        for name in self.GATES:
            with self.subTest(gate=name):
                exc = _refused(getattr(server, name)(
                    current_user=_customer_owner()))
                self.assertEqual(exc.status_code, 403)

    def test_an_ordinary_admin_is_still_admitted(self):
        for name in self.GATES:
            with self.subTest(gate=name):
                got = _run(getattr(server, name)(current_user=_admin()))
                self.assertEqual(got["id"], "u2")

    def test_a_cp_is_still_refused(self):
        for name in self.GATES:
            with self.subTest(gate=name):
                exc = _refused(getattr(server, name)(
                    current_user={"id": "u3", "role": "cp"}))
                self.assertEqual(exc.status_code, 403)

    def test_the_platform_operator_gate_is_the_flag_and_not_the_role(self):
        got = _run(server.get_platform_operator_user(current_user=_operator()))
        self.assertEqual(got["id"], "op1")
        self.assertEqual(
            _refused(server.get_platform_operator_user(
                current_user=_customer_owner())).status_code, 403)
        self.assertEqual(
            _refused(server.get_platform_operator_user(
                current_user=_admin())).status_code, 403)

    def test_that_gate_does_not_inherit_the_shadow(self):
        """`require_platform_operator` LOGS AND ALLOWS while
        PLATFORM_GATES_ENFORCED is unset. A hard gate written on it would pass
        its own tests and protect nothing, which is why there are two."""
        self.assertFalse(server.PLATFORM_GATES_ENFORCED)
        self.assertIsNotNone(
            _run(server.require_platform_operator(current_user=_admin())),
            "premise: the shadowed dependency really does let a non-operator "
            "through, so the strict gate cannot be built on it")

    def test_the_negative_fixture_omits_the_key_rather_than_setting_it_false(self):
        """THE SHAPE PRODUCTION ACTUALLY HAS, asserted so it stays that way.

        Exactly one document in the database carries this field. On every
        other account the KEY IS ABSENT — not False. A fixture that wrote
        False would be testing a shape no real row has, and would go on
        passing over a predicate that only misreads a missing key.
        """
        self.assertNotIn("is_platform_operator", _customer_owner())
        self.assertNotIn("is_platform_operator", _admin())
        self.assertFalse(server.is_platform_operator(_customer_owner()))

    def test_is_company_admin_is_the_named_rule_and_answers_both_ways(self):
        self.assertTrue(server.is_company_admin(_operator()))
        self.assertTrue(server.is_company_admin(_admin()))
        self.assertTrue(server.is_company_admin({"role": " ADMIN "}))
        self.assertFalse(server.is_company_admin(_customer_owner()))
        self.assertFalse(server.is_company_admin({"role": "cp"}))
        self.assertFalse(server.is_company_admin({}))
        self.assertFalse(server.is_company_admin(None))


class TheSweptGatesStoppedReadingTheRole(unittest.TestCase):
    """The long tail, by census rather than by sample.

    Each name below was a `role != "owner"` or a `role in ("admin", "owner")`
    written inline in a route body. Two things are asserted of each: the
    retired string is gone, and the replacement is one of the two named rules
    — because deleting the word and leaving no check is also a way to make an
    absence test pass.
    """

    # → is_platform_operator. Cross-tenant, or the operator configuring DOB
    #   authorization on a client's behalf.
    PLATFORM = (
        "get_platform_operator_user",
        "link_gc_license_to_company",
        "list_filing_reps", "add_filing_rep", "update_filing_rep",
        "delete_filing_rep",
        "get_company_authorization", "post_company_authorization",
        "admin_list_filing_jobs", "admin_list_notifications",
        "admin_resend_notification",
        "migrate_company_data",
        "list_pending_deletion_projects",
    )

    # → company admin. Every one of these read as "owner" only because signup
    #   minted owners; none of them is a cross-tenant power.
    ADMIN = (
        "update_password",
        "delete_logbook",
        "whatsapp_debug_audio_probe", "whatsapp_debug_audio_diag",
        "whatsapp_debug_bot_ids", "whatsapp_debug_page_index",
        "whatsapp_debug_convo_state_indexes", "whatsapp_debug_webhook_log",
        "whatsapp_debug_waapi_config", "whatsapp_debug_recent_messages",
        "whatsapp_debug_pending_codes", "whatsapp_update_group_config",
        "debug_indexed_pages",
        "bootstrap_checkin_point", "remove_cp_checkin_point",
        "_get_checklist_candidates", "_process_whatsapp_message",
    )

    def _body(self, name):
        """The function's own source, comments and docstrings already gone.

        ENDS AT THE NEXT TOP-LEVEL `def`, not at a character count. A window
        measured in characters is not a scope: anything inserted above the
        line under test silently changes what the assertion can see, which is
        how a sibling test in this suite once failed for a gate that was
        exactly where it belonged.
        """
        needle = f"def {name}("
        i = SRC.index(needle)
        rest = SRC[i + len(needle):]
        ends = [x for x in (rest.find("\nasync def "), rest.find("\ndef "),
                            rest.find("\nclass ")) if x != -1]
        return SRC[i:i + len(needle) + (min(ends) if ends else len(rest))]

    def test_every_swept_gate_was_found_in_the_source(self):
        """The instrument. A typo in a name above would make `_body` raise —
        but a name that silently matched a PREFIX of another function would
        not, so the census is pinned to its own size."""
        self.assertEqual(len(self.PLATFORM) + len(self.ADMIN), 30)
        for name in self.PLATFORM + self.ADMIN:
            with self.subTest(fn=name):
                self.assertTrue(self._body(name).strip())

    def test_none_of_them_still_names_the_retired_role(self):
        for name in self.PLATFORM + self.ADMIN:
            with self.subTest(fn=name):
                self.assertNotIn('"owner"', self._body(name))

    def test_the_platform_ones_ask_the_operator_question(self):
        for name in self.PLATFORM:
            with self.subTest(fn=name):
                self.assertIn("is_platform_operator(", self._body(name))

    def test_the_admin_ones_ask_the_company_admin_question(self):
        for name in self.ADMIN:
            with self.subTest(fn=name):
                self.assertIn("is_company_admin(", self._body(name))


class TheNotificationRecipientQueriesToo(unittest.TestCase):
    """Two Mongo `$in: ["admin", "owner"]` recipient lists outside server.py.

    Not gates — nobody is refused by a recipient query — so the failure they
    can produce is the quiet one: the operator stops being told. They are
    swept with the rest, and the flag is added beside the role so the account
    migration cannot drop him from a mailing list nobody is watching.
    """

    def test_neither_library_still_selects_on_the_retired_role(self):
        for f in ("lib/notifications.py", "lib/notifications_inbox.py"):
            with self.subTest(file=f):
                self.assertNotIn(
                    '"owner"', code_of(f),
                    f"{f} still selects recipients on the retired role")

    def test_both_still_select_admins_and_also_the_operator_flag(self):
        for f in ("lib/notifications.py", "lib/notifications_inbox.py"):
            with self.subTest(file=f):
                code = code_of(f)
                self.assertIn('"admin"', code)
                self.assertIn('"is_platform_operator": True', code)


class TheClientIsToldWhetherItIsTheOperator(unittest.TestCase):
    """/auth/me must ANSWER the question, not merely echo a stored field.

    It returns the user document minus secrets, so `is_platform_operator`
    reached the client only when a human had written it to the row. The
    bootstrap operator — recognised by PLATFORM_OPERATOR_EMAILS — carried no
    such field, so the one screen the ruling says must read the flag would
    have read `undefined` for exactly the account it exists for.
    """

    def test_get_me_computes_the_capability(self):
        body = SRC[SRC.index("async def get_me("):]
        body = body[:body.index("\nasync def ", 1)]
        self.assertIn('out["is_platform_operator"] = is_platform_operator(',
                      body)

    def test_it_is_still_a_response_only_field(self):
        """The write side is what makes the flag a trust anchor. If it ever
        enters an allow-list, every gate swept above becomes API-mutable."""
        for allowlist in ("ALLOWED_USER_FIELDS", "ALLOWED_SUB_FIELDS",
                          "ALLOWED_WORKER_FIELDS", "ALLOWED_FIELDS"):
            if hasattr(server, allowlist):
                with self.subTest(allowlist=allowlist):
                    self.assertNotIn("is_platform_operator",
                                     getattr(server, allowlist))


class TheScreensFollowedTheServer(unittest.TestCase):
    """The frontend half. A gate the server opens and the screen hides is
    still a feature the operator cannot reach."""

    SCREENS = (
        "app/admin/checklists/index.jsx",
        "app/admin/safety-staff.jsx",
        "app/admin/superintendent.jsx",
        "app/documents.jsx",
        "app/index.jsx",
        "app/logbooks/index.jsx",
        "app/project/[id]/dob-logs.jsx",
        "app/project/[id].jsx",
        "app/projects/[id]/files.jsx",
        "app/reports.jsx",
        "app/settings.jsx",
        "app/workers/[id].jsx",
        "src/components/FloatingNav.js",
        "src/components/PDFViewer.native.jsx",
        "src/components/PDFViewerWeb.jsx",
    )

    def test_no_screen_still_compares_a_role_to_the_retired_string(self):
        for s in self.SCREENS:
            with self.subTest(screen=s):
                self.assertNotIn(
                    "'owner'", code_of(f"frontend/{s}"),
                    f"{s} still compares a role to the retired string")

    def test_each_one_asks_the_shared_rule_instead(self):
        for s in self.SCREENS:
            with self.subTest(screen=s):
                self.assertIn(
                    "isCompanyAdmin(", code_of(f"frontend/{s}"),
                    f"{s} does not ask the shared rule")

    def test_the_shared_rule_admits_the_operator_by_flag(self):
        code = code_of("frontend/src/context/AuthContext.js")
        self.assertIn("export function isCompanyAdmin", code)
        self.assertIn("export function isPlatformOperator", code)
        self.assertIn("is_platform_operator", code)

    def test_an_absent_flag_reads_as_not_the_operator(self):
        """`=== true`, NOT `!== false`, AND THE DIFFERENCE IS THE WHOLE RULE.

        /auth/me is deliberately not a response model — it serves a user and a
        gate tablet through one handler — so it returns the principal document
        minus secrets rather than a shape with defaults filled in. The server
        now computes this key on the way out, but a client holding a principal
        cached from before that deploy, or a site-device shape, may not carry
        it at all. Under `!== false` every one of those is the operator.
        """
        code = code_of("frontend/src/context/AuthContext.js")
        body = code[code.index("export function isPlatformOperator"):]
        # `\n}` — the function's own closing brace at column 0. NOT the first
        # "}", which is the `{}` inside `(user || {})` and cuts the body off
        # before the comparison this test is about.
        body = body[:body.index("\n}")]
        self.assertIn("=== true", body)
        self.assertNotIn("!== false", body)

    def test_the_owner_portal_reads_the_flag_and_not_the_role(self):
        code = code_of("frontend/app/owner/pending-deletion.jsx")
        self.assertIn("isPlatformOperator(user)", code)
        self.assertNotIn("=== 'owner'", code)
        self.assertNotIn("isCompanyAdmin(", code,
                         "the purge queue is the operator's, not an admin's")


if __name__ == "__main__":
    unittest.main()
