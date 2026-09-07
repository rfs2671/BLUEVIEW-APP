"""THE ELEVEN ITEMS ARE DECLARED TWICE. THIS IS THE CHECK THAT SAYS SO.

`frontend/src/utils/superintendentLogModel.js` opens with:

    A MIRROR OF backend/lib/logbook/superintendent_log.py, and the parity is
    asserted by superintendentLogModel.test.cjs, which reads the Python and
    compares the two lists.

THAT FILE HAS NEVER EXISTED. The docstring cited a test by name, in the module
whose whole subject is drift between two hand-maintained copies of a statutory
list, and nothing anywhere compared them.

AND THEY HAD ALREADY DRIFTED, ON THE FIELD THE DOCSTRING'S OWN ARGUMENT IS
ABOUT. Python's item 2 carries `"provenance": True` with a long comment
explaining that the flag must ship before the client half "because retrofitting
provenance onto filed records is impossible". The JavaScript item 2 does not
carry it. The client half was never built, and the reason the divergence went
unnoticed for its whole life is the sentence above.

── WHY THIS IS PYTHON AND NOT THE .cjs THE DOCSTRING NAMED ──────────────────

`CS_LOG_ITEMS` is an ESM `export const`, so a CommonJS test cannot require it
and would have to REGEX-PARSE BOTH SIDES. From here the Python list is imported
natively and exactly, and only the JavaScript is parsed -- one parser instead of
two, and the side whose declarations are load-bearing for the renderer is the
one read without interpretation.

The docstring has been corrected to name this file. A pointer that names the
wrong artifact is the §10 failure, and correcting it is half the fix; the other
half is that the artifact now exists.

── WHAT IS COMPARED, AND WHAT IS DELIBERATELY NOT ───────────────────────────

Every key the Python declares is either MIRRORED or NAMED IN `_PY_ONLY` with a
reason. That is the property that stops the next divergence: a key added to the
Python that the JavaScript does not carry fails here unless somebody writes down
why it is server-only. A test that compared a fixed list of fields would have
passed happily through `provenance` being added to one side.

── AND THE PARSE ITSELF IS GUARDED FIRST ────────────────────────────────────

`test_tenant_scope_census.py` reported a clean tree over an EMPTY WALK because
`ast.unparse` spells strings with single quotes and the check was written
against the source spelling. A parser that silently matches nothing satisfies
every comparison below it. So the first assertions here are about the parse:
ten items, every required key present, and the `sunsetOn` identifier RESOLVED to
a date rather than left as the literal token `COMPETENT_PERSON_SUNSET`.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib.logbook.superintendent_log import (  # noqa: E402
    COMPETENT_PERSON_SUNSET, ITEMS,
)

_JS = (_BACKEND.parent / "frontend" / "src" / "utils"
       / "superintendentLogModel.js").read_text(encoding="utf-8")

#: Python key -> JavaScript key, for the ones spelled differently.
_RENAMED = {"sunset_on": "sunsetOn", "starts_on": "startsOn"}

#: Keys the Python declares that the JavaScript deliberately does NOT carry,
#: each with its reason. NAMED, never inferred from absence: a count cannot
#: tell a deliberate exception from a field somebody forgot to mirror.
_PY_ONLY = {
    "citation": (
        "the section each item answers, printed under the item label by "
        "_superintendent_log_html and suppressed on the investor report via "
        "`legal_record`. It is rendered only server-side; no client screen "
        "shows a citation, so mirroring it would put a statutory reference in "
        "a file that never prints one and could drift unnoticed."
    ),
    "daily": (
        "`daily: False` on item 10 records that the weekly-meeting obligation "
        "is not a daily field, which is an argument addressed to the reader of "
        "the renderer about why a blank there must not teach the reader that "
        "blank is normal. The client never asks the question -- item 10 is "
        "`collected: False` and renders as a scope line -- so the flag has no "
        "client-side consumer to keep honest."
    ),
}

#: Required on every item, both sides. If the parser stops finding these the
#: comparisons below become vacuous rather than failing.
_REQUIRED = ("key", "number", "label", "attestable", "collected", "fields")


# ── A small reader for the JavaScript object literal ─────────────────────────
#
# NOT A COMMA SPLIT. Three labels contain commas ("Violations, stop work orders
# and summonses"), so splitting on them silently truncates a label and the
# comparison then fails for the wrong reason -- or worse, passes because both
# sides were read with the same broken rule. This scans values, respecting
# quotes and brackets.

def _js_consts() -> dict:
    return {m.group(1): m.group(2)
            for m in re.finditer(r"export const (\w+) = '([^']*)';", _JS)}


def _read_value(text: str, i: int, consts: dict):
    while i < len(text) and text[i] == " ":
        i += 1
    if text[i] == "'":
        j = text.index("'", i + 1)
        return text[i + 1:j], j + 1
    if text[i] == "[":
        j = text.index("]", i)
        inner = text[i + 1:j]
        return ([x.strip()[1:-1] for x in inner.split(",") if x.strip()], j + 1)
    j = i
    while j < len(text) and text[j] not in ",}":
        j += 1
    raw = text[i:j].strip()
    if raw == "true":
        return True, j
    if raw == "false":
        return False, j
    if raw.isdigit():
        return int(raw), j
    if raw in consts:
        return consts[raw], j
    return raw, j          # an unresolved identifier, surfaced not swallowed


def _js_items() -> list:
    consts = _js_consts()
    block = _JS[_JS.index("CS_LOG_ITEMS = Object.freeze(["):]
    block = block[:block.index("\n]);")]
    out = []
    for line in block.split("\n"):
        line = line.strip()
        if not (line.startswith("{") and "key:" in line):
            continue
        inner = line[1:line.rindex("}")]
        item, i = {}, 0
        while i < len(inner):
            m = re.compile(r"\s*(\w+):").match(inner, i)
            if not m:
                break
            value, i = _read_value(inner, m.end(), consts)
            item[m.group(1)] = value
            while i < len(inner) and inner[i] in ", ":
                i += 1
        out.append(item)
    return out


_JS_ITEMS = _js_items()
_JS_BY_KEY = {i.get("key"): i for i in _JS_ITEMS}
_PY_BY_KEY = {i["key"]: i for i in ITEMS}


class TheParseWorked(unittest.TestCase):
    """FIRST, BECAUSE A PARSER THAT MATCHED NOTHING PASSES EVERY TEST BELOW."""

    def test_ten_items_were_read_from_the_javascript(self):
        self.assertEqual(
            len(_JS_ITEMS), len(ITEMS),
            f"parsed {len(_JS_ITEMS)} JS items against {len(ITEMS)} Python "
            "items -- if the JS list was reformatted onto multiple lines this "
            "reader needs updating, and until then it is checking nothing")

    def test_every_parsed_item_carries_the_required_keys(self):
        for item in _JS_ITEMS:
            with self.subTest(item.get("key")):
                for key in _REQUIRED:
                    self.assertIn(key, item)

    def test_a_label_containing_a_comma_survived_the_reader(self):
        """The specific way a comma-splitting reader fails: it truncates at the
        first comma and both sides then disagree for a reason that has nothing
        to do with drift."""
        self.assertEqual(_JS_BY_KEY["dob_actions"]["label"],
                         "Violations, stop work orders and summonses")

    def test_the_sunset_identifier_was_resolved_and_not_left_as_a_token(self):
        self.assertEqual(_JS_BY_KEY["competent_person"]["sunsetOn"],
                         COMPETENT_PERSON_SUNSET)
        self.assertNotEqual(_JS_BY_KEY["competent_person"]["sunsetOn"],
                            "COMPETENT_PERSON_SUNSET")


class TheTwoListsAgree(unittest.TestCase):

    def test_the_same_items_in_the_same_order(self):
        self.assertEqual([i["key"] for i in ITEMS],
                         [i["key"] for i in _JS_ITEMS])

    def test_every_python_key_is_mirrored_or_named_as_server_only(self):
        """THE CLAUSE THAT STOPS THE NEXT DRIFT. A fixed list of compared
        fields would have let `provenance` be added to one side in silence,
        which is exactly what happened."""
        unaccounted = []
        for item in ITEMS:
            for key in item:
                if key in _PY_ONLY:
                    continue
                js_key = _RENAMED.get(key, key)
                if js_key not in _JS_BY_KEY[item["key"]]:
                    unaccounted.append(f'{item["key"]}.{key}')
        self.assertEqual(
            unaccounted, [],
            "the Python declares fields the JavaScript does not carry, and "
            "none of them is named in _PY_ONLY with a reason: "
            + ", ".join(unaccounted))

    def test_and_the_values_match(self):
        for item in ITEMS:
            js = _JS_BY_KEY[item["key"]]
            for key, value in item.items():
                if key in _PY_ONLY:
                    continue
                with self.subTest(f'{item["key"]}.{key}'):
                    self.assertEqual(js[_RENAMED.get(key, key)], value)

    def test_the_javascript_declares_nothing_the_python_does_not(self):
        """The other direction. A client-only field on a statutory item is a
        rule the renderer cannot see."""
        back = {v: k for k, v in _RENAMED.items()}
        for item in _JS_ITEMS:
            py = _PY_BY_KEY[item["key"]]
            for key in item:
                with self.subTest(f'{item["key"]}.{key}'):
                    self.assertIn(back.get(key, key), py)

    def test_the_sunset_constant_is_the_same_date_on_both_sides(self):
        self.assertEqual(_js_consts()["COMPETENT_PERSON_SUNSET"],
                         COMPETENT_PERSON_SUNSET)


class TheExemptionsAreRealAndReasoned(unittest.TestCase):

    def test_each_one_states_why(self):
        for key, reason in _PY_ONLY.items():
            with self.subTest(key):
                self.assertGreater(len(reason), 80,
                                   "an exemption without a reason is a hole")

    def test_the_exempt_keys_really_are_absent_from_the_javascript(self):
        """An exemption for a key the JS actually carries would be a licence to
        let that one drift."""
        for key in _PY_ONLY:
            for item in _JS_ITEMS:
                with self.subTest(f'{item["key"]}.{key}'):
                    self.assertNotIn(key, item)

    def test_and_each_is_declared_by_the_python_somewhere(self):
        """A stale exemption for a field nobody declares any more would sit
        here forever looking like a considered decision."""
        declared = {k for item in ITEMS for k in item}
        for key in _PY_ONLY:
            with self.subTest(key):
                self.assertIn(key, declared)


class TheDocstringNamesThisFile(unittest.TestCase):
    """The other half of the §8 fix. The claim that made the absence invisible
    was a POINTER, and a corrected pointer is worth as much as the artifact."""

    # `assertIn`/`assertNotIn` ON A 9KB FILE PRINTS THE WHOLE FILE on failure.
    # A gate whose output has to be scrolled past is one the reader learns to
    # skim, which is the same argument the tenant census makes about false
    # positives. Booleans with short messages.

    def test_the_javascript_no_longer_cites_a_test_that_does_not_exist(self):
        """A CORRECTION MARKER, NOT A BAN ON THE STRING.

        The first draft asserted the name was simply absent, and it failed on
        this change's OWN correction — the docstring now says "this sentence
        used to name superintendentLogModel.test.cjs, which has never existed",
        which is worth keeping: a reader who greps for the old name should land
        on the retraction rather than on nothing. `test_ledger_reach_is_stated_
        correctly.py` hit this exactly and settled it the same way. The question
        is whether an occurrence is MARKED AS RETRACTED, not whether it occurs.
        """
        markers = ("used to name", "has never existed", "never existed")
        for m in re.finditer(re.escape("superintendentLogModel.test.cjs"), _JS):
            window = _JS[max(0, m.start() - 400):m.start() + 200].lower()
            self.assertTrue(
                any(k.lower() in window for k in markers),
                "superintendentLogModel.js cites a test file that has never "
                f"existed, unretracted, at offset {m.start()}")

    def test_it_cites_this_one_instead(self):
        self.assertTrue(
            "test_superintendent_model_parity.py" in _JS,
            "superintendentLogModel.js does not name the test that checks it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
