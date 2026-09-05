"""RESOLVING AN ALERT MUST NOT SILENCE A CONDITION THAT IS STILL TRUE.

Every `compliance_alerts` writer checks for an existing row before inserting,
so a nightly re-run cannot stack duplicates. Three of those checks did not ask
whether the existing row was RESOLVED — and resolve is the only action
`/admin/compliance-alerts` offers. So taking it matched forever after, and the
alert never came back while the condition went on being true:

    missing_logbook             the required daily logbook stays unfiled
    unique_index_not_enforced   the index stays unbuilt
    cors_preflight_refused      the server goes on refusing the header

`missing_logbook` is the worst of the three. It is a statutory filing gap for a
day that cannot come back, and one click destroyed the only surviving statement
that the day was never filed.

── THE RULE IS NOT UNIVERSAL, AND THAT IS THE POINT OF THIS FILE ────────────

`worker_cert_expiring` is deliberately different and must stay that way. Its
condition — a certification thirty days from expiry — does NOT change when the
admin acts, so a bare `resolved: False` would re-raise the same alert the same
night and decay resolve into "cleared for one night". It suppresses on an
unchanged `details.earliest_expiration` instead, via `$or`, so resolve means
"I have handled this expiry" and a NEW date is a new fact.

So the test is: `resolved` is consulted, or the site is a NAMED exception with
a written reason. A count alone cannot tell a deliberate omission from a missed
one — the lesson from the fourteenth signature call site — so the exception is
named here and its reason is asserted to exist.

── WHY A CENSUS AND NOT THREE ASSERTIONS ────────────────────────────────────

Four of the eight sites already had the clause before this change; three did
not; one is the exception. A per-site test would have passed on the four and
said nothing about a ninth alert added next month, which is exactly how three
sites came to be missing it in the first place — the fix was applied to the one
somebody was reading.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

#: The RAW file. `code_of` blanks docstrings, and a blanked docstring used as a
#: dict value leaves `{"content": },` behind, which `ast.parse` refuses.
_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)

#: Sites that legitimately do not key on `resolved`, each with the reason.
#: Removing an entry here is what re-enables the check for that site.
_EXEMPT = {
    "worker_cert_expiring":
        "its condition (a cert 30 days from expiry) does not change when the "
        "admin acts, so a bare resolved:False would re-raise the same night; "
        "it suppresses on an unchanged details.earliest_expiration via $or, "
        "which makes resolve mean 'I have handled this expiry'",
}


def _dedupe_reads():
    """Every `compliance_alerts.find_one(...)` that guards an insert.

    Read from the AST rather than by regex: the queries are dict literals
    spread over several lines and three of them now carry a paragraph of
    comment in the middle, which a windowed text search would either miss or
    match on the prose explaining the rule.
    """
    out = []
    for node in ast.walk(_TREE):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "find_one"):
            continue
        if "compliance_alerts" not in ast.unparse(f):
            continue
        arg = node.args[0] if node.args else None
        # `worker_cert_expiring` builds its query in a local `dedup` dict, so
        # the call site carries a Name rather than a literal. Resolve it from
        # the enclosing source instead of skipping it, or the one site whose
        # shape this file exists to permit would never be examined.
        if isinstance(arg, ast.Dict):
            keys = [k.value for k in arg.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            atype = None
            for k, v in zip(arg.keys, arg.values):
                if (isinstance(k, ast.Constant) and k.value == "alert_type"
                        and isinstance(v, ast.Constant)):
                    atype = v.value
            out.append((atype, keys, node.lineno, ast.unparse(arg)))
        elif isinstance(arg, ast.Name):
            out.append((None, None, node.lineno, arg.id))
    return out


class EveryDedupeAsksWhetherTheRowWasResolved(unittest.TestCase):

    def test_the_census_is_not_empty(self):
        """A scan that matched nothing satisfies every assertion below."""
        reads = _dedupe_reads()
        self.assertGreaterEqual(
            len(reads), 8,
            f"only {len(reads)} compliance_alerts dedupe reads found; the walk "
            "is stale")

    def test_every_literal_dedupe_keys_on_resolved(self):
        offenders = []
        for atype, keys, lineno, src in _dedupe_reads():
            if keys is None:
                continue                      # resolved separately below
            if atype in _EXEMPT:
                continue
            if not any(k == "resolved" or k.startswith("resolved")
                       for k in keys):
                offenders.append(f"server.py:{lineno} alert_type={atype!r}")
        self.assertEqual(
            offenders, [],
            "a resolved alert will suppress these forever while the condition "
            "stays true: " + "; ".join(offenders))

    def test_the_three_that_were_missing_it_now_have_it(self):
        """Named, so the fix cannot be reverted quietly on one of them."""
        found = {a: keys for a, keys, _l, _s in _dedupe_reads() if keys}
        for atype in ("missing_logbook", "unique_index_not_enforced",
                      "cors_preflight_refused"):
            with self.subTest(atype):
                self.assertIn(atype, found, "the site vanished")
                self.assertIn("resolved", found[atype])

    def test_the_four_that_already_had_it_still_do(self):
        found = {a: keys for a, keys, _l, _s in _dedupe_reads() if keys}
        for atype in ("unsigned_stale_logbook", "missing_ssp", "ssp_expiring",
                      "staff_license_expiring"):
            with self.subTest(atype):
                self.assertIn(atype, found, "the site vanished")
                self.assertIn("resolved", found[atype])


class TheExceptionIsNamedAndStillCorrect(unittest.TestCase):
    """`worker_cert_expiring` is the reason the rule is not universal. A silent
    exception would read as an oversight; this one carries its argument."""

    def test_the_exemption_states_why(self):
        for name, reason in _EXEMPT.items():
            with self.subTest(name):
                self.assertGreater(len(reason), 80,
                                   "an exemption without a reason is a hole")

    def test_it_still_suppresses_on_the_expiry_DATE_and_not_only_on_resolved(self):
        """The shape it is exempt FOR. If this ever becomes a bare
        `resolved: False`, resolve decays into 'cleared for one night' and the
        exemption should be deleted rather than left standing."""
        i = _SRC.index('dedup = {"alert_type": "worker_cert_expiring"')
        block = _SRC[i:i + 400]
        self.assertIn("$or", block)
        self.assertIn("details.earliest_expiration", block)
        self.assertIn('{"resolved": False}', block)

    def test_and_it_falls_back_to_resolved_when_there_is_no_date(self):
        i = _SRC.index('dedup = {"alert_type": "worker_cert_expiring"')
        block = _SRC[i:i + 400]
        self.assertIn('dedup["resolved"] = False', block)


class TheConditionIsStillReVerified(unittest.TestCase):
    """RE-RAISING IS ONLY ACCEPTABLE BECAUSE THE CONDITION IS RE-CHECKED.

    If any of the three stopped re-verifying, `resolved: False` would turn a
    handled alert into a nightly duplicate — the failure the exception above
    exists to avoid. Asserted on the guard that precedes each insert."""

    def test_missing_logbook_only_fires_when_the_log_is_absent(self):
        i = _SRC.index('"alert_type": "missing_logbook", "project_id": pid,')
        before = _SRC[max(0, i - 800):i]
        self.assertIn("db.logbooks.find_one", before)
        self.assertIn("if not existing:", before)

    def test_the_index_alert_only_fires_after_a_failed_build(self):
        i = _SRC.index('"alert_type": "unique_index_not_enforced",')
        before = _SRC[max(0, i - 1500):i]
        self.assertIn("E11000", before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
