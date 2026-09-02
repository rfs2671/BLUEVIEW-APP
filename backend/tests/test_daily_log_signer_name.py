"""The filed daily log printed the role label where the man's name belongs.

THE DOCUMENT SAID "Superintendent (Superintendent)". Not a blank, not a crash —
the role label twice, in the slot reserved for the name of the person who
attested to the day. That is why it survived: it degrades instead of failing.

THE ROOT CAUSE is a dead model. `SignatureData` in server.py declares
`signer_name` and `signed_at` and has exactly one occurrence in the backend:
its own definition. `DailyLogCreate.superintendent_signature` is a bare
`Optional[Dict]`, so nothing validates against it and the frontend's real
SignaturePad payload — {paths, signerName, timestamp, affirmed, affirmedAt,
affirmedLang} — is stored verbatim. Readers were written against the DECLARED
shape rather than the STORED one, so every one of them reads a key no writer
has ever written.

The stored shape is not negotiable: thousands of filed documents carry it. The
readers are what is wrong. The precedent for reading both spellings is already
in this file — `render_signature_html` does
`sig.get("signer_name") or sig.get("signerName") or ""` — and these tests hold
the daily-log PDF to it.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server  # noqa: E402


# ── The fake db, same shape the other report tests use ───────────────────────

class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    async def to_list(self, *a, **k):
        return list(self._docs)


class _Coll:
    def __init__(self, docs=None, one=None):
        self._docs = docs or []
        self._one = one

    def find(self, *a, **k):
        return _Cursor(self._docs)

    async def find_one(self, *a, **k):
        return self._one

    async def to_list(self, *a, **k):
        return list(self._docs)


class _Db:
    def __init__(self, **colls):
        self._c = colls

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._c.get(n) or _Coll()


# ── The production payload ───────────────────────────────────────────────────
#
# EXACTLY what SignaturePad.js emits on confirm: paths / signerName / timestamp
# / affirmed / affirmedAt / affirmedLang. No `signer_name`. No `signed_at`.
# Twelve points so _signature_paths_to_svg's percentile bounding box engages,
# i.e. the ink renders and we exercise the branch a signed document takes.

def _ink():
    return [[{"x": float(i), "y": float(20 + (i % 3) * 5)} for i in range(12)]]


def _signature_pad_payload(name):
    return {
        "paths": _ink(),
        "signerName": name,
        "timestamp": "2026-08-19T15:01:10.726Z",
        "affirmed": True,
        "affirmedAt": "2026-08-19T15:01:10.726Z",
        "affirmedLang": "en",
    }


def _render(daily_log):
    """Call the real report renderer against a fake db and return the HTML."""
    db = _Db(
        projects=_Coll(one={"_id": "p1", "name": "8 Walworth St",
                            "address": "8 Walworth St"}),
        logbooks=_Coll(docs=[]),
        daily_logs=_Coll(one=daily_log),
        checkins=_Coll(docs=[]),
        workers=_Coll(docs=[]),
    )
    with patch.object(server, "db", db):
        return asyncio.run(server.generate_combined_report("p1", "2026-08-19"))


def _daily_log(sup=None, cp=None):
    log = {
        "_id": "dl1", "project_id": "p1", "date": "2026-08-19",
        "weather": "clear", "worker_count": 3,
        "subcontractor_cards": [], "safety_checklist": {},
        "corrective_actions_na": True, "incident_log_na": True,
    }
    if sup is not None:
        log["superintendent_signature"] = sup
    if cp is not None:
        log["competent_person_signature"] = cp
    return log


class TheFiledPdfPrintsTheSignersName(unittest.TestCase):
    """THE ESSENTIAL ASSERTION. A daily log signed by a real man through the
    real SignaturePad must print HIS NAME on the filed document."""

    @classmethod
    def setUpClass(cls):
        cls.html = _render(_daily_log(
            sup=_signature_pad_payload("Roy Fishman"),
            cp=_signature_pad_payload("Michael Cespedes"),
        ))

    def test_the_superintendent_block_names_the_superintendent(self):
        self.assertIn("Superintendent (Roy Fishman):", self.html)

    def test_the_pdf_does_not_print_the_role_label_twice(self):
        """The live defect, stated as the operator saw it."""
        self.assertNotIn("Superintendent (Superintendent)", self.html)

    def test_the_cp_block_names_the_competent_person(self):
        self.assertIn("Competent Person (Michael Cespedes):", self.html)

    def test_the_cp_block_does_not_print_the_role_label_twice(self):
        self.assertNotIn("Competent Person (Competent Person)", self.html)


class BothSpellingsAreRead(unittest.TestCase):
    """Legacy documents may carry either spelling, so both must render. This
    is render_signature_html's rule, applied to the daily-log block."""

    def test_the_legacy_snake_case_name_still_prints(self):
        html = _render(_daily_log(
            sup={"paths": _ink(), "signer_name": "Legacy Lou"},
            cp={"paths": _ink(), "signer_name": "Legacy Cara"},
        ))
        self.assertIn("Superintendent (Legacy Lou):", html)
        self.assertIn("Competent Person (Legacy Cara):", html)

    def test_the_camelcase_name_wins_when_a_document_carries_both(self):
        """Both spellings on one record: snake_case first, matching
        render_signature_html's `signer_name or signerName` order exactly.
        Named so a future reader knows the order was chosen, not stumbled on."""
        html = _render(_daily_log(sup={
            "paths": _ink(), "signer_name": "Snake Sam", "signerName": "Camel Cam",
        }))
        self.assertIn("Superintendent (Snake Sam):", html)


class AnUnnamedSignatureIsNotGivenTheRoleAsAName(unittest.TestCase):
    """When no writer supplied a name, the document must say so by SAYING
    NOTHING — not by printing the role in the parenthetical, which reads as an
    assertion that a man named "Superintendent" signed."""

    def test_no_parenthetical_when_the_signature_carries_no_name(self):
        html = _render(_daily_log(sup={"paths": _ink()}))
        self.assertIn("Superintendent:", html)
        self.assertNotIn("Superintendent (", html)

    def test_no_parenthetical_for_the_cp_either(self):
        html = _render(_daily_log(cp={"paths": _ink()}))
        self.assertIn("Competent Person:", html)
        self.assertNotIn("Competent Person (", html)


class TheModelDescribesTheShapeThatIsActuallyStored(unittest.TestCase):
    """SignatureData validates nothing — it is documentation, and it was
    documenting a shape no writer produces. Kept and corrected rather than
    deleted: it is the only written record of the signature contract, and a
    reader who consults it must not be sent back to the same wrong keys."""

    def test_the_model_carries_the_field_names_the_frontend_writes(self):
        fields = set(server.SignatureData.model_fields)
        self.assertIn("signerName", fields)
        self.assertIn("timestamp", fields)

    def test_the_model_no_longer_declares_fields_no_writer_writes(self):
        fields = set(server.SignatureData.model_fields)
        self.assertNotIn("signed_at", fields,
                         "signed_at is written by no writer anywhere")

    def test_the_model_accepts_a_real_signature_pad_payload(self):
        """The point of the correction: what the app actually sends validates."""
        sig = server.SignatureData(**_signature_pad_payload("Roy Fishman"))
        self.assertEqual(sig.signerName, "Roy Fishman")

    def test_the_model_still_accepts_the_legacy_spelling(self):
        sig = server.SignatureData(signer_name="Legacy Lou", paths=_ink())
        self.assertEqual(sig.signer_name, "Legacy Lou")


if __name__ == "__main__":
    unittest.main()
