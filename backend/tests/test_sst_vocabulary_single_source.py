"""SST_TEMPORARY is an SST card everywhere, or the DOB gets a contradiction.

THE DEFECT. server.py held the canonical four-member SST_CLASS_TYPES. Two
consumers under lib/ each carried a hardcoded THREE-member copy that dropped
SST_TEMPORARY:

    lib/logbook/ll196.py:47          _SST_CERT_TYPES = ("SST_FULL", "SST_LIMITED", "SST_SUPERVISOR")
    lib/statistical_engine/score.py  ("SST_FULL", "SST_LIMITED", "SST_SUPERVISOR")

So one worker produced two contradictory statements: the gate admitted him as
holding a legible SST class, and the LL196 attestation PDF -- a document filed
with the DOB -- counted him MISSING. The risk score excluded him from
sst_expiring_30d, which is the worst of the three: a temporary card is the
SHORTEST-LIVED SST credential, so the expiring-soon count silently excluded
exactly the cards most likely to be expiring soon.

THE FIX. One definition in lib/cert_vocab.py, imported by all three. It lives
BELOW both consumers rather than in server.py because server.py imports ll196
and score -- a lib module importing server would be circular.

WHAT THIS FILE GUARDS. Not the identifier. A renamed constant holding the same
three strings is the same defect wearing a different name, so the sweep below
keys on the MEMBERS.

    python backend/tests/test_sst_vocabulary_single_source.py
"""

import ast
import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402
from lib.cert_vocab import (  # noqa: E402
    OSHA_TYPES, RECOGNIZED_SST_TYPES, SST_CLASS_TYPES, SST_UNSPECIFIED,
)
from lib.logbook import ll196  # noqa: E402
from lib.statistical_engine import score  # noqa: E402

CANONICAL = {"SST_FULL", "SST_LIMITED", "SST_SUPERVISOR", "SST_TEMPORARY"}
# The three-member set that was hardcoded twice. Any collection containing
# exactly these and not SST_TEMPORARY is the defect, whatever it is called.
TRUNCATED = {"SST_FULL", "SST_LIMITED", "SST_SUPERVISOR"}


class TheVocabulary(unittest.TestCase):

    def test_it_has_the_four_members(self):
        self.assertEqual(set(SST_CLASS_TYPES), CANONICAL)

    def test_SST_TEMPORARY_is_one_of_them(self):
        """The member whose absence produced the contradiction."""
        self.assertIn("SST_TEMPORARY", SST_CLASS_TYPES)

    def test_recognized_adds_only_the_unreadable_class(self):
        self.assertEqual(set(RECOGNIZED_SST_TYPES), CANONICAL | {SST_UNSPECIFIED})

    def test_unspecified_is_not_a_legible_class(self):
        """It means "an SST card is present but its class could not be read" --
        it satisfies the OSHA baseline and must never count as class-confirmed."""
        self.assertNotIn(SST_UNSPECIFIED, SST_CLASS_TYPES)

    def test_osha_types_are_unchanged(self):
        self.assertEqual(set(OSHA_TYPES), {"OSHA_10", "OSHA_30", "OSHA_UNSPECIFIED"})

    def test_the_set_is_immutable(self):
        """Three modules share this object. A consumer doing `.add()` or
        `.discard()` on a mutable set would edit the vocabulary for all of them
        at runtime, which is a worse version of the bug being fixed."""
        self.assertIsInstance(SST_CLASS_TYPES, frozenset)
        self.assertIsInstance(OSHA_TYPES, frozenset)


class AllThreeConsumersShareOneObject(unittest.TestCase):
    """Not "hold equal values" -- ARE the same object. Equality would pass for
    two independent literals that happen to match today."""

    def test_server_imports_it(self):
        self.assertIs(server.SST_CLASS_TYPES, SST_CLASS_TYPES)

    def test_ll196_imports_it(self):
        self.assertIs(ll196._SST_CERT_TYPES, SST_CLASS_TYPES)

    def test_score_imports_it(self):
        self.assertIs(score.SST_CLASS_TYPES, SST_CLASS_TYPES)

    def test_the_gate_and_the_attestation_now_agree_about_a_temporary_card(self):
        """THE CONTRADICTION, stated as the two verdicts it produced."""
        self.assertIn("SST_TEMPORARY", server.RECOGNIZED_SST_TYPES)   # gate: admitted
        self.assertIn("SST_TEMPORARY", ll196._SST_CERT_TYPES)         # PDF: counted


def _string_set_literals(path):
    """Every set/tuple/list/frozenset of plain strings in a file, as sets.

    Read with `ast` rather than a regex: a literal split across lines, or
    wrapped in frozenset(), is the same defect and a line-based search misses
    both.
    """
    # utf-8-SIG: backend/test_peer_cohort.py carries a BOM, and ast.parse on
    # BOM-prefixed text raises. Skipping unparseable files would quietly shrink
    # the sweep's reach; decoding the BOM away keeps every file in it.
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    # A literal wrapped in frozenset(...) is ONE definition, not two. Walking
    # naively yields the Call and the Set inside it, which double-counts every
    # frozenset in the file -- and made the "defined exactly once" assertion
    # read 2 for a file that defines it once.
    wrapped = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ("frozenset", "set") and len(node.args) == 1
                and isinstance(node.args[0], (ast.Set, ast.Tuple, ast.List))):
            wrapped.add(id(node.args[0]))
    out = []
    for node in ast.walk(tree):
        elts = None
        if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
            if id(node) in wrapped:
                continue          # counted via its frozenset() wrapper
            elts = node.elts
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in ("frozenset", "set") and len(node.args) == 1
              and isinstance(node.args[0], (ast.Set, ast.Tuple, ast.List))):
            elts = node.args[0].elts
        if not elts:
            continue
        vals = [e.value for e in elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if len(vals) == len(elts) and vals:
            out.append(set(vals))
    return out


class NoSecondDefINITIONAnywhere(unittest.TestCase):
    """KEYED ON THE MEMBERS, NOT THE IDENTIFIER.

    `_SST_CERT_TYPES` was one of the two copies. Asserting that name is gone
    would pass the moment somebody wrote the same three strings under any other
    name -- which is precisely how a copy gets reintroduced: not by restoring a
    deleted constant, but by someone inlining the list they see in a docstring.
    """

    def _python_files(self):
        skip = {"__pycache__", ".venv", "venv", "node_modules"}
        for p in BACKEND.rglob("*.py"):
            if any(part in skip for part in p.parts):
                continue
            if p.parent.name == "tests":
                continue          # this file names both sets on purpose
            yield p

    def test_no_file_carries_the_truncated_three_member_set(self):
        """The exact shape of the bug: the three legible classes with
        SST_TEMPORARY missing."""
        offenders = []
        for p in self._python_files():
            for lit in _string_set_literals(p):
                if lit == TRUNCATED:
                    offenders.append(str(p.relative_to(BACKEND)))
        self.assertEqual(offenders, [], "a truncated SST set reappeared")

    def test_only_cert_vocab_defines_the_canonical_set(self):
        """One address. A second literal holding all four is not wrong today,
        but it is the next copy to drift when a fifth class is added."""
        offenders = []
        for p in self._python_files():
            if p.relative_to(BACKEND) == Path("lib/cert_vocab.py"):
                continue
            for lit in _string_set_literals(p):
                if lit == CANONICAL:
                    offenders.append(str(p.relative_to(BACKEND)))
        self.assertEqual(offenders, [], "the vocabulary is defined twice")

    def test_the_sweep_actually_reads_files(self):
        """A scan that silently matched nothing would pass forever. It must find
        the canonical set exactly once, in cert_vocab itself."""
        found = [lit for lit in _string_set_literals(BACKEND / "lib" / "cert_vocab.py")
                 if lit == CANONICAL]
        self.assertEqual(len(found), 1)
        self.assertGreater(len(list(self._python_files())), 20)

    def test_ll196_binds_the_name_to_the_IMPORT_not_a_literal(self):
        """READ AS CODE, NOT AS TEXT.

        This was a substring check for `_SST_CERT_TYPES = ("SST_FULL"` and it
        FAILED -- on the comment directly above the fix, which quotes the old
        line so a reader knows what changed. A source assertion matching prose
        ABOUT the thing instead of the thing: the fifth time on this project,
        and the reason test_absence_literals_are_specific exists.

        The AST cannot see a comment.
        """
        path = BACKEND / "lib" / "logbook" / "ll196.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))

        imported = any(
            isinstance(n, ast.ImportFrom) and n.module == "lib.cert_vocab"
            and any(a.name == "SST_CLASS_TYPES" for a in n.names)
            for n in ast.walk(tree)
        )
        self.assertTrue(imported, "ll196 does not import the shared vocabulary")

        for n in ast.walk(tree):
            if not isinstance(n, ast.Assign):
                continue
            names = [t.id for t in n.targets if isinstance(t, ast.Name)]
            if "_SST_CERT_TYPES" not in names:
                continue
            self.assertIsInstance(
                n.value, ast.Name,
                "_SST_CERT_TYPES is bound to a literal again, not the import")
            self.assertEqual(n.value.id, "SST_CLASS_TYPES")


class TheImportDirectionIsSafe(unittest.TestCase):
    """cert_vocab must import nothing of ours, or the circularity it exists to
    avoid comes back through it."""

    def test_cert_vocab_imports_no_project_module(self):
        tree = ast.parse((BACKEND / "lib" / "cert_vocab.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.fail(f"cert_vocab imports {node.names[0].name}")
            if isinstance(node, ast.ImportFrom):
                self.fail(f"cert_vocab imports from {node.module}")

    def test_server_still_exports_the_names_it_always_did(self):
        """Callers elsewhere read these off server. Moving the definition must
        not move the names."""
        for name in ("SST_CLASS_TYPES", "SST_UNSPECIFIED", "RECOGNIZED_SST_TYPES",
                     "OSHA_TYPES"):
            self.assertTrue(hasattr(server, name), name)


class TheGateBehaviourIsUnchangedForEveryOtherShape(unittest.TestCase):
    """Widening a set is only safe if it widens exactly one thing."""

    def _validate(self, cert_type, exp=None):
        w = {"certifications": [{"type": cert_type, "expiration_date": exp}]}
        return server.validate_worker_certifications(w)

    def test_an_unreadable_class_still_satisfies_the_osha_baseline(self):
        out = self._validate(SST_UNSPECIFIED)
        self.assertTrue(out["cleared"])

    def test_a_worker_with_no_certs_is_still_blocked_on_osha(self):
        out = server.validate_worker_certifications({"certifications": []})
        self.assertFalse(out["cleared"])
        self.assertIn("MISSING_OSHA", [b["type"] for b in out["blocks"]])

    def test_an_osha_10_alone_still_clears_the_baseline(self):
        self.assertTrue(self._validate("OSHA_10")["cleared"])

    def test_a_temporary_card_satisfies_the_baseline_as_it_always_did(self):
        """Unchanged at the gate -- SST_CLASS_TYPES already had it there. This
        pins that the widening did not alter the one place that was correct."""
        self.assertTrue(self._validate("SST_TEMPORARY")["cleared"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
