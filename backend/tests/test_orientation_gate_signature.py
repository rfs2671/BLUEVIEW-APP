"""THE GATE WRITES A FULL DATA URL, AND NO TEST HAS EVER RENDERED ONE.

checkin.html does `canvas.toDataURL('image/png')` and posts the result as
`signature`. register_and_checkin stores that value verbatim into
`data.worker_signature` on the subcontractor_orientation logbook it creates.
So the shape that reaches the orientation PDF is:

    "data:image/png;base64,iVBORw0KGgo..."

a PREFIXED string. Every existing fixture uses the vector shape
`{"paths": [...]}`, a bare unprefixed base64 string, or None — which is why
two defects in the export survived to a field report:

1.  render_signature_html._img concatenates its own `data:image/png;base64,`
    prefix unconditionally, so a gate signature renders
    `src="data:image/png;base64,data:image/png;base64,iVBOR..."` — a broken
    image. _preshift_signature_cell, one function away, has the guard.

2.  The not-affirmed banner asserts the mark is an "inherited signature". For
    a gate signature that is FALSE: it was drawn on the spot, for that
    orientation, by that worker. Nothing on a bare string records provenance,
    so the renderer cannot know either way and must not assert it.

WHAT IS *NOT* CHANGED, AND MUST NOT BE. A bare string is still UNAFFIRMED.
_is_affirmed_signature stays `dict and affirmed is True`. The inherited
credential this app exists to catch — `workers.signature` copied onto a roster
row — is ALSO a bare string, indistinguishable from a gate capture. Making the
string shape count as affirmed would stamp "AFFIRMED for this document" on the
exact object the predicate was written to refuse, and would let one satisfy a
submission gate. The claim that is dropped is only the one the code cannot
support: WHERE the mark came from.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import server  # noqa: E402

# A 1x1 transparent PNG, exactly as the gate canvas emits it.
_RAW_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYPhfDwAChwGA60e6"
    "kgAAAABJRU5ErkJggg=="
)
_GATE_SIG = "data:image/png;base64," + _RAW_B64


class GateDataUrlRendersOnceTest(unittest.TestCase):
    """DEFECT 1 — the doubled prefix."""

    def test_prefixed_string_is_not_double_prefixed(self):
        html = server.render_signature_html(_GATE_SIG, "Worker Acknowledgment")
        self.assertNotIn("data:image/png;base64,data:", html)
        self.assertIn('src="' + _GATE_SIG + '"', html)

    def test_prefixed_string_carries_exactly_one_prefix(self):
        html = server.render_signature_html(_GATE_SIG, "Worker Acknowledgment")
        self.assertEqual(html.count("data:image/png;base64,"), 1)

    def test_unprefixed_string_still_gets_its_prefix(self):
        # The legacy shape must render exactly as it always has.
        html = server.render_signature_html(_RAW_B64, "CP Signature")
        self.assertIn('src="data:image/png;base64,' + _RAW_B64 + '"', html)
        self.assertNotIn("base64,data:", html)

    def test_prefixed_data_key_on_a_dict_is_not_double_prefixed(self):
        # {data: "<data url>"} reaches the same _img. Same rule.
        html = server.render_signature_html({"data": _GATE_SIG}, "CP Signature")
        self.assertNotIn("data:image/png;base64,data:", html)
        self.assertIn('src="' + _GATE_SIG + '"', html)

    def test_matches_preshift_cell_convention(self):
        """ONE CONVENTION, NOT TWO. _preshift_signature_cell already solved
        this; _img must reach the identical src for the identical input."""
        cell = server._preshift_signature_cell({"worker_signature": _GATE_SIG})
        rendered = server.render_signature_html(_GATE_SIG, "Worker Acknowledgment")
        self.assertIn('src="' + _GATE_SIG + '"', cell)
        self.assertIn('src="' + _GATE_SIG + '"', rendered)


class NoUnsupportedProvenanceClaimTest(unittest.TestCase):
    """DEFECT 2 — the banner asserts an origin the object does not record."""

    def test_gate_signature_is_not_called_inherited(self):
        html = server.render_signature_html(_GATE_SIG, "Worker Acknowledgment")
        self.assertNotIn("inherited", html.lower())

    def test_no_shape_is_called_inherited(self):
        # The renderer has no provenance field for ANY shape, so the claim is
        # unsupportable everywhere, not only for the gate string.
        for sig in (
            _GATE_SIG,
            _RAW_B64,
            {"data": _RAW_B64},
            {"paths": [[{"x": 1, "y": 2}]], "signerName": "Ada CP"},
            {"signerName": "Ada", "affirmed": False},
            {},
        ):
            with self.subTest(sig=sig):
                self.assertNotIn(
                    "inherited", server._signature_affirmation_html(sig).lower()
                )

    def test_unaffirmed_verdict_is_unchanged(self):
        """THE DEFICIENCY IS STILL REPORTED. Only the origin claim is dropped."""
        for sig in (
            _GATE_SIG,
            _RAW_B64,
            {"data": _RAW_B64},
            {"paths": [[{"x": 1, "y": 2}]], "signerName": "Ada CP"},
            {"signerName": "Ada", "affirmed": False},
            {},
        ):
            with self.subTest(sig=sig):
                self.assertIn("UNAFFIRMED", server._signature_affirmation_html(sig))

    def test_affirmed_still_affirmed(self):
        html = server.render_signature_html(
            {"data": _RAW_B64, "affirmed": True, "affirmedAt": "2026-07-29T13:45:06Z"},
            "CP Signature",
        )
        self.assertIn("AFFIRMED for this document", html)
        self.assertNotIn("UNAFFIRMED", html)


class PredicateIsUnchangedTest(unittest.TestCase):
    """THE GUARD ON THE FIX ITSELF.

    The tempting fix for the field report is 'a gate signature is affirmed'.
    It is the wrong one and these assertions are what stop it being made
    later. A bare string cannot be told apart from an inherited credential.
    """

    def test_gate_string_is_still_not_affirmed(self):
        self.assertFalse(server._is_affirmed_signature(_GATE_SIG))
        self.assertFalse(server._is_affirmed_signature(_RAW_B64))

    def test_gate_string_still_has_ink(self):
        # It is a real mark — it just carries no affirmation record.
        self.assertTrue(server._has_signature_ink(_GATE_SIG))

    def test_affirmed_predicate_still_requires_dict_and_true(self):
        self.assertTrue(server._is_affirmed_signature({"affirmed": True}))
        self.assertFalse(server._is_affirmed_signature({"affirmed": "yes"}))
        self.assertFalse(server._is_affirmed_signature({}))
        self.assertFalse(server._is_affirmed_signature(None))


class _Collection:
    """Records the NAME of every collection touched, so the test can assert
    what was NOT read as well as what was."""

    def __init__(self, name, doc, log):
        self._name = name
        self._doc = doc
        self._log = log

    async def find_one(self, query=None, projection=None, sort=None):
        self._log.append(self._name)
        return self._doc

    def find(self, *a, **k):
        self._log.append(self._name)
        return self

    def sort(self, *a, **k):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def to_list(self, *a, **k):
        return []


class _Db:
    def __init__(self):
        self.touched = []
        self._cols = {
            "projects": _Collection(
                "projects", {"name": "Site A", "address": "1 Main St"}, self.touched),
            # If the renderer ever reaches for an enrollment signature, THIS is
            # the collection it would have to touch — and it hands back a mark
            # deliberately different from the one on the document.
            "workers": _Collection(
                "workers",
                {"_id": "w1", "name": "juan perez",
                 "signature": "data:image/png;base64,ENROLLMENTNOTTHEGATEMARK"},
                self.touched),
        }

    def __getattr__(self, name):
        cols = self.__dict__["_cols"]
        if name not in cols:
            cols[name] = _Collection(name, None, self.__dict__["touched"])
        return cols[name]


class OrientationPdfUsesItsOwnSignatureTest(unittest.TestCase):
    """READING (a) vs (b), pinned as a regression.

    The orientation branch of generate_single_logbook_html must render the
    signature stored on THAT logbook document and nothing else. No enrollment
    signature off `workers`, no previous orientation's mark.
    """

    def setUp(self):
        self._orig_db = server.db
        self._orig_tqid = server.to_query_id
        self.db = _Db()
        server.db = self.db
        server.to_query_id = lambda v: v

    def tearDown(self):
        server.db = self._orig_db
        server.to_query_id = self._orig_tqid

    @staticmethod
    def _orientation_doc(worker_sig):
        return {
            "_id": "abc",
            "log_type": "subcontractor_orientation",
            "project_id": "p1",
            "project_name": "Site A",
            "date": "2026-09-01",
            "status": "draft",
            "cp_signature": None,
            "cp_name": None,
            "data": {
                "worker_id": "w1",
                "worker_name": "juan perez",
                "worker_company": "Acme",
                "worker_trade": "laborer",
                "worker_signature": worker_sig,
                "checklist": {"ppe": True},
                "completed_at": "2026-09-01T12:00:00",
            },
        }

    def _render(self, worker_sig):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                server.generate_single_logbook_html(self._orientation_doc(worker_sig))
            )
        finally:
            loop.close()

    def test_gate_signature_renders_on_the_orientation_pdf(self):
        html = self._render(_GATE_SIG)
        self.assertIn('src="' + _GATE_SIG + '"', html)
        self.assertNotIn("data:image/png;base64,data:", html)

    def test_no_enrollment_signature_is_substituted(self):
        """READING (a), refuted and kept refuted. The bytes on the page are the
        bytes on the record — the renderer never falls back to workers.signature
        or to any other document."""
        html = self._render(_GATE_SIG)
        self.assertNotIn("ENROLLMENTNOTTHEGATEMARK", html)
        # `projects` is the only collection the orientation branch may consult.
        self.assertEqual(self.db.touched, ["projects"])

    def test_orientation_pdf_makes_no_inheritance_claim(self):
        html = self._render(_GATE_SIG)
        self.assertNotIn("inherited", html.lower())

    def test_null_worker_signature_still_prints_unsigned(self):
        # The manual-entry path writes null. That honesty is not touched.
        html = self._render(None)
        self.assertIn("UNSIGNED", html)


if __name__ == "__main__":
    unittest.main()
