"""The wrong card says so.

A purple card is a Worker Wallet, not an SST credential. resolve_card_class has
always identified it correctly and build_worker_certifications has always been
right to refuse to invent a certification for it -- but the REASON was thrown
away at the only call site, so the worker was refused with MISSING_OSHA: "No
OSHA card on file". That is wrong (nothing was learned about his OSHA card; he
never photographed one) and unactionable (it does not tell him the card in his
hand is the wrong one). The comment above that early return has claimed since it
was written that "the caller surfaces not_sst to the worker".

These tests make that claim true and keep it true.

They also pin the second half of the same change: the second return element used
to be `sst_expiration_unparseable`, which was computed, returned, unpacked and
NEVER READ by anything. Dropping it lost nothing, and TheDeadFlagLostNothing
below is what proves that rather than asserting it.

Run:  python -m pytest backend/tests/test_gate_card_not_sst.py -q
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

import server  # noqa: E402

NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)
SRC = (_BACKEND / "server.py").read_text(encoding="utf-8")
CHECKIN_HTML = (_BACKEND / "checkin.html").read_text(encoding="utf-8")


def ocr(**kw):
    d = {
        "name": "Jose Luna", "sst_number": "X2L5QYKYEJ", "card_type": "SST",
        "card_class": None, "issued": "03/17/2023", "expiration": "03/17/2028",
        "card_dominant_color": None, "card_color_confidence": None,
        "card_color_conditions": [],
    }
    d.update(kw)
    return d


def build(existing=None, **kw):
    return server.build_worker_certifications(
        list(existing or []), ocr(**kw), "X2L5QYKYEJ", "img", NOW,
    )


PURPLE = dict(card_dominant_color="PURPLE", card_color_confidence="high")


class TheReasonTravels(unittest.TestCase):
    def test_purple_returns_not_sst(self):
        certs, not_sst = build(**PURPLE)
        self.assertEqual(certs, [], "a Worker Wallet must not mint any cert row")
        self.assertEqual(not_sst, server.CARD_NOT_SST_WORKER_WALLET)

    def test_ordinary_card_returns_none(self):
        certs, not_sst = build(card_dominant_color="BLUE", card_color_confidence="high")
        self.assertIsNone(not_sst)
        self.assertEqual(len(certs), 1)

    def test_no_colour_reported_returns_none(self):
        # The commonest case today: the client sends no colour at all. It must
        # not be mistaken for "not an SST card".
        certs, not_sst = build()
        self.assertIsNone(not_sst)
        self.assertEqual(len(certs), 1)


class WhatTheWorkerIsTold(unittest.TestCase):
    def test_purple_scan_alone_blocks_as_missing_osha_before_relabel(self):
        # The precondition the re-label exists to fix: with no certs on file, a
        # purple scan produces no cert, and validate can only call that
        # MISSING_OSHA -- it has no idea a wallet was photographed.
        certs, not_sst = build(**PURPLE)
        result = server.validate_worker_certifications({"certifications": certs})
        self.assertFalse(result["cleared"])
        self.assertEqual([b["type"] for b in result["blocks"]], ["MISSING_OSHA"])
        self.assertEqual(not_sst, server.CARD_NOT_SST_WORKER_WALLET)

    def test_relabel_is_scoped_to_an_existing_block(self):
        # A RETURNING WORKER IS NOT NEWLY BLOCKED. He has a valid SST on file and
        # happens to photograph his wallet: validate clears him, so there is no
        # block to re-label and `not_sst` must not manufacture one. This is the
        # invariant that keeps the change about WORDING, not about who gets in.
        on_file = [{
            "type": "SST_FULL", "card_number": "X2L5QYKYEJ",
            "expiration_date": datetime(2028, 3, 17, tzinfo=timezone.utc),
            "verified": True,
        }]
        certs, not_sst = build(existing=on_file, **PURPLE)
        self.assertEqual(certs, on_file, "a wallet scan must not disturb certs on file")
        self.assertEqual(not_sst, server.CARD_NOT_SST_WORKER_WALLET)
        result = server.validate_worker_certifications({"certifications": certs})
        self.assertTrue(
            result["cleared"],
            "a worker with a valid SST on file is cleared regardless of what he photographed",
        )

    def test_register_relabels_only_a_refusal_it_did_not_create(self):
        # The re-label lives inline in register_and_checkin (which needs a DB),
        # so its GUARD is pinned at the source. Two properties matter and both
        # are here: it is conditioned on the block ALREADY existing
        # (`not cert_result["cleared"]`), and it only ever rewrites MISSING_OSHA.
        block = SRC[SRC.index("if not cert_result[\"cleared\"] and not_sst:"):][:600]
        self.assertIn("CARD_NOT_SST", block)
        self.assertIn('b.get("type") == "MISSING_OSHA"', block)
        self.assertRegex(
            block,
            r'if not cert_result\["cleared"\] and not_sst:',
            "the re-label must never fire on a worker who was cleared",
        )

    def test_worker_facing_copy_exists_in_both_languages(self):
        # A block code with no copy renders as the bilingual generic, which is
        # exactly the unactionable message this change removes.
        self.assertIn("CARD_NOT_SST: 'blockCardNotSst'", CHECKIN_HTML)
        occurrences = re.findall(r"blockCardNotSst:\s*'([^']+)'", CHECKIN_HTML)
        self.assertEqual(len(occurrences), 2, "need EN and ES copy, found: %r" % (occurrences,))
        for text in occurrences:
            self.assertIn("SST", text)
            self.assertTrue(text.strip(), "copy must not be empty")


class TheDeadFlagLostNothing(unittest.TestCase):
    """`sst_expiration_unparseable` is gone. Nothing it described is gone."""

    def test_second_element_is_no_longer_the_expiry_flag(self):
        # An unparseable expiry used to set the second element True. It is now
        # None -- the slot means `not_sst` and nothing else.
        certs, not_sst = build(expiration="MARCH 17 2028")
        self.assertIsNone(not_sst)
        self.assertEqual(len(certs), 1)

    def test_the_unparseable_expiry_still_reaches_the_record(self):
        # THE POINT. The flag was redundant: the same fact is carried on the
        # cert row itself, which is what the CP's review queue and the frozen
        # check-in snapshot actually read.
        certs, _ = build(expiration="MARCH 17 2028")
        cert = certs[0]
        self.assertIsNone(cert["expiration_date"], "a bad expiry is never stored as fact")
        self.assertEqual(cert["expiration_raw_rejected"], "MARCH 17 2028")
        self.assertEqual(cert["review_reason"], "EXPIRY_UNPARSEABLE")
        self.assertTrue(cert["needs_review"])

    def test_an_implausible_expiry_is_distinguishable_from_an_unparseable_one(self):
        # The removed bool covered only UNPARSEABLE. The distinction it could
        # have carried is preserved on the row, at finer grain than the bool had.
        certs, _ = build(issued="03/17/2023", expiration="03/17/2099")
        self.assertEqual(certs[0]["review_reason"], "EXPIRY_IMPLAUSIBLE")

    def test_the_dead_name_is_gone_from_the_module(self):
        code = re.sub(r'"""(?:.|\n)*?"""', "", SRC)   # strip docstrings
        code = re.sub(r"#[^\n]*", "", code)           # strip comments
        self.assertNotIn(
            "sst_expiration_unparseable", code,
            "the dead flag must not survive anywhere outside prose",
        )


if __name__ == "__main__":
    unittest.main()
