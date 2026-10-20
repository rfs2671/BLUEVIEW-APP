"""The DM answer scorer (lib/dm_eval.py) and its script, on synthetic rows.

No phone numbers or real links in this file: the ones the scrubber must
remove are built at run time from obviously fake parts.
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib import dm_eval  # noqa: E402
from scripts import dm_eval as script  # noqa: E402

T0 = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)
FAKE_DIGITS = " ".join(["9" * 3, "9" * 3, "9" * 4])          # phone-shaped, not a phone
FAKE_LINK = "https://" + "app.example.invalid" + "/api/public/punch/abc.sig"


def row(user, minutes, q, a, path="job_agent", fallback=False, reason="agent"):
    return {"user_id": user, "company_id": "co", "project_id": "p",
            "path": path, "fallback": fallback, "reason": reason,
            "question": q, "answer": a, "created_at": T0 + timedelta(minutes=minutes)}


class ScrubTest(unittest.TestCase):
    def test_phone_link_email_are_removed(self):
        s = dm_eval.scrub(f"call {FAKE_DIGITS} or open {FAKE_LINK} or mail a.b@example.invalid")
        self.assertNotIn(FAKE_DIGITS, s)
        self.assertNotIn("example.invalid", s)
        self.assertIn("[number]", s)
        self.assertIn("[link]", s)
        self.assertIn("[email]", s)

    def test_plain_words_survive(self):
        self.assertEqual(dm_eval.scrub("  4 on   site "), "4 on site")


class SkeletonTest(unittest.TestCase):
    def test_numbers_and_names_fold_into_one_shape(self):
        a = dm_eval.skeleton("4 on site at 588 now: Power Direct 4.")
        b = dm_eval.skeleton("7 on site at 9 Menahan now: Apex Steel 7.")
        self.assertEqual(a, b)

    def test_first_word_of_a_sentence_is_kept(self):
        self.assertTrue(dm_eval.skeleton("Nobody checked in yet.").startswith("nobody"))


class ScoreTest(unittest.TestCase):
    def test_canned_needs_several_different_questions(self):
        rows = [row(f"u{i}", i, q, f"{n} on site at Job{i} now.")
                for i, (q, n) in enumerate([("how many on site", 4), ("whos there", 7),
                                            ("headcount pls", 2)])]
        r = dm_eval.score(rows)
        self.assertEqual(r["canned_answers"], 3)
        self.assertEqual(r["canned_shapes"][0]["questions"], 3)

    def test_same_question_three_times_is_not_canned(self):
        rows = [row(f"u{i}", i, "how many on site", f"{i} on site now.") for i in range(3)]
        self.assertEqual(dm_eval.score(rows)["canned_answers"], 0)

    def test_fixed_text_paths_are_not_counted_as_canned(self):
        rows = [row(f"u{i}", i, f"q{i} something", "Which job? Reply 1 or 2.", path="menu")
                for i in range(4)]
        r = dm_eval.score(rows)
        self.assertEqual(r["canned_answers"], 0)
        self.assertEqual(r["template_path_answers"], 4)

    def test_the_10_21_repeat_is_caught(self):
        same = "Window protection is on SSP-011.00."
        rows = [row("u1", 0, "where is window protection", same),
                row("u1", 1, "Show me", same),
                row("u1", 2, "Show me details", same)]
        r = dm_eval.score(rows)
        self.assertEqual(r["repeats"], 2)

    def test_repeat_needs_the_same_user(self):
        rows = [row("u1", 0, "a b c", "same"), row("u2", 1, "d e f", "same")]
        self.assertEqual(dm_eval.score(rows)["repeats"], 0)

    def test_reask_is_a_close_question_soon_after(self):
        rows = [row("u1", 0, "how many subs on site", "3 people."),
                row("u1", 1, "how many subs are on site?", "4 subs: …"),
                row("u1", 30, "how many subs on site", "4 subs: …")]
        r = dm_eval.score(rows)
        self.assertEqual(r["reasks"], 1)

    def test_fallbacks_and_reasons(self):
        rows = [row("u1", 0, "q", "", fallback=True, reason="no_answer"),
                row("u1", 9, "q2", "x", path="headcount", fallback=True, reason="check_failed"),
                row("u2", 0, "q3", "fine")]
        r = dm_eval.score(rows)
        self.assertEqual(r["fallbacks"], 2)
        self.assertEqual(r["fallback_pct"], 66.7)
        self.assertEqual(r["fallback_reasons"], {"no_answer": 1, "check_failed": 1})

    def test_long_answer_to_a_short_question(self):
        rows = [row("u1", 0, "who's here", " ".join(["word"] * 80))]
        self.assertEqual(dm_eval.score(rows)["long_answers"], 1)

    def test_report_strings_are_scrubbed(self):
        bad = f"Ask {FAKE_DIGITS}, see {FAKE_LINK}"
        rows = [row(f"u{i}", i, f"{w} question", bad) for i, w in enumerate(["one", "two", "three"])]
        text = json.dumps(dm_eval.score(rows)) + dm_eval.render(dm_eval.score(rows))
        self.assertNotIn(FAKE_DIGITS, text)
        self.assertNotIn("example.invalid", text)

    def test_empty_log(self):
        r = dm_eval.score([])
        self.assertEqual(r["answers"], 0)
        self.assertIn("DM answers: 0", dm_eval.render(r))


class ReviewFixesTest(unittest.TestCase):
    """The five Codex findings on #815."""

    def test_sheet_markers_are_not_model_answers(self):
        rows = [row(f"u{i}", i, f"show me {w}", f"[Sheet] A-10{i} — Plan", path="sheet")
                for i, w in enumerate(["one", "two", "three"])]
        r = dm_eval.score(rows)
        self.assertEqual(r["canned_answers"], 0)
        self.assertEqual(r["top_openers"], [])
        self.assertEqual(r["template_path_answers"], 3)

    def test_a_question_in_between_does_not_hide_a_repeat(self):
        same = "Window protection is on SSP-011.00."
        rows = [row("u1", 0, "where is window protection", same),
                row("u1", 1, "who is on site", "3 people."),
                row("u1", 2, "Show me", same)]
        self.assertEqual(dm_eval.score(rows)["repeats"], 1)

    def test_a_question_in_between_does_not_hide_a_reask(self):
        rows = [row("u1", 0, "how many subs on site", "3 people."),
                row("u1", 1, "thanks", "Anytime."),
                row("u1", 2, "how many subs are on site?", "4 subs.")]
        self.assertEqual(dm_eval.score(rows)["reasks"], 1)

    def test_each_answer_counts_once(self):
        same = "Same text."
        rows = [row("u1", 0, "a one", same), row("u1", 1, "b two", same),
                row("u1", 2, "c three", same)]
        self.assertEqual(dm_eval.score(rows)["repeats"], 2)

    def test_hebrew_script_has_words(self):
        q1 = "\u05d5\u05d5\u05d9 \u05e4\u05d9\u05dc\u05e2 \u05de\u05e2\u05e0\u05d8\u05e9\u05df"
        q2 = q1 + " \u05d3\u05d0"
        self.assertTrue(dm_eval._words(q1))
        self.assertGreaterEqual(dm_eval.similarity(q1, q2), 0.5)
        rows = [row("u1", 0, q1, "3."), row("u1", 1, q2, "4.")]
        self.assertEqual(dm_eval.score(rows)["reasks"], 1)

    def test_names_from_tool_data_are_masked(self):
        td = {"company": "Acme Glass", "by_company": [["Bolt Electric", 2]],
              "workers": [{"name": "Shmuel", "company": "Bolt Electric"}], "added": ["Yossi"]}
        self.assertEqual(dm_eval.known_names(td), {"Acme Glass", "Bolt Electric", "Shmuel", "Yossi"})
        out = dm_eval.mask_names("2 on site: Bolt Electric 2 (Shmuel, yossi). Ask Moshe Klein.",
                                 dm_eval.known_names(td))
        for n in ("Bolt", "Shmuel", "yossi", "Moshe", "Klein"):
            self.assertNotIn(n, out)
        self.assertIn("2 on site", out)

    def test_script_masks_names_unless_kept(self):
        r = {**row("user-abc", 0, "who is from Bolt Electric", "Shmuel from Bolt Electric."),
             "tool_data": {"workers": [{"name": "Shmuel", "company": "Bolt Electric"}]}}
        masked = script.anonymise([r])[0]
        self.assertNotIn("Shmuel", masked["answer"])
        self.assertNotIn("Bolt", masked["question"])
        self.assertNotIn("tool_data", masked)
        kept = script.anonymise([r], keep_names=True)[0]
        self.assertIn("Shmuel", kept["answer"])

    def test_live_limit_keeps_the_newest_rows_in_time_order(self):
        import asyncio
        import os
        import types
        from unittest.mock import patch
        docs = [{"user_id": "u", "question": f"q{i}", "answer": "a", "path": "general",
                 "created_at": T0 + timedelta(minutes=i)} for i in range(5)]

        class Cur:
            def __init__(self, d): self.d = list(d)
            def sort(self, k, direction):
                self.d.sort(key=lambda x: x[k], reverse=direction < 0); return self
            def limit(self, n): self.d = self.d[:n]; return self
            def __aiter__(self):
                async def gen():
                    for x in self.d:
                        yield x
                return gen()

        class Coll:
            def find(self, *a, **k): return Cur(docs)

        class Client:
            def __init__(self, *a, **k): pass
            def __getitem__(self, name): return types.SimpleNamespace(whatsapp_dm_answers=Coll())

        fake = types.ModuleType("motor.motor_asyncio")
        fake.AsyncIOMotorClient = Client
        with patch.dict(sys.modules, {"motor.motor_asyncio": fake}), \
                patch.dict(os.environ, {"MONGO_URL": "mongodb://x", "DB_NAME": "d"}):
            got = asyncio.run(script._live_rows(days=365 * 10, limit=2))
        self.assertEqual([g["question"] for g in got], ["q3", "q4"])


class ReplayRulesTest(unittest.TestCase):
    """What the replay of Oct 20 taught the scorer."""

    def test_a_sheet_sent_again_is_not_a_repeat(self):
        rows = [row("u1", 0, "Show me", "[Sheet] SSP-011.00", path="sheet"),
                row("u1", 1, "send it", "[Sheet] SSP-011.00", path="sheet")]
        self.assertEqual(dm_eval.score(rows)["repeats"], 0)

    def test_the_same_data_question_reworded_is_not_a_repeat(self):
        same = "4 subs on site at 588: Arkon, Quality Plumbing, J&G, Power Direct."
        rows = [{**row("u1", 0, "How many subs on site?", same, path="headcount"), "kind": "subs"},
                {**row("u1", 1, "How many companies on site", same, path="headcount"),
                 "tool_data": {"kind": "subs"}}]
        self.assertEqual(dm_eval.score(rows)["repeats"], 0)

    def test_a_subs_question_given_the_worker_count_still_is(self):
        """The 9:01 failure: same text, different kind of question."""
        same = "31 on site at 588 now."
        rows = [{**row("u1", 0, "Update on workers 588", same, path="headcount"), "kind": "count"},
                {**row("u1", 1, "How many subs on site?", same, path="headcount"), "kind": "subs"}]
        self.assertEqual(dm_eval.score(rows)["repeats"], 1)

    def test_the_export_keeps_the_kind(self):
        r = {**row("user-abc", 0, "how many subs", "4 subs."), "tool_data": {"kind": "subs"}}
        self.assertEqual(script.anonymise([r])[0]["kind"], "subs")


class SampleTest(unittest.TestCase):
    def test_spread_across_paths_and_labelled_columns(self):
        rows = [row("u1", i, f"q{i}", f"a{i}", path=p)
                for i, p in enumerate(["job_agent"] * 10 + ["headcount"] * 2 + ["sheet"])]
        s = dm_eval.review_sample(rows, n=6)
        self.assertEqual(len(s), 6)
        self.assertEqual({x["path"] for x in s}, {"job_agent", "headcount", "sheet"})
        self.assertIn("sounds_human_1_5", s[0])


class ScriptTest(unittest.TestCase):
    def test_offline_run_writes_scrubbed_files_and_no_ids(self):
        rows = [row("user-abc", i, f"q{i} {FAKE_DIGITS}", f"a {FAKE_LINK}") for i in range(3)]
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "in.jsonl")
            src.write_text("\n".join(json.dumps({**r, "created_at": r["created_at"].isoformat()})
                                     for r in rows), encoding="utf-8")
            out_json, out_csv, out_exp = (Path(d, n) for n in ("r.json", "s.csv", "e.jsonl"))
            rc = script.main(["--from-file", str(src), "--json", str(out_json),
                              "--sample", str(out_csv), "--export", str(out_exp)])
            self.assertEqual(rc, 0)
            blob = out_json.read_text() + out_csv.read_text() + out_exp.read_text()
            self.assertNotIn(FAKE_DIGITS, blob)
            self.assertNotIn("example.invalid", blob)
            self.assertNotIn("user-abc", blob)
            exported = [json.loads(x) for x in out_exp.read_text().splitlines()]
            self.assertEqual({e["user_id"] for e in exported}, {"u1"})
            self.assertNotIn("company_id", exported[0])
            with open(out_csv, newline="") as f:
                self.assertEqual(len(list(csv.DictReader(f))), 3)

    def test_live_mode_refuses_without_a_database(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                script.main(["--days", "1"])


if __name__ == "__main__":
    unittest.main()
