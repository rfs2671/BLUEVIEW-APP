"""THE CHAIN IS GONE. THIS IS WHAT IS LEFT TO SAY ABOUT IT.

── WHAT THIS FILE USED TO BE ──────────────────────────────────────────────

A census. It read every arm of `generate_single_logbook_html`'s per-type chain,
every schema in `lib/legal_render`, and every type in the registry, and refused
three things:

  * a CONVERTED type keeping its old branch -- dead code that looks alive, and
    the next reader to fix a defect on that document fixes the copy nobody
    prints;
  * an UNCONVERTED type with no branch -- the engine's fall-through reaching a
    generic arm that printed a title and the word Status on a statutory record;
  * more than one type in the overlap window without somebody counting it.

── AND WHY IT IS NOT THAT ANY MORE ────────────────────────────────────────

All thirteen types are declared and all thirteen arms are deleted. The chain
does not exist, so two of those three refusals have no subject: there is no
branch to shadow and no unconverted type to strand. `BRANCHED` is empty, and
every set difference against an empty set passes while proving nothing -- which
is the exact vacuity this file was written to refuse, so it refuses it about
itself.

THE THIRD CLAIM SURVIVES AND IS WORTH MORE THAN THE OTHER TWO EVER WERE: the
chain must not grow back. Thirteen branches came from "we will delete it
later", and the cheapest moment to refuse the fourteenth is before it is
written.

── SO THE FILE IS NOW TWO ASSERTIONS AND A FLOOR ──────────────────────────

Every defined type has a schema. Nothing in the filed renderer switches on
`log_type`. And the registry is non-empty, because both of those pass
gloriously on nothing.
"""

from __future__ import annotations

import ast
import io
import os
import re
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from lib import legal_render  # noqa: E402

_SRC = io.open(BACKEND / "server.py", encoding="utf-8").read()
_TREE = ast.parse(_SRC)


def _filed_renderer() -> str:
    node = next(n for n in ast.walk(_TREE)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "generate_single_logbook_html")
    return "".join(
        _SRC.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])


#: Every type the app defines. The registry is the product's own list.
DEFINED = {t["key"] for t in server.LOGBOOK_TYPE_REGISTRY}

#: Every type the declarative engine has a schema for.
CONVERTED = set(legal_render.CONVERTED_TYPES)


class TheCensusFoundSomethingToCompare(unittest.TestCase):
    """THE VACUITY GUARD. Both assertions below are about `DEFINED`, and an
    empty registry satisfies them without meaning anything."""

    def test_the_registry_was_read(self):
        self.assertGreaterEqual(len(DEFINED), 12)

    def test_the_renderer_was_read(self):
        self.assertGreater(len(_filed_renderer()), 2000)


class EveryDefinedTypeHasASchema(unittest.TestCase):

    def test_nothing_is_stranded(self):
        """THE CLAIM THE GENERIC ARM USED TO ABSORB.

        A type with no schema reaches the not-configured notice -- a document
        that says it is NOT the record and names what is missing. That is the
        right behaviour for a retired type with live records, and the wrong
        one for a type the product currently offers: filing a logbook whose
        PDF cannot print it is a hole nobody would find until an inspector
        asked.
        """
        stranded = sorted(DEFINED - CONVERTED)
        self.assertEqual(
            stranded, [],
            f"these types can be filed and cannot be printed: {stranded}. "
            f"Their PDF is the not-configured notice, which says in words "
            f"that it is not the record.")

    def test_and_the_engine_declines_only_what_it_has_no_schema_for(self):
        """THE PREMISE OF THE ASSERTION ABOVE. If `render` ever learned to
        decline a type it HAS a schema for, every one of the thirteen would
        reach the notice on the day it did."""
        self.assertIsNone(legal_render.render("not_a_log_type", [], {}))
        src = io.open(BACKEND / "lib" / "legal_render" / "engine.py",
                      encoding="utf-8").read()
        body = src[src.index("def render("):]
        self.assertEqual(body.count("return None"), 1)


class TheChainDoesNotGrowBack(unittest.TestCase):
    """THIRTEEN BRANCHES CAME FROM 'WE WILL DELETE IT LATER'.

    The cheapest moment to refuse the fourteenth is before it is written, and
    this is the only assertion in the suite positioned to do it."""

    def test_the_filed_renderer_switches_on_no_type(self):
        # ANCHORED AFTER THE DISPATCH, and the first run of this assertion is
        # why. `if log_type == "preshift_signin"` and its superintendent twin
        # appear ABOVE it, where the caller resolves the async work a
        # synchronous renderer cannot do -- signin signatures, an affirmation
        # count, the BC 3301.13.13 register. Those are not chain arms, and a
        # census that counts them reports the chain as growing back on a tree
        # where it is gone.
        #
        # FIFTH INSTANCE of this shape in the repository, and the second in
        # this very file.
        _fn = _filed_renderer()
        _after = _fn[_fn.index("if log_type in legal_render.CONVERTED_TYPES:"):]
        arms = re.findall(r'(?:el)?if log_type == "(\w+)"', _after)
        self.assertEqual(
            arms, [],
            f"a per-type branch is back in the filed renderer for {arms}. "
            f"Whatever it does belongs in that type's declaration: a "
            f"primitive, a formatter, or a key on the section. If it "
            f"genuinely cannot be declared, that is a finding about the "
            f"engine and it goes in the defect document -- not into an `if`.")

    def test_and_the_dispatch_is_still_the_thing_that_decides(self):
        """The other half: refusing a chain means nothing if the dispatch
        itself was removed."""
        self.assertIn("if log_type in legal_render.CONVERTED_TYPES:",
                      _filed_renderer())


if __name__ == "__main__":
    unittest.main(verbosity=2)
