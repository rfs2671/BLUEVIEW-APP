"""DAILY SIGNATURE AFFIRMATION — B10, the record and the sheet.

The worker signed ONCE, at orientation. Printing that image against today's date
asserts he signed today's sheet: the same overstatement as the "UNAFFIRMED —
inherited signature" warning already carried on the CP's signatures. Affirming at
the gate each morning turns a stamp into a real daily attestation.

Behavioural where it can be. Five source assertions on this project have been
satisfied by prose ABOUT the thing rather than the thing, the last one by a
comment saying it had been removed — so the render states and the age rule are
executed, and the source assertions that remain are anchored inside one function
and matched on code, never on a word that could appear in an explanation.
"""
from __future__ import annotations

import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

_SRC = Path(server.__file__).read_text(encoding="utf-8")


def _fn(name: str) -> str:
    """One function's source, so a match cannot come from somewhere else."""
    body = _SRC[_SRC.index(name):]
    return body[:body.index("@api_router", 10)]


class TestTheSheetSaysWhichOfThreeThingsIsTrue(unittest.TestCase):
    """Blank cannot be told apart from a column nobody filled, and this document
    has never claimed a worker signed before."""

    def test_affirmed_prints_the_signature(self):
        cell = server._preshift_signature_cell(
            {"worker_signature": "iVBORw0KG", "signature_affirmed": True})
        self.assertIn("<img", cell)
        self.assertIn("data:image/png;base64,iVBORw0KG", cell)

    def test_a_data_url_is_not_double_prefixed(self):
        cell = server._preshift_signature_cell(
            {"worker_signature": "data:image/png;base64,iVBORw0KG",
             "signature_affirmed": True})
        self.assertEqual(cell.count("data:image/png;base64,"), 1)

    def test_on_file_but_not_affirmed_says_so_and_prints_nothing(self):
        cell = server._preshift_signature_cell(
            {"worker_signature": "iVBORw0KG", "signature_affirmed": False})
        self.assertIn("NOT AFFIRMED", cell)
        self.assertNotIn("<img", cell)

    def test_nothing_on_file_is_a_DIFFERENT_fact(self):
        cell = server._preshift_signature_cell({"signature_affirmed": True})
        self.assertIn("NO SIGNATURE ON FILE", cell)
        self.assertNotIn("NOT AFFIRMED", cell)

    def test_no_state_is_ever_blank(self):
        for row in ({}, {"worker_signature": ""}, {"worker_signature": "   "},
                    {"worker_signature": "x"},
                    {"worker_signature": "x", "signature_affirmed": True}):
            with self.subTest(row=row):
                cell = server._preshift_signature_cell(row)
                visible = re.sub(r"<[^>]+>", "", cell).strip()
                self.assertTrue(visible or "<img" in cell,
                                "a blank cell reads as a column nobody filled")

    def test_the_legacy_inline_key_still_renders(self):
        """Two storage shapes, one output: some rows carry `signature` rather
        than `worker_signature`."""
        cell = server._preshift_signature_cell(
            {"signature": "iVBORw0KG", "signature_affirmed": True})
        self.assertIn("<img", cell)


class TestTheAgeIsShownAndNeverEnforced(unittest.TestCase):
    def test_the_earliest_orientation_is_when_he_signed(self):
        """A later orientation on another project did not re-capture the
        signature; reporting that date would overstate how fresh it is, which is
        the one thing the kiosk is showing him."""
        got = server._worker_signature_signed_at({
            "signature": "x",
            "safety_orientations": [
                {"completed_at": "2026-08-01T09:00:00+00:00"},
                {"completed_at": "2025-07-29T08:00:00+00:00"},
            ],
        })
        self.assertEqual(got, "2025-07-29T08:00:00+00:00")

    def test_a_datetime_is_accepted_as_well_as_a_string(self):
        got = server._worker_signature_signed_at({
            "signature": "x",
            "safety_orientations": [
                {"completed_at": datetime(2025, 7, 29, tzinfo=timezone.utc)}],
        })
        self.assertTrue(got.startswith("2025-07-29"))

    def test_no_signature_means_no_date(self):
        self.assertIsNone(server._worker_signature_signed_at(
            {"safety_orientations": [{"completed_at": "2025-07-29"}]}))

    def test_it_never_raises_on_junk(self):
        for worker in (None, {}, {"signature": "x"},
                       {"signature": "x", "safety_orientations": [None, "x", {}]}):
            with self.subTest(worker=worker):
                server._worker_signature_signed_at(worker)


class TestThePublicEndpointNeverShipsTheImage(unittest.TestCase):
    """lookup-worker is PUBLIC and keyed on a phone number. Returning the PNG
    would make signature images enumerable by phone — the one artefact where that
    matters, and the same enumeration E3 is already open about."""

    def test_it_returns_a_boolean_and_a_date_only(self):
        body = _fn("async def lookup_worker")
        self.assertIn('"has_signature": bool(worker.get("signature"))', body)
        self.assertIn('"signature_signed_at"', body)
        self.assertIsNone(
            re.search(r'"signature":\s*worker\.get\("signature"\)', body),
            "the public lookup must never return the image itself")


class TestToolboxIsExplicitlyExcluded(unittest.TestCase):
    """#135 ruled that a worker does not sign a toolbox talk, and that carrying a
    gate signature there would misrepresent its provenance. The in-app viewer
    already renders `worker_signature`, so that ruling would reverse itself by
    side effect the moment the field populated."""

    def test_the_model_still_nulls_the_attendee_signature(self):
        model = (Path(server.__file__).parents[1] / "frontend" / "src" /
                 "utils" / "toolboxTalkModel.js").read_text(encoding="utf-8")
        build = model[model.index("export function buildAttendees"):]
        build = build[:build.index("export function reconcileAttendees")]
        self.assertIn("signature: null", build)

    def test_no_toolbox_renderer_reads_the_affirmation(self):
        """The affirmation is scoped to the PRE-SHIFT SIGN-IN LOG. If a toolbox
        branch ever reads it, the exclusion has been lost."""
        for start, end in (('elif log_type == "toolbox_talk":',
                            'elif log_type == "preshift_signin":'),
                           ('toolbox = _filed_log', 'preshift = _filed_log')):
            with self.subTest(branch=start):
                block = _SRC[_SRC.index(start):_SRC.index(end)]
                self.assertNotIn("signature_affirmed", block)
                self.assertNotIn("_preshift_signature_cell", block)


class TestTheRecordIsAFactAboutToday(unittest.TestCase):
    def test_it_is_written_on_the_checkin_not_the_worker_doc(self):
        fn = _fn("async def register_and_checkin")
        self.assertIn('"signature_affirmed": _sig_affirmed', fn)
        self.assertIn('"signature_affirmed_at": now if _sig_affirmed else None', fn)

    def test_the_language_is_frozen_from_what_was_SHOWN(self):
        """Reading it back from live state later would let the record change
        after the fact, and a worker affirming Spanish copy is evidence about
        what he read."""
        fn = _fn("async def register_and_checkin")
        self.assertIn('data.get("signature_affirmed_lang")', fn)
        self.assertIn('if _sig_lang not in ("en", "es")', fn)

    def test_not_affirming_records_no_time_and_no_language(self):
        fn = _fn("async def register_and_checkin")
        self.assertIn(
            '"signature_affirmed_lang": _sig_lang if _sig_affirmed else None', fn)

    def test_the_roster_carries_it_on_the_pass_that_has_it(self):
        self.assertIn('"signature_affirmed": bool(c.get("signature_affirmed"))', _SRC)

    def test_the_card_path_reports_false_by_construction(self):
        """The enrollment gate has no affirmation control, so this is false
        because there is nothing to read — not because a read returned false."""
        self.assertIn('"signature_affirmed": False,', _SRC)

    def test_nothing_blocks_a_worker_for_not_affirming(self):
        """The standing rule: the gate does not stop a man working. An
        unaffirmed signature is a gap on a sheet, not a locked turnstile."""
        fn = _fn("async def register_and_checkin")
        for line in fn.splitlines():
            stripped = line.strip()
            if "_sig_affirmed" in stripped and stripped.startswith(("if ", "raise")):
                self.fail(f"affirmation is gating the check-in: {stripped}")


if __name__ == "__main__":
    unittest.main()
