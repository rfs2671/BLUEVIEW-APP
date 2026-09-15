"""The backfill, because widening the parser clears NOBODY already flagged.

`needs_review` and `review_reason` are written ONCE, in
`build_worker_certifications`, at check-in/registration. Nothing re-derives them
on read -- `_sst_cert_state` and `validate_worker_certifications` never consult
`needs_review` at all. So the parser fix on its own only stops the NEXT twelve;
the twelve already on the record stay flagged forever.

The raw string is preserved verbatim in `expiration_raw_rejected`, so the
backfill is deterministic: re-run the widened parser over it and, where it
resolves, write `expiration_date`, clear `expiration_raw_rejected`, and let the
gate say what the flag should now be.

THE RULE THIS FILE EXISTS TO ENFORCE: RE-DERIVE, NEVER HAND-LOWER.
`test_the_planner_never_assigns_the_flag_by_hand` reads the planner's AST and
fails if it ever writes a literal to `needs_review`. Assigning
`needs_review = False` by hand is exactly what made PR #530 look like a cure
and got it parked.
"""

import ast
import importlib.util
import inspect
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "backfill_iso_expiry", str(_BACKEND / "scripts" / "backfill_iso_expiry.py"))
_bf = importlib.util.module_from_spec(_spec)
sys.modules["backfill_iso_expiry"] = _bf
_spec.loader.exec_module(_bf)
plan_for_worker = _bf.plan_for_worker

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def cert(raw, **kw):
    row = {"type": "SST_FULL", "card_number": "SST629DDBC6",
           "issue_date": None, "expiration_date": None, "verified": False,
           "needs_review": True, "review_reason": "EXPIRY_UNPARSEABLE",
           "expiration_raw_rejected": raw, "extraction_completeness": 0.75}
    row.update(kw)
    return row


def worker(*certs, name="Samuel Boateng", **kw):
    w = {"id": "w-1", "name": name, "certifications": list(certs)}
    w.update(kw)
    return w


class ItRecoversTheTwelveAndNothingElse(unittest.TestCase):

    def test_an_iso_row_is_planned_for_recovery(self):
        p = plan_for_worker(worker(cert("2027-10-03")), NOW)[0]
        self.assertEqual(p["action"], "recover")
        self.assertEqual(p["recovered"],
                         datetime(2027, 10, 3, tzinfo=timezone.utc))
        self.assertFalse(p["after"]["needs_review"])
        self.assertIsNone(p["after"]["review_reason"])
        self.assertEqual(p["set"]["expiration_date"],
                         datetime(2027, 10, 3, tzinfo=timezone.utc))
        self.assertIsNone(p["set"]["expiration_raw_rejected"])

    def test_the_three_ambiguous_shapes_are_left_for_the_human(self):
        for raw in ("10272029", "062427", "05/35"):
            p = plan_for_worker(worker(cert(raw)), NOW)[0]
            self.assertEqual(p["action"], "leave", raw)
            self.assertIsNone(p["recovered"], raw)
            self.assertEqual(p["after"]["review_reason"], "EXPIRY_UNPARSEABLE")
            self.assertTrue(p["after"]["needs_review"])
            self.assertEqual(p["set"], {}, f"{raw!r} must produce NO write")

    def test_illegible_and_null_are_left_too(self):
        for raw in ("illegible", "null"):
            p = plan_for_worker(worker(cert(raw)), NOW)[0]
            self.assertEqual(p["action"], "leave", raw)
            self.assertEqual(p["set"], {})

    def test_a_row_with_no_rejected_string_is_not_visited(self):
        clean = cert(None, needs_review=False, review_reason=None,
                     expiration_date=datetime(2030, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(plan_for_worker(worker(clean), NOW), [])

    def test_a_verified_row_is_never_touched(self):
        """`build_worker_certifications` refuses to let a re-scan modify a
        verified row -- 'admin-confirmed'. A backfill has even less standing."""
        p = plan_for_worker(worker(cert("2027-10-03", verified=True)), NOW)[0]
        self.assertEqual(p["action"], "skip-verified")
        self.assertEqual(p["set"], {})


class ItReDerivesThroughTheRealGate(unittest.TestCase):
    """Not 'it clears the flag'. It asks the gate, and the gate may say no."""

    def test_a_recovered_date_past_the_ceiling_is_refused_again(self):
        """The 7-year ceiling still has a say on a recovered date. This row
        goes from EXPIRY_UNPARSEABLE to EXPIRY_IMPLAUSIBLE and stays flagged --
        a hand-lowered flag would have called it clean."""
        p = plan_for_worker(worker(cert("2099-01-01")), NOW)[0]
        self.assertEqual(p["action"], "leave")
        self.assertEqual(p["after"]["review_reason"], "EXPIRY_IMPLAUSIBLE")
        self.assertTrue(p["after"]["needs_review"])

    def test_a_recovered_date_before_the_issue_date_is_refused_again(self):
        row = cert("2023-01-01",
                   issue_date=datetime(2024, 6, 13, tzinfo=timezone.utc))
        p = plan_for_worker(worker(row), NOW)[0]
        self.assertEqual(p["after"]["review_reason"], "EXPIRY_IMPLAUSIBLE")
        self.assertEqual(p["action"], "leave")

    def test_a_recovered_past_date_is_recovered_and_reads_as_expired(self):
        """HECTOR RAMIREZ. '2026-05-06' is real, plausible and in the past.
        Recovering it does not clear him; it replaces 'we could not read your
        card' with 'your card expired in May'. That is the point."""
        p = plan_for_worker(worker(cert("2026-05-06"),
                                   name="Hector Ramirez"), NOW)[0]
        self.assertEqual(p["action"], "recover")
        self.assertFalse(p["after"]["needs_review"])
        self.assertEqual(p["after"]["sst_state"], "expired")

    def test_an_unreadable_class_keeps_its_own_reason(self):
        """Recovering the expiry must not clear a reason the expiry never
        caused. SST_UNSPECIFIED is CLASS_UNVERIFIED and stays flagged."""
        p = plan_for_worker(
            worker(cert("2027-10-03", type="SST_UNSPECIFIED")), NOW)[0]
        self.assertEqual(p["action"], "recover")
        self.assertTrue(p["after"]["needs_review"])
        self.assertEqual(p["after"]["review_reason"], "CLASS_UNVERIFIED")

    def test_a_missing_card_number_keeps_the_row_flagged(self):
        p = plan_for_worker(
            worker(cert("2027-10-03", card_number=None)), NOW)[0]
        self.assertTrue(p["after"]["needs_review"])

    def test_a_colour_only_class_keeps_the_row_flagged(self):
        p = plan_for_worker(
            worker(cert("2027-10-03", class_source="color_only")), NOW)[0]
        self.assertTrue(p["after"]["needs_review"])

    def test_amendment_c_two_unverified_sst_rows_both_stay_flagged(self):
        """`build_worker_certifications` ends by flagging every unverified SST
        row when there are two. The backfill must not undo that by clearing one
        of them in isolation."""
        a = cert("2027-10-03", card_number="SST629DDBC6")
        b = cert(None, card_number="SSTB08B0F9A", needs_review=True,
                 review_reason="DUPLICATE_SST",
                 expiration_date=datetime(2030, 1, 1, tzinfo=timezone.utc))
        p = plan_for_worker(worker(a, b), NOW)[0]
        self.assertTrue(p["after"]["needs_review"])
        self.assertEqual(p["after"]["review_reason"], "DUPLICATE_SST")

    def test_the_planner_agrees_with_the_scanner(self):
        """THE POINT OF EXTRACTING THE GATE. The same raw string, through the
        scanner and through the backfill, must produce the same verdict."""
        for raw in ("2027-10-03", "2026-05-06", "10272029", "062427",
                    "05/35", "illegible", "2099-01-01"):
            certs, _ = server.build_worker_certifications(
                [], {"name": "A WORKER", "card_type": "SST",
                     "card_class": "Worker", "expiration": raw},
                "SST629DDBC6", None, NOW)
            scanned = certs[0]
            planned = plan_for_worker(worker(cert(raw)), NOW)[0]["after"]
            self.assertEqual(planned["needs_review"], scanned["needs_review"], raw)
            self.assertEqual(planned["review_reason"], scanned["review_reason"], raw)
            self.assertEqual(planned["expiration_date"],
                             scanned["expiration_date"], raw)


class TheImageLockIsReportedPerRow(unittest.TestCase):
    """`card_image_may_be_replaced` reads `needs_review or expiration_date is
    None`. Every row this backfill clears flips it to False, which means a card
    photo can no longer be replaced by a later re-scan. That consequence is
    printed for every row, per the rule that it must be argued and not
    inherited silently."""

    def test_a_worker_with_no_image_does_not_move(self):
        """ALL TWELVE ARE THIS CASE ON PRODUCTION TODAY: no osha_card_image and
        no osha_card_r2_key, so the predicate short-circuits to True on the
        no-image branch and the backfill changes nothing about it."""
        p = plan_for_worker(worker(cert("2027-10-03")), NOW)[0]
        self.assertTrue(p["img_before"])
        self.assertTrue(p["img_after"])
        self.assertFalse(p["img_locks"])

    def test_a_worker_with_a_stored_image_is_reported_as_locking(self):
        p = plan_for_worker(
            worker(cert("2027-10-03"), osha_card_r2_key="cards/x.jpg"), NOW)[0]
        self.assertTrue(p["img_before"])
        self.assertFalse(p["img_after"])
        self.assertTrue(p["img_locks"])

    def test_a_row_left_alone_never_locks_an_image(self):
        p = plan_for_worker(
            worker(cert("10272029"), osha_card_r2_key="cards/x.jpg"), NOW)[0]
        self.assertTrue(p["img_after"])
        self.assertFalse(p["img_locks"])


class TheScriptIsReadOnlyUntilToldOtherwise(unittest.TestCase):

    def test_the_planner_never_lowers_the_flag_by_hand(self):
        """PR #530's SIDE DOOR, CLOSED BY A TEST RATHER THAN BY A PROMISE.

        `needs_review` may receive exactly two things in this planner:
          * whatever came back from `server.derive_cert_review` -- the gate; or
          * the literal `True`, which RAISES the flag (Amendment C, two
            unverified SST rows).
        Anything else -- and `needs_review = False` above all -- is the
        hand-lowering that made #530 look like a cure. The asymmetry is the
        point: raising a flag on a compliance record is always safe, lowering
        one is only safe if the gate said so.
        """
        tree = ast.parse(inspect.getsource(plan_for_worker))
        seen_from_gate = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            flat = []
            for t in targets:
                flat.extend(t.elts if isinstance(t, ast.Tuple) else [t])
            names = {t.id for t in flat if isinstance(t, ast.Name)}
            names |= {t.attr for t in flat if isinstance(t, ast.Attribute)}
            if "needs_review" not in names:
                continue
            val = node.value
            if (isinstance(val, ast.Call)
                    and getattr(val.func, "id", getattr(val.func, "attr", None))
                    == "derive_cert_review"):
                seen_from_gate = True
                continue
            self.assertTrue(
                isinstance(val, ast.Constant) and val.value is True,
                "needs_review may only come from derive_cert_review, or be "
                "raised to the literal True; never lowered by hand")
        self.assertTrue(seen_from_gate,
                        "the planner must get its verdict from the real gate")
        src = inspect.getsource(plan_for_worker)
        self.assertIn("derive_cert_review", src)
        self.assertIn("evaluate_cert_expiry", src)

    def test_the_planner_never_writes_a_literal_false_flag(self):
        """Belt and braces on the same rule, at the $set payload."""
        src = inspect.getsource(plan_for_worker)
        self.assertNotIn("needs_review\": False", src)
        self.assertNotIn("needs_review': False", src)
        self.assertNotIn("needs_review = False", src)

    def test_the_planner_mutates_nothing(self):
        row = cert("2027-10-03")
        w = worker(row)
        plan_for_worker(w, NOW)
        self.assertTrue(row["needs_review"])
        self.assertEqual(row["review_reason"], "EXPIRY_UNPARSEABLE")
        self.assertEqual(row["expiration_raw_rejected"], "2027-10-03")
        self.assertIsNone(row["expiration_date"])

    def test_report_is_the_default_and_execute_must_be_asked_for(self):
        self.assertFalse(_bf.wants_execute([]))
        self.assertFalse(_bf.wants_execute(["--report"]))
        self.assertTrue(_bf.wants_execute(["--execute"]))

    def test_the_module_says_read_only_by_default(self):
        self.assertIn("--report", _bf.__doc__)
        self.assertIn("--execute", _bf.__doc__)


if __name__ == "__main__":
    unittest.main()
