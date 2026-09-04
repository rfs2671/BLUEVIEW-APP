"""THE FIFTH SHAPE: an absence assertion whose literal is not the thing.

tests/source_text.py already closed one way an absence test can be about the
wrong text — it read the PROSE describing a rule instead of the code
implementing it, four times, twice after the shape had been written up. That
fix was mechanical rather than a reminder, and this is the same treatment for
the other half of the problem.

    self.assertNotIn("Pass", html)

`in` on a string is SUBSTRING containment, so this bans four characters, not a
result cell. It is satisfied — or broken — by anything that happens to contain
them: "Passed", "Bypass", "Password", a CSS class, an aria-label, a worker
called Passarelli. The assertion says one thing and checks another, and which
way it goes is luck:

  * A legitimate future addition containing the substring breaks a correct
    build, and the fix that gets reached for under time pressure is deleting
    the assertion.
  * A spelling the code actually uses but the literal does not match — "PASS"
    for "Pass" — leaves the banned thing on the page with the test green.

Neither happens when the literal is ANCHORED: `render_pass_cell(`, `>Pass<`,
`"result": "Pass"`, `pass_label =`. A syntactic anchor is the difference
between banning a construct and banning a word.

WHAT THIS FILE DOES. It reads the backend suite with `ast`, finds every
`assertNotIn` whose haystack it can PROVE is a string, and requires the needle
literal to carry an anchor or to be named below with a reason. Nothing here
inspects behaviour; it audits how the other tests are written, which is the
only place this defect lives.

WHAT IT DELIBERATELY DOES NOT COVER, and says so rather than implying
otherwise: an `assertNotIn` against a dict, a list or a set is EXACT membership
and is not this shape at all, so a bare key name there is correct and is not
flagged. The classifier only flags haystacks it can prove are strings, which
makes its reach a LOWER BOUND — `unclassified_count` is asserted so the number
is visible and a future refactor that hides every haystack behind a helper
cannot quietly empty this file out.

A NEIGHBOUR, REPORTED AS A LEAD AND NOT ADDRESSED HERE. Six assertions across
five files still hand-roll their own comment stripper instead of going through
tests/source_text.py — test_audit_production, test_notification_presets_shape,
test_ranker_reads_what_the_editor_writes (three), test_report_print_width. Each
strips ONE comment syntax, which is the half-covered shape that helper exists to
stop being re-derived per file; test_logbook_renderers' crew_name check was the
seventh and is converted in this change because its own docstring claimed
docstrings were handled and its stripper only removed `#` lines. The remaining
six are a different guard's job — several strip a partial slice deliberately —
and they are named here so the count is on the record rather than implied to be
zero.

Run:  python -m pytest tests/test_absence_literals_are_specific.py -q
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_TESTS = Path(__file__).resolve().parent

# A literal containing any of these bans a CONSTRUCT rather than a word: no
# longer identifier, no other casing and no unrelated sentence can contain it
# by accident. A bare token has none of them.
_ANCHORS = set(".()[]{}=:<>/\\\"'`;,|+*!?@#$%^&~ -\n\t")

# ── Haystacks this proves are strings ────────────────────────────────────────
# A name is source text if it is BOUND to one of these in the same module.
_STRING_CALLS = {
    "code_of", "read_text", "strip_python", "strip_js", "strip_css",
    # The OTHER way this suite gets source text: round-tripping a live object
    # through inspect/ast/textwrap instead of reading the file off disk. All
    # four return `str` by contract, and assertions written against them were
    # going unaudited purely because the classifier only knew the file-reading
    # spelling. `unparse` in particular is how the role-gate tests read a
    # function body without hard-coding its formatting.
    #
    # TWO BRANCHES ARRIVED AT THIS INDEPENDENTLY, which is the argument for it.
    # Each tripped the unclassified floor at exactly 400 -- the message that
    # says "if this has grown a lot, the classifier needs the new binding
    # shape" -- and each answered by teaching it rather than raising the
    # ceiling. One reached `getsource` alone, the other all four; this is the
    # union. Between them the floor fell to the 380s and ZERO new bare literals
    # surfaced, so this widens the guard's reach without relaxing it by a
    # single assertion.
    "unparse", "getsource", "dedent", "getdoc",
}
# ...or produced by one of the renderers, which return HTML strings.
_RENDER_PREFIXES = ("render", "generate", "_render", "_generate", "build_html")


def _call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    return getattr(f, "attr", None) or getattr(f, "id", None)


def _produces_string(node: ast.AST) -> bool:
    """True when this expression is provably a str."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.JoinedStr):
        return True
    # "\n".join(...) and "".join(...)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "join" and _produces_string(node.func.value):
            return True
    name = _call_name(node)
    if name is None:
        # X.replace(...) / X + Y where either side is a string
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return _produces_string(node.left) or _produces_string(node.right)
        return False
    if name in _STRING_CALLS:
        return True
    if name in ("replace", "strip", "lower", "upper", "format", "join"):
        return True
    if name == "read":
        return True
    if any(name.startswith(p) for p in _RENDER_PREFIXES):
        return True
    return False


def _string_names(tree: ast.AST) -> set[str]:
    """Every NAME in this module provably bound to a string."""
    out: set[str] = set()
    # Two passes, so `code = src.replace(...)` resolves after `src = read_text()`.
    for _ in range(2):
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None:
                continue
            is_str = _produces_string(value)
            if not is_str and isinstance(value, ast.Name):
                is_str = value.id in out
            if not is_str and isinstance(value, ast.Call):
                f = value.func
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                    is_str = f.value.id in out and f.attr in (
                        "replace", "strip", "lower", "upper", "format",
                    )
            if not is_str:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
    return out


def _haystack_is_string(hay: ast.AST, names: set[str]) -> bool:
    """Whether this assertNotIn haystack is provably source text.

    `_produces_string` alone cannot answer for a NAME — that needs the module's
    bindings — so the two are combined here, at the one place both are in hand.

    SLICING A STRING YIELDS A STRING, and that is the shape this helper was
    extracted to add. `SRC[i:nxt]` — a window cut out of a source file so an
    assertion can be about one function rather than the whole module — is a
    common haystack in this suite, and the classifier could not see through the
    subscript, so every assertion written that way went UNAUDITED. Three did.

    A SLICE ONLY. `docs[0]` and `d["key"]` are indexing, not slicing: the first
    is a list element and the second a dict value, and neither says anything
    about the type. Requiring `ast.Slice` keeps the proof honest — this
    recognises "a piece of a string", not "a piece of something".
    """
    if _produces_string(hay):
        return True
    if isinstance(hay, ast.Name):
        return hay.id in names
    if isinstance(hay, ast.Subscript) and isinstance(hay.slice, ast.Slice):
        return _haystack_is_string(hay.value, names)
    return False


class _Finding:
    __slots__ = ("file", "line", "literal")

    def __init__(self, file: str, line: int, literal: str) -> None:
        self.file, self.line, self.literal = file, line, literal

    def __repr__(self) -> str:  # pragma: no cover - only on failure
        return f"{self.file}:{self.line} assertNotIn({self.literal!r}, <string>)"


def _scan() -> tuple[list[_Finding], int, int]:
    """(bare findings, anchored count, unclassified count)."""
    bare: list[_Finding] = []
    anchored = 0
    unclassified = 0
    for path in sorted(_TESTS.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
            continue
        names = _string_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) != "assertNotIn":
                continue
            if len(node.args) < 2:
                continue
            needle, hay = node.args[0], node.args[1]
            if not (isinstance(needle, ast.Constant) and isinstance(needle.value, str)):
                continue
            if not _haystack_is_string(hay, names):
                unclassified += 1
                continue
            literal = needle.value
            if any(c in _ANCHORS for c in literal):
                anchored += 1
            else:
                bare.append(_Finding(path.name, node.lineno, literal))
    return bare, anchored, unclassified


# ── BARE BY DESIGN ───────────────────────────────────────────────────────────
#
# Each entry is (file, literal, reason). A bare literal is allowed only when
# banning the WORD is genuinely the claim — a name that must not appear at all
# in the file under test, in any form, so a longer identifier containing it
# would be a violation too and NOT a false alarm.
#
# The line number is deliberately absent: it would rot on every edit above it,
# and the claim is about the file and the word, not the position.
_BARE_BY_DESIGN: set[tuple[str, str]] = {
    # ── SENTINELS the test itself planted ────────────────────────────────────
    # The value exists in the document ONLY because the fixture put it there,
    # so any occurrence at all is the finding and there is nothing to anchor to.
    ("test_logbook_renderers.py", "PHANTOM"),
    ("test_report_six_defects.py", "ORIGINAL"),
    ("test_report_six_defects.py", "AMENDMENT"),
    ("test_source_text_helper.py", "forbidden"),
    ("test_text_format.py", "Sst12345678"),

    # ── BADGE WORDS ──────────────────────────────────────────────────────────
    # A rendered all-caps status token. The claim IS the word: this document
    # must not carry that badge in any position, and no longer identifier
    # containing it exists to false-alarm on.
    ("test_logbook_renderers.py", "UNSIGNED"),
    ("test_signature_affirmation.py", "UNAFFIRMED"),

    # ── VOCABULARY BANS ──────────────────────────────────────────────────────
    # The claim is literally about the WORD appearing in prose a human reads.
    # The GC-voice text must not talk in analyst vocabulary, and the kiosk's
    # affirm label must not name a toolbox talk in either language (#135 ruled
    # a worker does not sign one). Anchoring these would weaken them.
    ("test_pr50_defcon_gc_voice.py", "ratio"),
    ("test_pr50_defcon_gc_voice.py", "cohort"),
    ("test_pr50_defcon_gc_voice.py", "baseline"),
    ("test_pr50_defcon_gc_voice.py", "threshold"),
    ("test_kiosk_affirm_control.py", "toolbox"),
    ("test_kiosk_affirm_control.py", "charla"),

    # ── A SYMBOL THAT MUST NOT EXIST IN A MODULE, UNDER ANY SPELLING ─────────
    # Here the word IS the unit: a longer identifier containing it is the same
    # violation, not a false alarm, so anchoring would weaken the claim.
    #
    #   crew_name        server.py must not READ the phantom key anywhere.
    #   GraphEdge /      trade_taxonomy_v1.py must not know the signed rules
    #   build_sequence_  graph exists; either name appearing in any form is
    #     rules_v1       exactly the coupling being refused.
    #   opencv           the enhancement path must not pull cv2 in by any
    #                    route, including a vendored or re-exported one.
    ("test_logbook_renderers.py", "crew_name"),
    ("test_trade_taxonomy_chip_filter.py", "GraphEdge"),
    ("test_trade_taxonomy_chip_filter.py", "build_sequence_rules_v1"),
    ("test_photo_enhance.py", "opencv"),

    # ── A WHOLE SUBJECT, BANNED FROM A MODULE ────────────────────────────────
    # card_audit.py must not mention a toolbox confirmation AT ALL — if it ever
    # captures one, the row that hardcodes False has to read it instead. A
    # longer identifier containing "toolbox" is that same finding, not a false
    # alarm, which is what makes the word the right unit here.
    ("test_fix1_checkins_today_flags.py", "toolbox"),

    # ── A SYMBOL REMOVED IN AN OUTAGE, BANNED FROM RETURNING ────────────────
    # _read_client_minimum_supported read frontend/app.json at module scope in
    # an image that ships backend/ only, and its except handler called `logger`
    # ~280 lines before logger exists. NameError at import, crash loop, 502 on
    # every path.
    #
    # The word IS the unit here: a call site, a rename that keeps the stem, or
    # a helper wrapping it are all the same violation, not false alarms. That
    # is what makes this bare by design rather than anchorable.
    #
    # IT WAS CAUGHT LATE because the fix was pushed straight to main during the
    # outage, which skipped CI. CI would have flagged it on the way in.
    ("test_client_version_floor.py", "_read_client_minimum_supported"),

    # ── SURFACED BY THE SLICE CLASSIFIER ─────────────────────────────────────
    # Both were already written this way and both were UNAUDITED until
    # _haystack_is_string learned to see through `SRC[i:nxt]`. Neither is a
    # defect; both are the "symbol banned from a window" shape above, and they
    # are recorded here rather than anchored because the word is the unit.
    #
    #   _is_affirmed_signature   amend_logbook's body must not gate on the
    #                            ORIGINAL log's affirmation — the child carries
    #                            its own signature. A wrapper, a rename keeping
    #                            the stem, or a call through a helper are all
    #                            the same violation, not false alarms.
    #   with_transaction         the instance_seq count-then-insert is asserted
    #                            NON-atomic by reading the code. That test's own
    #                            message says "if this ever gains a transaction,
    #                            delete this test", so ANY spelling appearing in
    #                            the window is exactly the intended trigger.
    ("test_affirmation_enforced_on_submit.py", "_is_affirmed_signature"),
    ("test_instance_seq.py", "with_transaction"),

    # ── SURFACED BY THE inspect/ast SOURCE-TEXT SPELLING ─────────────────────
    # Twelve assertions of ONE shape, previously unaudited because the
    # classifier only knew `Path.read_text()` and not the other way this suite
    # reads code:
    #
    #     code = ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))
    #     self.assertNotIn("<symbol>", code)
    #
    # Every one bans a SYMBOL from one function's body — the category already
    # documented above under "a symbol that must not exist in a module, under
    # any spelling". The word is the right unit in each: a rename keeping the
    # stem, a call through a wrapper, or a longer identifier containing it are
    # the same violation, not false alarms. And each sits beside an assertIn on
    # the same `code`, which is the positive control that the haystack really is
    # that function's source.
    #
    #   ROLES_SCOPED_TO_ASSIGNED_PROJECTS / is_superintendent
    #        project_access_ok is the three-branch security rule; the
    #        create_logbook fix must not have widened it.
    #   _card_number_shape
    #        neither reader may re-implement the card rule it already had to
    #        scope to SST types once.
    #   to_query_id
    #        _record_client_version filters on the RAW id; a conversion
    #        appearing would make the test above stop being load-bearing.
    #   raise / HTTPException
    #        the CS attribution module describes and never blocks. Any raising
    #        at all is the finding.
    #   daily_jobsite / activities
    #        item_provenance must read only what was STORED, never compare
    #        against a CP log that can change afterwards.
    #   class_by_key
    #        osha_review_index must not rebuild the classification map.
    #   LOGBOOK_SIGNATURE_REQUIRES_AUTH
    #        the authenticated path injects rather than consulting the flag.
    #   unsafe_conditions / cs_applicable_items
    #        neither renderer may build its own item list.
    ("test_assigned_project_gate_roles.py", "ROLES_SCOPED_TO_ASSIGNED_PROJECTS"),
    ("test_assigned_project_gate_roles.py", "is_superintendent"),
    ("test_card_finding_both_reads.py", "_card_number_shape"),
    ("test_client_version_stamp.py", "to_query_id"),
    ("test_cs_attribution.py", "raise"),
    ("test_cs_attribution.py", "HTTPException"),
    ("test_cs_attribution.py", "daily_jobsite"),
    ("test_cs_attribution.py", "activities"),
    ("test_osha_cert_type_is_stored.py", "class_by_key"),
    ("test_public_signature_guard.py", "LOGBOOK_SIGNATURE_REQUIRES_AUTH"),
    ("test_superintendent_log.py", "unsafe_conditions"),
    ("test_superintendent_log.py", "cs_applicable_items"),

    # ── THE INVESTOR REPORT'S DROPPED BADGE ──────────────────────────────────
    # Same claim as the test_signature_affirmation.py entry above, on the other
    # document: the combined report must not carry the badge in any position.
    # It cannot usefully be anchored either way -- "AFFIRMED" is a SUBSTRING of
    # "UNAFFIRMED", so an anchor built around the shorter word matches the
    # longer one, and an anchor built around the longer sentence would pass on
    # a reworded banner that still accuses the signer.
    ("test_report_document_layout.py", "UNAFFIRMED"),

    # ── A SENTINEL THE FIXTURE PLANTED ───────────────────────────────────────
    # The base64 PNG magic prefix. It is in the document ONLY if item 1 pasted
    # the superintendent's signature blob in as body text, which is the whole
    # finding, so any occurrence at all is the violation and there is nothing
    # to anchor to.
    ("test_report_document_layout.py", "iVBORw0KGgo"),
}


class AbsenceLiteralsAreSpecific(unittest.TestCase):
    """Every string-haystack assertNotIn bans a construct, not a word."""

    def test_no_unjustified_bare_literal(self):
        bare, _anchored, _unclassified = _scan()
        offenders = [
            f for f in bare
            if (f.file, f.literal) not in _BARE_BY_DESIGN
        ]
        self.assertEqual(
            [], offenders,
            "assertNotIn against a STRING bans a substring, so a bare word is "
            "satisfied — or broken — by anything that happens to contain it. "
            "Anchor the literal (>Pass<, render_pass_cell(, \"result\": \"Pass\") "
            "or add it to _BARE_BY_DESIGN with a reason: " + repr(offenders),
        )

    def test_the_allowlist_does_not_rot(self):
        """An entry that no longer matches anything is a stale rule."""
        bare, _anchored, _unclassified = _scan()
        live = {(f.file, f.literal) for f in bare}
        stale = sorted(_BARE_BY_DESIGN - live)
        self.assertEqual(
            [], stale,
            "these _BARE_BY_DESIGN entries no longer match any assertNotIn — "
            "the assertion was anchored, moved or deleted: " + repr(stale),
        )

    def test_the_scanner_is_still_finding_things(self):
        """Every assertion above is vacuously true against an empty scan.

        The classifier only flags haystacks it can PROVE are strings, so a
        refactor that routes every source read through a helper it does not
        recognise would silently empty this file out and leave it green. These
        two floors fail loudly instead.
        """
        bare, anchored, unclassified = _scan()
        self.assertGreater(
            anchored, 15,
            f"the scanner found only {anchored} anchored assertNotIn calls "
            "against a string — it has stopped recognising source-text bindings",
        )
        self.assertGreater(
            len(bare) + anchored, 20,
            "the scanner classified almost nothing as a string haystack",
        )
        # A LOWER BOUND, stated. Most of these are dict / list membership,
        # which is exact and not this shape — but the count is asserted so a
        # sudden jump is visible rather than silent.
        #
        # 400 -> 410 with test_filed_log_photo_append.py, which asserts that a
        # server-minted photo row carries no `base64` and no `enhance_status`
        # key. That is dict membership — exact, and precisely the kind this
        # bucket exists to hold. The ceiling moves; the shape of the rule does
        # not.
        self.assertLess(
            unclassified, 410,
            f"{unclassified} assertNotIn haystacks could not be classified; "
            "if this has grown a lot, the classifier needs the new binding shape",
        )

    def test_an_anchored_literal_is_recognised_as_anchored(self):
        """The control: the rule must be able to tell the two apart."""
        self.assertTrue(any(c in _ANCHORS for c in 'render_pass_cell('))
        self.assertTrue(any(c in _ANCHORS for c in '>Pass<'))

    def test_a_slice_of_a_string_is_classified_as_a_string(self):
        """The control for the shape _haystack_is_string was extended to see.

        Without this the extension is invisible: it would silently stop
        recognising slices again and the only symptom would be `unclassified`
        drifting back up, which is exactly the kind of quiet emptying-out
        test_the_scanner_is_still_finding_things exists to prevent.

        The negative half matters as much as the positive: INDEXING must stay
        unclassified. `docs[0]` is a list element and `d["k"]` a dict value,
        and treating either as a string would flag correct exact-membership
        assertions as substring bans.
        """
        tree = ast.parse(
            "SRC = read_text()\n"
            "i = 0\n"
            "sliced = SRC[i:9]\n"
            "indexed = SRC[0]\n"
        )
        names = _string_names(tree)
        self.assertIn("SRC", names)
        body = {t.targets[0].id: t.value for t in tree.body}
        self.assertTrue(_haystack_is_string(body["sliced"], names))
        self.assertFalse(_haystack_is_string(body["indexed"], names))
        # A slice of something NOT known to be a string stays unclassified.
        other = ast.parse("x = unknown[1:2]\n").body[0].value
        self.assertFalse(_haystack_is_string(other, names))
        self.assertTrue(any(c in _ANCHORS for c in 'db.logbooks'))
        self.assertTrue(any(c in _ANCHORS for c in 'OSHA 40hr'))
        self.assertFalse(any(c in _ANCHORS for c in 'Pass'))
        self.assertFalse(any(c in _ANCHORS for c in 'crew_name'))

    def test_a_dict_haystack_is_not_flagged(self):
        """A bare key against a mapping is EXACT membership and is correct.

        Asserted by running the classifier over a synthetic module rather than
        by trusting the description of it.
        """
        mod = ast.parse(
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        body = {'a': 1}\n"
            "        self.assertNotIn('company', body)\n"
        )
        names = _string_names(mod)
        self.assertNotIn("body", names, "a dict literal is not a string binding")

    def test_a_source_haystack_is_flagged(self):
        """And the same classifier DOES see a source read."""
        mod = ast.parse(
            "from tests.source_text import code_of\n"
            "SRC = code_of('server.py')\n"
            "CODE = SRC.replace('x', 'y')\n"
        )
        names = _string_names(mod)
        self.assertIn("SRC", names)
        self.assertIn("CODE", names, "a derived string is still a string")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
