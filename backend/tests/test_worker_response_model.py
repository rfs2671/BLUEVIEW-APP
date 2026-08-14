"""GET /workers/{id} 500'd for every worker created at a gate.

`WorkerResponse.company` was required and had no default. The check-in writer
deliberately stopped recording a worker-level company — register_and_checkin
says so where it builds the doc: "no `trade` / `company` here. Those are
per-project and live in worker_project_trades; a worker-level copy is what bled
across jobs."

So `WorkerResponse(**worker)` raised a pydantic ValidationError INSIDE the
handler, i.e. an unhandled 500, and the screen rendered its generic catch. The
LIST endpoint has no response_model and never validated, which is why the
roster listed workers whose detail screen could not open — that asymmetry is
the whole defect.

These build each writer's ACTUAL document shape and validate it, so a model
that drifts from a writer again fails here rather than on a jobsite.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server as S  # noqa: E402

_SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")
_NOW = datetime.now(timezone.utc)

# Transcribed from each `db.workers.insert_one` site.
WRITERS = {
    "register_and_checkin": {
        "name": "W", "phone": "", "osha_number": "", "osha_data": None,
        "osha_card_image": None, "selfie_image": None, "signature": None,
        "safety_orientations": [], "certifications": [], "admin_id": "a",
        "company_id": "c", "status": "active", "created_at": _NOW,
        "updated_at": _NOW, "is_deleted": False,
    },
    "checkin_submit": {
        "name": "W", "phone": "p", "admin_id": "a", "company_id": "c",
        "created_at": _NOW, "updated_at": _NOW, "status": "active",
        "is_deleted": False,
    },
    "workers_register": {
        "name": "W", "phone": "p", "trade": "T", "company": "C",
        "device_id": None, "created_at": _NOW, "is_deleted": False,
    },
    "post_workers": {
        "name": "W", "phone": "p", "trade": "T", "company": "C",
        "device_id": None, "status": "active", "created_at": _NOW,
        "updated_at": _NOW, "certifications": [], "signature": None,
        "is_deleted": False, "company_id": "c",
    },
}


class TheModelMatchesEveryWriter(unittest.TestCase):
    def test_every_writer_validates(self):
        for label, doc in WRITERS.items():
            with self.subTest(writer=label):
                S.WorkerResponse(id="x", **doc)   # must not raise

    def test_company_and_trade_are_optional(self):
        """The per-project ruling showing through. A worker-level copy is what
        bled across jobs, so the model must not demand one."""
        for f in ("company", "trade"):
            self.assertFalse(S.WorkerResponse.model_fields[f].is_required(), f)

    def test_the_gate_writer_still_records_neither(self):
        """If that writer ever starts setting them again, this fails and the
        model's optionality gets re-decided rather than silently outliving its
        reason."""
        i = _SRC.index("# Create new worker with full data.")
        block = _SRC[i:i + 900]
        self.assertIn("no `trade` / `company` here", block)
        self.assertNotIn('"company":', block)
        self.assertNotIn('"trade":', block)

    def test_only_id_and_name_are_required(self):
        req = {f for f, i in S.WorkerResponse.model_fields.items() if i.is_required()}
        self.assertEqual(req, {"id", "name"})

    def test_the_handler_still_constructs_the_model_in_process(self):
        """`WorkerResponse(**...)` inside the handler makes a mismatch a 500,
        not a 422. Pinned so the failure mode stays understood."""
        fn = _SRC[_SRC.index('@api_router.get("/workers/{worker_id}"'):]
        fn = fn[:fn.index("@api_router.put")]
        self.assertIn("WorkerResponse(**serialize_id(worker))", fn)


class TheListEndpointStillDoesNotValidate(unittest.TestCase):
    """The asymmetry that hid this: the list returns raw documents, the detail
    validates. Recorded rather than changed — adding a response_model to the
    list would have turned a working screen into a broken one."""

    def test_the_list_has_no_response_model(self):
        fn = _SRC[_SRC.index('@api_router.get("/workers")'):]
        fn = fn[:fn.index("@api_router.post")]
        self.assertNotIn("response_model", fn.split("\n")[0])


class NoOtherResponseModelDemandsWhatNoWriterProduces(unittest.TestCase):
    """Swept every response_model in the app. Reported, not blind-fixed."""

    def test_nfc_tag_info_is_populated_with_fallbacks(self):
        """Its four required fields all have defaults at the call site, so a
        tag with no location_description cannot 500."""
        fn = _SRC[_SRC.index('@api_router.get("/nfc-tags/{tag_id}/info"'):]
        fn = fn[:fn.index("return NfcTagInfo") + 400]
        self.assertIn('tag.get("location_description", "Check-In Point")', fn)
        self.assertIn('"Unknown Project"', fn)

    def test_subcontractor_response_requires_contact_name(self):
        """NOW FIXED AT THE SEED, not at the model — the ruling was that the
        model is right and every real writer already satisfies it.

        This previously asserted the seed OMITTED contact_name, recording the
        defect. It now asserts the opposite. The model's requirement is
        unchanged, which is the point: loosening it to accommodate seed data
        would have weakened a contract real writers already meet.

        Full coverage of the guard and the seeded document lives in
        tests/test_startup_seed_guard.py."""
        self.assertTrue(
            S.SubcontractorResponse.model_fields["contact_name"].is_required())
        i = _SRC.index("# 6. Create test subcontractor")
        seed = _SRC[i:i + 900]
        self.assertIn('"contact_name"', seed)
